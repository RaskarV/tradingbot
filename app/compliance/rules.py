"""Deterministic compliance rules (backend code, not prompts). Fail-closed.

NOT legal advice: a qualified Indian securities-law professional must review and
own these rule sets before production use.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

RULESET_VERSION = "2026-11-v1"
_NEG = re.compile(r"(\bnot\b|\bno\b|\bnever\b|n't\b|\bcannot\b|\bwithout\b)", re.I)


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: re.Pattern
    negation_ok: bool = False   # a preceding "not/no/never/n't" neutralises the match


def _r(id_, pat, neg=False):
    return Rule(id_, re.compile(pat, re.I), neg)


RULES = [
    _r("GUARANTEED_RETURNS",
       r"\bguarantee[ds]?\b.{0,30}\b(returns?|profits?|income|gains?|money)\b"
       r"|\b(assured|guaranteed|sure[- ]shot)\b.{0,20}\b(returns?|profits?|income|gains?)\b"
       r"|\brisk[- ]free\b|\b100% (profit|returns?|accuracy|success)\b", True),
    _r("PROFIT_PROMISE",
       r"\b(earn|make|get|generate)\b.{0,15}(₹|rs\.?|inr|\$)\s?\d[\d,]*(k|l|lakh|lakhs|crore)?\b"
       r".{0,25}\b(per|a|every|each)\s(day|week|month)\b"),
    _r("PERSONAL_ADVICE",
       r"\byou (should|must|need to)\b.{0,15}\b(buy|sell|hold|short|invest in)\b"
       r"|\bi (recommend|suggest|advise)\b.{0,20}\b(buy|sell|hold|invest|stocks?|shares?)\b"),
    _r("COLLECT_CAPITAL",
       r"\bhow much\b.{0,25}\b(capital|money|funds?|savings)\b.{0,25}\b(invest|trade|trading|have|deploy)\b"
       r"|\bwhat('s| is) your (trading )?capital\b|\binvestment (amount|budget)\b"),
    _r("REGISTRATION_CLAIM",
       r"\bsebi[- ]registered\b|\bregistered (investment )?advis[eo]rs?\b|\bsebi (approved|certified)\b", True),
    _r("CLAIMS_HUMAN", r"\bi(?:'m| am) (a )?(real |actual )?(human|person)\b", True),
    _r("FALSE_URGENCY",
       r"\b(last chance|only today|today only|offer (ends|expires)|hurry|act now"
       r"|limited (seats|spots|slots)|seats (are )?filling|don't miss out|ends tonight)\b"),
]
PLACEHOLDER_RULE = _r("UNRESOLVED_PLACEHOLDER", r"FILL_IN|PLACEHOLDER|\[[A-Z_]+ not configured\]")

_ADVICE_REQUEST = re.compile(
    r"\bshould i (buy|sell|hold|invest|short)\b"
    r"|\b(which|what)\b.{0,20}\b(stocks?|shares?|scrips?|options?|etfs?|crypto|coins?)\b.{0,30}\b(buy|sell|invest|pick|best)\b"
    r"|\b(buy|sell)\b.{0,12}\b(or|/)\b.{0,12}\b(hold|sell|buy)\b"
    r"|\b(give|share|send) me (a )?(stock )?tips?\b", re.I)


@dataclass(frozen=True)
class Decision:
    verdict: str                       # "allow" | "block"
    hits: tuple = field(default_factory=tuple)
    ruleset: str = RULESET_VERSION


def _negated(text: str, start: int) -> bool:
    return bool(_NEG.search(text[max(0, start - 25):start]))


def evaluate(text: str, *, real_send: bool = False) -> Decision:
    t = " ".join(text.split())
    hits = []
    rules = RULES + ([PLACEHOLDER_RULE] if real_send else [])
    for rule in rules:
        for m in rule.pattern.finditer(t):
            if rule.negation_ok and _negated(t, m.start()):
                continue
            hits.append(rule.id)
            break
    return Decision("block" if hits else "allow", tuple(hits))


def is_advice_request(text: str) -> bool:
    return bool(_ADVICE_REQUEST.search(text))
