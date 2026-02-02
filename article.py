import mwparserfromhell
import re
import sys
from wikilist import extract_list_items
from wikiapi import get_current_timestamp, get_wikipedia_article

reference_sections = [
    "references",
    "further reading",
    "external links",
    "bibliography",
    "works cited",
    "books",
    "articles",
    "sources"]

def extract_urls_from_text(text):
    url_regex = re.compile(r'(?:git|https?|ftps?)://[^\s\]\|\}]+')
    result = set(url_regex.findall(text))
    return result

def extract_templates_from_text(text):
    """
    Parse the provided wikitext fragment and extract template calls.

    Returns a list of dictionaries with keys:
    - template_name: normalized template name as string
    - full_text: the full text of the template call as it appears
    - parameters: list of {"key": str, "value": str} preserving order
    """
    try:
        wikicode = mwparserfromhell.parse(text)
    except Exception:
        return []

    templates = []
    try:
        for template in wikicode.filter_templates():
            # Normalize the template name to a simple string
            try:
                name = str(template.name).strip()
            except Exception:
                name = str(template.name)

            params = []
            for p in template.params:
                try:
                    key = str(p.name).strip()
                except Exception:
                    key = str(p.name)
                try:
                    value = str(p.value)
                except Exception:
                    value = ""
                params.append({"key": key, "value": value})

            templates.append({
                "template_name": name,
                "full_text": str(template),
                "parameters": params,
            })
    except Exception:
        # Be resilient to unexpected parsing issues
        return templates

    return templates

# reference_type values (application-level enum)
# 0=other; 1=inline; 2=endnote (extensible)
def classify_reference_type(raw_reference: str) -> int:
    if not raw_reference:
        return 0
    text = raw_reference.lower()
    # Inline references typically use <ref> tags
    if '<ref' in text:
        return 1
    # Endnotes often show as list items in References with citation templates
    if '{{cite' in text or '{{citation' in text:
        return 2
    return 0

