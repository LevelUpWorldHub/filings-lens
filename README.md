# filings-lens

[![CI](https://github.com/LevelUpWorldHub/filings-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/LevelUpWorldHub/filings-lens/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)

**Ask questions about SEC EDGAR filings (10-K, 10-Q, 8-K) and get answers where every
statement is cited back to the exact filing, item and character span.**

filings-lens is a small, research-grade tool. It is **read-only**: it only issues GET
requests to public SEC endpoints, and it has no trading, brokerage, order or advice code
paths. When it cannot cite evidence, it refuses to answer.

> **Not investment advice.** filings-lens is a research tool. Its output is not
> investment, legal, tax or accounting advice. Filings can be misparsed and models can
> be wrong, so check every citation against the original filing before relying on it.

## Quickstart

```bash
pip install "git+https://github.com/LevelUpWorldHub/filings-lens@v0.1.0"

# SEC fair-access policy: identify yourself with a contact email
export FILINGS_LENS_USER_AGENT="Jane Doe research jane@example.com"

filings-lens ask --ticker AAPL --form 10-K --year 2025 "What new risk factors were added?"
filings-lens diff --ticker AAPL --form 10-K --years 2024 2025          # Item 1A by default
filings-lens ask --ticker AAPL --form 10-Q --year 2025 "Why did Americas net sales increase?"
filings-lens ask --ticker AAPL --form 8-K --year 2025 --accession 0000320193-25-000077 \
  "What did the press release regarding financial results cover?"
filings-lens sections --ticker AAPL --year 2025                      # see the parsed items
```

`--year` is the calendar year the filing was **filed**. For example, Apple's fiscal-2025
10-K was filed on 2025-10-31. Add `--json` for machine-readable output. `ask` exits with
`0` when it answers, `2` when it refuses and `1` on error.

### Try it offline

The repo ships small recorded fixtures, so you can try the tool without any network access:

```bash
git clone https://github.com/LevelUpWorldHub/filings-lens && cd filings-lens
pip install -e ".[dev]"
export FILINGS_LENS_USER_AGENT="Jane Doe research jane@example.com"
filings-lens ask --ticker AAPL --year 2025 --fixtures tests/fixtures/edgar "What new risk factors were added?"
```

Example output, abridged:

```
- The Company is also subject to new and changing laws and regulations regarding online safety,
  including enhanced protections for minors and mandatory age verification requirements. [3]
...
Citations:
[3] Apple Inc. 10-K filed 2025-10-31 (acc. 0000320193-25-000079), Item 1A, chars 5071-5251
    https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm
```

## Architecture

```
            ┌──────────────┐  submissions JSON / index.json / primary doc (GET only)
 ticker ──▶ │ EdgarClient  │  User-Agent required · ≤10 req/s · on-disk cache · SEC-host allowlist
            └──────┬───────┘
                   ▼
            ┌──────────────┐  html_to_text → split_items (TOC-aware, 10-Q part-aware, 8-K x.xx)
            │   parse      │  → split_passages (paragraph-aligned, stable ids)
            └──────┬───────┘
                   ▼
   question ─▶ filter ──▶ extract ──▶ verify ──▶ aggregate ──▶ Answer | Refusal
              item hints   backend:    quote must    numbered claims,
              + BM25 top-k  mock |      be verbatim   each with ≥1 citation
              (or diff for  openai |    in passage →
              "what's new") palimpzest  char offsets
```

| Module | Role |
|---|---|
| `edgar.py` | Polite EDGAR client: `cik_for_ticker`, `submissions`, `filing_index`, `find_filing`, `primary_document`. Includes `FixtureTransport` for offline use. |
| `parse.py` | Turns HTML into normalized text, splits it into items (10-K `1A`, `7`, …; 10-Q `I.2`, `II.1A`, …; 8-K `2.02`, …), then into passages. |
| `retrieval.py` | Deterministic BM25 and sentence splitting. No models, no network. |
| `pipeline.py` | The filter → extract → verify → aggregate steps. Refuses when there is no citation, and refuses advice requests. |
| `diff.py` | Passage-level shingle-Jaccard diff of an item across two filings (added / modified / removed). |
| `backends/` | `mock` (default), `openai` (OpenAI-compatible API). |
| `palimpzest_adapter.py` | Optional Palimpzest engine for the extract step (`sem_filter` + `sem_map`). |
| `evaluation.py` | Citation-accuracy evaluation. |

**Backends never get the last word.** A backend returns `(claim, passage_id, quote)`
triples. The pipeline keeps a claim only if `quote` is found verbatim in that passage,
and it converts the quote to absolute character offsets. The final answer is built only
from those verified claims. So a model that paraphrases or hallucinates can't slip an
uncited statement into an answer; its claim is dropped, and if nothing is left the tool
refuses.

## Citation format

Every claim carries one or more citations:

```json
{
  "cik": "0000320193",
  "company": "Apple Inc.",
  "accession": "0000320193-25-000079",
  "form": "10-K",
  "filing_date": "2025-10-31",
  "item": "1",
  "item_title": "Business",
  "passage_id": "0000320193-25-000079:1:p0003:a5cdfd60",
  "start": 1595,
  "end": 1690,
  "quote": "As of September 27, 2025, the Company had approximately 166,000 full-time equivalent employees.",
  "source_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm",
  "parser_version": "1"
}
```

- `start`/`end` are offsets into the **normalized text** of the primary document as
  produced by `filings_lens.parse.html_to_text` for that `parser_version`. The invariant
  `html_to_text(doc)[start:end] == quote` always holds, and
  `filings_lens.documents.verify_citation` checks it.
- `passage_id` = `{accession}:{item}:p{index}:{sha1(text)[:8]}`. It stays stable as long
  as the filing and parser version are unchanged.

## Model backends

| Backend | Select | Cost | Notes |
|---|---|---|---|
| `mock` (default) | `--backend mock` | free, offline | Deterministic and extractive: BM25 picks passages and the best-overlapping sentence becomes the claim. Used in tests and CI. |
| `openai` | `--backend openai` | depends on your server | Any OpenAI-compatible `/chat/completions` server, such as Ollama, vLLM or a hosted API. Configured **only** via env vars: `FILINGS_LENS_LLM_BASE_URL`, `FILINGS_LENS_LLM_MODEL`, optional `FILINGS_LENS_LLM_API_KEY`. |
| `palimpzest` | `--backend palimpzest` | depends on models | `pip install "filings-lens[palimpzest]"` and configure model keys the way Palimpzest expects (for example `OPENAI_API_KEY`). `FILINGS_LENS_PZ_POLICY=min_cost\|max_quality`. |

Tests and CI make no paid API calls. The OpenAI and Palimpzest backends are tested
against in-process fakes, and no keys are committed.

## EDGAR etiquette

- `FILINGS_LENS_USER_AGENT` is mandatory and must contain a contact email, as the
  [SEC fair-access policy](https://www.sec.gov/os/accessing-edgar-data) requires.
- Requests go through a limiter capped at **10 requests per second**.
- Responses are cached in `$FILINGS_LENS_CACHE_DIR`, or in `~/.cache/filings-lens` by
  default. Archive documents are immutable; submissions JSON is refreshed after 24 hours.
  Use `--no-cache` to bypass the cache.
- Only `https://www.sec.gov` and `https://data.sec.gov` are contacted.

## Evaluation

`scripts/eval_citations.py` scores the pipeline on hand-labeled questions
(`eval/questions.json`) over the recorded fixtures:

- **valid**: each citation's quote is exactly `text[start:end]`.
- **item_ok**: the top citation comes from the labeled item.
- **evidence**: some cited quote contains the labeled answer span.
- **refusal_ok**: unanswerable or advice questions are refused.

```bash
python scripts/eval_citations.py            # mock backend: valid 1.0 · item 1.0 · evidence 1.0 · refusal 1.0
```

Nine questions is a smoke test, not a benchmark. The mock backend was developed against
these fixtures, so its perfect score shows the pipeline is wired correctly; it says
nothing about how well the tool generalizes. To compare real models, run the same script
with `--backend openai` and a larger labeled set.

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest                      # offline: sockets and urlopen are blocked in tests
```

`scripts/record_fixtures.py` is the only script that touches the network, and it never
runs in CI. It records trimmed EDGAR responses into `tests/fixtures/edgar/`.

## Limitations

- **Parsing is heuristic.** Item detection relies on `Item N.` headings at the start of
  a line in the normalized text. Unusual layouts, such as headings split across table
  cells, all-caps cross-reference indexes or exhibit-only 10-Ks, can mis-assign
  sections. Use `filings-lens sections` to check.
- **Tables are flattened** into single lines of text. Numeric questions about financial
  statements are poorly supported, and XBRL is not used yet.
- **Mock backend is lexical.** It finds sentences that share terms with the question.
  It does not reason, compute or synthesize across passages.
- **"What's new" = text diff.** Novelty is measured by passage-level similarity to the
  prior year's filing. Reworded but substantively unchanged risks can show up as
  added or modified, and moved text is matched regardless of position.
- **Primary document only.** Exhibits (for example the 8-K press release in Exhibit
  99.1) and amendments (10-K/A) are not parsed yet. Only `filings.recent` from the
  submissions API is used, which covers about the last 1,000 filings.
- **Not advice.** Questions that ask for buy, sell or price-target style advice are
  refused, and nothing here should be read as a recommendation.

## Credits

- **[Palimpzest](https://github.com/mitdbg/palimpzest)** (MIT license), by the
  **MIT Data Systems Group (DSG)** at MIT CSAIL. filings-lens uses it as an optional
  semantic-operator engine. If you use that path, please cite: Liu et al., *Palimpzest:
  Optimizing AI-Powered Analytics with Declarative Query Processing*, CIDR 2025.
- Filing data comes from the U.S. SEC's public [EDGAR](https://www.sec.gov/edgar)
  system. The fixtures are trimmed excerpts of public Apple Inc. filings, used only for
  offline tests.

filings-lens is an independent project. It is not affiliated with or endorsed by MIT, the
Palimpzest authors, the SEC or any company whose filings it reads.

## License

[MIT](LICENSE)
