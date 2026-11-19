"""The ONLY path to a gateway. Every outbound message passes: environment gate,
opt-out, consent, compliance rules, approval record; any error blocks (fail closed)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.compliance.rules import evaluate

PRE_CONSENT_KINDS = {"onboarding", "opt_out_ack"}


@dataclass
class SendResult:
    status: str          # sent | blocked | suppressed | failed
    reason: str = ""
    hits: tuple = ()
    text: str = ""


class OutboundMessageService:
    def __init__(self, store, gateway, settings):
        self.store, self.gateway, self.settings = store, gateway, settings

    async def send(self, lead, text, *, kind, now, buttons=None, attachment=None) -> SendResult:
        try:
            return await self._send(lead, text, kind, now, buttons, attachment)
        except Exception as exc:  # noqa: BLE001 - fail closed on anything unexpected
            self.store.audit("outbound_internal_error", user_id=lead.user_id, error=type(exc).__name__)
            return SendResult("blocked", "internal_error", text=text)

    async def _send(self, lead, text, kind, now, buttons, attachment) -> SendResult:
        s = self.store
        real = bool(getattr(self.gateway, "is_real", False))
        digest = hashlib.sha256(text.encode()).hexdigest()[:12]

        def record(verdict, reason, hits=()):
            s.add_decision(lead.user_id, kind, verdict, hits, now, reason=f"{reason}|{digest}")

        if real and not self.settings.tenant_activated:
            record("block", "tenant_not_activated")
            return SendResult("blocked", "tenant_not_activated", text=text)
        if lead.opted_out and kind != "opt_out_ack":
            record("suppress", "opted_out")
            return SendResult("suppressed", "opted_out", text=text)
        if kind not in PRE_CONSENT_KINDS and not lead.consent_given:
            record("suppress", "no_consent")
            return SendResult("suppressed", "no_consent", text=text)

        decision = evaluate(text, real_send=real)
        if decision.verdict == "block":
            record("block", "compliance:" + decision.ruleset, decision.hits)
            s.add_ticket(lead.user_id, "compliance_block", ",".join(decision.hits), now)
            return SendResult("blocked", "compliance", decision.hits, text)
        record("allow", "ok")

        try:
            await self.gateway.send(lead.user_id, text, buttons=buttons, attachment=attachment)
        except Exception as exc:  # noqa: BLE001
            s.audit("gateway_error", user_id=lead.user_id, error=type(exc).__name__)
            return SendResult("failed", "gateway_error", text=text)
        s.add_message(lead.user_id, "out", text, now, kind)
        return SendResult("sent", text=text)
