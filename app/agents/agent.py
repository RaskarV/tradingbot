"""Agent loop: LLM -> tool calls -> LLM ... -> final draft text. Bounded, time-limited,
rate-limited, and failure always degrades to the deterministic path (ok=False)."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from app.ai.prompt import build_system_prompt
from app.ai.provider import Message
from .tools import AgentTools, tool_specs

MAX_USER_CHARS = 1000


@dataclass
class AgentReply:
    ok: bool
    text: Optional[str] = None
    actions: list = field(default_factory=list)
    escalated: bool = False
    rounds: int = 0
    tools_used: list = field(default_factory=list)
    error: Optional[str] = None


def _wrap(text: str) -> str:
    clean = text.replace("<user_message>", "").replace("</user_message>", "")[:MAX_USER_CHARS]
    return f"<user_message>{clean}</user_message>"


class AgentRunner:
    def __init__(self, provider, store, notifier, client, *, allow_general_education=True,
                 max_rounds=3, history_messages=10, timeout=20.0, max_calls_per_hour=20):
        self.provider, self.store, self.notifier, self.client = provider, store, notifier, client
        self.allow_general_education, self.max_rounds = allow_general_education, max_rounds
        self.history_messages, self.timeout, self.max_calls = history_messages, timeout, max_calls_per_hour
        self._calls = defaultdict(list)

    def _history(self, user_id) -> list:
        rows = [m for m in self.store.messages if m["user_id"] == user_id]
        rows = rows[-(self.history_messages + 1):-1]            # exclude the current inbound message
        msgs: list = []
        for r in rows:
            role = "user" if r["direction"] == "in" else "assistant"
            content = _wrap(r["text"]) if role == "user" else r["text"]
            if msgs and msgs[-1].role == role:
                msgs[-1].content += "\n" + content
            else:
                msgs.append(Message(role, content))
        while msgs and msgs[0].role != "user":
            msgs.pop(0)
        return msgs

    async def run(self, lead, text: str, now) -> AgentReply:
        recent = [t for t in self._calls[lead.user_id] if now - t < timedelta(hours=1)]
        if len(recent) >= self.max_calls:
            self.store.audit("agent_rate_limited", user_id=lead.user_id)
            return AgentReply(False, error="rate_limited")
        recent.append(now)
        self._calls[lead.user_id] = recent

        tools = AgentTools(self.store, self.client, self.notifier, lead, now)
        specs = tool_specs(self.client)
        system = build_system_prompt(self.client, lead, allow_general_education=self.allow_general_education)
        msgs = self._history(lead.user_id) + [Message("user", _wrap(text))]
        used: list = []
        try:
            for rnd in range(1, self.max_rounds + 2):
                resp = await asyncio.wait_for(self.provider.complete(system, msgs, specs), self.timeout)
                if not resp.tool_calls:
                    final = (resp.text or "").strip()
                    self.store.audit("agent_run", user_id=lead.user_id, rounds=rnd, tools=used,
                                     escalated=tools.escalated)
                    if not final:
                        return AgentReply(False, error="empty_reply", rounds=rnd, tools_used=used)
                    return AgentReply(True, final, tools.actions, tools.escalated, rnd, used)
                if rnd > self.max_rounds:
                    break
                msgs.append(Message("assistant", resp.text or "", tool_calls=list(resp.tool_calls)))
                for tc in resp.tool_calls:
                    used.append(tc.name)
                    result = await tools.execute(tc.name, tc.args)
                    msgs.append(Message("tool", json.dumps(result, ensure_ascii=False),
                                        tool_call_id=tc.id, name=tc.name))
            self.store.audit("agent_too_many_rounds", user_id=lead.user_id)
            return AgentReply(False, error="too_many_rounds", tools_used=used)
        except Exception as exc:  # noqa: BLE001 - timeout, provider error, anything: degrade safely
            self.store.audit("agent_error", user_id=lead.user_id, error=type(exc).__name__)
            return AgentReply(False, error=type(exc).__name__, tools_used=used)
