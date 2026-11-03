"""Meta Model API client (OpenAI-compatible) with a hard, cumulative spend cap.

Stdlib only. Every live call is priced from the returned usage and appended to a
JSONL ledger; a call is refused up front if its worst-case cost would push the
ledger past the cap.
"""
from __future__ import annotations

import json
import re
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
# USD per 1M tokens: (input, cached input, output). Contributor variants are
# deliberately absent: Meta may train on those prompts, and résumés are personal.
PRICES = {
    "muse-spark-1.3": (1.25, 0.15, 4.25),
    "muse-spark-1.1": (1.25, 0.15, 4.25),
}
WEB_SEARCH_PER_QUERY = 0.0025


class BudgetExceeded(RuntimeError):
    pass


class ModelError(RuntimeError):
    pass


def load_env(path: Path):
    """Minimal .env loader: KEY=VALUE lines, existing environment wins."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Ledger:
    def __init__(self, path: Path, cap_usd: float):
        self.path = path
        self.cap = cap_usd
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def spent(self) -> float:
        if not self.path.exists():
            return 0.0
        total = 0.0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                total += float(json.loads(line)["cost_usd"])
            except (ValueError, KeyError, TypeError):
                continue
        return round(total, 6)

    def calls(self) -> int:
        if not self.path.exists():
            return 0
        return sum(1 for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip())

    def reserve(self, worst_case: float):
        if self.spent() + worst_case > self.cap:
            raise BudgetExceeded(
                f"Refusing call: spent ${self.spent():.4f} + worst case ${worst_case:.4f} "
                f"would exceed cap ${self.cap:.2f}. Raise GROUNDED_BUDGET_USD to continue."
            )

    def record(self, entry: dict):
        with self.lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def price(model: str, usage: dict) -> float:
    inp, cached, out = PRICES.get(model, PRICES[DEFAULT_MODEL])
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    hit = int(details.get("cached_tokens") or 0)
    return ((prompt - hit) * inp + hit * cached + completion * out) / 1_000_000


class MetaClient:
    """Live client. `chat_json` returns (parsed_json, meta) or raises."""

    live = True

    def __init__(self, ledger: Ledger, api_key: str, model: str = DEFAULT_MODEL, base: str = DEFAULT_BASE):
        self.ledger = ledger
        self.key = api_key
        self.model = model
        self.base = base.rstrip("/")

    def _post(self, path: str, body: dict, timeout: int = 180) -> dict:
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:800]
            raise ModelError(f"HTTP {e.code} from Meta API: {detail}") from None
        except urllib.error.URLError as e:
            raise ModelError(f"Network error calling Meta API: {e.reason}") from None

    def _worst_case(self, messages: list, max_out: int) -> float:
        chars = len(json.dumps(messages))
        inp, _, out = PRICES.get(self.model, PRICES[DEFAULT_MODEL])
        # ~3 chars/token is conservative for English; base64 PDFs are counted as text, which over-reserves.
        return (chars / 3 * inp + max_out * out) / 1_000_000

    def chat_json(self, task: str, messages: list, schema: dict, max_out: int = 4000,
                  reasoning: str = "low") -> tuple[dict, dict]:
        self.ledger.reserve(self._worst_case(messages, max_out))
        body = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": max_out,
            "reasoning_effort": reasoning,
            "response_format": {"type": "json_schema", "json_schema": {"name": task, "schema": schema, "strict": True}},
        }
        started = time.time()
        try:
            data = self._post("/chat/completions", body)
        except ModelError as e:
            # Some preview deployments reject strict schemas; fall back to JSON mode and validate locally.
            if "response_format" not in str(e) and "schema" not in str(e):
                raise
            body["response_format"] = {"type": "json_object"}
            body["messages"] = messages + [{"role": "system", "content": "Return only JSON matching this schema: " + json.dumps(schema)}]
            data = self._post("/chat/completions", body)
        usage = data.get("usage") or {}
        cost = price(self.model, usage)
        meta = {"task": task, "model": data.get("model", self.model), "usage": usage,
                "cost_usd": round(cost, 6), "seconds": round(time.time() - started, 2), "ts": int(started)}
        self.ledger.record(meta)
        if (data.get("choices") or [{}])[0].get("finish_reason") == "length":
            # Reasoning tokens count against max_completion_tokens, so a long think can truncate the JSON.
            raise ModelError(f"{task} hit max_completion_tokens={max_out} "
                             f"({(usage.get('completion_tokens_details') or {}).get('reasoning_tokens')} reasoning tokens); try again or lower reasoning effort.")
        try:
            text = data["choices"][0]["message"]["content"]
            return json.loads(text), meta
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            raise ModelError(f"Model did not return valid JSON for {task}: {e}") from None

    def web_research(self, query: str, max_out: int = 2000) -> tuple[str, dict]:
        """Responses API + web_search tool. Returns plain text summary."""
        # Search results are fed back as input (~16k tokens observed for 5 searches), so reserve for 30k extra.
        inp = PRICES.get(self.model, PRICES[DEFAULT_MODEL])[0]
        self.ledger.reserve(self._worst_case([query], max_out) + 30_000 * inp / 1_000_000 + 8 * WEB_SEARCH_PER_QUERY)
        started = time.time()
        data = self._post("/responses", {
            "model": self.model, "input": query, "tools": [{"type": "web_search"}],
            "max_output_tokens": max_out, "reasoning": {"effort": "low"},
        })
        usage = data.get("usage") or {}
        searches = sum(1 for item in data.get("output", []) if "search" in str(item.get("type", "")))
        cost = price(self.model, usage) + searches * WEB_SEARCH_PER_QUERY
        meta = {"task": "research", "model": data.get("model", self.model), "usage": usage, "web_searches": searches,
                "cost_usd": round(cost, 6), "seconds": round(time.time() - started, 2), "ts": int(started)}
        self.ledger.record(meta)
        # The model narrates between searches ("I'll research..."); keep only the final message's text.
        messages = [item for item in data.get("output", []) if item.get("type") == "message"]
        text = ""
        for part in (messages[-1].get("content", []) if messages else []) or []:
            if part.get("type") in ("output_text", "text"):
                text += part.get("text", "")
        text = text or data.get("output_text") or ""
        first_bullet = re.search(r"^\s*[*\-•] ", text, re.M)
        if first_bullet:
            text = text[first_bullet.start():]
        return text.strip(), meta


def make_client(root: Path):
    """Live client when META_API_KEY is set, otherwise the deterministic offline stub."""
    load_env(root / ".env")
    cap = float(os.environ.get("GROUNDED_BUDGET_USD", "100"))
    ledger = Ledger(root / "data" / "spend.jsonl", cap)
    key = os.environ.get("META_API_KEY", "").strip()
    if key:
        return MetaClient(ledger, key, os.environ.get("META_MODEL", DEFAULT_MODEL),
                          os.environ.get("META_API_BASE", DEFAULT_BASE))
    from .offline import OfflineClient
    return OfflineClient(ledger)
