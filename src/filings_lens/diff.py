"""Compare an item (default: Item 1A Risk Factors) across two filings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from filings_lens.documents import ParsedFiling
from filings_lens.models import Citation
from filings_lens.parse import Passage

UNCHANGED = 0.8
MODIFIED = 0.5


def _shingles(text: str, k: int = 3) -> set[tuple[str, ...]]:
    w = re.findall(r"[a-z0-9]+", text.lower())
    if len(w) < k:
        return {tuple(w)}
    return {tuple(w[i : i + k]) for i in range(len(w) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


@dataclass
class DiffEntry:
    status: str  # added | removed | modified
    similarity: float
    citation: Citation
    previous: Citation | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {"status": self.status, "similarity": round(self.similarity, 3), "citation": self.citation.to_dict()}
        if self.previous is not None:
            d["previous"] = self.previous.to_dict()
        return d


@dataclass
class DiffResult:
    item: str
    old: str
    new: str
    entries: list[DiffEntry] = field(default_factory=list)
    unchanged: int = 0

    def by_status(self, status: str) -> list[DiffEntry]:
        return [e for e in self.entries if e.status == status]

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "old_accession": self.old,
            "new_accession": self.new,
            "unchanged": self.unchanged,
            "added": [e.to_dict() for e in self.by_status("added")],
            "modified": [e.to_dict() for e in self.by_status("modified")],
            "removed": [e.to_dict() for e in self.by_status("removed")],
        }


def resolve_item(doc: ParsedFiling, item: str) -> str:
    keys = {s.item for s in doc.sections}
    if item in keys:
        return item
    if doc.filing.form.upper().startswith("10-Q"):
        mapped = {"1A": "II.1A", "7": "I.2", "3": "II.1", "7A": "I.3"}.get(item, item)
        if mapped in keys:
            return mapped
    return item


def diff_item(old: ParsedFiling, new: ParsedFiling, item: str = "1A") -> DiffResult:
    old_item, new_item = resolve_item(old, item), resolve_item(new, item)
    old_ps: list[Passage] = old.passages_for([old_item])
    new_ps: list[Passage] = new.passages_for([new_item])
    old_sh = [_shingles(p.text) for p in old_ps]
    new_sh = [_shingles(p.text) for p in new_ps]
    res = DiffResult(item=item, old=old.filing.accession, new=new.filing.accession)

    matched_old: set[int] = set()
    for j, p in enumerate(new_ps):
        best_i, best = -1, 0.0
        for i, s in enumerate(old_sh):
            sim = jaccard(new_sh[j], s)
            if sim > best:
                best_i, best = i, sim
        if best >= UNCHANGED:
            res.unchanged += 1
            matched_old.add(best_i)
        elif best >= MODIFIED:
            matched_old.add(best_i)
            res.entries.append(DiffEntry("modified", best, new.cite(p), old.cite(old_ps[best_i])))
        else:
            res.entries.append(DiffEntry("added", best, new.cite(p)))

    for i, p in enumerate(old_ps):
        if i in matched_old:
            continue
        best = max((jaccard(old_sh[i], s) for s in new_sh), default=0.0)
        if best < MODIFIED:
            res.entries.append(DiffEntry("removed", best, old.cite(p)))
    return res
