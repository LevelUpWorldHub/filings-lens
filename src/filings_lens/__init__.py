"""filings-lens: cited, read-only semantic questions over SEC EDGAR filings.

Research tooling only. Nothing in this package places orders, connects to a
brokerage, or produces investment advice.
"""

__version__ = "0.1.0"

from filings_lens.models import Answer, Citation, Claim, Filing, Refusal  # noqa: E402

__all__ = ["Answer", "Citation", "Claim", "Filing", "Refusal", "__version__"]
