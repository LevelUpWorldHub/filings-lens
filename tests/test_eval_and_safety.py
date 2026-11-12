from __future__ import annotations

import re
from pathlib import Path

from filings_lens.evaluation import run_eval

ROOT = Path(__file__).resolve().parents[1]


def test_eval_citation_accuracy(fixtures_dir):
    rep = run_eval(ROOT / "eval" / "questions.json", fixtures_dir)
    s = rep.summary()
    assert s["valid"] == 1.0, rep.rows  # citations must always be verbatim spans
    assert s["refusal_ok"] == 1.0, rep.rows
    assert rep.overall >= 0.9, rep.rows


FORBIDDEN = re.compile(
    r"place_order|submit_order|create_order|brokerage_api|alpaca|robinhood|interactive ?brokers|"
    r"buy_signal|sell_signal|execute_trade",
    re.I,
)
SECRET = re.compile(r"(sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")


def _repo_files():
    for p in ROOT.rglob("*"):
        if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts and "fixtures" not in p.parts:
            yield p


def test_no_trading_code_paths():
    for p in (ROOT / "src").rglob("*.py"):
        assert not FORBIDDEN.search(p.read_text()), p


def test_no_committed_secrets():
    for p in _repo_files():
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            continue
        assert not SECRET.search(text), p
