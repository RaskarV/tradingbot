import copy
import unittest

import yaml

from app.config.client import ClientConfigError, load_client, parse_client
from app.config.sentinel import find_placeholders, is_unset
from app.config.settings import ConfigError, Settings, assert_startup_ok, production_problems
from tests.helpers import FIXTURE, ROOT

CLIENTONE = ROOT / "clients" / "clientone.yaml"


class SentinelTests(unittest.TestCase):
    def test_unset_values(self):
        for v in (None, "", "  ", "PLACEHOLDER", "FILL_IN", "placeholder-token"):
            self.assertTrue(is_unset(v), v)
        self.assertFalse(is_unset("real-value"))

    def test_find_placeholders_paths(self):
        self.assertEqual(list(find_placeholders({"a": {"b": "FILL_IN"}, "c": ["ok", "PLACEHOLDER"]})),
                         ["a.b", "c[1]"])


class ClientConfigTests(unittest.TestCase):
    def raw(self):
        return copy.deepcopy(yaml.safe_load(open(FIXTURE, encoding="utf-8")))

    def test_clientone_loads_with_placeholders(self):
        c = load_client(CLIENTONE)
        self.assertEqual([s.day for s in c.followup_steps], [1, 3, 7])
        self.assertEqual(c.contact_capture, "before_questions")

    def test_unknown_key_rejected(self):
        r = self.raw(); r["surprise"] = 1
        with self.assertRaises(ClientConfigError):
            parse_client(r)

    def test_secret_in_yaml_rejected(self):
        r = self.raw(); r["client"]["name"] = "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        with self.assertRaises(ClientConfigError) as cm:
            parse_client(r)
        self.assertIn("secret", str(cm.exception))

    def test_env_reference_must_be_a_name(self):
        r = self.raw(); r["booking"]["url_env"] = "https://cal.com/x"
        with self.assertRaises(ClientConfigError):
            parse_client(r)

    def test_followup_days_must_increase(self):
        r = self.raw(); r["followups"]["schedule"][1]["day"] = 1
        with self.assertRaises(ClientConfigError):
            parse_client(r)

    def test_missing_message_template_rejected(self):
        r = self.raw(); del r["messages"]["guide_intro"]
        with self.assertRaises(ClientConfigError):
            parse_client(r)


class StartupGuardTests(unittest.TestCase):
    def test_production_refuses_clientone_placeholders(self):
        client = load_client(CLIENTONE)
        with self.assertRaises(ConfigError) as cm:
            assert_startup_ok(Settings(env={"APP_ENV": "production"}), client)
        msg = str(cm.exception)
        self.assertIn("TELEGRAM_BOT_TOKEN", msg)
        self.assertIn("legal_review_completed", msg)
        self.assertIn("TENANT_ACTIVATED", msg)

    def test_development_reports_but_does_not_raise(self):
        problems = assert_startup_ok(Settings(env={"APP_ENV": "development"}), load_client(CLIENTONE))
        self.assertTrue(problems)

    def test_placeholder_env_values_count_as_missing(self):
        client = load_client(FIXTURE)
        env = {"TELEGRAM_BOT_TOKEN": "PLACEHOLDER", "LLM_API_KEY": "real", "BOOKING_URL": "https://x.y",
               "SALES_NOTIFICATION_CHAT_ID": "123", "FREE_GUIDE_PATH": "/g.pdf", "TENANT_ACTIVATED": "true",
               "LLM_PROVIDER": "anthropic", "LLM_MODEL": "some-model"}
        problems = production_problems(Settings(env=env), client)
        self.assertEqual(len(problems), 1)
        self.assertIn("TELEGRAM_BOT_TOKEN", problems[0])
        env["TELEGRAM_BOT_TOKEN"] = "real-token"
        self.assertEqual(production_problems(Settings(env=env), client), [])

    def test_llm_enabled_requires_real_provider_and_model_in_production(self):
        client = load_client(FIXTURE)
        env = {"TELEGRAM_BOT_TOKEN": "t", "LLM_API_KEY": "k", "BOOKING_URL": "https://x.y",
               "SALES_NOTIFICATION_CHAT_ID": "1", "FREE_GUIDE_PATH": "/g.pdf", "TENANT_ACTIVATED": "true",
               "LLM_PROVIDER": "mock"}
        problems = " ".join(production_problems(Settings(env=env), client))
        self.assertIn("LLM_PROVIDER", problems)
        self.assertIn("LLM_MODEL", problems)

    def test_bad_app_env_rejected(self):
        with self.assertRaises(ConfigError):
            Settings(env={"APP_ENV": "prod"}).app_env


if __name__ == "__main__":
    unittest.main()
