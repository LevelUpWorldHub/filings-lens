"""Optional OpenAI-compatible chat-completions backend.

Configured only through environment variables (never flags, never files):

* ``FILINGS_LENS_LLM_BASE_URL`` - e.g. ``http://localhost:11434/v1`` (Ollama) or a hosted API
* ``FILINGS_LENS_LLM_MODEL``    - model name
* ``FILINGS_LENS_LLM_API_KEY``  - optional; omitted for local servers

Using a hosted API may cost money; that is the caller's choice. Tests and CI
never use this backend against a real server.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from filings_lens.backends.base import RawClaim
from filings_lens.parse import Passage

SYSTEM_PROMPT = (
    "You answer questions about SEC filings using ONLY the numbered passages provided. "
    'Return strict JSON: {"claims": [{"text": str, "passage_id": str, "quote": str}]}. '
    "Each quote MUST be copied verbatim from the cited passage (a sentence or clause). "
    'If the passages do not answer the question, return {"claims": []}. '
    "Never give investment advice or recommendations."
)


class OpenAICompatBackend:
    name = "openai"

    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: float = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> OpenAICompatBackend:
        base = os.environ.get("FILINGS_LENS_LLM_BASE_URL")
        model = os.environ.get("FILINGS_LENS_LLM_MODEL")
        if not base or not model:
            raise RuntimeError(
                "openai backend needs FILINGS_LENS_LLM_BASE_URL and FILINGS_LENS_LLM_MODEL "
                "(and FILINGS_LENS_LLM_API_KEY for hosted APIs)"
            )
        return cls(base, model, os.environ.get("FILINGS_LENS_LLM_API_KEY"))

    def __repr__(self) -> str:  # never leak the key
        return f"OpenAICompatBackend(base_url={self.base_url!r}, model={self.model!r})"

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - network
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode())

    def build_messages(self, question: str, passages: list[Passage], intent: str) -> list[dict[str, str]]:
        blocks = [f"[{p.passage_id}] (Item {p.item} {p.item_title})\n{p.text}" for p in passages]
        task = (
            "These passages are NEW or CHANGED compared with the prior filing; summarize each relevant one."
            if intent == "novel"
            else "Answer the question."
        )
        user = f"{task}\nQuestion: {question}\n\nPassages:\n\n" + "\n\n".join(blocks)
        return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]

    def extract(self, question: str, passages: list[Passage], intent: str) -> list[RawClaim]:
        if not passages:
            return []
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": self.build_messages(question, passages, intent),
        }
        resp = self._post(payload)
        content = resp["choices"][0]["message"]["content"]
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return []
        out = []
        for c in data.get("claims", []) or []:
            if not isinstance(c, dict):
                continue
            text, pid, quote = c.get("text"), c.get("passage_id"), c.get("quote")
            if isinstance(text, str) and isinstance(pid, str) and isinstance(quote, str) and quote:
                out.append(RawClaim(text=text, passage_id=pid, quote=quote))
        return out
