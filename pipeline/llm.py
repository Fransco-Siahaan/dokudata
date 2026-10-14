"""LLM access behind one small interface so providers (or a fake, in tests) are swappable.

The Claude implementation uses structured outputs (``output_config.format``) so
the response is JSON that matches the schema, then the caller re-validates it
with Pydantic. The model is never given tools: document text can only ever
become *data* in that JSON, never an action.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# USD per million tokens (input, output). Check current pricing before relying on cost numbers.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
DEFAULT_MODEL = "claude-opus-5"


class LLMError(RuntimeError):
    pass


class LLMRefusalError(LLMError):
    pass


class LLMUnavailableError(LLMError):
    pass


@dataclass(slots=True)
class LLMResponse:
    data: dict[str, Any]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


class LLMClient(Protocol):
    name: str

    def generate_json(
        self, *, system: str, content: list[dict[str, Any]], schema: dict[str, Any], max_tokens: int = 4096
    ) -> LLMResponse: ...


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES_PER_MTOK.get(model, PRICES_PER_MTOK[DEFAULT_MODEL])
    return (input_tokens * pin + output_tokens * pout) / 1_000_000


class ClaudeClient:
    """Claude via the official Anthropic SDK.

    Credentials resolve the SDK's usual way (``ANTHROPIC_API_KEY`` or an ``ant
    auth login`` profile). ``DOKUDATA_LLM_MODEL`` and ``DOKUDATA_LLM_EFFORT``
    override the model and effort level.
    """

    def __init__(
        self,
        model: str | None = None,
        effort: str | None = None,
        timeout: float = 120.0,
        api_key: str | None = None,
    ) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise LLMUnavailableError("anthropic SDK not installed") from exc
        self._anthropic = anthropic
        self.model = model or os.environ.get("DOKUDATA_LLM_MODEL", DEFAULT_MODEL)
        # Field extraction is a bounded task; low effort keeps p95 latency inside the PRD budget.
        self.effort = effort or os.environ.get("DOKUDATA_LLM_EFFORT", "low")
        self.name = f"claude:{self.model}"
        try:
            kwargs: dict[str, Any] = {"api_key": api_key} if api_key else {}
            self._client = anthropic.Anthropic(timeout=timeout, max_retries=2, **kwargs)
        except Exception as exc:
            raise LLMUnavailableError(f"Claude client could not be created: {exc}") from exc

    def generate_json(
        self, *, system: str, content: list[dict[str, Any]], schema: dict[str, Any], max_tokens: int = 4096
    ) -> LLMResponse:
        anthropic = self._anthropic
        start = time.perf_counter()
        try:
            params: dict[str, Any] = {
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": content}],
                "output_config": {"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                # On a policy decline the API re-runs the request on a recommended fallback model.
                "betas": ["server-side-fallback-2026-07-01"],
                "fallbacks": "default",
            }
            resp = self._client.beta.messages.create(**params)
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailableError("Claude credentials missing or invalid") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError(f"rate limited: {exc.message}") from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"bad request: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailableError(f"cannot reach the Claude API: {exc}") from exc
        latency = (time.perf_counter() - start) * 1000
        if resp.stop_reason == "refusal":
            category = resp.stop_details.category if resp.stop_details else None
            raise LLMRefusalError(f"model declined the request (category={category})")
        if resp.stop_reason == "max_tokens":
            raise LLMError("response truncated at max_tokens")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise LLMError("response contained no text block")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"invalid JSON from model: {exc}") from exc
        usage = resp.usage
        in_tok = (usage.input_tokens or 0) + (usage.cache_read_input_tokens or 0)
        out_tok = usage.output_tokens or 0
        return LLMResponse(
            data=data,
            model=resp.model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency,
            cost_usd=estimate_cost(self.model, in_tok, out_tok),
            meta={"request_id": getattr(resp, "_request_id", None)},
        )


class FakeLLMClient:
    """Deterministic stand-in used by tests and offline demos."""

    name = "fake"

    def __init__(self, responder: Callable[[str, list[dict[str, Any]]], dict[str, Any]]) -> None:
        self.responder = responder
        self.calls: list[dict[str, Any]] = []

    def generate_json(
        self, *, system: str, content: list[dict[str, Any]], schema: dict[str, Any], max_tokens: int = 4096
    ) -> LLMResponse:
        self.calls.append({"system": system, "content": content, "schema": schema})
        return LLMResponse(
            data=self.responder(system, content), model="fake", input_tokens=0, output_tokens=0
        )


def default_llm_client() -> LLMClient:
    return ClaudeClient()
