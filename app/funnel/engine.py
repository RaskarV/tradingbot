"""Funnel engine implementing the client flow:

reel -> bot link -> name+phone -> qualifying questions -> free guide -> book a call?
   yes -> sales team calls
   no  -> follow-ups (day 1, 3, 7 from guide delivery) -> books later -> sales team calls

Replies are drafts: every one goes through OutboundMessageService.
"""
from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.compliance.rules import is_advice_request
from app.knowledge.lookup import lookup_verified_information
from app.messaging.gateways import CONTACT_BUTTON

START_RE = re.compile(r"^/start(?:@\w+)?(?:\s+(\S+))?\s*$", re.I)
OPT_OUT_RE = re.compile(
    r"^\s*/?(stop|unsubscribe)\s*[.!]*\s*$"
    r"|\b(unsubscribe|opt[- ]?out|stop (messaging|texting|contacting|sending)"
    r"|do not (message|contact)|don'?t (message|contact))\b", re.I)
CONSENT_YES = re.compile(r"^\s*(yes|y|i agree|agree|ok|okay|sure|accept|i accept|continue)\s*[.!]*\s*$", re.I)
CONSENT_NO = re.compile(r"^\s*(no|n|no thanks|decline|i disagree|disagree)\s*[.!]*\s*$", re.I)
BOOK_NO = re.compile(r"\b(not now|maybe later|later|nope|no)\b", re.I)
BOOK_YES = re.compile(r"\b(yes|yeah|yep|sure|book|schedule|call|interested|ok|okay)\b", re.I)
PAYLOAD_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

B_CONSENT = ["I agree", "No thanks"]
B_BOOK = ["Yes, book a call", "Not now"]


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def normalize_phone(text: str, default_cc: str):
    d = re.sub(r"[\s\-().]", "", text)
    if not re.fullmatch(r"\+?\d{8,15}", d):
        return None
    if d.startswith("+"):
        return d
    if len(d) == 10:
        return default_cc + d
    if len(d) > 10:
        return "+" + d
    return None


def _valid_name(text: str) -> bool:
    t = text.strip()
    return 2 <= len(t) <= 60 and any(c.isalpha() for c in t) and "?" not in t and not t.startswith("/")


@dataclass
class Ctx:
    lead: object
    now: datetime
    out: list = field(default_factory=list)


