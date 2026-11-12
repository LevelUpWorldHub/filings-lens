"""Citation-accuracy evaluation over hand-labeled fixture questions.

Metrics per question (answered questions only, unless noted):

* ``valid``     - every citation's quote equals ``document_text[start:end]``
* ``item_ok``   - the top citation is from an expected item
* ``evidence``  - some citation quote contains the hand-labeled ``expect_quote``
* ``refusal_ok``- for ``expect_refusal`` questions, the system refused
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from filings_lens.backends import get_backend
from filings_lens.documents import ParsedFiling, load_filing, verify_citation
from filings_lens.edgar import EdgarClient, FixtureTransport
from filings_lens.models import Answer
from filings_lens.pipeline import AskOptions, ask, is_novelty_question


@dataclass
class EvalReport:
    rows: list[dict[str, Any]] = field(default_factory=list)

    def score(self, key: str) -> float:
        vals = [r[key] for r in self.rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else 1.0

    def summary(self) -> dict[str, float]:
        return {k: round(self.score(k), 3) for k in ("valid", "item_ok", "evidence", "refusal_ok")}

    @property
    def overall(self) -> float:
        s = self.summary()
        return round(sum(s.values()) / len(s), 3)


def _doc(client: EdgarClient, q: dict[str, Any], cache: dict[str, ParsedFiling]) -> ParsedFiling:
    cik = client.cik_for_ticker(q.get("ticker", "AAPL"))
    if q.get("accession"):
        f = next(f for f in client.list_filings(cik) if f.accession == q["accession"])
    else:
        f = client.find_filing(cik, q["form"], q["year"])
    if f.accession not in cache:
        cache[f.accession] = load_filing(client, f)
    return cache[f.accession]


def run_eval(
    questions_path: Path, fixtures: Path, backend_name: str = "mock", user_agent: str | None = None
) -> EvalReport:
    questions = json.loads(Path(questions_path).read_text())
    client = EdgarClient(
        user_agent=user_agent or "filings-lens-eval offline-fixtures@example.invalid",
        transport=FixtureTransport(fixtures),
        use_cache=False,
    )
    backend = get_backend(backend_name)
    cache: dict[str, ParsedFiling] = {}
    report = EvalReport()
    for q in questions:
        doc = _doc(client, q, cache)
        prior = None
        if is_novelty_question(q["question"]) and doc.filing.form in {"10-K", "10-Q"}:
            prior = _doc(client, {**q, "accession": None, "year": int(doc.filing.filing_date[:4]) - 1}, cache)
        res = ask(q["question"], doc, backend, AskOptions(), prior=prior)
        row: dict[str, Any] = {
            "id": q["id"],
            "status": "answered" if isinstance(res, Answer) else "refused",
            "valid": None,
            "item_ok": None,
            "evidence": None,
            "refusal_ok": None,
        }
        if q.get("expect_refusal"):
            row["refusal_ok"] = not isinstance(res, Answer)
        elif isinstance(res, Answer):
            cites = res.citations
            row["valid"] = all(verify_citation(doc, c) for c in cites)
            row["item_ok"] = cites[0].item in q["expect_items"]
            row["evidence"] = any(q["expect_quote"] in c.quote for c in cites)
        else:
            row.update(valid=True, item_ok=False, evidence=False)
        report.rows.append(row)
    return report
