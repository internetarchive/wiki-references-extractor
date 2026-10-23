from refs_extractor.article import CITATION_TYPES, classify_citation_type, extract_all, extract_references, extract_urls_from_text, strip_ref_wrapper


def _by_raw(results):
    return {r["raw_reference"]: r for r in results}


def test_extract_references_types_and_offsets_and_dedupe_external_links():
    wikitext = (
        "Lead text. <!-- <ref>https://comment.invalid</ref> -->\n"
        "Inline <ref name=foo>https://example.com/a</ref> then more.\n"
        "And a short footnote {{Sfn|Smith|2020|p=12}} here.\n"
        "\n"
        "==External links==\n"
        "* [https://archive.org Internet Archive]\n"
        "\n"
        "==Other section==\n"
        "* No links here\n"
        "* Has a bare url https://example.com/b\n"
        "\n"
        "Standalone https://example.com/c at end.\n"
    )

    results = extract_references(wikitext, include_offsets=True)
    by_raw = _by_raw(results)

    ref_raw = "<ref name=foo>https://example.com/a</ref>"
    assert ref_raw in by_raw
    assert by_raw[ref_raw]["reference_name"] == "foo"
    assert by_raw[ref_raw]["offset_start"] == wikitext.find(ref_raw)
    assert by_raw[ref_raw]["length"] == len(ref_raw)

    sfn_raw = "{{Sfn|Smith|2020|p=12}}"
    assert sfn_raw in by_raw
    assert by_raw[sfn_raw]["reference_name"] is None
    assert by_raw[sfn_raw]["offset_start"] == wikitext.find(sfn_raw)

    list_raw = "* [https://archive.org Internet Archive]"
    assert list_raw in by_raw
    assert by_raw[list_raw]["offset_start"] == wikitext.find(list_raw)

    # Bare URL list item in non-reference section should be included
    item_raw = "* Has a bare url https://example.com/b"
    assert item_raw in by_raw

    # Standalone URL should be included, but URL inside <ref> should not be emitted as standalone
    assert "https://example.com/c" in by_raw
    assert "https://example.com/a" not in by_raw


def test_self_closing_refs_are_reuse_events_not_references():
    wikitext = 'X <ref name=bar /> Y <ref name="bar"/> Z <ref name="baz" group="n" /> <ref name=qux>body</ref> <ref name=qux />'
    out = extract_all(wikitext)
    # no reference is emitted for a self-closing tag, in either API
    assert [r["raw_reference"] for r in out["references"]] == ["<ref name=qux>body</ref>"]
    assert extract_references(wikitext) == out["references"]
    # one reuse per occurrence, in document order, with offsets — the same
    # text twice is NOT collapsed the way reference texts are
    reuses = out["reuses"]
    assert [r["ref_name"] for r in reuses] == ["bar", "bar", "baz", "qux"]
    assert reuses[0]["offset_start"] == wikitext.find("<ref name=bar />")
    assert reuses[0]["length"] == len("<ref name=bar />")
    assert reuses[1]["offset_start"] == wikitext.find('<ref name="bar"/>')
    assert reuses[3]["offset_start"] == wikitext.rfind("<ref name=qux />")
    # a self-closing tag without a name is nothing
    assert extract_all("<ref/> <ref />")["reuses"] == []


def test_candidate_kind_and_citation_type():
    wikitext = (
        "A<ref>{{cite web |url=https://e.org/1 |title=T}}</ref> "
        "B<ref name=p>Smith, J. (2001). ''Book''. Press.</ref> "
        "C<ref>https://e.org/2</ref> "
        "D<ref>[https://e.org/3 label text]</ref> "
        "E<ref>see [https://e.org/4] and more</ref> "
        "F {{sfn|Smith|2001|p=3}} G {{harvnb|Jones|1999}} H {{Harvp|Lee|2010}}\n"
        "\n==References==\n"
        "* Doe, J. (1990). ''Endnote''.\n"
        "\n==Text==\n"
        "Bare https://e.org/5 and [https://e.org/6 bracketed].\n"
    )
    refs = extract_references(wikitext)
    kinds = {r["raw_reference"]: (r["candidate_kind"], r["citation_type"]) for r in refs}
    assert kinds["<ref>{{cite web |url=https://e.org/1 |title=T}}</ref>"] == ("ref", "template")
    assert kinds["<ref name=p>Smith, J. (2001). ''Book''. Press.</ref>"] == ("ref", "ref_tag")
    assert kinds["<ref>https://e.org/2</ref>"] == ("ref", "bare_url")
    assert kinds["<ref>[https://e.org/3 label text]</ref>"] == ("ref", "bare_url")
    assert kinds["<ref>see [https://e.org/4] and more</ref>"] == ("ref", "ref_tag")
    assert kinds["{{sfn|Smith|2001|p=3}}"] == ("shorthand", "shorthand")
    assert kinds["{{harvnb|Jones|1999}}"] == ("shorthand", "shorthand")
    assert kinds["{{Harvp|Lee|2010}}"] == ("shorthand", "shorthand")
    assert kinds["* Doe, J. (1990). ''Endnote''."] == ("list_item", "endnote")
    assert kinds["https://e.org/5"] == ("external_link", "external_link")
    assert kinds["[https://e.org/6 bracketed]"] == ("external_link", "external_link")
    assert {t for _, t in kinds.values()} <= set(CITATION_TYPES)


