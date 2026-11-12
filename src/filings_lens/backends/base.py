from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from filings_lens.parse import Passage


@dataclass(frozen=True)
class RawClaim:
    """Backend output before verification.

    ``quote`` must be a verbatim substring of the passage identified by
    ``passage_id``; the pipeline discards any claim whose quote cannot be
    located, so a backend can never introduce an uncited statement.
    """

    text: str
    passage_id: str
    quote: str


class Backend(Protocol):
    name: str

    def extract(self, question: str, passages: list[Passage], intent: str) -> list[RawClaim]:
        """Return supporting claims for ``question`` drawn from ``passages``.

        ``intent`` is ``"lookup"`` (answer from content) or ``"novel"`` (passages
        are already known to be new/changed; summarize each).
        """
        ...
