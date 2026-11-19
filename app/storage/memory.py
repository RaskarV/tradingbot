"""In-memory store (one instance per tenant). Phase 1 replaces this with PostgreSQL + RLS."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Lead:
    user_id: int
    source: Optional[str] = None
    campaign: Optional[str] = None
    stage: str = "started"
    awaiting: Optional[str] = None       # "name" | "phone" | "q:<key>" | None
    name: Optional[str] = None
    phone: Optional[str] = None
    answers: dict = field(default_factory=dict)
    consent_given: bool = False
    opted_out: bool = False
    booked: bool = False
    guide_sent: bool = False
    booking_link_sent: bool = False
    qualified: bool = False


@dataclass
class Job:
    id: int
    user_id: int
    day: int
    text: str
    due_at: datetime
    status: str = "pending"      # pending | sent | cancelled | blocked | failed
    attempts: int = 0
    reason: str = ""


class InMemoryStore:
    def __init__(self):
        self.leads: dict[int, Lead] = {}
        self.messages: list[dict] = []
        self.consents: list[dict] = []
        self.decisions: list[dict] = []
        self.audit_log: list[dict] = []
        self.tickets: list[dict] = []
        self.handoffs: list[dict] = []
        self.jobs: list[Job] = []
        self._seen: set = set()
        self._ids = itertools.count(1)

    def get_lead(self, user_id): return self.leads.get(user_id)

    def get_or_create_lead(self, user_id, **kw) -> tuple[Lead, bool]:
        if user_id in self.leads:
            return self.leads[user_id], False
        self.leads[user_id] = Lead(user_id=user_id, **kw)
        return self.leads[user_id], True

    def seen_update(self, key) -> bool:
        if key in self._seen:
            return True
        self._seen.add(key)
        return False

    def add_message(self, user_id, direction, text, ts, kind=""):
        self.messages.append(dict(user_id=user_id, direction=direction, text=text, ts=ts, kind=kind))

    def add_consent(self, user_id, status, ts, notice_ref):
        self.consents.append(dict(user_id=user_id, status=status, ts=ts, notice=notice_ref))

    def add_decision(self, user_id, kind, verdict, hits, ts, reason=""):
        self.decisions.append(dict(user_id=user_id, kind=kind, verdict=verdict,
                                   hits=list(hits), ts=ts, reason=reason))

    def audit(self, action, **details):
        self.audit_log.append(dict(action=action, **details))

    def add_ticket(self, user_id, reason, detail, ts):
        self.tickets.append(dict(user_id=user_id, reason=reason, detail=detail, ts=ts, status="open"))

    def add_handoff(self, **kw):
        self.handoffs.append(dict(status="pending_call", **kw))

    def add_job(self, user_id, day, text, due_at) -> Optional[Job]:
        if any(j.user_id == user_id and j.day == day for j in self.jobs):
            return None                       # idempotent scheduling
        job = Job(next(self._ids), user_id, day, text, due_at)
        self.jobs.append(job)
        return job

    def cancel_jobs(self, user_id, reason):
        n = 0
        for j in self.jobs:
            if j.user_id == user_id and j.status == "pending":
                j.status, j.reason = "cancelled", reason
                n += 1
        return n

    def due_jobs(self, now):
        return sorted((j for j in self.jobs if j.status == "pending" and j.due_at <= now),
                      key=lambda j: (j.due_at, j.day))
