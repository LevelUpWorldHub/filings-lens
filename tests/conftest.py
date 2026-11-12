from __future__ import annotations

import socket
import urllib.request
from pathlib import Path

import pytest

from filings_lens.documents import load_filing
from filings_lens.edgar import EdgarClient, FixtureTransport

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"
UA = "filings-lens tests tests@example.invalid"
CIK = "0000320193"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Any attempt to open a socket or URL in tests is a bug."""

    def boom(*a, **k):
        raise RuntimeError("network access attempted in tests")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setenv("FILINGS_LENS_USER_AGENT", UA)
    for k in ("FILINGS_LENS_LLM_BASE_URL", "FILINGS_LENS_LLM_MODEL", "FILINGS_LENS_LLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def client() -> EdgarClient:
    return EdgarClient(user_agent=UA, transport=FixtureTransport(FIXTURES), use_cache=False)


@pytest.fixture
def tenk_2025(client):
    return load_filing(client, client.find_filing(CIK, "10-K", 2025))


@pytest.fixture
def tenk_2024(client):
    return load_filing(client, client.find_filing(CIK, "10-K", 2024))


@pytest.fixture
def tenq_2025(client):
    return load_filing(client, client.find_filing(CIK, "10-Q", 2025))


@pytest.fixture
def eightk(client):
    f = next(f for f in client.list_filings(CIK) if f.accession == "0000320193-25-000077")
    return load_filing(client, f)
