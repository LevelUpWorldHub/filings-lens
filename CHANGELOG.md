# Changelog

## 0.1.0 (2026-11-11)

First release.

- Polite, read-only EDGAR client: required `FILINGS_LENS_USER_AGENT`, <=10 req/s limiter, on-disk cache, SEC-host allowlist.
- 10-K / 10-Q / 8-K item sectioning (TOC-aware, part-aware for 10-Q) and paragraph passages with stable ids.
- `ask` pipeline: item filter -> BM25 retrieval -> backend extract -> verbatim citation verification -> composed answer; refuses without a citation and refuses advice requests.
- Backends: deterministic offline `mock` (default), env-configured OpenAI-compatible, optional MIT Palimpzest adapter.
- `diff`: added / modified / removed passages in an item (default 1A Risk Factors) across two years.
- Recorded, trimmed Apple Inc. fixtures; pytest + ruff; GitHub Actions CI on Python 3.11 and 3.12.
- `scripts/eval_citations.py`: citation-accuracy eval over hand-labeled questions.
