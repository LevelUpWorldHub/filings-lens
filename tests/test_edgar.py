from __future__ import annotations

import pytest

from filings_lens.edgar import (
    MAX_REQUESTS_PER_SECOND,
    DiskCache,
    EdgarClient,
    EdgarError,
    FixtureTransport,
    RateLimiter,
    UserAgentMissingError,
)

from .conftest import CIK, FIXTURES, UA


def test_user_agent_required(monkeypatch):
    monkeypatch.delenv("FILINGS_LENS_USER_AGENT", raising=False)
    with pytest.raises(UserAgentMissingError):
        EdgarClient(use_cache=False)
    with pytest.raises(UserAgentMissingError):
        EdgarClient(user_agent="no-contact-email", use_cache=False)


def test_user_agent_from_env(monkeypatch):
    monkeypatch.setenv("FILINGS_LENS_USER_AGENT", "Jane research jane@example.com")
    assert EdgarClient(use_cache=False).user_agent == "Jane research jane@example.com"


def test_user_agent_header_sent():
    seen = {}

    def transport(url, headers):
        seen.update(headers)
        return b"{}"

    EdgarClient(user_agent=UA, transport=transport, use_cache=False).get("https://data.sec.gov/x.json")
    assert seen["User-Agent"] == UA


@pytest.mark.parametrize(
    "url",
    ["http://www.sec.gov/x", "https://evil.example.com/x", "https://sec.gov.evil.com/x", "file:///etc/passwd"],
)
def test_only_sec_hosts(url):
    c = EdgarClient(user_agent=UA, transport=lambda u, h: b"", use_cache=False)
    with pytest.raises(EdgarError):
        c.get(url)


def test_rate_limiter_enforces_10_per_second():
    t = [0.0]
    slept = []

    def clock():
        return t[0]

    def sleep(d):
        slept.append(d)
        t[0] += d

    rl = RateLimiter(10, clock=clock, sleep=sleep)
    for _ in range(21):
        rl.wait()
    # 21 requests need at least 2.0 s at 10 rps
    assert t[0] == pytest.approx(2.0)
    assert all(d <= 0.1 + 1e-9 for d in slept)


def test_rate_limiter_rejects_above_sec_limit():
    with pytest.raises(ValueError):
        RateLimiter(MAX_REQUESTS_PER_SECOND + 1)


def test_disk_cache_roundtrip_and_ttl(tmp_path):
    calls = []

    def transport(url, headers):
        calls.append(url)
        return b"payload"

    c = EdgarClient(user_agent=UA, transport=transport, cache_dir=tmp_path)
    assert c.get("https://www.sec.gov/a") == b"payload"
    assert c.get("https://www.sec.gov/a") == b"payload"
    assert calls == ["https://www.sec.gov/a"]
    cache = DiskCache(tmp_path)
    assert cache.get("https://www.sec.gov/a", max_age=-1) is None  # expired
    assert cache.get("https://www.sec.gov/a") == b"payload"


def test_fixture_transport_refuses_unknown_urls():
    t = FixtureTransport(FIXTURES)
    with pytest.raises(EdgarError):
        t("https://www.sec.gov/not-recorded", {"User-Agent": UA})


def test_ticker_and_filings(client):
    assert client.cik_for_ticker("aapl") == CIK
    with pytest.raises(EdgarError):
        client.cik_for_ticker("ZZZZ")
    f = client.find_filing(CIK, "10-K", 2025)
    assert f.accession == "0000320193-25-000079"
    assert f.filing_date == "2025-10-31"
    assert f.document_url.endswith("/320193/000032019325000079/aapl-20250927.htm")
    with pytest.raises(EdgarError):
        client.find_filing(CIK, "10-K", 1990)


def test_filing_index(client):
    f = client.find_filing(CIK, "10-K", 2025)
    names = [i["name"] for i in client.filing_index(f)["directory"]["item"]]
    assert f.primary_document in names
