"""lookup_verified_information: answers ONLY from approved FAQ entries; never invents."""
from __future__ import annotations

import re

from app.config.sentinel import is_unset

_STOP = {"the", "a", "an", "is", "are", "do", "does", "i", "you", "your", "my", "me", "to", "of",
         "for", "and", "or", "in", "on", "it", "can", "what", "how", "much", "will", "this", "that",
         "with", "be", "there", "have", "has", "about", "tell"}


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP}


def lookup_verified_information(faqs, question: str):
    qt = _tokens(question)
    best, best_score = None, 0
    for f in faqs:
        if is_unset(f.answer):
            continue                       # unfilled answers are unverified: never use them
        kw = {k.lower() for k in f.keywords}
        score = len(qt & _tokens(f.question)) + 2 * len(qt & kw)
        if score > best_score:
            best, best_score = f, score
    return best.answer if best and best_score >= 2 else None


def search_verified(faqs, question: str, limit: int = 3):
    """Return up to `limit` approved FAQ entries relevant to the question (score >= 2)."""
    qt = _tokens(question)
    scored = []
    for f in faqs:
        if is_unset(f.answer):
            continue
        kw = {k.lower() for k in f.keywords}
        score = len(qt & _tokens(f.question)) + 2 * len(qt & kw)
        if score >= 2:
            scored.append((score, f))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:limit]]
