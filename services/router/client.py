from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from openai import OpenAI

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_FALLBACK_MODEL = "anthropic/claude-sonnet-5-5"


@dataclass
class CompletionResult:
    content: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    raw_message: Any | None = None


class ChatBackend(Protocol):
    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> CompletionResult: ...


def _usage_tokens(usage: Any) -> tuple[int, int]:
    if usage is None:
        return 0, 0
    return int(getattr(usage, "prompt_tokens", 0) or 0), int(
        getattr(usage, "completion_tokens", 0) or 0
    )


class OpenAIChatBackend:
    def __init__(self, *, base_url: str, api_key: str, provider: str) -> None:
        self.provider = provider
        self._client = OpenAI(base_url=base_url, api_key=api_key)

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> CompletionResult:
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if response_format:
            kwargs["response_format"] = response_format
        resp = self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        content = msg.content or ""
        inp, out = _usage_tokens(resp.usage)
        return CompletionResult(
            content=content,
            provider=self.provider,
            model=model,
            input_tokens=inp,
            output_tokens=out,
            raw_message=msg,
        )


class AnthropicChatBackend:
    """Claude through the official Anthropic SDK. Tools are not used by the router."""

    def __init__(self, *, api_key: str) -> None:
        import anthropic

        self.provider = "anthropic"
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=30.0)

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> CompletionResult:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        if response_format:
            system += "\nReply with the JSON object only."
        turns = [m for m in messages if m["role"] != "system"]
        resp = self._client.messages.create(
            model=model, max_tokens=1024, system=system, messages=turns
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if "{" in text and "}" in text:  # keep the JSON object only
            text = text[text.index("{") : text.rindex("}") + 1]
        return CompletionResult(
            content=text,
            provider=self.provider,
            model=model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            raw_message=resp,
        )


def model_for_tier(tier: str) -> tuple[str, str, str]:
    """Return (model, provider_hint, base configuration key). Haiku is the cheap tier."""
    if tier == "small":
        return os.environ.get("ROUTER_SMALL_MODEL") or "claude-haiku-5-5", "anthropic", "anthropic"
    return os.environ.get("ROUTER_LARGE_MODEL") or "claude-sonnet-5-5", "anthropic", "anthropic"


def build_primary_backend() -> AnthropicChatBackend | None:
    key = os.environ.get("ANTHROPIC_API_KEY") or ""
    if not key.strip():
        return None
    return AnthropicChatBackend(api_key=key)


def build_fallback_backend() -> OpenAIChatBackend | None:
    key = os.environ.get("OPENROUTER_API_KEY") or ""
    if not key.strip():
        return None
    return OpenAIChatBackend(base_url=OPENROUTER_BASE, api_key=key, provider="openrouter")


def complete_with_fallback(
    backend: ChatBackend | None,
    *,
    tier: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    response_format: dict[str, Any] | None = None,
) -> CompletionResult:
    model, _, _ = model_for_tier(tier)
    fallbacks = []
    if backend is not None:
        fallbacks.append((backend, model))
    fb = build_fallback_backend()
    if fb is not None:
        fb_model = (
            OPENROUTER_FALLBACK_MODEL
            if tier == "large"
            else (os.environ.get("OPENROUTER_SMALL_MODEL") or "anthropic/claude-haiku-5-5")
        )
        if not any(b.provider == fb.provider for b, _ in fallbacks):
            fallbacks.append((fb, fb_model))
    if not fallbacks:
        raise RuntimeError("no_api_key")
    last_err: Exception | None = None
    for b, m in fallbacks:
        try:
            return b.complete(
                model=m, messages=messages, tools=tools, response_format=response_format
            )
        except Exception as exc:  # noqa: BLE001 — try next provider
            last_err = exc
    assert last_err is not None
    raise last_err


def list_models_http() -> list[dict[str, Any]]:
    key = os.environ.get("ANTHROPIC_API_KEY") or ""
    if not key.strip():
        return []
    import anthropic

    return [{"id": m.id} for m in anthropic.Anthropic(api_key=key).models.list()]
