"""Follow-up runner (day 1/3/7). Every send re-checks consent, opt-out, booking and
compliance at SEND time. Disabled unless BOTH the client feature and FOLLOWUPS_ENABLED are on."""
from __future__ import annotations

from datetime import timedelta

MAX_ATTEMPTS = 3
RETRY_DELAY = timedelta(hours=1)


class FollowupScheduler:
    def __init__(self, store, outbound, client, settings):
        self.store, self.outbound, self.client, self.settings = store, outbound, client, settings

    def enabled(self) -> bool:
        return self.client.followups_enabled and self.settings.followups_enabled

    async def run_due(self, now) -> dict:
        stats = dict(sent=0, cancelled=0, blocked=0, retry=0, failed=0, deferred=0)
        for job in self.store.due_jobs(now):
            if not self.enabled():
                stats["deferred"] += 1
                continue
            lead = self.store.get_lead(job.user_id)
            if lead is None or lead.booked or lead.opted_out or not lead.consent_given:
                job.status, job.reason = "cancelled", "ineligible_at_send_time"
                stats["cancelled"] += 1
                continue
            text = job.text.format_map(_Safe(
                name=lead.name or "there", client_name=self.client.name,
                booking_url=self.settings.get(self.client.booking_url_env) or "[BOOKING_URL not configured]"))
            res = await self.outbound.send(lead, text, kind="followup", now=now)
            if res.status == "sent":
                job.status = "sent"; stats["sent"] += 1
            elif res.status in ("blocked", "suppressed"):
                job.status, job.reason = "blocked", res.reason; stats["blocked"] += 1
            else:
                job.attempts += 1
                if job.attempts >= MAX_ATTEMPTS:
                    job.status, job.reason = "failed", "max_attempts"; stats["failed"] += 1
                else:
                    job.due_at = now + RETRY_DELAY; stats["retry"] += 1
        return stats


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"
