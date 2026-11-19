"""Gateway ports. The LLM / funnel never talks to Telegram directly; only the
OutboundMessageService calls a gateway."""
from __future__ import annotations

CONTACT_BUTTON = "@share_contact"


class MockGateway:
    is_real = False

    def __init__(self):
        self.sent: list[dict] = []
        self.fail_next = 0           # raise on the next N sends (retry tests)

    async def send(self, chat_id, text, buttons=None, attachment=None):
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ConnectionError("simulated gateway failure")
        self.sent.append(dict(chat_id=chat_id, text=text, buttons=buttons, attachment=attachment))


class ConsoleGateway:
    is_real = False

    async def send(self, chat_id, text, buttons=None, attachment=None):
        print(f"\nBOT> {text}")
        if attachment:
            print(f"     [attachment: {attachment}]")
        if buttons:
            labels = ["(share phone button)" if b == CONTACT_BUTTON else b for b in buttons]
            print(f"     [buttons: {' | '.join(labels)}]")
