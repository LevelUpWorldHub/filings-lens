# Fixtures

`edgar/` holds trimmed recordings of public SEC EDGAR responses for Apple Inc.
(CIK 0000320193): `company_tickers.json` (3 tickers), the submissions JSON
(filings since 2024), and the primary documents plus `index.json` for:

| accession | form | filed |
|---|---|---|
| 0000320193-25-000079 | 10-K | 2025-10-31 |
| 0000320193-24-000123 | 10-K | 2024-11-01 |
| 0000320193-25-000073 | 10-Q | 2025-08-01 |
| 0000320193-25-000077 | 8-K  | 2025-10-30 |

Documents are reduced to a few passages per item by `scripts/record_fixtures.py`
(re-rendered as minimal HTML). They are public SEC records, included only to
make tests run offline; they are not complete filings. `manifest.json` maps
each URL to its file, and `FixtureTransport` fails on any URL it does not know,
so tests never reach the network.
