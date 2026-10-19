import mwparserfromhell
import re
import sys
from .wikilist import extract_list_items
from .wikiapi import get_current_timestamp, get_wikipedia_article
from .wiki_config import get_reference_sections, get_citation_template_prefixes, get_citation_template_exact, get_shorthand_templates
from citation_normalizer import sanitize_ref_name as _sanitize_ref_name, sanitize_extracted_name as _sanitize_extracted_name, normalize_template_name as _normalize_template_name

# Unicode punctuation that may cling to extracted URLs (curly quotes, guillemets, etc.)
_URL_TRAILING_PUNCT = set('\u201c\u201d\u2018\u2019\u00ab\u00bb\u2039\u203a.,;:!?\u2026)\u201e\u201a')


def _strip_trailing_url_punct(url: str) -> str:
    """Remove common trailing Unicode/typographic punctuation from a URL."""
    while url and url[-1] in _URL_TRAILING_PUNCT:
        url = url[:-1]
    return url


def extract_urls_from_text(text):
    url_regex = re.compile(r'(?:git|https?|ftps?)://[^\s\]\|\}]+')
    result = set(_strip_trailing_url_punct(u) for u in url_regex.findall(text))
    result.discard('')
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
def classify_reference_type(raw_reference: str, domain: str = "en.wikipedia.org") -> int:
    if not raw_reference:
        return 0
    text = raw_reference.lower()
    # Inline references typically use <ref> tags
    if '<ref' in text:
        return 1
    # Endnotes often show as list items in References with citation templates
    # Prefixes match the start of a template name (e.g. "cite" matches "{{cite web}}")
    for prefix in get_citation_template_prefixes(domain):
        if '{{' + prefix in text:
            return 2
    # Exact names must match the full template name
    for exact in get_citation_template_exact(domain):
        if '{{' + exact + '}}' in text or '{{' + exact + '|' in text:
            return 2
    return 0


# citation_type values (Stage 1, see docs/design/proposed_extractor.md):
#   ref_tag        <ref>…</ref> whose content is prose / anything else
#   template       <ref>…</ref> containing a citation template (wikis.yaml citation_templates)
#   bare_url       <ref>…</ref> whose content is only a URL or one bracketed link
#   endnote        a list item in a reference section (or carrying a URL)
#   shorthand      a standalone {{sfn}}-family template (wikis.yaml shorthand_templates)
#   external_link  a bracketed or bare URL outside any of the above
CITATION_TYPES = ("ref_tag", "template", "bare_url", "endnote", "shorthand", "external_link")

_REF_OPEN_RE = re.compile(r"^<ref\b[^>]*>", re.IGNORECASE | re.DOTALL)
_REF_CLOSE_RE = re.compile(r"</ref\s*>\s*$", re.IGNORECASE)
_BARE_URL_RE = re.compile(r"^(?:(?:git|https?|ftps?)://\S+|\[(?:git|https?|ftps?)://\S+(?:\s[^\]]*)?\])$")


def strip_ref_wrapper(raw_reference: str) -> str:
    """The inner content of ``<ref …>…</ref>``; other text is returned as is."""
    m = _REF_OPEN_RE.match(raw_reference)
    if not m:
        return raw_reference
    inner = raw_reference[m.end():]
    return _REF_CLOSE_RE.sub("", inner)


def _is_citation_template_name(name: str, domain: str) -> bool:
    n = _normalize_template_name(name or "")
    if not n:
        return False
    if n in set(get_citation_template_exact(domain)):
        return True
    return any(n.startswith(p) for p in get_citation_template_prefixes(domain))


def classify_citation_type(candidate_kind: str, raw_reference: str, templates, domain: str = "en.wikipedia.org") -> str:
    """Map the scanner that found a reference (plus its templates) to a ``citation_type``."""
    if candidate_kind == "shorthand":
        return "shorthand"
    if candidate_kind == "list_item":
        return "endnote"
    if candidate_kind == "external_link":
        return "external_link"
    # candidate_kind == "ref"
    if any(_is_citation_template_name((t or {}).get("template_name"), domain) for t in (templates or [])):
        return "template"
    inner = strip_ref_wrapper(raw_reference).strip()
    if inner and _BARE_URL_RE.match(inner):
        return "bare_url"
    return "ref_tag"


def _span_overlaps(a_start, a_end, b_start, b_end):
    return not (a_end <= b_start or b_end <= a_start)


def _span_contains(pos: int, spans) -> bool:
    for s, e in spans:
        if s <= pos < e:
            return True
    return False


