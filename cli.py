import argparse
import json
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="refs_extractor",
        description=(
            "Extract Wikipedia references from a given article title, optionally as of a timestamp."
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Print full JSON output (metadata + references). By default prints references only.",
    )
    parser.add_argument(
        "title",
        help='Wikipedia article title (e.g. "Easter Island").',
    )
    parser.add_argument(
        "timestamp",
        nargs="?",
        default=None,
        help=(
            "Optional timestamp in YYYY-MM-DDTHH:MM:SSZ format. "
            "If omitted, uses the current timestamp."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Local import so importing this module does not force optional runtime deps.
    # Support both:
    #   - `python3 -m refs_extractor ...` (package context, relative imports work)
    #   - `python3 refs_extractor/cli.py ...` (script context, no parent package)
    try:
        from .article import extract_references_from_page
        from .wikiapi import get_current_timestamp
    except ImportError:
        # When executed as a script, `__package__` is typically None and relative
        # imports fail. Add the project root (parent of `refs_extractor/`) so
        # `import refs_extractor.*` works.
        project_root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(project_root))
        from refs_extractor.article import extract_references_from_page
        from refs_extractor.wikiapi import get_current_timestamp

    parser = build_parser()
    args = parser.parse_args(argv)

    as_of = args.timestamp or get_current_timestamp()

    try:
        page_id, revision_id, revision_timestamp, refs = extract_references_from_page(
            args.title,
            as_of=as_of,
        )
    except Exception as e:
        # Surface a readable error for CLI users; keep the exception available via -vv in shells.
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if page_id is None:
        print(
            f"Article not found (or did not exist) at timestamp {as_of}: {args.title}",
            file=sys.stderr,
        )
        return 2

    if not args.full:
        refs_text = []
        for ref in refs:
            if isinstance(ref, dict) and "raw_reference" in ref:
                refs_text.append(str(ref["raw_reference"]))
            else:
                refs_text.append(str(ref))
        if refs_text:
            sys.stdout.write("\n\n".join(refs_text))
            sys.stdout.write("\n")
        return 0

    output = {
        "title": args.title,
        "as_of": as_of,
        "page_id": page_id,
        "revision_id": revision_id,
        "revision_timestamp": revision_timestamp,
        "references": refs,
    }
    json.dump(output, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
