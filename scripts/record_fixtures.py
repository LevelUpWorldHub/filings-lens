#!/usr/bin/env python3
"""Record small, trimmed EDGAR fixtures for offline tests.

This is the ONLY script in the repo that touches the network, and it is never
run in CI. It needs FILINGS_LENS_USER_AGENT. Recorded filings are trimmed to a
handful of passages per item so the fixtures stay small; SEC filings are public
records.

    FILINGS_LENS_USER_AGENT="Name research you@example.com" python scripts/record_fixtures.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from filings_lens.diff import MODIFIED, _shingles, jaccard  # noqa: E402
from filings_lens.edgar import TICKERS_URL, EdgarClient  # noqa: E402
from filings_lens.models import Filing  # noqa: E402
from filings_lens.parse import html_to_text, split_items, split_passages  # noqa: E402

_PART_LINE = re.compile(r"^PART\s+(?:I{1,3}|IV)\b.*$", re.MULTILINE | re.IGNORECASE)
OUT = ROOT / "tests" / "fixtures" / "edgar"
CIK = "0000320193"
TICKERS = {"AAPL", "MSFT", "NVDA"}
# (accession, form) to record. Newest 10-K first: it drives the 1A selection.
FILINGS = [
    ("0000320193-25-000079", "10-K"),
    ("0000320193-24-000123", "10-K"),
    ("0000320193-25-000073", "10-Q"),
    ("0000320193-25-000077", "8-K"),
]
KEEP_PER_ITEM = {"1": 3, "1A": 6, "1C": 2, "3": 2, "7": 4, "7A": 2, "I.2": 4, "II.1A": 2, "II.1": 2}
DEFAULT_KEEP = 1
MAX_ADDED_1A = 4
MAX_REMOVED_1A = 2


def to_html(lines: list[str], title: str) -> str:
    body = "\n".join(f"<p>{html.escape(line)}</p>" for line in lines)
    return f"<html><head><title>{html.escape(title)}</title></head><body>\n{body}\n</body></html>\n"


def trim(text: str, form: str, accession: str, keep_1a: set[int] | None) -> tuple[list[str], list[str]]:
    secs = split_items(text, form)
    ps = split_passages(text, secs, accession)
    head = text[: secs[0].start].split("\n")
    lines = head[:12] + [ln for ln in head[12:] if ln.lower().startswith(("item", "part"))]
    kept_1a_text: list[str] = []
    prev = secs[0].start
    for sec in secs:
        # keep PART headings that sit between sections (needed for 10-Q keys)
        lines.extend(m.group(0) for m in _PART_LINE.finditer(text, prev, sec.start))
        prev = sec.start + 1
        lines.append(text[sec.start : text.index("\n", sec.start) if "\n" in text[sec.start : sec.end] else sec.end])
        sec_ps = [p for p in ps if p.item == sec.item]
        if sec.item == "1A" and keep_1a is not None:
            chosen = [p for p in sec_ps if p.index in keep_1a]
            kept_1a_text = [p.text for p in chosen]
        else:
            chosen = sec_ps[: KEEP_PER_ITEM.get(sec.item, DEFAULT_KEEP)]
            if sec.item in {"7", "I.2"}:  # keep the net sales discussion too
                extra = [p for p in sec_ps if "net sales increased" in p.text.lower() and p not in chosen]
                extra += [p for p in sec_ps if "net sales" in p.text.lower() and p not in chosen + extra]
                chosen = sorted(chosen + extra[:4], key=lambda p: p.index)
            if sec.item == "1":  # and the human capital headcount
                extra = [p for p in sec_ps if "full-time equivalent employees" in p.text and p not in chosen]
                chosen = sorted(chosen + extra[:1], key=lambda p: p.index)
            if sec.item == "1A":
                kept_1a_text = [p.text for p in chosen]
        for p in chosen:
            lines.extend(p.text.split("\n"))
    return lines, kept_1a_text


def main() -> None:
    client = EdgarClient(use_cache=True)
    manifest: dict[str, str] = {}

    tick = client.get_json(TICKERS_URL)
    small = {k: v for k, v in tick.items() if v["ticker"] in TICKERS}
    (OUT / "company_tickers.json").parent.mkdir(parents=True, exist_ok=True)
    (OUT / "company_tickers.json").write_text(json.dumps(small, indent=1))
    manifest[TICKERS_URL] = "company_tickers.json"

    sub = client.submissions(CIK)
    recent = sub["filings"]["recent"]
    keep_idx = [i for i, d in enumerate(recent["filingDate"]) if d >= "2024-01-01"]
    sub_small = {k: sub[k] for k in ("cik", "name", "tickers", "exchanges", "sic", "sicDescription", "fiscalYearEnd")}
    sub_small["filings"] = {"recent": {k: [v[i] for i in keep_idx] for k, v in recent.items()}, "files": []}
    p = OUT / "submissions" / f"CIK{CIK}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sub_small, indent=1))
    manifest[f"https://data.sec.gov/submissions/CIK{CIK}.json"] = str(p.relative_to(OUT))

    filings = {f.accession: f for f in client.list_filings(CIK)}
    new_1a_kept: list[str] = []
    new_all_1a: list[str] = []
    for n, (acc, form) in enumerate(FILINGS):
        f: Filing = filings[acc]
        text = html_to_text(client.primary_document(f))
        keep_1a = None
        if form == "10-K":
            ps = [x for x in split_passages(text, split_items(text, form), acc) if x.item == "1A"]
            sh = [_shingles(x.text) for x in ps]
            if n == 0:
                # first 6 + up to MAX_ADDED_1A passages new vs. the prior 10-K
                prior = filings[FILINGS[1][0]]
                pt = html_to_text(client.primary_document(prior))
                pps = [x for x in split_passages(pt, split_items(pt, "10-K"), prior.accession) if x.item == "1A"]
                psh = [_shingles(x.text) for x in pps]
                sims = [(max(jaccard(s, o) for o in psh), x.index) for x, s in zip(ps, sh)]
                added = [i for sim, i in sorted(sims) if sim < 0.2]  # most novel first
                keep_1a = set(range(6)) | set(added[:MAX_ADDED_1A])
                new_all_1a = [x.text for x in ps]
            else:
                ksh = [_shingles(t) for t in new_1a_kept]
                nsh = [_shingles(t) for t in new_all_1a]
                matches = {x.index for x, s in zip(ps, sh) if max(jaccard(s, k) for k in ksh) >= MODIFIED}
                removed = [x.index for x, s in zip(ps, sh) if max(jaccard(s, k) for k in nsh) < 0.2]
                keep_1a = matches | set(removed[:MAX_REMOVED_1A])
        lines, kept = trim(text, form, acc, keep_1a)
        if n == 0:
            new_1a_kept = kept
        rel = Path("docs") / f.accession_nodash / f.primary_document
        (OUT / rel).parent.mkdir(parents=True, exist_ok=True)
        (OUT / rel).write_text(to_html(lines, f"{f.company} {form} {acc} (trimmed fixture)"))
        manifest[f.document_url] = str(rel)
        idx = client.filing_index(f)
        idx_rel = Path("docs") / f.accession_nodash / "index.json"
        items = [i for i in idx["directory"]["item"] if i["name"] in {f.primary_document, f"{acc}.txt"}]
        (OUT / idx_rel).write_text(
            json.dumps(
                {"directory": {**{k: v for k, v in idx["directory"].items() if k != "item"}, "item": items}}, indent=1
            )
        )
        manifest[f.index_url] = str(idx_rel)

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(f"recorded {len(manifest)} responses into {OUT} ({client.requests_made} live requests)")


if __name__ == "__main__":
    main()
