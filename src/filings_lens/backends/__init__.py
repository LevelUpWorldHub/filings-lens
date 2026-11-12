"""Model backends. ``mock`` is the default and is fully offline + deterministic."""

from __future__ import annotations

from filings_lens.backends.base import Backend, RawClaim


def get_backend(name: str) -> Backend:
    name = (name or "mock").lower()
    if name == "mock":
        from filings_lens.backends.mock import MockBackend

        return MockBackend()
    if name in {"openai", "openai-compatible"}:
        from filings_lens.backends.openai_compat import OpenAICompatBackend

        return OpenAICompatBackend.from_env()
    if name in {"palimpzest", "pz"}:
        from filings_lens.palimpzest_adapter import PalimpzestBackend

        return PalimpzestBackend.from_env()
    raise ValueError(f"unknown backend {name!r} (choose mock, openai, palimpzest)")


__all__ = ["Backend", "RawClaim", "get_backend"]