def test_citation_type_uses_domain_template_config():
    tpl = [{"template_name": "Cita web"}]
    assert classify_citation_type("ref", "<ref>{{Cita web|url=x}}</ref>", tpl, domain="it.wikipedia.org") == "template"
    assert classify_citation_type("ref", "<ref>{{Cita web|url=x}}</ref>", tpl, domain="en.wikipedia.org") == "ref_tag"
    assert classify_citation_type("ref", "<ref>{{Citation|title=x}}</ref>", [{"template_name": "Citation"}]) == "template"
    assert classify_citation_type("ref", "<ref>{{cite_book|title=x}}</ref>", [{"template_name": "cite_book"}]) == "template"
    # it.wikipedia does not list {{harvp}} as shorthand
    assert [r["citation_type"] for r in extract_references("A {{harvp|X|2000}} B", domain="it.wikipedia.org")] == []
    assert [r["citation_type"] for r in extract_references("A {{harvnb|X|2000}} B", domain="it.wikipedia.org")] == ["shorthand"]


def test_strip_ref_wrapper():
    assert strip_ref_wrapper('<ref name="a" group=n>inner</ref>') == "inner"
    assert strip_ref_wrapper("<REF>x</REF >") == "x"
    assert strip_ref_wrapper("{{sfn|A|2000}}") == "{{sfn|A|2000}}"
    assert strip_ref_wrapper("<ref>unclosed") == "unclosed"


def test_scheme_without_host_is_not_a_link():
    """Rehearsal-shard finding: ``<nowiki>http://</nowiki>`` (help text) and
    ``[http:// vandalism]`` / ``[http://\\nwww.x.com]`` were extracted as
    external links with no URL in them. MediaWiki renders all of these as
    text: a URL needs at least one URL character after the scheme, a
    bracketed link's URL starts right after ``[``, and ``]`` is on the same line."""
    wikitext = (
        "Type <nowiki>http://</nowiki>'' then the address.\n"
        "[http:// LIAR! LIAR! archives.cnn.com/2000/story]\n"
        "[http://\nwww.example.com/poll.htm]\n"
        "ftp://</nowiki>''at\n"
        "A real one: [https://e.org/ok label] and https://e.org/bare\n"
    )
    refs = extract_references(wikitext)
    assert sorted(r["raw_reference"] for r in refs) == ["[https://e.org/ok label]", "https://e.org/bare"]
    assert extract_urls_from_text('see http://</nowiki> and "https://e.org/q?a=1" or <https://e.org/r>') == {"https://e.org/q?a=1", "https://e.org/r"}
    # the same rule for the bare_url ref classification
    assert classify_citation_type("ref", "<ref>http://</nowiki></ref>", []) == "ref_tag"
    assert classify_citation_type("ref", "<ref>[http:// label]</ref>", []) == "ref_tag"
    assert classify_citation_type("ref", "<ref>[https://e.org/x label]</ref>", []) == "bare_url"


def test_template_cache_gives_same_results_and_reuses_entries():
    rev1 = (
        "A <ref>{{cite web|url=https://example.com/a|title=A}}</ref> "
        "B <ref name=b>{{cite book|title=B|year=2001}}</ref>\n"
    )
    rev2 = rev1 + "C <ref>{{cite news|title=C}}</ref>\n"
    cache = {}
    first = extract_all(rev1, template_cache=cache)
    assert first == extract_all(rev1)
    assert len(cache) == 2
    second = extract_all(rev2, template_cache=cache)
    assert second == extract_all(rev2)
    assert len(cache) == 3
    # the repeated reference's templates come from the cache, not a fresh parse
    a_text = "<ref>{{cite web|url=https://example.com/a|title=A}}</ref>"
    assert _by_raw(second["references"])[a_text]["templates"] is cache[a_text]


def test_span_set_matches_linear_overlap_check():
    import random

    from refs_extractor.article import _span_overlaps, _SpanSet

    rng = random.Random(7)
    for _ in range(300):
        spans = _SpanSet(rng.randint(0, 60))
        plain = []
        for _ in range(rng.randint(0, 12)):
            s = rng.randint(-3, 70)
            span = (s, s + rng.randint(-2, 15))
            spans.append(span)
            plain.append(span)
            for _ in range(20):
                a = rng.randint(-5, 80)
                b = a + rng.randint(-2, 12)
                assert spans.overlaps(a, b) == any(_span_overlaps(a, b, x, y) for x, y in plain), (plain, a, b)
