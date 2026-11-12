from __future__ import annotations

import json

from filings_lens.cli import main


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_ask_text(capsys, fixtures_dir):
    code, out, _ = run(
        capsys,
        "ask",
        "--ticker",
        "AAPL",
        "--form",
        "10-K",
        "--year",
        "2025",
        "--fixtures",
        str(fixtures_dir),
        "What new risk factors were added?",
    )
    assert code == 0
    assert "Citations:" in out and "0000320193-25-000079" in out and "not investment" in out


def test_ask_json(capsys, fixtures_dir):
    code, out, _ = run(
        capsys,
        "ask",
        "--ticker",
        "AAPL",
        "--year",
        "2025",
        "--json",
        "--fixtures",
        str(fixtures_dir),
        "Where is the company headquartered?",
    )
    d = json.loads(out)
    assert code == 0 and d["status"] == "answered"
    c = d["claims"][0]["citations"][0]
    assert set(c) >= {"cik", "accession", "form", "filing_date", "item", "start", "end", "source_url", "quote"}


def test_ask_refusal_exit_code(capsys, fixtures_dir):
    code, out, _ = run(
        capsys, "ask", "--ticker", "AAPL", "--year", "2025", "--fixtures", str(fixtures_dir), "zebra quantum pizza"
    )
    assert code == 2 and "REFUSED" in out


def test_ask_8k_by_accession(capsys, fixtures_dir):
    code, out, _ = run(
        capsys,
        "ask",
        "--ticker",
        "AAPL",
        "--form",
        "8-K",
        "--year",
        "2025",
        "--accession",
        "0000320193-25-000077",
        "--fixtures",
        str(fixtures_dir),
        "What did the press release regarding financial results cover?",
    )
    assert code == 0 and "Item 2.02" in out


def test_diff(capsys, fixtures_dir):
    code, out, _ = run(capsys, "diff", "--ticker", "AAPL", "--years", "2024", "2025", "--fixtures", str(fixtures_dir))
    assert code == 0 and "ADDED" in out and "REMOVED" in out
    code, out, _ = run(
        capsys, "diff", "--cik", "320193", "--years", "2024", "2025", "--json", "--fixtures", str(fixtures_dir)
    )
    assert code == 0 and json.loads(out)["added"]


def test_sections(capsys, fixtures_dir):
    code, out, _ = run(capsys, "sections", "--ticker", "AAPL", "--year", "2025", "--fixtures", str(fixtures_dir))
    assert code == 0 and "Risk Factors" in out


def test_errors_are_clean(capsys, fixtures_dir, monkeypatch):
    code, _, err = run(capsys, "ask", "--ticker", "ZZZZ", "--year", "2025", "--fixtures", str(fixtures_dir), "q")
    assert code == 1 and "unknown ticker" in err
    monkeypatch.delenv("FILINGS_LENS_USER_AGENT")
    code, _, err = run(capsys, "ask", "--ticker", "AAPL", "--year", "2025", "--fixtures", str(fixtures_dir), "q")
    assert code == 1 and "FILINGS_LENS_USER_AGENT" in err
