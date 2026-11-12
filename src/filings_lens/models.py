"""Core data types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Filing:
    """Metadata for one EDGAR filing (one accession number)."""

    cik: str  # 10-digit, zero padded
    company: str
    form: str
    accession: str  # 0000320193-25-000079
    filing_date: str  # YYYY-MM-DD
    report_date: str
    primary_document: str

    @property
    def cik_int(self) -> int:
        return int(self.cik)

    @property
    def accession_nodash(self) -> str:
        return self.accession.replace("-", "")

    @property
    def folder_url(self) -> str:
        return f"https://www.sec.gov/Archives/edgar/data/{self.cik_int}/{self.accession_nodash}/"

    @property
    def index_url(self) -> str:
        return self.folder_url + "index.json"

    @property
    def document_url(self) -> str:
        return self.folder_url + self.primary_document


@dataclass(frozen=True)
class Citation:
    """Pointer to the exact passage text supporting a claim.

    ``start``/``end`` are character offsets into the normalized document text
    (see :func:`filings_lens.parse.html_to_text`, ``parser_version``), and
    ``quote == normalized_text[start:end]`` always holds for a valid citation.
    """

    cik: str
    company: str
    accession: str
    form: str
    filing_date: str
    item: str
    item_title: str
    passage_id: str
    start: int
    end: int
    quote: str
    source_url: str
    parser_version: str

    def short(self) -> str:
        return (
            f"{self.company} {self.form} filed {self.filing_date} "
            f"(acc. {self.accession}), Item {self.item}, chars {self.start}-{self.end}"
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Claim:
    text: str
    citations: tuple[Citation, ...]


@dataclass
class Answer:
    question: str
    answer: str
    claims: list[Claim]
    backend: str
    filings: list[str] = field(default_factory=list)

    @property
    def citations(self) -> list[Citation]:
        out: list[Citation] = []
        seen: set[tuple[str, int, int]] = set()
        for claim in self.claims:
            for c in claim.citations:
                key = (c.passage_id, c.start, c.end)
                if key not in seen:
                    seen.add(key)
                    out.append(c)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "answered",
            "question": self.question,
            "answer": self.answer,
            "backend": self.backend,
            "filings": self.filings,
            "claims": [{"text": c.text, "citations": [x.to_dict() for x in c.citations]} for c in self.claims],
            "disclaimer": DISCLAIMER,
        }


@dataclass
class Refusal:
    """Returned instead of an Answer when no verifiable citation exists."""

    question: str
    reason: str
    backend: str
    filings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "refused",
            "question": self.question,
            "reason": self.reason,
            "backend": self.backend,
            "filings": self.filings,
            "disclaimer": DISCLAIMER,
        }


DISCLAIMER = (
    "filings-lens is a research tool. Output is not investment, legal, tax or "
    "accounting advice; verify every citation against the original filing."
)
