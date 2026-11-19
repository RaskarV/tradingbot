"""Internal notifications to the client's sales team (not customer messages)."""
from __future__ import annotations


class MockNotifier:
    def __init__(self):
        self.notes: list[str] = []

    async def notify(self, text: str):
        self.notes.append(text)


class ConsoleNotifier:
    async def notify(self, text: str):
        print(f"\n[SALES TEAM NOTIFICATION]\n{text}")
