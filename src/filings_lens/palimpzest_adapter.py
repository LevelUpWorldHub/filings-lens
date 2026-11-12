"""Optional adapter that runs the extract step with MIT DSG's Palimpzest.

Palimpzest (https://github.com/mitdbg/palimpzest, MIT license) is a declarative
system for semantic operators (``sem_filter``, ``sem_map``, ...) with a
cost-based optimizer. filings-lens treats it as an *optional engine*: install
with ``pip install "filings-lens[palimpzest]"`` and configure model credentials
the way Palimpzest expects (e.g. ``OPENAI_API_KEY``). Model calls may cost money.

Every Palimpzest output still passes through filings-lens citation
verification, so quotes that are not verbatim are discarded.
"""

from __future__ import annotations

import os
from typing import Any

from filings_lens.backends.base import RawClaim
from filings_lens.parse import Passage


def palimpzest_available() -> bool:
    try:
        import palimpzest  # noqa: F401
    except Exception:
        return False
    return True


class PalimpzestNotInstalledError(RuntimeError):
    pass


QUOTE_COL = {
    "name": "quote",
    "type": str,
    "desc": "A sentence copied VERBATIM from `text` that answers the question; empty string if none.",
}
CLAIM_COL = {
    "name": "claim",
    "type": str,
    "desc": "One-sentence factual restatement of the quote. No investment advice.",
}


class PalimpzestBackend:
    name = "palimpzest"

    def __init__(self, policy: str = "min_cost", pz: Any = None) -> None:
        if pz is None:
            try:
                import palimpzest as pz  # type: ignore[no-redef]
            except Exception as exc:  # pragma: no cover - depends on env
                raise PalimpzestNotInstalledError(
                    'Palimpzest is not installed. pip install "filings-lens[palimpzest]"'
                ) from exc
        self.pz = pz
        self.policy = policy

    @classmethod
    def from_env(cls) -> PalimpzestBackend:
        return cls(policy=os.environ.get("FILINGS_LENS_PZ_POLICY", "min_cost"))

    def _policy(self) -> Any:
        return self.pz.MaxQuality() if self.policy == "max_quality" else self.pz.MinCost()

    def build_dataset(self, question: str, passages: list[Passage], intent: str) -> Any:
        pz = self.pz
        vals = [{"passage_id": p.passage_id, "item": p.item, "text": p.text} for p in passages]
        ds = pz.MemoryDataset(id="filings-lens-passages", vals=vals)
        if intent != "novel":
            ds = ds.sem_filter(
                f"The passage contains information that helps answer: {question}",
                depends_on=["text"],
            )
        return ds.sem_map([QUOTE_COL, CLAIM_COL], depends_on=["text"])

    def extract(self, question: str, passages: list[Passage], intent: str) -> list[RawClaim]:
        if not passages:
            return []
        ds = self.build_dataset(question, passages, intent)
        config = self.pz.QueryProcessorConfig(policy=self._policy(), verbose=False)
        output = ds.run(config)
        rows = output.to_df(cols=["passage_id", "quote", "claim"]).to_dict("records")
        claims = []
        for r in rows:
            quote = (r.get("quote") or "").strip()
            if quote:
                claims.append(RawClaim(text=(r.get("claim") or quote).strip(), passage_id=r["passage_id"], quote=quote))
        return claims