def _find_comment_spans(wikitext: str):
    spans = []
    i = 0
    n = len(wikitext)
    while i < n:
        start = wikitext.find("<!--", i)
        if start == -1:
            break
        end = wikitext.find("-->", start + 4)
        if end == -1:
            # Unterminated comment: treat rest of page as comment
            spans.append((start, n))
            break
        spans.append((start, end + 3))
        i = end + 3
    return spans




def _extract_ref_name_from_tag_open(tag_open_text: str):
    # Minimal attribute parsing for name= (supports quoted, curly-quoted, and unquoted values)
    m = re.search(
        r'\bname\s*=\s*(?:'
        r'"([^"]*)"|'              # straight double quotes
        r"'([^']*)'|"              # straight single quotes
        r'\u201c([^\u201d]*)\u201d|'  # curly double quotes
        r'\u2018([^\u2019]*)\u2019|'  # curly single quotes
        r'([^\s/>]+)'              # unquoted fallback
        r')',
        tag_open_text, flags=re.IGNORECASE
    )
    if not m:
        return None
    for g in m.groups():
        if g is not None:
            return _sanitize_ref_name(g)
    return ""


def _scan_ref_tags(wikitext: str, ignored_spans, reuses=None):
    """Scan ``<ref>`` tags. Content-bearing tags are returned as candidates;
    self-closing ``<ref name="X" />`` tags are appended to ``reuses`` (one
    entry per occurrence, with offset) and produce no candidate."""
    results = []
    n = len(wikitext)
    i = 0
    lower = wikitext.lower()

    while i < n:
        start = lower.find("<ref", i)
        if start == -1:
            break
        if _span_contains(start, ignored_spans):
            i = start + 4
            continue

        # Parse opening tag up to '>' respecting quoted attribute values
        j = start + 4
        in_quote = None
        while j < n:
            ch = wikitext[j]
            if in_quote:
                closing = {'"': '"', "'": "'", '\u201c': '\u201d', '\u2018': '\u2019'}
                if ch == closing.get(in_quote, in_quote):
                    in_quote = None
            else:
                if ch in ('"', "'", '\u201c', '\u2018'):
                    in_quote = ch
                elif ch == ">":
                    break
            j += 1
        if j >= n:
            break

        tag_open_end = j + 1
        tag_open_text = wikitext[start:tag_open_end]
        ref_name = _extract_ref_name_from_tag_open(tag_open_text)

        # Determine self-closing
        self_closing = False
        k = tag_open_end - 2
        while k > start and wikitext[k].isspace():
            k -= 1
        if k > start and wikitext[k] == "/":
            self_closing = True

        if self_closing:
            end = tag_open_end
            if reuses is not None and ref_name:
                reuses.append({
                    "ref_name": ref_name,
                    "offset_start": start,
                    "length": end - start,
                })
            i = end
            continue

        close_start = lower.find("</ref>", tag_open_end)
        if close_start == -1:
            # Malformed / unclosed tag; treat opening tag as the reference
            end = tag_open_end
        else:
            end = close_start + len("</ref>")

        results.append({
            "raw_reference": wikitext[start:end],
            "offset_start": start,
            "offset_end": end,
            "reference_name": ref_name,
        })
        i = end

    return results




def _scan_sfn_templates(wikitext: str, ignored_spans, occupied_spans, domain: str = "en.wikipedia.org"):
    """Standalone shorthand templates (``wikis.yaml`` ``shorthand_templates``)."""
    results = []
    n = len(wikitext)
    i = 0
    shorthand = set(get_shorthand_templates(domain))

    while i < n:
        start = wikitext.find("{{", i)
        if start == -1:
            break
        if _span_contains(start, ignored_spans) or any(_span_overlaps(start, start + 2, s, e) for s, e in occupied_spans):
            i = start + 2
            continue

        # Read template name up to '|' or '}}'
        j = start + 2
        while j < n and wikitext[j].isspace():
            j += 1
        name_start = j
        while j < n and wikitext[j] not in ("|", "}"):
            j += 1
        name = wikitext[name_start:j]
        name = _sanitize_extracted_name(name) or ""
        norm = _normalize_template_name(name)
        if norm not in shorthand:
            i = start + 2
            continue

        # Balanced brace scan
        depth = 0
        k = start
        while k < n - 1:
            if wikitext.startswith("{{", k):
                depth += 1
                k += 2
                continue
            if wikitext.startswith("}}", k):
                depth -= 1
                k += 2
                if depth == 0:
                    end = k
                    results.append({
                        "raw_reference": wikitext[start:end],
                        "offset_start": start,
                        "offset_end": end,
                        "reference_name": None,
                    })
                    break
                continue
            k += 1

        i = start + 2

    return results


_LEVEL2_HEADING_RE = re.compile(r"(?m)^==(?!=)\s*(.*?)\s*==(?!=)\s*$")