class FlowEngine:
    def __init__(self, store, outbound, notifier, client, settings, clock=None, agent=None):
        self.agent = agent
        self.store, self.outbound, self.notifier = store, outbound, notifier
        self.client, self.settings = client, settings
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._locks = defaultdict(asyncio.Lock)

    # ---------- helpers ----------
    def _booking_url(self):
        return self.settings.get(self.client.booking_url_env) or "[BOOKING_URL not configured]"

    def _render(self, template: str, lead) -> str:
        ctx = _Safe(client_name=self.client.name, name=(lead.name or "there"),
                    booking_url=self._booking_url(), privacy_notice=self.client.privacy_notice)
        try:
            return template.format_map(ctx)
        except (KeyError, ValueError, IndexError, AttributeError):
            return template

    async def _say(self, c: Ctx, text, kind="flow", buttons=None, attachment=None, raw=False):
        res = await self.outbound.send(c.lead, text if raw else self._render(text, c.lead), kind=kind,
                                       now=c.now, buttons=buttons, attachment=attachment)
        c.out.append(res)
        return res

    async def _msg(self, c: Ctx, key, kind="flow", buttons=None, attachment=None):
        return await self._say(c, self.client.messages[key], kind, buttons, attachment)

    def _ticket(self, c: Ctx, reason, detail):
        self.store.add_ticket(c.lead.user_id, reason, detail, c.now)

    # ---------- entry point ----------
    async def handle(self, user_id, text="", *, update_id=None, contact_phone=None, now=None):
        now = now or self.clock()
        if update_id is not None and self.store.seen_update((user_id, update_id)):
            return []
        async with self._locks[user_id]:
            text = (text or "").strip()
            m = START_RE.match(text)
            payload = m.group(1) if m else None
            if payload is not None and not PAYLOAD_RE.match(payload):
                payload = None
            source = campaign = None
            if payload:
                source, _, campaign = payload.partition("_")
                campaign = campaign or None
            lead, created = self.store.get_or_create_lead(user_id, source=source, campaign=campaign)
            c = Ctx(lead, now)
            self.store.add_message(user_id, "in", text or "[contact]", now)

            if m:
                await self._on_start(c, created)
                return c.out
            if text and OPT_OUT_RE.search(text):
                await self._opt_out(c)
                return c.out
            if lead.opted_out or lead.stage == "declined":
                return c.out                                   # stay silent until /start
            if lead.stage == "started":                        # first contact without /start
                await self._on_start(c, True)
                return c.out
            if lead.stage == "consent_pending":
                await self._on_consent(c, text)
                return c.out
            if lead.booked:
                await self._after_booking(c, text)
                return c.out

            if contact_phone and lead.awaiting == "phone":
                await self._take_phone(c, contact_phone)
                return c.out
            if not text:
                return c.out
            if is_advice_request(text):
                await self._msg(c, "advice_deflection")
                self._ticket(c, "advice_request", text[:200])
                await self._reprompt(c)
                return c.out
            if "?" in text:
                await self._answer_question(c, text)
                await self._reprompt(c)
                return c.out
            if lead.awaiting:
                await self._take_answer(c, text)
                return c.out
            if lead.stage == "guide_sent":
                await self._on_booking_reply(c, text)
            return c.out

    # ---------- steps ----------
    async def _on_start(self, c: Ctx, created: bool):
        lead = c.lead
        if created or lead.opted_out or lead.stage == "declined":
            lead.opted_out, lead.consent_given = False, False
            lead.stage = "consent_pending"
            await self._msg(c, "intro", "onboarding")
            await self._msg(c, "consent_prompt", "onboarding", buttons=B_CONSENT)
            return
        await self._msg(c, "welcome_back")
        if lead.booked:
            await self._msg(c, "already_booked")
        else:
            await self._reprompt(c)

    async def _on_consent(self, c: Ctx, text: str):
        lead = c.lead
        if CONSENT_YES.match(text):
            lead.consent_given, lead.stage = True, "contact_capture"
            self.store.add_consent(lead.user_id, "granted", c.now, "privacy_notice")
            await self._prompt_next(c)
        elif CONSENT_NO.match(text):
            lead.stage = "declined"
            self.store.add_consent(lead.user_id, "declined", c.now, "privacy_notice")
            await self._msg(c, "consent_declined", "onboarding")
        else:
            lead.stage = "consent_pending"
            await self._msg(c, "consent_prompt", "onboarding", buttons=B_CONSENT)

    async def _opt_out(self, c: Ctx):
        lead = c.lead
        lead.opted_out, lead.consent_given, lead.stage, lead.awaiting = True, False, "opted_out", None
        self.store.add_consent(lead.user_id, "withdrawn", c.now, "opt_out")
        n = self.store.cancel_jobs(lead.user_id, "opted_out")
        self.store.audit("opt_out", user_id=lead.user_id, cancelled_jobs=n)
        await self._msg(c, "opt_out_ack", "opt_out_ack")

    async def _prompt_next(self, c: Ctx):
        lead, cl = c.lead, self.client
        order = ["name", "phone", "questions"] if cl.contact_capture == "before_questions" \
            else ["questions", "name", "phone"]
        for item in order:
            if item == "name" and not lead.name:
                lead.awaiting = "name"
                await self._msg(c, "ask_name")
                return
            if item == "phone" and not lead.phone:
                lead.awaiting = "phone"
                await self._msg(c, "ask_phone", buttons=[CONTACT_BUTTON])
                return
            if item == "questions":
                q = next((q for q in cl.questions if q.key not in lead.answers), None)
                if q:
                    lead.awaiting, lead.stage = f"q:{q.key}", "qualifying"
                    await self._say(c, q.prompt)
                    return
        lead.qualified = True
        await self._deliver_guide(c)

    async def _reprompt(self, c: Ctx):
        if c.lead.awaiting:
            await self._prompt_next(c)

    async def _take_answer(self, c: Ctx, text: str):
        lead, aw = c.lead, c.lead.awaiting
        if aw == "name":
            if not _valid_name(text):
                await self._msg(c, "invalid_name")
                return
            lead.name = text.strip()
        elif aw == "phone":
            await self._take_phone(c, text)
            return
        elif aw.startswith("q:"):
            lead.answers[aw[2:]] = text[:500]
        lead.awaiting = None
        await self._prompt_next(c)

    async def _take_phone(self, c: Ctx, text: str):
        phone = normalize_phone(text, self.client.default_country_code)
        if not phone:
            await self._msg(c, "invalid_phone", buttons=[CONTACT_BUTTON])
            return
        c.lead.phone, c.lead.awaiting = phone, None
        await self._prompt_next(c)

    async def _deliver_guide(self, c: Ctx):
        lead = c.lead
        if lead.guide_sent:
            return
        lead.awaiting, lead.guide_sent, lead.stage = None, True, "guide_sent"
        magnet = next(m for m in self.client.lead_magnets if m["id"] == self.client.guide_magnet_id)
        path = self.settings.get(magnet["path_env"])
        if path:
            await self._msg(c, "guide_intro", "resource", attachment=path)
        else:
            self.store.audit("guide_path_unset", user_id=lead.user_id)
            await self._msg(c, "guide_unavailable", "resource")
        for step in self.client.followup_steps:
            self.store.add_job(lead.user_id, step.day, step.text, c.now + timedelta(days=step.day))
        await self._msg(c, "booking_offer", buttons=B_BOOK)

    async def _on_booking_reply(self, c: Ctx, text: str):
        lead = c.lead
        if BOOK_NO.search(text):
            await self._msg(c, "no_booking_ack")
        elif BOOK_YES.search(text):
            lead.booking_link_sent = True
            await self._msg(c, "booking_link")
        else:
            await self._answer_question(c, text)

    async def _answer_with_agent(self, c: Ctx, text: str) -> bool:
        """LLM conversation. Returns False to fall back to the deterministic FAQ path."""
        if self.agent is None or not self.client.llm_enabled:
            return False
        reply = await self.agent.run(c.lead, text, c.now)
        if not reply.ok:
            return False
        res = await self._say(c, reply.text, "agent", raw=True)          # LLM text is never templated
        if res.status == "blocked":                                       # compliance gate said no
            await self._msg(c, "faq_fallback")
            await self.notifier.notify(f"Agent reply blocked ({','.join(res.hits) or res.reason}) "
                                       f"for lead {c.lead.user_id}")
            return True
        for kind, rid in reply.actions:
            if kind == "booking":
                c.lead.booking_link_sent = True
                await self._msg(c, "booking_link")
            elif kind == "resource":
                magnet = next(m for m in self.client.lead_magnets if m["id"] == rid)
                path = self.settings.get(magnet["path_env"])
                await self._say(c, f"Here is {magnet.get('title', 'your resource')}.", "resource",
                                attachment=path)
        return True

    async def _answer_question(self, c: Ctx, text: str):
        if await self._answer_with_agent(c, text):
            return
        answer = lookup_verified_information(self.client.faqs, text)
        if answer:
            await self._say(c, answer, "answer")
        else:
            await self._msg(c, "faq_fallback")
            self._ticket(c, "unanswered_question", text[:200])
            await self.notifier.notify(f"Unanswered question from lead {c.lead.user_id}: {text[:200]}")

    async def _after_booking(self, c: Ctx, text: str):
        if "?" in text:
            await self._answer_question(c, text)
        else:
            await self._msg(c, "already_booked")

    # ---------- booking confirmation (from Cal.com/Calendly webhook or dashboard) ----------
    async def confirm_booking(self, user_id, now=None, slot=None):
        now = now or self.clock()
        lead = self.store.get_lead(user_id)
        if lead is None or lead.booked:
            return False
        c = Ctx(lead, now)
        lead.booked, lead.stage, lead.awaiting = True, "booked", None
        cancelled = self.store.cancel_jobs(user_id, "booked")
        self.store.add_handoff(user_id=user_id, name=lead.name, phone=lead.phone, source=lead.source,
                               campaign=lead.campaign, answers=dict(lead.answers), slot=slot, ts=now)
        self.store.audit("booking_confirmed", user_id=user_id, cancelled_followups=cancelled)
        summary = "\n".join([
            "New booked call - sales team to phone this lead",
            f"Name: {lead.name}", f"Phone: {lead.phone}",
            f"Source: {lead.source or '-'} / {lead.campaign or '-'}",
            "Answers: " + "; ".join(f"{k}={v}" for k, v in lead.answers.items()),
            f"Slot: {slot or 'see booking tool'}"])
        await self.notifier.notify(summary)
        await self._msg(c, "booking_confirmed", "service")
        return True
