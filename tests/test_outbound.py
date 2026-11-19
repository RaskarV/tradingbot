import unittest
from tests.helpers import T0, build
from app.messaging.gateways import MockGateway


class FakeRealGateway(MockGateway):
    is_real = True


class OutboundGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_gateway_blocked_without_activation(self):
        app = build(gateway=FakeRealGateway())
        lead, _ = app["store"].get_or_create_lead(1)
        lead.consent_given = True
        r = await app["outbound"].send(lead, "Hello", kind="flow", now=T0)
        self.assertEqual((r.status, r.reason), ("blocked", "tenant_not_activated"))
        self.assertEqual(app["gw"].sent, [])

    async def test_real_gateway_sends_when_activated(self):
        app = build(env={"TENANT_ACTIVATED": "true"}, gateway=FakeRealGateway())
        lead, _ = app["store"].get_or_create_lead(1)
        lead.consent_given = True
        r = await app["outbound"].send(lead, "Hello there", kind="flow", now=T0)
        self.assertEqual(r.status, "sent")

    async def test_placeholder_text_never_leaves_via_real_gateway(self):
        app = build(env={"TENANT_ACTIVATED": "true"}, gateway=FakeRealGateway())
        lead, _ = app["store"].get_or_create_lead(1)
        lead.consent_given = True
        r = await app["outbound"].send(lead, "The fee is FILL_IN", kind="flow", now=T0)
        self.assertEqual((r.status, r.hits), ("blocked", ("UNRESOLVED_PLACEHOLDER",)))
        self.assertEqual(app["gw"].sent, [])

    async def test_no_consent_suppressed_but_onboarding_allowed(self):
        app = build()
        lead, _ = app["store"].get_or_create_lead(1)
        self.assertEqual((await app["outbound"].send(lead, "Hi", kind="flow", now=T0)).status, "suppressed")
        self.assertEqual((await app["outbound"].send(lead, "Hi", kind="onboarding", now=T0)).status, "sent")

    async def test_opted_out_only_ack_allowed(self):
        app = build()
        lead, _ = app["store"].get_or_create_lead(1)
        lead.consent_given, lead.opted_out = True, True
        self.assertEqual((await app["outbound"].send(lead, "Hi", kind="followup", now=T0)).status, "suppressed")
        self.assertEqual((await app["outbound"].send(lead, "Bye", kind="opt_out_ack", now=T0)).status, "sent")

    async def test_compliance_block_is_recorded_and_ticketed(self):
        app = build()
        lead, _ = app["store"].get_or_create_lead(1)
        lead.consent_given = True
        r = await app["outbound"].send(lead, "Guaranteed returns of 30%!", kind="flow", now=T0)
        self.assertEqual(r.status, "blocked")
        self.assertEqual(app["gw"].sent, [])
        self.assertEqual(app["store"].decisions[-1]["verdict"], "block")
        self.assertEqual(app["store"].tickets[-1]["reason"], "compliance_block")

    async def test_gateway_error_does_not_crash_and_is_not_logged_as_sent(self):
        app = build()
        lead, _ = app["store"].get_or_create_lead(1)
        lead.consent_given = True
        app["gw"].fail_next = 1
        r = await app["outbound"].send(lead, "Hello", kind="flow", now=T0)
        self.assertEqual(r.status, "failed")
        self.assertFalse([m for m in app["store"].messages if m["direction"] == "out"])


if __name__ == "__main__":
    unittest.main()
