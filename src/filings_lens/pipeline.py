"""Filter -> extract -> verify -> aggregate, with mandatory citations."""

from __future__ import annotations

import re
from dataclasses import dataclass

from filings_lens.backends.base import Backend, RawClaim
from filings_lens.diff import diff_item
from filings_lens.documents import ParsedFiling
from filings_lens.models import Answer, Claim, Refusal
from filings_lens.retrieval import rank

# question keyword -> 10-K item
ITEM_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcyber", re.I), "1C"),
    (re.compile(r"\brisk", re.I), "1A"),
    (
        re.compile(
            r"\b(md&a|management'?s discussion|results of operations|liquidity|net sales|revenue|gross margin)", re.I
        ),
        "7",
    ),
    (re.compile(r"\b(legal proceedings|litigation|lawsuit)", re.I), "3"),
    (re.compile(r"\b(market risk|interest rate risk|foreign (exchange|currency) risk)", re.I), "7A"),
    (re.compile(r"\b(business overview|segments?|products|employees|human capital)", re.I), "1"),
]
TEN_Q_MAP = {"1A": "II.1A", "7": "I.2", "3": "II.1", "7A": "I.3", "1C": "II.1A", "1": "I.2"}
NOVELTY = re.compile(r"\b(new|newly|added|changed|change[sd]?|since (the )?(last|prior|previous)|compared)\b", re.I)


def infer_items(question: str, form: str) -> list[str]:
    items: list[str] = []
    for pat, item in ITEM_HINTS:
        if pat.search(question) and item not in items:
            items.append(item)
    if "7A" in items:  # "market risk" questions are not Item 1A questions
        items = ["7A"] + [i for i in items if i not in {"7A", "1A"}]
    if form.upper().startswith("10-Q"):
        items = list(dict.fromkeys(TEN_Q_MAP.get(i, i) for i in items))
    elif not form.upper().startswith("10-K"):
        items = []  # 8-K etc: search everything
    return items


ADVICE = re.compile(
    r"\b(should i (buy|sell|short|hold|invest)|buy or sell|price target|"
    r"is it a (good|bad) (buy|investment)|recommend(ation)? (to )?(buy|sell)|place an? (order|trade))\b",
    re.I,
)


def is_advice_request(question: str) -> bool:
    return bool(ADVICE.search(question))


def is_novelty_question(question: str) -> bool:
    return bool(NOVELTY.search(question))


@dataclass
class AskOptions:
    items: list[str] | None = None
    top_k: int = 8


def _verify(doc_by_pid: dict[str, ParsedFiling], raw: list[RawClaim]) -> list[Claim]:
    claims: list[Claim] = []
    seen_quotes: set[str] = set()
    for rc in raw:
        if rc.quote in seen_quotes:  # filings often repeat boilerplate verbatim
            continue
        doc = doc_by_pid.get(rc.passage_id)
        if doc is None:
            continue
        p = doc.passage(rc.passage_id)
        rel = p.text.find(rc.quote)
        if rel < 0:
            continue  # hallucinated / paraphrased quote -> dropped
        s = p.start + rel
        seen_quotes.add(rc.quote)
        claims.append(Claim(text=rc.text, citations=(doc.cite(p, s, s + len(rc.quote)),)))
    return claims


def _compose(claims: list[Claim]) -> str:
    return "\n".join(f"- {c.text} [{i}]" for i, c in enumerate(claims, 1))


def ask(
    question: str,
    doc: ParsedFiling,
    backend: Backend,
    opts: AskOptions | None = None,
    prior: ParsedFiling | None = None,
) -> Answer | Refusal:
    """Answer ``question`` from ``doc``. If ``prior`` is given and the question
    asks what is new/changed, candidates are restricted to passages that are
    added or modified relative to ``prior``."""
    opts = opts or AskOptions()
    filings = [doc.filing.accession]
    if is_advice_request(question):
        return Refusal(
            question,
            "filings-lens is read-only research tooling and does not give investment advice "
            "or trade recommendations; ask what the filing says instead",
            backend.name,
            filings,
        )
    items = opts.items or infer_items(question, doc.filing.form)

    intent = "lookup"
    if prior is not None and is_novelty_question(question):
        intent = "novel"
        filings.append(prior.filing.accession)
        item = items[0] if items else "1A"
        d = diff_item(prior, doc, item=item if not item.startswith(("I.", "II.")) else item.split(".", 1)[1])
        changed_ids = {e.citation.passage_id for e in d.entries if e.status in {"added", "modified"}}
        # order: added first (document order), then modified
        added = [e.citation.passage_id for e in d.by_status("added")]
        modified = [e.citation.passage_id for e in d.by_status("modified")]
        candidates = [doc.passage(pid) for pid in added + modified if pid in changed_ids]
        candidates = candidates[: opts.top_k]
    else:
        pool = doc.passages_for(items) or doc.passages
        candidates = [p for p, _ in rank(question, pool, opts.top_k)]
        if not candidates and items:
            candidates = [p for p, _ in rank(question, doc.passages, opts.top_k)]

    if not candidates:
        return Refusal(question, "no passage in the filing matched the question", backend.name, filings)

    raw = backend.extract(question, candidates, intent)
    doc_by_pid = {p.passage_id: doc for p in doc.passages}
    claims = _verify(doc_by_pid, raw)
    if not claims:
        return Refusal(
            question,
            "no verifiable citation could be produced; refusing to answer without evidence",
            backend.name,
            filings,
        )
    return Answer(question=question, answer=_compose(claims), claims=claims, backend=backend.name, filings=filings)
