"""Yangi foydalanuvchi haqida adminga bildirishnoma testlari."""

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiogram.filters import CommandObject

from bot.config import get_config
from bot.handlers import common
from core.economy import START_COINS, EconomyStore


class FakeBot:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        if self.fail:
            raise RuntimeError("telegram ishlamayapti")
        self.messages.append((chat_id, text))


class FakeMessage:
    def __init__(
        self,
        user_id: int,
        username: str = "ali",
        full_name: str = "Ali Valiyev",
        language_code: str = "uz",
        fail_bot: bool = False,
    ) -> None:
        self.from_user = SimpleNamespace(
            id=user_id,
            username=username,
            full_name=full_name,
            language_code=language_code,
        )
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.text = "/start"
        self.bot = FakeBot(fail=fail_bot)
        self.answers: list[str] = []
        self.markups: list[object] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)
        self.markups.append(kwargs.get("reply_markup"))


class StartNotificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "BOT_TOKEN": "123456:TEST",
                "ADMIN_ID": "424242",
                "SUPABASE_URL": "",
                "SUPABASE_KEY": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        get_config.cache_clear()
        self.addCleanup(get_config.cache_clear)

        self.store = EconomyStore(url="", key="", client=None)
        self.economy_patch = patch.object(
            common, "get_economy", return_value=self.store
        )
        self.economy_patch.start()
        self.addCleanup(self.economy_patch.stop)
        self.admin_patch = patch.object(common, "is_admin", return_value=False)
        self.admin_patch.start()
        self.addCleanup(self.admin_patch.stop)

    def _start(
        self, user_id: int, args: str | None = None, fail_bot: bool = False
    ) -> FakeMessage:
        message = FakeMessage(user_id, fail_bot=fail_bot)
        command = CommandObject(args=args) if args else None
        asyncio.run(common.start_command(message, command))
        return message

    def test_first_start_notifies_admin_once(self) -> None:
        message = self._start(99001)
        admin_messages = [
            text for chat_id, text in message.bot.messages if chat_id == 424242
        ]
        self.assertEqual(len(admin_messages), 1)
        text = admin_messages[0]
        self.assertIn("Yangi foydalanuvçi qöşildi", text)
        self.assertIn("Ali Valiyev", text)
        self.assertIn("@ali", text)
        self.assertIn("<code>99001</code>", text)
        self.assertIn("<b>Til:</b> uz", text)
        self.assertIn("Töğridan-töğri", text)
        self.assertIn("1 kişi", text)
        self.assertEqual(self.store.get_user(99001).coins, START_COINS)

        second = self._start(99001)
        self.assertEqual(
            [t for c, t in second.bot.messages if c == 424242], []
        )

    def test_referral_inviter_is_shown(self) -> None:
        self.store.ensure_user(99002, "inviter", "Inviter Person")
        message = self._start(99003, "ref_99002")
        text = [
            body for chat_id, body in message.bot.messages if chat_id == 424242
        ][-1]
        self.assertIn("@inviter", text)
        self.assertIn("<code>99002</code>", text)
        self.assertIn("2 kişi", text)

    def test_blocked_user_gets_no_welcome_or_notification(self) -> None:
        self.store.ensure_user(99005, "blocked", "Blocked User")
        self.store.set_blocked(99005, True)
        message = self._start(99005)
        self.assertIn("bloklangan", message.answers[-1])
        self.assertEqual(
            [t for c, t in message.bot.messages if c == 424242], []
        )

    def test_notification_failure_does_not_break_start(self) -> None:
        message = self._start(99004, fail_bot=True)
        self.assertIn("Salom", message.answers[-1])
        self.assertIsNotNone(message.markups[-1])
        self.assertEqual(self.store.get_user(99004).coins, START_COINS)


if __name__ == "__main__":
    unittest.main()
