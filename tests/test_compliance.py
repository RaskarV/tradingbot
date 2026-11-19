import unittest

from app.compliance.rules import evaluate, is_advice_request
from tests.helpers import FIXTURE
from app.config.client import load_client

MUST_BLOCK = {
    "GUARANTEED_RETURNS": ["This course guarantees 20% returns every month", "You will get assured profits",
                           "A risk-free way to earn", "We deliver 100% accuracy"],
    "PROFIT_PROMISE": ["Earn ₹50,000 per month trading"],
    "PERSONAL_ADVICE": ["You should buy Reliance today", "I recommend you buy HDFC shares"],
    "COLLECT_CAPITAL": ["How much capital do you have to invest?", "What is your trading capital?"],
    "REGISTRATION_CLAIM": ["We are SEBI registered advisers"],
    "CLAIMS_HUMAN": ["I am a human, don't worry"],
    "FALSE_URGENCY": ["Only today! Limited seats left", "Hurry, enrolment ends tonight"],
}
MUST_ALLOW = [
    "We do not guarantee any returns; markets involve risk.",
    "There are no guaranteed profits in trading.",
    "Stocks are risky and you can lose money.",
    "A stop-loss is an order that limits your loss.",
    "I am an automated assistant, not a human.",
    "We are not SEBI registered investment advisers.",
    "The course covers candlestick patterns and risk management.",
    "Our team will call you at the time you booked.",
]


class RuleTests(unittest.TestCase):
    def test_must_block(self):
        for rule, texts in MUST_BLOCK.items():
            for t in texts:
                d = evaluate(t)
                self.assertEqual(d.verdict, "block", t)
                self.assertIn(rule, d.hits, t)

    def test_must_allow(self):
        for t in MUST_ALLOW:
            self.assertEqual(evaluate(t).verdict, "allow", t)

    def test_placeholder_blocked_only_for_real_sends(self):
        self.assertEqual(evaluate("Fee: FILL_IN").verdict, "allow")
        self.assertEqual(evaluate("Fee: FILL_IN", real_send=True).hits, ("UNRESOLVED_PLACEHOLDER",))
        self.assertEqual(evaluate("Link [BOOKING_URL not configured]", real_send=True).verdict, "block")

    def test_every_default_template_passes_rules(self):
        c = load_client(FIXTURE)
        texts = list(c.messages.values()) + [s.text for s in c.followup_steps] + [q.prompt for q in c.questions]
        for t in texts:
            self.assertEqual(evaluate(t, real_send=True).verdict, "allow", t)

    def test_advice_request_detection(self):
        for t in ["Should I buy Tata Motors?", "which stock is best to buy now", "give me tips"]:
            self.assertTrue(is_advice_request(t), t)
        for t in ["What is a stop loss?", "How long is the course?"]:
            self.assertFalse(is_advice_request(t), t)


if __name__ == "__main__":
    unittest.main()
