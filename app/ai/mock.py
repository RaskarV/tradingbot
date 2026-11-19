"""Test doubles. ScriptedLLM for tests; RuleBasedMockLLM lets the dev console exercise the
real agent loop without any API key. Neither is allowed in production."""
from __future__ import annotations

import json
import re

from .provider import LLMResponse, ToolCall


class ScriptedLLM:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    async def complete(self, system, messages, tools):
        self.calls.append(dict(system=system, messages=list(messages), tools=tools))
        r = self.responses.pop(0) if self.responses else LLMResponse(text="OK")
        if isinstance(r, Exception):
            raise r
        return r


class RuleBasedMockLLM:
    """lookup -> answer from verified facts, or escalate and admit it does not know."""

    async def complete(self, system, messages, tools):
        last_user = max(i for i, m in enumerate(messages) if m.role == "user")
        turn = messages[last_user:]
        called = {tc.name for m in turn if m.role == "assistant" for tc in m.tool_calls}
        if len(turn) == 1:
            q = re.sub(r"</?user_message>", "", turn[0].content).strip()
            return LLMResponse(tool_calls=[ToolCall("m1", "lookup_verified_information", {"query": q})])
        results = [json.loads(m.content) for m in turn if m.role == "tool"]
        facts = [x for r in results for x in r.get("matches", [])]
        if facts:
            return LLMResponse(text=facts[0]["answer"])
        if "escalate_to_human" not in called:
            return LLMResponse(tool_calls=[ToolCall("m2", "escalate_to_human",
                                                    {"reason": "No verified information for the question"})])
        return LLMResponse(text="I don't have verified information on that, so I won't guess. "
                                "I've asked our team to follow up with you.")
