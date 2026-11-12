from __future__ import annotations

from filings_lens.backends.base import RawClaim
from filings_lens.backends.mock import MockBackend
from filings_lens.documents import verify_citation
from filings_lens.models import Answer, Refusal
from filings_lens.pipeline import AskOptions, ask, infer_items, is_advice_request, is_novelty_question
from filings_lens.retrieval import sentences


def test_infer_items():
    assert infer_items("What are the main risk factors?", "10-K") == ["1A"]
    assert infer_items("How is cybersecurity governed?", "10-K") == ["1C"]
    assert infer_items("What is the exposure to interest rate risk?", "10-K") == ["7A"]
    assert infer_items("What drove net sales?", "10-Q") == ["I.2"]
    assert infer_items("What drove net sales?", "8-K") == []


def test_intent_detectors():
    assert is_novelty_question("What new risk factors were added?")
    assert not is_novelty_question("What are the risk factors?")
    assert is_advice_request("Should I buy AAPL?")
    assert is_advice_request("what's your price target")
    assert not is_advice_request("What drove net sales?")


def test_sentences_respect_abbreviations():
    text = "On Oct. 30, Apple Inc. issued a release about results. The U.S. market grew strongly this year."
    got = [text[s:e] for s, e in sentences(text)]
    assert got == ["On Oct. 30, Apple Inc. issued a release about results.", "The U.S. market grew strongly this year."]


def test_answer_has_verified_citations(tenk_2025):
    res = ask("How many full-time employees does the company have?", tenk_2025, MockBackend())
    assert isinstance(res, Answer)
    c = res.citations[0]
    assert "166,000 full-time equivalent employees" in c.quote
    assert verify_citation(tenk_2025, c)
    assert (c.cik, c.accession, c.form, c.filing_date, c.item) == (
        "0000320193",
        "0000320193-25-000079",
        "10-K",
        "2025-10-31",
        "1",
    )
    assert c.source_url.startswith("https://www.sec.gov/Archives/edgar/data/320193/")
    assert "[1]" in res.answer
    d = res.to_dict()
    assert d["status"] == "answered" and "not investment" in d["disclaimer"]


def test_every_claim_is_cited(tenk_2025):
    res = ask("What are the risks from competition?", tenk_2025, MockBackend())
    assert isinstance(res, Answer)
    assert all(claim.citations for claim in res.claims)
    assert all(verify_citation(tenk_2025, c) for c in res.citations)


def test_refuses_without_evidence(tenk_2025):
    res = ask("zebra quantum pizza", tenk_2025, MockBackend())
    assert isinstance(res, Refusal)
    assert res.to_dict()["status"] == "refused"


def test_refuses_advice(tenk_2025):
    res = ask("Should I buy AAPL stock?", tenk_2025, MockBackend())
    assert isinstance(res, Refusal)
    assert "investment advice" in res.reason


class HallucinatingBackend:
    name = "hallucinating"

    def extract(self, question, passages, intent):
        p = passages[0]
        return [
            RawClaim("made up", p.passage_id, "This sentence does not appear in the filing."),
            RawClaim("wrong id", "nope:1A:p9999:deadbeef", p.text[:40]),
        ]


def test_unverifiable_quotes_are_dropped_and_refused(tenk_2025):
    res = ask("What are the risks from competition?", tenk_2025, HallucinatingBackend())
    assert isinstance(res, Refusal)
    assert "verifiable citation" in res.reason


class MixedBackend(HallucinatingBackend):
    def extract(self, question, passages, intent):
        p = passages[0]
        return super().extract(question, passages, intent) + [RawClaim("real", p.passage_id, p.text[5:60])]


def test_only_verified_claims_survive(tenk_2025):
    res = ask("What are the risks from competition?", tenk_2025, MixedBackend())
    assert isinstance(res, Answer)
    assert [c.text for c in res.claims] == ["real"]
    c = res.citations[0]
    assert tenk_2025.text[c.start : c.end] == c.quote


def test_novelty_question_uses_diff(tenk_2025, tenk_2024):
    res = ask("What new risk factors were added?", tenk_2025, MockBackend(), prior=tenk_2024)
    assert isinstance(res, Answer)
    assert res.filings == [tenk_2025.filing.accession, tenk_2024.filing.accession]
    assert all(c.item == "1A" and c.accession == tenk_2025.filing.accession for c in res.citations)
    assert any("online safety" in c.quote for c in res.citations)


def test_item_restriction(tenk_2025):
    res = ask("What does the company say about competition?", tenk_2025, MockBackend(), AskOptions(items=["1A"]))
    assert isinstance(res, Answer)
    assert {c.item for c in res.citations} == {"1A"}


def test_10q_and_8k(tenq_2025, eightk):
    r1 = ask("Why did Americas net sales increase?", tenq_2025, MockBackend())
    assert isinstance(r1, Answer) and r1.citations[0].item == "I.2"
    r2 = ask("What did the press release regarding financial results cover?", eightk, MockBackend())
    assert isinstance(r2, Answer) and r2.citations[0].item == "2.02"
    assert r2.citations[0].quote.startswith("On October 30, 2025, Apple Inc.")
