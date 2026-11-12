from __future__ import annotations

from filings_lens.diff import diff_item, jaccard
from filings_lens.documents import verify_citation


def test_jaccard_bounds():
    assert jaccard(set(), set()) == 1.0
    assert jaccard({1}, {2}) == 0.0


def test_risk_factor_diff(tenk_2024, tenk_2025):
    d = diff_item(tenk_2024, tenk_2025, "1A")
    added, modified, removed = d.by_status("added"), d.by_status("modified"), d.by_status("removed")
    assert added and removed and d.unchanged >= 1
    assert any("online safety" in e.citation.quote for e in added)
    for e in added + modified:
        assert e.citation.accession == tenk_2025.filing.accession
        assert verify_citation(tenk_2025, e.citation)
    for e in modified:
        assert e.previous is not None and verify_citation(tenk_2024, e.previous)
    for e in removed:
        assert e.citation.accession == tenk_2024.filing.accession
        assert verify_citation(tenk_2024, e.citation)
    out = d.to_dict()
    assert set(out) >= {"added", "modified", "removed", "unchanged"}


def test_identical_filings_have_no_changes(tenk_2025):
    d = diff_item(tenk_2025, tenk_2025, "1A")
    assert d.entries == []
    assert d.unchanged == len(tenk_2025.passages_for(["1A"]))