def extract_references(wikitext):
    """
    Extract raw references from the provided wikitext and return both the raw
    reference text and its character offsets (offset_start, offset_end) in the
    original, UTF-8 decoded wikitext (prior to any normalization, expansion, or
    rendering).

    Returns a list of dicts with keys:
    - raw_reference: the exact raw reference text as found in the wikitext
    - offset_start: starting character offset (inclusive)
    - offset_end: ending character offset (exclusive)
    - reference_type: int enum describing the type (0=other, 1=inline, 2=endnote)
    """
    original_wikitext = wikitext
    wikicode = mwparserfromhell.parse(wikitext)
    # Keep collected references along with optional metadata (e.g., reference_name)
    reference_items = []  # list of {"raw_reference": str, "reference_name": Optional[str]}
    seen_texts = set()
    found_urls = set()

    # Remove all HTML comments
    for comment in wikicode.filter_comments():
        try:
            wikicode.remove(comment)
        except ValueError:  # Already removed, somehow
            pass

    # Extract <ref> tags content
    for tag in wikicode.filter_tags(matches=lambda node: node.tag == "ref"):
        tag_text = str(tag)
        for url in extract_urls_from_text(tag_text):
            found_urls.add(url)
        # Extract optional reference name attribute
        ref_name = None
        try:
            # mwparserfromhell represents attributes as a list of Attribute objects
            for attr in getattr(tag, 'attributes', []) or []:
                try:
                    attr_name = str(getattr(attr, 'name', '')).strip().lower()
                except Exception:
                    attr_name = ''
                if attr_name == 'name':
                    # If the name attribute exists but is empty, use empty string; otherwise, its string value
                    val = getattr(attr, 'value', None)
                    ref_name = (str(val) if val is not None else "")
                    break
        except Exception:
            # Be resilient: if attribute parsing fails, skip name extraction
            ref_name = None

        if tag_text not in seen_texts:
            seen_texts.add(tag_text)
            reference_items.append({
                "raw_reference": tag_text,
                "reference_name": ref_name,
            })
        # Remove to prevent confusion later in the process
        try:
            wikicode.remove(tag)
        except ValueError:  # Already removed, somehow
            pass

    # Extract all {{Sfn}} templates in the body of the article
    for template in wikicode.filter_templates():
        if template.name.matches("Sfn"):
            for url in extract_urls_from_text(str(template)):
                found_urls.add(url)
            t_text = str(template)
            if t_text not in seen_texts:
                seen_texts.add(t_text)
                reference_items.append({
                    "raw_reference": t_text,
                    "reference_name": None,
                })
            try:
                wikicode.remove(template)
            except ValueError:  # Already removed, somehow
                pass

    # Extract all list items with links, or list items in certain sections
    # regardless of link presence
    for section in wikicode.get_sections(levels=[2], include_lead=True):
        section_title = section.filter_headings()
        if section_title:
            title_text = section_title[0].title.strip_code().strip()
        else:
            title_text = ""
        for line in extract_list_items(section):
            # Avoid stripping so that offsets match raw text
            raw_line = str(line)
            if raw_line.startswith('*') or raw_line.startswith('#'):
                extracted_urls = extract_urls_from_text(raw_line)
                if len(extracted_urls) > 0 or title_text.lower() in reference_sections:
                    for url in extracted_urls:
                        found_urls.add(url)
                    if raw_line not in seen_texts:
                        seen_texts.add(raw_line)
                        reference_items.append({
                            "raw_reference": raw_line,
                            "reference_name": None,
                        })

    # Extract external link nodes not attached to any other reference type
    for external_link in wikicode.filter_external_links():
        if str(external_link.url) not in found_urls:
            e_text = str(external_link)
            if e_text not in seen_texts:
                seen_texts.add(e_text)
                reference_items.append({
                    "raw_reference": e_text,
                    "reference_name": None,
                })

    # Compute offsets against the original wikitext
    results = []
    used_spans = []  # list of (start, end) for already matched references

    def span_overlaps(a_start, a_end, b_start, b_end):
        return not (a_end <= b_start or b_end <= a_start)

    for item in reference_items:
        ref_text = item["raw_reference"]
        start = -1
        search_pos = 0
        while True:
            start = original_wikitext.find(ref_text, search_pos)
            if start == -1:
                # Not found; fall back by skipping offsets
                break
            end = start + len(ref_text)
            if any(span_overlaps(start, end, s, e) for s, e in used_spans):
                search_pos = start + 1
                continue
            # Found a non-overlapping span
            used_spans.append((start, end))
            results.append({
                "raw_reference": ref_text,
                "offset_start": start,
                "offset_end": end,
                "reference_type": classify_reference_type(ref_text),
                "reference_name": item.get("reference_name"),
                # Per-reference extracted data
                "templates": extract_templates_from_text(ref_text),
                "urls": sorted(list(extract_urls_from_text(ref_text))),
            })
            break
        if start == -1:
            # Could not locate the exact text (due to prior normalization); still return the text
            results.append({
                "raw_reference": ref_text,
                "offset_start": None,
                "offset_end": None,
                "reference_type": classify_reference_type(ref_text),
                "reference_name": item.get("reference_name"),
                # Per-reference extracted data
                "templates": extract_templates_from_text(ref_text),
                "urls": sorted(list(extract_urls_from_text(ref_text))),
            })

    return results

def extract_references_from_page(title, domain="en.wikipedia.org", as_of=None):
    if as_of is None:
        as_of = get_current_timestamp()
    title = title.replace(" ", "_")
    page_id, revision_id, revision_timestamp, wikitext = get_wikipedia_article(domain, title, as_of)
    return page_id, revision_id, revision_timestamp, extract_references(wikitext)

if __name__ == "__main__":
    page_title = "Easter Island"
    as_of = None
    if len(sys.argv) >= 2:
        page_title = sys.argv[1]
        if len(sys.argv) == 3:
            as_of = sys.argv[2]

    page_id, revision_id, revision_timestamp, refs = extract_references_from_page(page_title, as_of=as_of)
    for ref in refs:
        print(ref, end="\n\n")
