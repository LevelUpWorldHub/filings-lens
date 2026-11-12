"""Deterministic offline backend: extractive, lexical, zero cost."""

from __future__ import annotations

from filings_lens.backends.base import RawClaim
from filings_lens.parse import Passage
from filings_lens.retrieval import sentences, terms


class MockBackend:
    name = "mock"

    def __init__(self, max_claims: int = 5, max_chars: int = 400) -> None:
        self.max_claims = max_claims
        self.max_chars = max_chars

    def _best_sentence(self, question: str, p: Passage) -> tuple[int, int, int] | None:
        q = set(terms(question))
        best = None
        for s, e in sentences(p.text):
            overlap = len(q & set(terms(p.text[s:e])))
            if overlap and (best is None or overlap > best[0]):
                best = (overlap, s, e)
        return best

    def extract(self, question: str, passages: list[Passage], intent: str) -> list[RawClaim]:
        claims: list[RawClaim] = []
        for p in passages:
            if len(claims) >= self.max_claims:
                break
            if intent == "novel":
                spans = sentences(p.text)
                if not spans:
                    continue
                # skip a bare heading line ("Macroeconomic and Industry Risks")
                full = [sp for sp in spans if p.text[sp[1] - 1] in ".!?:"]
                s, e = (full or spans)[0]
            else:
                hit = self._best_sentence(question, p)
                if hit is None:
                    continue
                _, s, e = hit
            quote = p.text[s:e]
            if len(quote) > self.max_chars:
                quote = quote[: self.max_chars]
            text = quote if len(quote) <= 240 else quote[:237].rstrip() + "..."
            claims.append(RawClaim(text=text, passage_id=p.passage_id, quote=quote))
        return claims
