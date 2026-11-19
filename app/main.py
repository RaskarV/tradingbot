"""CLI: python -m app.main <check-config|console|telegram> [--client clients/clientone.yaml]"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config.client import ClientConfigError, load_client
from app.config.settings import ConfigError, Settings, assert_startup_ok
from app.followups.scheduler import FollowupScheduler
from app.funnel.engine import FlowEngine
from app.messaging.gateways import ConsoleGateway
from app.messaging.outbound import OutboundMessageService
from app.notifications.notifier import ConsoleNotifier
from app.storage.memory import InMemoryStore


def load_dotenv(path=".env"):
    p = Path(path)
    if not p.exists():
        print(f"[warn] {p.resolve()} not found - environment variables will not be loaded "
              "(the file must be named exactly .env and sit in the project folder)", file=sys.stderr)
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip()
            if v[:1] in ("'", '"'):
                v = v.strip(v[0])
            else:
                v = v.split(" #", 1)[0].split("\t#", 1)[0].strip()   # drop trailing "# comment"
            os.environ.setdefault(k.strip(), v)


def build_runtime(settings, client, store, gateway, notifier):
    from app.agents.agent import AgentRunner
    from app.ai.factory import build_provider
    outbound = OutboundMessageService(store, gateway, settings)
    provider = build_provider(settings)
    agent = None
    if provider is not None and client.llm_enabled:
        agent = AgentRunner(provider, store, notifier, client,
                            allow_general_education=client.llm_allow_general_education,
                            max_rounds=client.llm_max_rounds, history_messages=client.llm_history)
    return (FlowEngine(store, outbound, notifier, client, settings, agent=agent),
            FollowupScheduler(store, outbound, client, settings))


def cmd_check(settings, client) -> int:
    problems = assert_startup_ok(settings, client)
    print(f"client={client.slug} env={settings.app_env}")
    if problems:
        print(f"{len(problems)} item(s) still needed before production:")
        for p in problems:
            print(" -", p)
        return 1 if settings.app_env == "production" else 0
    print("All production-critical settings are present.")
    return 0


async def cmd_console(settings, client):
    if settings.app_env == "production":
        raise SystemExit("The console simulator is for development/test only.")
    store, offset = InMemoryStore(), timedelta()
    engine, scheduler = build_runtime(settings, client, store, ConsoleGateway(), ConsoleNotifier())
    now = lambda: datetime.now(timezone.utc) + offset
    uid = 1
    print("Console simulator (no real messages are sent).")
    print("Type as the user. Commands: :advance N (days)  :booked  :contact +91...  :status  :quit")
    print("Start with:  /start reel_demo")
    while True:
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, input, "\nYOU> ")
        except EOFError:
            break
        line = line.strip()
        if line == ":quit":
            break
        elif line.startswith(":advance"):
            offset += timedelta(days=int(line.split()[1]))
            print("followups:", await scheduler.run_due(now()))
        elif line == ":booked":
            await engine.confirm_booking(uid, now())
        elif line.startswith(":contact"):
            await engine.handle(uid, "", contact_phone=line.split(maxsplit=1)[1], now=now())
        elif line == ":status":
            lead = store.get_lead(uid)
            print(lead, [(j.day, j.status) for j in store.jobs])
        elif line:
            await engine.handle(uid, line, now=now())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="app.main")
    ap.add_argument("command", choices=["check-config", "console", "telegram"])
    ap.add_argument("--client", default="clients/clientone.yaml")
    ap.add_argument("--llm", choices=["mock"], help="console only: use the mock LLM (no API key)")
    ap.add_argument("--enable-followups", action="store_true", help="console only: simulate follow-ups")
    a = ap.parse_args(argv)
    load_dotenv()
    try:
        client = load_client(a.client)
        env = dict(os.environ)
        if a.enable_followups and a.command == "console":
            env["FOLLOWUPS_ENABLED"] = "true"
        if a.llm and a.command == "console":
            env["LLM_PROVIDER"] = a.llm
        settings = Settings(env=env)
        if a.command == "check-config":
            return cmd_check(settings, client)
        if a.command == "console":
            asyncio.run(cmd_console(settings, client))
            return 0
        # telegram
        if settings.app_env == "production":
            raise SystemExit("Production needs the Phase 1 PostgreSQL store; in-memory storage is dev-only.")
        assert_startup_ok(settings, client)
        from app.bots.telegram_bot import run_polling
        store = InMemoryStore()
        asyncio.run(run_polling(settings, client, store,
                                lambda gw, nt: build_runtime(settings, client, store, gw, nt)))
        return 0
    except (ConfigError, ClientConfigError) as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
