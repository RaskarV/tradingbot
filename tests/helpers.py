import os
from datetime import datetime, timezone
from pathlib import Path

from app.config.client import load_client
from app.config.settings import Settings
from app.followups.scheduler import FollowupScheduler
from app.funnel.engine import FlowEngine
from app.messaging.gateways import MockGateway
from app.messaging.outbound import OutboundMessageService
from app.notifications.notifier import MockNotifier
from app.storage.memory import InMemoryStore

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "test_client.yaml"
T0 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)

BASE_ENV = {"APP_ENV": "test", "BOOKING_URL": "https://cal.example/test",
            "FREE_GUIDE_PATH": "/tmp/guide.pdf", "FOLLOWUPS_ENABLED": "true"}


def build(env=None, client_path=FIXTURE, gateway=None, llm=None, agent_kwargs=None):
    settings = Settings(env={**BASE_ENV, **(env or {})})
    client = load_client(client_path)
    store, gw, notifier = InMemoryStore(), gateway or MockGateway(), MockNotifier()
    outbound = OutboundMessageService(store, gw, settings)
    agent = None
    if llm is not None:
        from app.agents.agent import AgentRunner
        agent = AgentRunner(llm, store, notifier, client, **(agent_kwargs or {}))
    engine = FlowEngine(store, outbound, notifier, client, settings, agent=agent)
    scheduler = FollowupScheduler(store, outbound, client, settings)
    return dict(settings=settings, client=client, store=store, gw=gw, notifier=notifier,
                outbound=outbound, agent=agent, engine=engine, scheduler=scheduler)


async def run_to_guide(app, uid=1, payload="reel_launch1", t=T0):
    e = app["engine"]
    await e.handle(uid, f"/start {payload}", now=t)
    await e.handle(uid, "I agree", now=t)
    await e.handle(uid, "Asha Rao", now=t)
    await e.handle(uid, "9876543210", now=t)
    await e.handle(uid, "complete beginner", now=t)
    await e.handle(uid, "learn the basics", now=t)
    await e.handle(uid, "5 hours", now=t)
