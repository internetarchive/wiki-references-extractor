# wiki-references-extractor

The `wiki-references-extractor` is a component in the third-generation Wikipedia Citations Database. It is built to support the `wiki-references-db` (which builds a database of these extracted references) and the Internet Archive Reference Explorer (which provides similar data as an API).

In this context, a Wikipedia article "reference" is:
- Anything between `<ref>` and `</ref>` tags, inclusive of the tags themselves, corresponding to an in-line citation.
- A call of the `{{Sfn}}` template which creates an in-line citation
- A line item (ordered or unordered) in the "Bibliography", "Further reading", or "External links" sections, corresponding to an endnote.
- Any standalone external link that is not a part of any other reference.

References can contain any arbitrary wikitext.

## Setup

1. `git clone https://github.com/internetarchive/wiki-references-extractor refs_extractor`

2. `cd refs_extractor`

3. `python3 -m venv venv`

4. `source venv/bin/activate`

5. `pip3 install -r requirements.txt`

## Command-line usage

First, make sure you have the virtual environment activated:

`source venv/bin/activate`

To get a list of wikitext reference strings for an article, run `article.py` with the name of the title. Use quote marks if there are spaces, or use underscores in place of spaces.

`python3 article.py "Easter Island"`

Each reference in the output is separated by two newlines. This is to help visually distinguish between individual references when there are multi-line reference strings.

To request references for an article as of a certain point in time, specify a timestamp in the `YYYY-MM-DDTHH:mm:ssZ` format:

`python3 article.py "Easter Island" 2004-01-01T00:00:00Z`

## Usage in code

First, make sure that the dependencies in `requirements.txt` are installed.

### From page title

```python
from refs_extractor.article import extract_references_from_page

page_title = "Easter Island"

references_list = extract_references_from_page(page_title)

for ref in references_list:
    print(f"Reference found: {ref}")
```

By default, pages are retrieved from English Wikipedia. To specify a different MediaWiki site, use the `domain` parameter.

```python
references_list = extract_references_from_page(page_title, domain="fr.wikipedia.org")
```

You can also look up data for an article at a given point in time using a timestamp in standard `YYYY-MM-DDTHH:mm:ssZ` format:

```python
references_list = extract_references_from_page(page_title, as_of="2008-06-01T00:00:00Z")
```

### From wikicode

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

references_list = extract_references(wikitext)

for ref in references_list:
    print(f"Reference found: {ref}")
```
