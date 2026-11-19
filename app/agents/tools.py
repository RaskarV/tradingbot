"""The five agent tools. They validate every argument against client config and return
data; none of them can send a message. Deliveries are returned as `actions` that the funnel
engine sends through the OutboundMessageService."""
from __future__ import annotations

from app.knowledge.lookup import search_verified


def tool_specs(client) -> list:
    keys = [q.key for q in client.questions]
    magnets = [m["id"] for m in client.lead_magnets]
    return [
        {"name": "lookup_verified_information",
         "description": "Search approved business information (fees, duration, curriculum, policies). "
                        "Use before stating ANY business fact.",
         "input_schema": {"type": "object", "properties": {"query": {"type": "string", "maxLength": 300}},
                          "required": ["query"]}},
        {"name": "save_lead_qualification",
         "description": "Save something the user told you about themselves, using one of the allowed keys.",
         "input_schema": {"type": "object", "properties": {
             "key": {"type": "string", "enum": keys}, "value": {"type": "string", "maxLength": 300}},
             "required": ["key", "value"]}},
        {"name": "send_approved_resource",
         "description": "Queue an approved learning resource (lead magnet) for the user by id.",
         "input_schema": {"type": "object", "properties": {"resource_id": {"type": "string", "enum": magnets}},
                          "required": ["resource_id"]}},
        {"name": "provide_booking_link",
         "description": "Send the user the booking link for a free call with the team. Takes no arguments.",
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "escalate_to_human",
         "description": "Hand the conversation to the human team (sensitive, unknown or complex questions).",
         "input_schema": {"type": "object", "properties": {"reason": {"type": "string", "maxLength": 300}},
                          "required": ["reason"]}},
    ]


class AgentTools:
    def __init__(self, store, client, notifier, lead, now):
        self.store, self.client, self.notifier, self.lead, self.now = store, client, notifier, lead, now
        self.actions: list = []
        self.escalated = False

    async def execute(self, name: str, args) -> dict:
        if not isinstance(args, dict):
            return {"error": "arguments must be an object"}
        handler = getattr(self, f"_t_{name}", None) if name in {
            "lookup_verified_information", "save_lead_qualification", "send_approved_resource",
            "provide_booking_link", "escalate_to_human"} else None
        if handler is None:
            return {"error": f"unknown tool '{name}'"}
        try:
            return await handler(args)
        except Exception as exc:  # noqa: BLE001 - a broken tool must not crash the conversation
            return {"error": f"tool failed: {type(exc).__name__}"}

    async def _t_lookup_verified_information(self, a):
        q = str(a.get("query", ""))[:300]
        hits = search_verified(self.client.faqs, q)
        if not hits:
            return {"matches": [], "note": "No verified information found. Do not guess; escalate."}
        return {"matches": [{"question": f.question, "answer": f.answer} for f in hits]}

    async def _t_save_lead_qualification(self, a):
        valid = [q.key for q in self.client.questions]
        key, value = a.get("key"), str(a.get("value", "")).strip()[:300]
        if key not in valid:
            return {"error": "invalid key", "allowed_keys": valid}
        if not value:
            return {"error": "empty value"}
        self.lead.answers[key] = value
        return {"saved": key}

    async def _t_send_approved_resource(self, a):
        rid = a.get("resource_id")
        magnet = next((m for m in self.client.lead_magnets if m["id"] == rid), None)
        if magnet is None:
            return {"error": "unknown resource", "allowed": [m["id"] for m in self.client.lead_magnets]}
        if rid == self.client.guide_magnet_id:
            if self.lead.guide_sent:
                return {"status": "already_sent"}
            return {"status": "not_yet", "note": "The free guide is delivered automatically after the "
                                                 "short intro questions. Tell the user that."}
        self.actions.append(("resource", rid))
        return {"status": "queued"}

    async def _t_provide_booking_link(self, a):
        if self.lead.booked:
            return {"status": "already_booked"}
        self.actions.append(("booking", None))
        return {"status": "queued"}

    async def _t_escalate_to_human(self, a):
        reason = str(a.get("reason", "unspecified"))[:300]
        self.store.add_ticket(self.lead.user_id, "agent_escalation", reason, self.now)
        await self.notifier.notify(f"Agent escalation for lead {self.lead.user_id}: {reason}")
        self.escalated = True
        return {"status": "escalated"}
