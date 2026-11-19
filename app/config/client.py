"""Loading and validating a client YAML file (one file per client/tenant)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]{1,40}$")
SECRET_PATTERNS = [
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"),   # Telegram bot token shape
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),          # LLM key shape
    re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),            # AWS key shape
]
ALLOWED_TOP = {"client", "brand_voice", "funnel", "messages", "faqs", "qualification",
               "lead_magnets", "booking", "followups", "escalation", "compliance",
               "knowledge", "features", "secrets", "llm"}
REQUIRED_MESSAGES = [
    "intro", "consent_prompt", "consent_declined", "opt_out_ack", "ask_name", "ask_phone",
    "invalid_name", "invalid_phone", "guide_intro", "guide_unavailable", "booking_offer",
    "booking_link", "no_booking_ack", "booking_confirmed", "already_booked",
    "advice_deflection", "faq_fallback", "welcome_back",
]


class ClientConfigError(Exception):
    pass


@dataclass(frozen=True)
class Question:
    key: str
    prompt: str


@dataclass(frozen=True)
class Faq:
    question: str
    answer: str
    keywords: tuple


@dataclass(frozen=True)
class FollowupStep:
    day: int
    text: str


@dataclass(frozen=True)
class ClientConfig:
    raw: dict
    slug: str
    name: str
    default_country_code: str
    privacy_notice: str
    contact_capture: str          # "before_questions" (as in the flow diagram) | "at_guide"
    messages: dict
    faqs: tuple
    questions: tuple
    lead_magnets: tuple
    guide_magnet_id: str
    booking_url_env: str
    followup_steps: tuple
    followups_enabled: bool
    notify_chat_id_env: str
    telegram_token_env: str
    llm_key_env: str
    legal_review_completed: bool
    llm_enabled: bool = False
    llm_allow_general_education: bool = True
    llm_max_rounds: int = 3
    llm_history: int = 10


def _walk_strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)
    elif isinstance(obj, str):
        yield obj


def parse_client(raw: dict) -> ClientConfig:
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise ClientConfigError("client file must be a YAML mapping")
    for k in raw:
        if k not in ALLOWED_TOP:
            errors.append(f"unknown top-level key '{k}'")
    for s in _walk_strings(raw):
        if any(p.search(s) for p in SECRET_PATTERNS):
            errors.append("a value looks like a real secret; secrets belong in environment variables")
            break

    def need(d, key, where):
        if not isinstance(d, dict) or key not in d:
            errors.append(f"missing '{where}.{key}'")
            return None
        return d[key]

    c = raw.get("client", {})
    slug = need(c, "slug", "client")
    if slug is not None and not SLUG_RE.match(str(slug)):
        errors.append("client.slug must be lowercase letters/digits/_/-")
    name = need(c, "name", "client")
    cc = c.get("default_country_code", "+91") if isinstance(c, dict) else "+91"
    notice = need(c, "privacy_notice", "client")

    funnel = raw.get("funnel", {}) or {}
    capture = funnel.get("contact_capture", "before_questions")
    if capture not in ("before_questions", "at_guide"):
        errors.append("funnel.contact_capture must be 'before_questions' or 'at_guide'")

    messages = raw.get("messages", {}) or {}
    for m in REQUIRED_MESSAGES:
        if m not in messages:
            errors.append(f"missing message template 'messages.{m}'")

    qs, seen = [], set()
    for i, q in enumerate((raw.get("qualification", {}) or {}).get("questions", [])):
        key, prompt = q.get("key"), q.get("prompt")
        if not key or not prompt:
            errors.append(f"qualification.questions[{i}] needs key and prompt")
        elif key in seen:
            errors.append(f"duplicate qualification key '{key}'")
        else:
            seen.add(key)
            qs.append(Question(key, prompt))

    faqs = tuple(Faq(f.get("q", ""), f.get("a", ""), tuple(f.get("keywords", [])))
                 for f in raw.get("faqs", []) or [])

    magnets = tuple(raw.get("lead_magnets", []) or [])
    for m in magnets:
        if not ENV_RE.match(str(m.get("path_env", ""))):
            errors.append(f"lead magnet '{m.get('id')}' needs a valid path_env variable name")
    if not magnets:
        errors.append("at least one lead magnet (the free guide) is required")
    guide_id = (funnel.get("guide_magnet_id") or (magnets[0]["id"] if magnets else ""))

    booking = raw.get("booking", {}) or {}
    secrets = raw.get("secrets", {}) or {}
    esc = raw.get("escalation", {}) or {}
    envs = {
        "booking.url_env": booking.get("url_env"),
        "escalation.notify_chat_id_env": esc.get("notify_chat_id_env"),
        "secrets.telegram_bot_token_env": secrets.get("telegram_bot_token_env"),
        "secrets.llm_api_key_env": secrets.get("llm_api_key_env"),
    }
    for where, val in envs.items():
        if not val or not ENV_RE.match(str(val)):
            errors.append(f"'{where}' must be an environment variable NAME (e.g. BOOKING_URL)")

    fu = raw.get("followups", {}) or {}
    steps, last = [], 0
    for i, s in enumerate(fu.get("schedule", []) or []):
        d = s.get("day")
        if not isinstance(d, int) or d <= last:
            errors.append(f"followups.schedule[{i}].day must be an increasing positive integer")
        else:
            last = d
        if not s.get("text"):
            errors.append(f"followups.schedule[{i}] needs text")
        steps.append(FollowupStep(d if isinstance(d, int) else 0, s.get("text", "")))

    llm = raw.get("llm", {}) or {}
    rounds, hist = llm.get("max_tool_rounds", 3), llm.get("history_messages", 10)
    if not (isinstance(rounds, int) and 1 <= rounds <= 6):
        errors.append("llm.max_tool_rounds must be an integer from 1 to 6")
    if not (isinstance(hist, int) and 0 <= hist <= 30):
        errors.append("llm.history_messages must be an integer from 0 to 30")

    if errors:
        raise ClientConfigError("Invalid client config:\n - " + "\n - ".join(errors))

    feats = raw.get("features", {}) or {}
    comp = raw.get("compliance", {}) or {}
    return ClientConfig(
        raw=raw, slug=str(slug), name=str(name), default_country_code=str(cc),
        privacy_notice=str(notice), contact_capture=capture, messages=dict(messages),
        faqs=faqs, questions=tuple(qs), lead_magnets=magnets, guide_magnet_id=guide_id,
        booking_url_env=booking["url_env"], followup_steps=tuple(steps),
        followups_enabled=bool(feats.get("followups", False)),
        notify_chat_id_env=esc["notify_chat_id_env"],
        telegram_token_env=secrets["telegram_bot_token_env"],
        llm_key_env=secrets["llm_api_key_env"],
        legal_review_completed=bool(comp.get("legal_review_completed", False)),
        llm_enabled=bool(llm.get("enabled", False)),
        llm_allow_general_education=bool(llm.get("allow_general_education", True)),
        llm_max_rounds=rounds, llm_history=hist,
    )


def load_client(path) -> ClientConfig:
    with open(Path(path), encoding="utf-8") as f:
        return parse_client(yaml.safe_load(f))
