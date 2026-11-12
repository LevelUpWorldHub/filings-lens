"""Command line interface: ``filings-lens ask|diff|sections``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from filings_lens import __version__
from filings_lens.backends import get_backend
from filings_lens.diff import diff_item
from filings_lens.documents import ParsedFiling, load_filing
from filings_lens.edgar import EdgarClient, EdgarError, FixtureTransport
from filings_lens.models import DISCLAIMER, Answer
from filings_lens.pipeline import AskOptions, ask

FIXTURES_ENV = "FILINGS_LENS_FIXTURES"


def _client(args: argparse.Namespace) -> EdgarClient:
    fixtures = args.fixtures or os.environ.get(FIXTURES_ENV)
    if fixtures:
        return EdgarClient(transport=FixtureTransport(Path(fixtures)), use_cache=False)
    return EdgarClient(use_cache=not args.no_cache)


def _cik(client: EdgarClient, args: argparse.Namespace) -> str:
    if args.cik:
        return f"{int(args.cik):010d}"
    if args.ticker:
        return client.cik_for_ticker(args.ticker)
    raise EdgarError("pass --ticker or --cik")


def _load(client: EdgarClient, cik: str, form: str, year: int, accession: str | None = None) -> ParsedFiling:
    if accession:
        for f in client.list_filings(cik):
            if f.accession == accession:
                return load_filing(client, f)
        raise EdgarError(f"accession {accession} not found for CIK {cik}")
    return load_filing(client, client.find_filing(cik, form, year))


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--ticker", help="e.g. AAPL")
    p.add_argument("--cik", help="SEC CIK (overrides --ticker)")
    p.add_argument("--form", default="10-K", choices=["10-K", "10-Q", "8-K"])
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--fixtures", help="serve EDGAR from a recorded fixture dir (offline)")
    p.add_argument("--no-cache", action="store_true", help="bypass the on-disk cache")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="filings-lens",
        description="Cited, read-only questions over SEC EDGAR filings. " + DISCLAIMER,
    )
    ap.add_argument("--version", action="version", version=f"filings-lens {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("ask", help="answer a question with citations")
    _common(a)
    a.add_argument("--year", type=int, required=True, help="calendar year the filing was filed")
    a.add_argument("--accession", help="pick an exact filing (e.g. 0000320193-25-000077)")
    a.add_argument("--item", action="append", help="restrict to item(s), e.g. 1A, 7, II.1A")
    a.add_argument(
        "--backend",
        default=os.environ.get("FILINGS_LENS_BACKEND", "mock"),
        help="mock (default, offline) | openai | palimpzest",
    )
    a.add_argument("--top-k", type=int, default=8)
    a.add_argument("question")

    d = sub.add_parser("diff", help="compare an item (default 1A Risk Factors) across two years")
    _common(d)
    d.add_argument("--years", type=int, nargs=2, metavar=("OLD", "NEW"), required=True)
    d.add_argument("--item", default="1A")
    d.add_argument("--limit", type=int, default=20, help="max entries per status in text output")

    s = sub.add_parser("sections", help="list parsed items and passage counts")
    _common(s)
    s.add_argument("--year", type=int, required=True)
    s.add_argument("--accession", help="pick an exact filing")
    return ap


def _print_answer(res, as_json: bool) -> None:
    if as_json:
        print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False))
        return
    if not isinstance(res, Answer):
        print(f"REFUSED: {res.reason}")
        print(f"\n{DISCLAIMER}")
        return
    print(res.answer)
    print("\nCitations:")
    for i, c in enumerate(res.citations, 1):
        print(f"[{i}] {c.short()}\n    {c.source_url}\n    passage {c.passage_id}")
    print(f"\n{DISCLAIMER}")


def cmd_ask(args: argparse.Namespace) -> int:
    client = _client(args)
    cik = _cik(client, args)
    doc = _load(client, cik, args.form, args.year, args.accession)
    backend = get_backend(args.backend)
    prior = None
    from filings_lens.pipeline import is_novelty_question

    if doc.filing.form in {"10-K", "10-Q"} and is_novelty_question(args.question):
        try:
            prior = _load(client, cik, doc.filing.form, int(doc.filing.filing_date[:4]) - 1)
        except EdgarError as exc:
            print(f"note: no prior-year {args.form} to compare against ({exc})", file=sys.stderr)
    res = ask(args.question, doc, backend, AskOptions(items=args.item, top_k=args.top_k), prior=prior)
    _print_answer(res, args.json)
    return 0 if isinstance(res, Answer) else 2


def cmd_diff(args: argparse.Namespace) -> int:
    client = _client(args)
    cik = _cik(client, args)
    old_y, new_y = args.years
    old, new = _load(client, cik, args.form, old_y), _load(client, cik, args.form, new_y)
    res = diff_item(old, new, item=args.item)
    if args.json:
        out = res.to_dict()
        out["disclaimer"] = DISCLAIMER
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    print(f"{new.filing.company} {args.form} Item {args.item}: {old.filing.filing_date} -> {new.filing.filing_date}")
    print(f"unchanged passages: {res.unchanged}")
    for status in ("added", "modified", "removed"):
        entries = res.by_status(status)
        print(f"\n{status.upper()} ({len(entries)})")
        for e in entries[: args.limit]:
            c = e.citation
            snippet = c.quote[:200].replace("\n", " ")
            print(f"- {snippet}{'...' if len(c.quote) > 200 else ''}")
            print(f"  [{c.accession} Item {c.item} chars {c.start}-{c.end}] {c.source_url}")
    print(f"\n{DISCLAIMER}")
    return 0


def cmd_sections(args: argparse.Namespace) -> int:
    client = _client(args)
    doc = _load(client, _cik(client, args), args.form, args.year, args.accession)
    rows = [
        {"item": s.item, "title": s.title, "start": s.start, "end": s.end, "passages": len(doc.passages_for([s.item]))}
        for s in doc.sections
    ]
    if args.json:
        print(json.dumps({"accession": doc.filing.accession, "sections": rows}, indent=2, ensure_ascii=False))
    else:
        print(f"{doc.filing.company} {doc.filing.form} {doc.filing.accession} ({doc.filing.filing_date})")
        for r in rows:
            print(f"  Item {r['item']:<6} {r['title'][:60]:<60} {r['passages']:>4} passages")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return {"ask": cmd_ask, "diff": cmd_diff, "sections": cmd_sections}[args.cmd](args)
    except (EdgarError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
