# wiki-references-extractor

The `wiki-references-extractor` is a component in the third-generation Wikipedia Citations Database. It is built to support the `wiki-references-db` (which builds a database of these extracted references) and the Internet Archive Reference Explorer (which provides similar data as an API).

In this context, a Wikipedia article "reference" includes:

- In-line citations
-- Anything between `<ref>` and `</ref>` tags, inclusive of the tags themselves.
-- A call of the `{{Sfn}}` template.
- Endnotes
-- A list item (ordered or unordered) in certain sections like "Bibliography", "Further reading", or "External links" sections with any content.
- Other references
-- A list item (ordered or unordered) in any section with a link on it
- Any standalone external link that is not a part of any other reference.

References can contain any arbitrary wikitext.

## Setup

1. `git clone https://github.com/internetarchive/wiki-references-extractor refs_extractor`

2. `cd refs_extractor`

3. `python3 -m venv venv`

4. `source venv/bin/activate`

5. `pip3 install -r requirements.txt`

6. Copy `example.env` to `.env` and configure your contact email. Optionally, add a secondary product token to the User-Agent:

```
CONTACT_EMAIL=your-email@example.com
# Example optional secondary token appended to User-Agent:
# SECONDARY_USER_AGENT=YourApp/2.3
```

## Command-line usage

First, make sure you have the virtual environment activated:

`source venv/bin/activate`

To get a list of wikitext reference strings for an article, run the extractor with the name of the title. Use quote marks if there are spaces, or use underscores in place of spaces.

`python3 -m refs_extractor "Easter Island"`

By default, each reference is printed as raw wikitext, separated by two newlines. This is to help visually distinguish between individual references when there are multi-line reference strings.

To print the full JSON output (including page/revision metadata and per-reference extracted fields), add `--full`:

`python3 -m refs_extractor --full "Easter Island"`

To request references for an article as of a certain point in time, specify a timestamp in the `YYYY-MM-DDTHH:mm:ssZ` format:

`python3 -m refs_extractor "Easter Island" 2004-01-01T00:00:00Z`

## Usage in code

First, make sure that the dependencies in `requirements.txt` are installed.

### From page title

```python
from refs_extractor.article import extract_references_from_page

page_title = "Easter Island"

page_id, revision_id, revision_timestamp, references = extract_references_from_page(page_title)

print(f"Page {page_id}, revision {revision_id} ({revision_timestamp})")
for ref in references:
    print(ref["raw_reference"])
```

By default, pages are retrieved from English Wikipedia. To specify a different MediaWiki site, use the `domain` parameter.

```python
page_id, revision_id, revision_timestamp, references = extract_references_from_page(
    page_title, domain="fr.wikipedia.org"
)
```

You can also look up data for an article at a given point in time using a timestamp in standard `YYYY-MM-DDTHH:mm:ssZ` format:

```python
page_id, revision_id, revision_timestamp, references = extract_references_from_page(
    page_title, as_of="2008-06-01T00:00:00Z"
)
```

### From wikitext

You can also extract directly from wikitext:

```python
from refs_extractor.article import extract_references

wikitext = """
Example wiki article.<ref>https://example.com</ref>

==References==
<references />

==External links==
* [https://archive.org Internet Archive]
"""

references = extract_references(wikitext)

for ref in references:
    print(ref["raw_reference"])
```

Each reference is a dictionary with the following keys:

- `raw_reference`: the exact raw reference text as found in the wikitext
- `offset_start`: starting character offset (inclusive)
- `length`: length of the raw reference in characters
- `reference_type`: int enum describing the type (`0`=other, `1`=inline, `2`=endnote)
- `reference_name`: the name attribute of the `<ref>` tag, if any
- `templates`: list of parsed template calls found within the reference
- `urls`: sorted list of URLs found within the reference
