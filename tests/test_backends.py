from __future__ import annotations

import json
import types

import pytest

from filings_lens.backends import get_backend
from filings_lens.backends.mock import MockBackend
from filings_lens.backends.openai_compat import OpenAICompatBackend
from filings_lens.models import Answer
from filings_lens.palimpzest_adapter import PalimpzestBackend
from filings_lens.pipeline import ask


def test_default_backend_is_mock():
    assert isinstance(get_backend("mock"), MockBackend)
    with pytest.raises(ValueError):
        get_backend("gpt-9000")


def test_mock_is_deterministic(tenk_2025):
    q = "What are the risks from competition?"
    a, b = ask(q, tenk_2025, MockBackend()), ask(q, tenk_2025, MockBackend())
    assert a.to_dict() == b.to_dict()


def test_openai_backend_requires_env():
    with pytest.raises(RuntimeError):
        get_backend("openai")


def test_openai_backend_env_and_repr(monkeypatch):
    monkeypatch.setenv("FILINGS_LENS_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("FILINGS_LENS_LLM_MODEL", "llama3")
    monkeypatch.setenv("FILINGS_LENS_LLM_API_KEY", "test-not-a-real-key")
    b = get_backend("openai")
    assert isinstance(b, OpenAICompatBackend)
    assert "test-not-a-real-key" not in repr(b)


def test_openai_backend_parses_and_is_verified(tenk_2025):
    b = OpenAICompatBackend("http://localhost:1/v1", "fake")
    sent = {}

    def fake_post(payload):
        sent.update(payload)
        p_text = payload["messages"][1]["content"]
        pid = p_text.split("[", 1)[1].split("]", 1)[0]
        passage = tenk_2025.passage(pid)
        claims = [
            {"text": "Real", "passage_id": pid, "quote": passage.text[:60]},
            {"text": "Fake", "passage_id": pid, "quote": "Apple will triple revenue next year."},
        ]
        return {"choices": [{"message": {"content": json.dumps({"claims": claims})}}]}

    b._post = fake_post  # no network
    res = ask("What are the risks from competition?", tenk_2025, b)
    assert sent["temperature"] == 0
    assert isinstance(res, Answer)
    assert [c.text for c in res.claims] == ["Real"]


def test_openai_backend_bad_json(tenk_2025):
    b = OpenAICompatBackend("http://localhost:1/v1", "fake")
    b._post = lambda payload: {"choices": [{"message": {"content": "not json"}}]}
    assert b.extract("q", tenk_2025.passages[:1], "lookup") == []


class _FakeOutput:
    def __init__(self, rows):
        self.rows = rows

    def to_df(self, cols=None):
        rows = self.rows

        class DF:
            def to_dict(self, orient):
                assert orient == "records"
                return rows

        return DF()


class _FakeDataset:
    def __init__(self, id, vals):
        self.vals, self.ops = vals, []

    def sem_filter(self, desc, depends_on=None):
        self.ops.append(("filter", desc))
        return self

    def sem_map(self, cols, depends_on=None):
        self.ops.append(("map", [c["name"] for c in cols]))
        return self

    def run(self, config):
        v = self.vals[0]
        return _FakeOutput(
            [
                {"passage_id": v["passage_id"], "quote": v["text"][:50], "claim": "pz claim"},
                {"passage_id": v["passage_id"], "quote": "", "claim": "empty"},
            ]
        )


def _fake_pz():
    return types.SimpleNamespace(
        MemoryDataset=_FakeDataset,
        QueryProcessorConfig=lambda **kw: kw,
        MinCost=lambda: "min_cost",
        MaxQuality=lambda: "max_quality",
    )


def test_palimpzest_adapter_with_fake_engine(tenk_2025):
    b = PalimpzestBackend(pz=_fake_pz())
    ds = b.build_dataset("q", tenk_2025.passages[:2], "lookup")
    assert [op[0] for op in ds.ops] == ["filter", "map"]
    res = ask("What are the risks from competition?", tenk_2025, b)
    assert isinstance(res, Answer)
    assert [c.text for c in res.claims] == ["pz claim"]


def test_palimpzest_real_engine_optional():
    pytest.importorskip("palimpzest")
    assert PalimpzestBackend.from_env().name == "palimpzest"
