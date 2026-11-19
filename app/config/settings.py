"""Environment-based settings and the production startup guard."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping, Optional

from .sentinel import find_placeholders, is_unset

VALID_ENVS = ("test", "development", "production")


class ConfigError(Exception):
    pass


def _truthy(v: object) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    env: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_environ(cls) -> "Settings":
        return cls(env=dict(os.environ))

    @property
    def app_env(self) -> str:
        v = self.env.get("APP_ENV", "development").strip().lower()
        if v not in VALID_ENVS:
            raise ConfigError(f"APP_ENV must be one of {VALID_ENVS}, got {v!r}")
        return v

    def get(self, name: str) -> Optional[str]:
        """Return an env value, or None if missing / placeholder."""
        v = self.env.get(name)
        return None if is_unset(v) else v.strip()

    @property
    def tenant_activated(self) -> bool:
        return _truthy(self.env.get("TENANT_ACTIVATED", "false"))

    @property
    def followups_enabled(self) -> bool:
        return _truthy(self.env.get("FOLLOWUPS_ENABLED", "false"))


def production_problems(settings: Settings, client) -> list[str]:
    problems: list[str] = []
    required = {client.telegram_token_env, client.llm_key_env,
                client.booking_url_env, client.notify_chat_id_env}
    required |= {m["path_env"] for m in client.lead_magnets}
    for name in sorted(required):
        if settings.get(name) is None:
            problems.append(f"environment variable {name} is missing or a placeholder")
    for p in find_placeholders(client.raw):
        problems.append(f"client config still has an unfilled value at '{p}'")
    if client.llm_enabled:
        if settings.env.get("LLM_PROVIDER", "none").strip().lower() != "anthropic":
            problems.append("llm.enabled is true but LLM_PROVIDER is not a real provider (anthropic)")
        if settings.get("LLM_MODEL") is None:
            problems.append("environment variable LLM_MODEL is missing or a placeholder")
    if not client.legal_review_completed:
        problems.append("compliance.legal_review_completed is false (legal review pending)")
    if not settings.tenant_activated:
        problems.append("TENANT_ACTIVATED is not true (explicit activation required)")
    return problems


def assert_startup_ok(settings: Settings, client) -> list[str]:
    """In production, refuse to start with any problem. Elsewhere just report them."""
    problems = production_problems(settings, client)
    if settings.app_env == "production" and problems:
        raise ConfigError("Refusing to start in production:\n - " + "\n - ".join(problems))
    return problems