def _iter_level2_sections(wikitext: str):
    """Yield (title_text, section_start, section_end, body_start) sections.

    title_text for the lead section is "".
    """
    matches = list(_LEVEL2_HEADING_RE.finditer(wikitext))
    if not matches:
        yield "", 0, len(wikitext), 0
        return

    # Lead
    first = matches[0]
    yield "", 0, first.start(), 0

    for idx, m in enumerate(matches):
        title = m.group(1).strip()
        body_start = m.end() + (1 if m.end() < len(wikitext) and wikitext[m.end():m.end() + 1] == "\n" else 0)
        section_start = m.start()
        section_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(wikitext)
        yield title, section_start, section_end, body_start


def _has_unclosed_braces(text: str) -> bool:
    depth = 0
    i = 0
    while i < len(text) - 1:
        if text[i] == '{' and text[i + 1] == '{':
            depth += 1
            i += 2
        elif text[i] == '}' and text[i + 1] == '}':
            depth -= 1
            i += 2
        else:
            i += 1
    return depth > 0


def _extract_list_items_with_offsets(section_text: str, base_offset: int):
    items = []
    pos = 0
    n = len(section_text)
    current_start = None
    current_end = None
    current_text = ""
    inside_item = False

    while pos < n:
        line_end = section_text.find("\n", pos)
        if line_end == -1:
            line_end = n
            line_nl_len = 0
        else:
            line_nl_len = 1

        line = section_text[pos:line_end]

        if line.startswith("*") or line.startswith("#"):
            if inside_item and current_start is not None and current_end is not None:
                items.append((current_text, current_start, current_end))
            inside_item = True
            current_start = base_offset + pos
            current_text = line
            current_end = base_offset + line_end
        elif inside_item and (line.startswith(" ") or _has_unclosed_braces(current_text)):
            current_text += "\n" + line
            current_end = base_offset + line_end
        elif not (line.startswith(" ") or line.startswith("*") or line.startswith("#")):
            if inside_item and current_start is not None and current_end is not None:
                items.append((current_text, current_start, current_end))
            inside_item = False
            current_start = None
            current_end = None
            current_text = ""

        pos = line_end + line_nl_len

    if inside_item and current_start is not None and current_end is not None:
        items.append((current_text, current_start, current_end))

    return items


def _scan_list_item_references(wikitext: str, ignored_spans, occupied_spans, found_urls, domain: str = "en.wikipedia.org"):
    results = []
    ref_sections = get_reference_sections(domain)
    for title, _section_start, section_end, body_start in _iter_level2_sections(wikitext):
        # Only scan body text (skip heading line itself)
        section_body = wikitext[body_start:section_end]
        title_text = title.strip()
        title_norm = title_text.lower()

        for raw_item, start, end in _extract_list_items_with_offsets(section_body, body_start):
            if _span_contains(start, ignored_spans) or any(_span_overlaps(start, end, s, e) for s, e in occupied_spans):
                continue

            extracted_urls = extract_urls_from_text(raw_item)
            keep = len(extracted_urls) > 0 or title_norm in ref_sections
            if not keep:
                continue

            for url in extracted_urls:
                found_urls.add(url)

            results.append({
                "raw_reference": raw_item,
                "offset_start": start,
                "offset_end": end,
                "reference_name": None,
            })
            occupied_spans.append((start, end))

    return results


_BRACKETED_EXTLINK_RE = re.compile(r"\[(?:git|https?|ftps?)://")


def _scan_external_links(wikitext: str, ignored_spans, occupied_spans, found_urls):
    results = []
    n = len(wikitext)

    # 1) Bracketed external links: [http://... label]
    for m in _BRACKETED_EXTLINK_RE.finditer(wikitext):
        start = m.start()
        if _span_contains(start, ignored_spans) or any(_span_overlaps(start, start + 1, s, e) for s, e in occupied_spans):
            continue
        end = wikitext.find("]", start + 1)
        if end == -1:
            continue
        end += 1
        if any(_span_overlaps(start, end, s, e) for s, e in occupied_spans):
            continue
        raw = wikitext[start:end]
        urls = extract_urls_from_text(raw)
        if any(u in found_urls for u in urls):
            continue
        results.append({
            "raw_reference": raw,
            "offset_start": start,
            "offset_end": end,
            "reference_name": None,
        })

    # 2) Bare URLs
    url_regex = re.compile(r'(?:git|https?|ftps?)://[^\s\]\|\}]+')
    for m in url_regex.finditer(wikitext):
        start = m.start()
        end = m.end()
        if _span_contains(start, ignored_spans) or any(_span_overlaps(start, end, s, e) for s, e in occupied_spans):
            continue
        url = m.group(0)
        if url in found_urls:
            continue
        results.append({
            "raw_reference": url,
            "offset_start": start,
            "offset_end": end,
            "reference_name": None,
        })

    return results

