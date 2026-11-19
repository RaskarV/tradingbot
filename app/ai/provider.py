"""Provider-neutral LLM types. The LLM only ever produces text + tool calls (drafts)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


class ProviderError(Exception):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Message:
    role: str                              # "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list = field(default_factory=list)   # assistant messages only
    tool_call_id: Optional[str] = None               # tool messages only
    name: Optional[str] = None                       # tool messages only


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list = field(default_factory=list)


class LLMProvider(Protocol):
    async def complete(self, system: str, messages: list, tools: list) -> LLMResponse: ...
