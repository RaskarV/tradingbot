from __future__ import annotations

from app.config.settings import ConfigError


def build_provider(settings):
    """LLM_PROVIDER: none (default) | mock (dev/test only) | anthropic."""
    name = settings.env.get("LLM_PROVIDER", "none").strip().lower()
    if name in ("", "none"):
        return None
    if name == "mock":
        if settings.app_env == "production":
            raise ConfigError("LLM_PROVIDER=mock is not allowed in production")
        from .mock import RuleBasedMockLLM
        return RuleBasedMockLLM()
    if name == "anthropic":
        key, model = settings.get("LLM_API_KEY"), settings.get("LLM_MODEL")
        if not key or not model:
            raise ConfigError("LLM_PROVIDER=anthropic needs LLM_API_KEY and LLM_MODEL (not placeholders)")
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(key, model)
    raise ConfigError(f"unknown LLM_PROVIDER '{name}' (use none | mock | anthropic)")