def extract_all(wikitext, domain: str = "en.wikipedia.org"):
    """Extract references and named-ref reuse events from wikitext.

    Returns ``{"references": [...], "reuses": [...]}``.

    Each reference dict has:
    - raw_reference: the exact raw reference text (HTML comments removed)
    - offset_start / length: character offsets in the decoded wikitext
    - reference_type: int enum (0=other, 1=inline, 2=endnote)
    - candidate_kind: which scanner found it: 'ref' | 'shorthand' | 'list_item' | 'external_link'
    - citation_type: one of CITATION_TYPES (see classify_citation_type)
    - reference_name: the ``name=`` attribute of a <ref>, else None
    - templates: template calls inside the reference
    - urls: URLs inside the reference, sorted

    Each reuse dict (one per self-closing ``<ref name="X" />`` occurrence) has
    ``ref_name``, ``offset_start`` and ``length``. Reuses are not references:
    they resolve to the defining citation through ref_name_links (Stage 5).
    """
    ignored_spans = _find_comment_spans(wikitext)
    found_urls = set()
    occupied_spans = []  # spans for reference types that should suppress external links
    reuses = []

    # 1) <ref>...</ref>; <ref ... /> becomes a reuse event
    ref_candidates = _scan_ref_tags(wikitext, ignored_spans, reuses)
    for c in ref_candidates:
        c["candidate_kind"] = "ref"
        occupied_spans.append((c["offset_start"], c["offset_end"]))
        for url in extract_urls_from_text(c["raw_reference"]):
            found_urls.add(url)
    for r in reuses:
        occupied_spans.append((r["offset_start"], r["offset_start"] + r["length"]))

    # 2) standalone shorthand templates (balanced braces), skipping those inside refs
    sfn_candidates = _scan_sfn_templates(wikitext, ignored_spans, occupied_spans, domain=domain)
    for c in sfn_candidates:
        c["candidate_kind"] = "shorthand"
        occupied_spans.append((c["offset_start"], c["offset_end"]))
        for url in extract_urls_from_text(c["raw_reference"]):
            found_urls.add(url)

    # 3) List items by section + line scanning, using section-title rules
    list_candidates = _scan_list_item_references(wikitext, ignored_spans, occupied_spans, found_urls, domain=domain)
    for c in list_candidates:
        c["candidate_kind"] = "list_item"

    # 4) External links not attached to any other reference type
    external_candidates = _scan_external_links(wikitext, ignored_spans, occupied_spans, found_urls)
    for c in external_candidates:
        c["candidate_kind"] = "external_link"

    candidates = ref_candidates + sfn_candidates + list_candidates + external_candidates

    # Build final results preserving the existing return shape and roughly the old dedupe semantics
    results = []
    used_spans = []
    seen_texts = set()

    for c in candidates:
        ref_text = re.sub(r'<!--.*?-->', '', c["raw_reference"])
        start = c.get("offset_start")
        end = c.get("offset_end")
        if ref_text in seen_texts:
            continue
        if start is None or end is None:
            continue
        if any(_span_overlaps(start, end, s, e) for s, e in used_spans):
            # Try later occurrences of the same raw text (if any)
            continue

        seen_texts.add(ref_text)
        used_spans.append((start, end))
        templates = extract_templates_from_text(ref_text)
        results.append({
            "raw_reference": ref_text,
            "offset_start": start,
            "length": end - start,
            "reference_type": classify_reference_type(ref_text, domain=domain),
            "candidate_kind": c["candidate_kind"],
            "citation_type": classify_citation_type(c["candidate_kind"], ref_text, templates, domain=domain),
            "reference_name": c.get("reference_name"),
            "templates": templates,
            "urls": sorted(list(extract_urls_from_text(ref_text))),
        })

    reuses.sort(key=lambda r: r["offset_start"])
    return {"references": results, "reuses": reuses}


def extract_references(wikitext, include_offsets: bool = False, domain: str = "en.wikipedia.org"):
    """The references of ``extract_all`` (kept for callers that want a list).

    ``include_offsets`` is accepted for compatibility; offsets are always
    included. Self-closing ``<ref name="X" />`` tags are no longer returned —
    use ``extract_all`` for the reuse events.
    """
    return extract_all(wikitext, domain=domain)["references"]


def extract_references_from_page(title, domain="en.wikipedia.org", as_of=None):
    if as_of is None:
        as_of = get_current_timestamp()
    title = title.replace(" ", "_")
    page_id, revision_id, revision_timestamp, wikitext = get_wikipedia_article(domain, title, as_of)
    return page_id, revision_id, revision_timestamp, extract_references(wikitext, domain=domain)
