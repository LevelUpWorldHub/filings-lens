"""Minimal, polite, read-only client for public SEC EDGAR endpoints.

* Only ``www.sec.gov`` and ``data.sec.gov`` GET requests are ever issued.
* A descriptive User-Agent is mandatory (SEC fair-access policy); it is read
  from ``FILINGS_LENS_USER_AGENT``, e.g. ``"Jane Doe research jane@example.com"``.
* Requests are throttled to <= 10 per second (SEC's published limit).
* Responses are cached on disk; archive documents are immutable so they are
  cached forever, submissions JSON is refreshed after ``submissions_ttl``.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from filings_lens.models import Filing

USER_AGENT_ENV = "FILINGS_LENS_USER_AGENT"
CACHE_DIR_ENV = "FILINGS_LENS_CACHE_DIR"
ALLOWED_HOSTS = frozenset({"www.sec.gov", "data.sec.gov"})
MAX_REQUESTS_PER_SECOND = 10.0
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

Transport = Callable[[str, dict[str, str]], bytes]


class EdgarError(RuntimeError):
    pass


class UserAgentMissingError(EdgarError):
    pass


def _urllib_transport(url: str, headers: dict[str, str]) -> bytes:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - host allowlisted
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip

            data = gzip.decompress(data)
        return data


class RateLimiter:
    """Simple thread-safe minimum-interval limiter."""

    def __init__(
        self,
        max_per_second: float = MAX_REQUESTS_PER_SECOND,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_per_second <= 0 or max_per_second > MAX_REQUESTS_PER_SECOND:
            raise ValueError(f"max_per_second must be in (0, {MAX_REQUESTS_PER_SECOND}]")
        self.interval = 1.0 / max_per_second
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if now < self._next:
                self._sleep(self._next - now)
                now = self._next
            self._next = now + self.interval


class DiskCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()
        return self.root / h[:2] / h

    def get(self, url: str, max_age: float | None = None) -> bytes | None:
        p = self._path(url)
        if not p.exists():
            return None
        if max_age is not None and time.time() - p.stat().st_mtime > max_age:
            return None
        return p.read_bytes()

    def put(self, url: str, data: bytes) -> None:
        p = self._path(url)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)


def default_cache_dir() -> Path:
    env = os.environ.get(CACHE_DIR_ENV)
    if env:
        return Path(env)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "filings-lens"


class EdgarClient:
    def __init__(
        self,
        user_agent: str | None = None,
        cache_dir: Path | None = None,
        transport: Transport | None = None,
        rate_limiter: RateLimiter | None = None,
        submissions_ttl: float = 24 * 3600,
        use_cache: bool = True,
    ) -> None:
        ua = user_agent if user_agent is not None else os.environ.get(USER_AGENT_ENV, "")
        ua = ua.strip()
        if not ua or "@" not in ua:
            raise UserAgentMissingError(
                f"SEC requires a descriptive User-Agent with contact email. Set {USER_AGENT_ENV}, "
                'e.g. export FILINGS_LENS_USER_AGENT="Your Name research you@example.com"'
            )
        self.user_agent = ua
        self.transport = transport or _urllib_transport
        self.limiter = rate_limiter or RateLimiter()
        self.cache = DiskCache(cache_dir or default_cache_dir()) if use_cache else None
        self.submissions_ttl = submissions_ttl
        self.requests_made = 0

    # -- low level -----------------------------------------------------
    def get(self, url: str, max_age: float | None = None) -> bytes:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise EdgarError(f"refusing non-SEC URL: {url}")
        if self.cache is not None:
            hit = self.cache.get(url, max_age=max_age)
            if hit is not None:
                return hit
        self.limiter.wait()
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip",
            "Host": parsed.hostname,
        }
        try:
            data = self.transport(url, headers)
        except Exception as exc:  # pragma: no cover - network specific
            raise EdgarError(f"GET {url} failed: {exc}") from exc
        self.requests_made += 1
        if self.cache is not None:
            self.cache.put(url, data)
        return data

    def get_json(self, url: str, max_age: float | None = None) -> Any:
        return json.loads(self.get(url, max_age=max_age).decode("utf-8"))

    # -- endpoints -----------------------------------------------------
    def cik_for_ticker(self, ticker: str) -> str:
        data = self.get_json(TICKERS_URL, max_age=7 * 24 * 3600)
        t = ticker.upper().strip()
        for row in data.values():
            if str(row.get("ticker", "")).upper() == t:
                return f"{int(row['cik_str']):010d}"
        raise EdgarError(f"unknown ticker: {ticker}")

    def submissions(self, cik: str) -> dict[str, Any]:
        url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
        return self.get_json(url, max_age=self.submissions_ttl)

    def filing_index(self, filing: Filing) -> dict[str, Any]:
        return self.get_json(filing.index_url)

    def list_filings(self, cik: str, forms: tuple[str, ...] | None = None) -> list[Filing]:
        sub = self.submissions(cik)
        recent = sub.get("filings", {}).get("recent", {})
        company = sub.get("name", "")
        out = []
        for i, form in enumerate(recent.get("form", [])):
            if forms and form not in forms:
                continue
            out.append(
                Filing(
                    cik=f"{int(cik):010d}",
                    company=company,
                    form=form,
                    accession=recent["accessionNumber"][i],
                    filing_date=recent["filingDate"][i],
                    report_date=recent.get("reportDate", [""] * (i + 1))[i],
                    primary_document=recent["primaryDocument"][i],
                )
            )
        return out

    def find_filing(self, cik: str, form: str, year: int) -> Filing:
        """Most recent filing of ``form`` whose *filing date* falls in ``year``."""
        matches = [f for f in self.list_filings(cik, (form,)) if f.filing_date.startswith(f"{year}-")]
        if not matches:
            raise EdgarError(f"no {form} filed in {year} for CIK {cik}")
        return sorted(matches, key=lambda f: f.filing_date)[-1]

    def primary_document(self, filing: Filing) -> str:
        return self.get(filing.document_url).decode("utf-8", errors="replace")


class FixtureTransport:
    """Offline transport that serves recorded responses from a directory.

    ``manifest.json`` maps URL -> relative file path. Any URL not in the
    manifest raises, which guarantees tests never touch the network.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.manifest: dict[str, str] = json.loads((self.root / "manifest.json").read_text())
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> bytes:
        if not headers.get("User-Agent"):
            raise EdgarError("User-Agent header missing")
        self.calls.append(url)
        rel = self.manifest.get(url)
        if rel is None:
            raise EdgarError(f"offline fixture has no recording for {url}")
        return (self.root / rel).read_bytes()
