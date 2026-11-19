# PROJECT_STATUS

Last updated: 2026-11-20. Test run: `python -m unittest discover -s tests -t .` -> 66 tests, all passing (Python 3.12, standard library + PyYAML only).

## What exists (follows the client flow diagram)
reel -> bot link -> name + phone -> questions -> free guide -> book a call? -> sales team calls / follow-ups day 1, 3, 7 -> books later -> sales team calls

| Area | Status |
|---|---|
| Config: env settings, client YAML validation, placeholder detection, production startup guard | Implemented, tested |
| Funnel engine (deep-link source tracking, consent, name/phone capture, one question at a time, guide delivery, booking link, booking confirmation -> sales handoff) | Implemented, tested on mocks |
| Outbound gate (environment/activation, opt-out, consent, compliance rules, approval records, fail-closed) | Implemented, tested |
| Compliance rules v1 (guaranteed returns, profit promises, personal advice, collecting capital, registration claims, claiming to be human, false urgency, unresolved placeholders) | Implemented, tested - NOT legally reviewed |
| Follow-up scheduler (day 1/3/7 from guide delivery, send-time re-checks, bounded retries, off by default) | Implemented, tested |
| FAQ lookup (approved answers only; unfilled answers are never used; misses escalate) | Implemented, tested |
| **Phase 2: LLM conversation layer** (provider-neutral port, agent loop, 5 tools, prompt built from client YAML, per-user rate limit, time and round limits, safe fallback to FAQ path) | Implemented, tested with scripted/mock LLMs |
| Tool safety (arguments validated against config; booking link and files come only from config; the LLM cannot send anything; unknown tools rejected) | Implemented, tested |
| LLM replies pass the same outbound compliance gate; a blocked reply is replaced by a safe fallback and escalated | Implemented, tested |
| Anthropic adapter (standard-library HTTP) | Written; request/response conversion tested offline; **NOT tested against the real API** |
| OpenAI adapter | Not built |
| Console simulator (`python -m app.main console`) | Implemented, smoke-tested |
| Telegram adapter (aiogram 3 long polling, contact-share button, own-contact check) | Written, **UNTESTED** (aiogram not installable in the build sandbox; no bot token) |
| Booking webhook (Cal.com/Calendly) | Not built; `FlowEngine.confirm_booking()` is the hook it will call |
| PostgreSQL, Alembic, tenant isolation (RLS) | Not built (Phase 1). Storage is in-memory, so production start is refused |
| Retrieval over documents (pgvector RAG) | Not built (Phase 7). The knowledge tool searches approved FAQ entries only |
| REST API, auth/RBAC, Next.js dashboard | Not built (Phases 5-6) |

## How the LLM is used
The scripted funnel (consent, name, phone, questions, guide, follow-ups) stays deterministic. The LLM only handles free-text side questions during the funnel and conversation after the guide. Advice requests, opted-out and declined users never reach it. If the LLM is off, errors, times out or is rate limited, the bot falls back to approved-FAQ answers.

## Assumptions taken (change if wrong)
0. `llm.allow_general_education: true` lets the model explain basic market concepts from general knowledge (never specific securities or advice). This needs legal approval; set false to restrict it to verified facts.
1. Name/phone are collected before the questions, exactly as drawn (`funnel.contact_capture`; use `at_guide` to delay).
2. Follow-up days 1/3/7 are counted from the moment the guide is delivered.
3. "Sales team calls" is triggered by a confirmed booking; the sales team gets a summary via SALES_NOTIFICATION_CHAT_ID.
4. Message wording in clientone.yaml is draft text pending client and legal approval.

## Not production-ready
Blocked until: client details filled in (see CLIENT_SETUP_CHECKLIST.md), privacy notice approved, legal review of compliance rules and messages, real-credential Telegram testing, database phase, end-to-end tests on real conversations.
