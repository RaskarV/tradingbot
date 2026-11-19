"""aiogram 3 adapter (long polling). STATUS: written but NOT tested - aiogram could not be
installed in the build sandbox and no real bot token is available. Test with a throwaway bot."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.messaging.gateways import CONTACT_BUTTON


class AiogramGateway:
    is_real = True

    def __init__(self, bot):
        self.bot = bot

    async def send(self, chat_id, text, buttons=None, attachment=None):
        from aiogram.types import FSInputFile, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
        markup = ReplyKeyboardRemove()
        if buttons:
            rows = [[KeyboardButton(text="Share my phone number" if b == CONTACT_BUTTON else b,
                                    request_contact=(b == CONTACT_BUTTON))] for b in buttons]
            markup = ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)
        if attachment:
            await self.bot.send_document(chat_id, FSInputFile(attachment), caption=text[:1024], reply_markup=markup)
        else:
            await self.bot.send_message(chat_id, text, reply_markup=markup)


class TelegramNotifier:
    def __init__(self, bot, chat_id):
        self.bot, self.chat_id = bot, chat_id

    async def notify(self, text: str):
        if self.chat_id:
            await self.bot.send_message(self.chat_id, text)


async def run_polling(settings, client, store, build_runtime):
    """build_runtime(gateway, notifier) -> (engine, scheduler)."""
    from aiogram import Bot, Dispatcher, F
    from aiogram.filters import CommandObject, CommandStart
    from aiogram.types import Message

    token = settings.get(client.telegram_token_env)
    if token is None:
        raise SystemExit(f"{client.telegram_token_env} is not set; use the console simulator instead.")
    if not settings.tenant_activated:
        raise SystemExit("TENANT_ACTIVATED is not true; real sending stays disabled.")

    bot = Bot(token)
    notifier = TelegramNotifier(bot, settings.get(client.notify_chat_id_env))
    engine, scheduler = build_runtime(AiogramGateway(bot), notifier)
    dp = Dispatcher()

    @dp.message(CommandStart(), F.chat.type == "private")
    async def on_start(m: Message, command: CommandObject):
        text = "/start" + (f" {command.args}" if command.args else "")
        await engine.handle(m.chat.id, text, update_id=m.message_id)

    @dp.message(F.contact, F.chat.type == "private")
    async def on_contact(m: Message):
        if m.contact.user_id == m.from_user.id:            # only accept the user's OWN number
            await engine.handle(m.chat.id, "", contact_phone=m.contact.phone_number, update_id=m.message_id)

    @dp.message(F.text, F.chat.type == "private")
    async def on_text(m: Message):
        await engine.handle(m.chat.id, m.text, update_id=m.message_id)

    async def ticker():
        while True:
            await scheduler.run_due(datetime.now(timezone.utc))
            await asyncio.sleep(60)

    task = asyncio.create_task(ticker())
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
