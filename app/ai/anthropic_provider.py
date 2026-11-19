"""Anthropic Messages API adapter (standard library only).
STATUS: written, offline-tested for request/response conversion, NOT tested against the real API."""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request

from .provider import LLMResponse, ProviderError, ToolCall

URL = "https://api.anthropic.com/v1/messages"


def convert_messages(messages) -> list:
    out, pending_results = [], []

    def flush():
        if pending_results:
            out.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for m in messages:
        if m.role == "tool":
            pending_results.append({"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content})
            continue
        flush()
        if m.role == "assistant" and m.tool_calls:
            blocks = ([{"type": "text", "text": m.content}] if m.content else [])
            blocks += [{"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.args} for tc in m.tool_calls]
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": m.role, "content": m.content})
    flush()
    return out


def parse_content(content_blocks) -> LLMResponse:
    text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text").strip()
    calls = [ToolCall(b["id"], b["name"], b.get("input") or {})
             for b in content_blocks if b.get("type") == "tool_use"]
    return LLMResponse(text=text, tool_calls=calls)


class AnthropicProvider:
    def __init__(self, api_key: str, model: str, max_tokens: int = 500, timeout: float = 20.0):
        self.api_key, self.model, self.max_tokens, self.timeout = api_key, model, max_tokens, timeout

    def _post(self, body: dict) -> dict:
        req = urllib.request.Request(
            URL, data=json.dumps(body).encode(), method="POST",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(type(exc).__name__) from exc       # never include the key/body

    async def complete(self, system, messages, tools) -> LLMResponse:
        body = {"model": self.model, "max_tokens": self.max_tokens, "system": system,
                "messages": convert_messages(messages),
                "tools": [{"name": t["name"], "description": t["description"],
                           "input_schema": t["input_schema"]} for t in tools]}
        data = await asyncio.to_thread(self._post, body)
        return parse_content(data.get("content", []))
