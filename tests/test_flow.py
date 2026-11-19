import unittest
from datetime import timedelta

from tests.helpers import T0, build, run_to_guide


def texts(app):
    return [m["text"] for m in app["gw"].sent]


class FunnelDiagramTests(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_reel_to_sales_call(self):
        app = build()
        e, store = app["engine"], app["store"]
        await e.handle(1, "/start reel_launch1", now=T0)
        lead = store.get_lead(1)
        self.assertEqual((lead.source, lead.campaign), ("reel", "launch1"))      # watches the reel
        self.assertIn("an AI, not a human", texts(app)[0])
        self.assertEqual(lead.stage, "consent_pending")

        await e.handle(1, "I agree", now=T0)                                      # consent
        self.assertEqual(lead.awaiting, "name")
        await e.handle(1, "Asha Rao", now=T0)                                     # shares name
        self.assertEqual(lead.awaiting, "phone")
        await e.handle(1, "98765 43210", now=T0)                                  # shares phone
        self.assertEqual(lead.phone, "+919876543210")
        self.assertEqual(lead.awaiting, "q:experience_level")                     # answers questions
        await e.handle(1, "complete beginner", now=T0)
        await e.handle(1, "learn the basics", now=T0)
        self.assertEqual(lead.stage, "qualifying")
        await e.handle(1, "5 hours", now=T0)

        self.assertTrue(lead.qualified and lead.guide_sent)                       # gets the free guide
        self.assertEqual(lead.stage, "guide_sent")
        self.assertEqual(app["gw"].sent[-2]["attachment"], "/tmp/guide.pdf")
        self.assertEqual(len([j for j in store.jobs if j.status == "pending"]), 3)

        await e.handle(1, "Yes, book a call", now=T0)                             # books a call? yes
        self.assertIn("https://cal.example/test", texts(app)[-1])
        await e.confirm_booking(1, now=T0, slot="Mon 11:00")
        self.assertEqual(lead.stage, "booked")                                    # sales team calls
        self.assertEqual(len(store.handoffs), 1)
        self.assertIn("+919876543210", app["notifier"].notes[-1])
        self.assertIn("reel / launch1", app["notifier"].notes[-1])
        self.assertTrue(all(j.status == "cancelled" for j in store.jobs))

    async def test_questions_asked_one_at_a_time_and_not_repeated(self):
        app = build()
        await run_to_guide(app)
        prompts = [q.prompt for q in app["client"].questions]
        for p in prompts:
            self.assertEqual(texts(app).count(p), 1)

    async def test_no_booking_then_followups_day_1_3_7_then_books_later(self):
        app = build()
        e, store, sched = app["engine"], app["store"], app["scheduler"]
        await run_to_guide(app)
        await e.handle(1, "Not now", now=T0)
        self.assertIn("No worries", texts(app)[-1])

        self.assertEqual((await sched.run_due(T0 + timedelta(hours=23)))["sent"], 0)   # too early
        s1 = await sched.run_due(T0 + timedelta(days=1))
        self.assertEqual(s1["sent"], 1)
        await sched.run_due(T0 + timedelta(days=3))
        followups = [m["text"] for m in app["gw"].sent if "Hi Asha" in m["text"]]
        self.assertEqual(len(followups), 2)
        self.assertEqual(len(set(followups)), 2)                                    # different messages

        await e.handle(1, "Yes please book me", now=T0 + timedelta(days=4))          # books later
        await e.confirm_booking(1, now=T0 + timedelta(days=4))
        s7 = await sched.run_due(T0 + timedelta(days=7))
        self.assertEqual(s7["sent"], 0)
        self.assertEqual(store.jobs[2].status, "cancelled")                          # day-7 cancelled
        self.assertEqual(len(store.handoffs), 1)

    async def test_followups_disabled_by_default_environment(self):
        app = build(env={"FOLLOWUPS_ENABLED": "false"})
        await run_to_guide(app)
        before = len(app["gw"].sent)
        stats = await app["scheduler"].run_due(T0 + timedelta(days=10))
        self.assertEqual((stats["sent"], stats["deferred"]), (0, 3))
        self.assertEqual(len(app["gw"].sent), before)

    async def test_opt_out_cancels_followups_and_silences_bot(self):
        app = build()
        e = app["engine"]
        await run_to_guide(app)
        await e.handle(1, "STOP", now=T0)
        self.assertIn("won't message you again", texts(app)[-1])
        n = len(app["gw"].sent)
        stats = await app["scheduler"].run_due(T0 + timedelta(days=8))
        self.assertEqual(stats["sent"], 0)
        await e.handle(1, "hello?", now=T0 + timedelta(days=9))
        self.assertEqual(len(app["gw"].sent), n)                                     # silent
        self.assertEqual(app["store"].consents[-1]["status"], "withdrawn")

    async def test_natural_language_opt_out(self):
        app = build()
        await run_to_guide(app)
        await app["engine"].handle(1, "please stop messaging me", now=T0)
        self.assertTrue(app["store"].get_lead(1).opted_out)

    async def test_restart_after_opt_out_requires_fresh_consent(self):
        app = build()
        e = app["engine"]
        await run_to_guide(app)
        await e.handle(1, "stop", now=T0)
        await e.handle(1, "/start", now=T0)
        lead = app["store"].get_lead(1)
        self.assertFalse(lead.consent_given)
        self.assertEqual(lead.stage, "consent_pending")

    async def test_declined_consent_stores_nothing_more(self):
        app = build()
        e = app["engine"]
        await e.handle(1, "/start", now=T0)
        await e.handle(1, "No thanks", now=T0)
        lead = app["store"].get_lead(1)
        self.assertEqual(lead.stage, "declined")
        n = len(app["gw"].sent)
        await e.handle(1, "my name is Bob", now=T0)
        self.assertEqual(len(app["gw"].sent), n)
        self.assertIsNone(lead.name)

    async def test_advice_request_is_deflected_not_answered(self):
        app = build()
        e = app["engine"]
        await e.handle(1, "/start", now=T0)
        await e.handle(1, "I agree", now=T0)
        await e.handle(1, "Should I buy Tata Motors?", now=T0)
        self.assertTrue(any("can't give personal recommendations" in t for t in texts(app)))
        self.assertEqual(app["store"].tickets[-1]["reason"], "advice_request")
        self.assertEqual(texts(app)[-1], "Great, thanks! What's your name?")        # pending question re-asked

    async def test_faq_answered_from_verified_info_and_unknown_is_escalated(self):
        app = build()
        e = app["engine"]
        await run_to_guide(app)
        await e.handle(1, "What is the course fee?", now=T0)
        self.assertIn("10000 rupees", texts(app)[-1])
        await e.handle(1, "Do you offer placements abroad?", now=T0)
        self.assertIn("won't guess", texts(app)[-1])
        self.assertEqual(app["store"].tickets[-1]["reason"], "unanswered_question")
        self.assertIn("Unanswered question", app["notifier"].notes[-1])

    async def test_clientone_unfilled_faq_is_not_used_as_an_answer(self):
        from tests.helpers import ROOT
        app = build(client_path=ROOT / "clients" / "clientone.yaml")
        e = app["engine"]
        await run_to_guide(app)
        await e.handle(1, "What is the course fee?", now=T0)
        self.assertNotIn("FILL_IN", texts(app)[-1])
        self.assertIn("won't guess", texts(app)[-1])

    async def test_duplicate_telegram_update_is_idempotent(self):
        app = build()
        e = app["engine"]
        await e.handle(1, "/start", update_id=100, now=T0)
        n = len(app["gw"].sent)
        await e.handle(1, "/start", update_id=100, now=T0)
        self.assertEqual(len(app["gw"].sent), n)

    async def test_invalid_phone_and_name_are_re_asked(self):
        app = build()
        e = app["engine"]
        await e.handle(1, "/start", now=T0)
        await e.handle(1, "I agree", now=T0)
        await e.handle(1, "12345", now=T0)
        self.assertIn("didn't catch a name", texts(app)[-1])
        await e.handle(1, "Asha", now=T0)
        await e.handle(1, "12345", now=T0)
        self.assertIn("valid phone", texts(app)[-1])
        await e.handle(1, "", contact_phone="+14155550123", now=T0)                 # shared-contact button
        self.assertEqual(app["store"].get_lead(1).phone, "+14155550123")

    async def test_at_guide_ordering_asks_questions_before_contact(self):
        import yaml, tempfile, os
        from tests.helpers import FIXTURE
        raw = yaml.safe_load(open(FIXTURE, encoding="utf-8"))
        raw["funnel"]["contact_capture"] = "at_guide"
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            yaml.safe_dump(raw, f)
        try:
            app = build(client_path=f.name)
        finally:
            os.unlink(f.name)
        e = app["engine"]
        await e.handle(1, "/start", now=T0)
        await e.handle(1, "I agree", now=T0)
        self.assertEqual(app["store"].get_lead(1).awaiting, "q:experience_level")
        for ans in ["beginner", "basics", "5h", "Asha Rao", "9876543210"]:
            await e.handle(1, ans, now=T0)
        self.assertTrue(app["store"].get_lead(1).guide_sent)

    async def test_two_leads_do_not_interfere(self):
        app = build()
        await run_to_guide(app, uid=1)
        await app["engine"].handle(2, "/start", now=T0)
        self.assertEqual(app["store"].get_lead(2).stage, "consent_pending")
        self.assertEqual(app["store"].get_lead(1).stage, "guide_sent")

    async def test_gateway_failure_retries_then_succeeds(self):
        app = build()
        await run_to_guide(app)
        app["gw"].fail_next = 1
        sched = app["scheduler"]
        t = T0 + timedelta(days=1)
        self.assertEqual((await sched.run_due(t))["retry"], 1)
        self.assertEqual((await sched.run_due(t + timedelta(hours=1)))["sent"], 1)


if __name__ == "__main__":
    unittest.main()
