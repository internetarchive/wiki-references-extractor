import mwparserfromhell
import sys
from list import extract_list_items
from wikiapi import get_current_timestamp, get_wikipedia_article

def extract_references(wikitext):
    wikicode = mwparserfromhell.parse(wikitext)
    reference_sections = ["Further reading", "External links", "Bibliography"]
    references = []

    # Extract <ref> tags content
    for tag in wikicode.filter_tags(matches=lambda node: node.tag == "ref"):
        references.append(str(tag))

    # Extract lines from specific sections
    for section in wikicode.get_sections(levels=[2]):
        section_title = section.filter_headings()
        if section_title:
            title_text = section_title[0].title.strip_code().strip()
            if title_text in reference_sections:
                for line in extract_list_items(section):
                    if line.strip().startswith('*') or line.strip().startswith('#'):
                        references.append(line.strip())
    return references

def extract_references_from_page(title, domain="en.wikipedia.org", as_of=None):
    if as_of is None:
        as_of = get_current_timestamp()
    title = title.replace(" ", "_")
    wikitext = get_wikipedia_article(domain, title, as_of)
    return extract_references(wikitext)

if __name__ == "__main__":
    page_title = "Easter Island"
    as_of = None
    if len(sys.argv) >= 2:
        page_title = sys.argv[1]
        if len(sys.argv) == 3:
            as_of = sys.argv[2]

    for ref in extract_references_from_page(page_title, as_of=as_of):
        print(ref, end="\n\n")
