"""Referal tizimi: havola, taklif hisobi va /start ref_ oqimi testlari."""

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiogram.filters import CommandObject

from bot.config import get_config
from bot.handlers import common
from core.economy import (
    REFERRAL_BONUS,
    START_COINS,
    EconomyStore,
    referral_earnings,
)


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append((chat_id, text))


class FakeMessage:
    def __init__(self, user_id: int = 71001, text: str = "") -> None:
        self.from_user = SimpleNamespace(
            id=user_id, username="ali", full_name="Ali Valiyev"
        )
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.text = text
        self.bot = FakeBot()
        self.answers: list[str] = []
        self.markups: list[object] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)
        self.markups.append(kwargs.get("reply_markup"))

    async def reply(self, text: str, **kwargs) -> None:
        await self.answer(text, **kwargs)


class ReferralLinkTest(unittest.TestCase):
    def test_link_and_parsing(self) -> None:
        self.assertEqual(
            common.referral_link("revilend_gamesbot", 12345),
            "https://t.me/revilend_gamesbot?start=ref_12345",
        )
        self.assertEqual(common.parse_referral_arg("ref_12345"), 12345)
        self.assertEqual(common.parse_referral_arg("REF_777"), 777)
        self.assertEqual(common.parse_referral_arg(" ref_42 "), 42)

    def test_non_referral_arguments(self) -> None:
        self.assertIsNone(common.parse_referral_arg(None))
        self.assertIsNone(common.parse_referral_arg(""))
        self.assertIsNone(common.parse_referral_arg("shop_500"))
        self.assertIsNone(common.parse_referral_arg("ref_"))
        self.assertIsNone(common.parse_referral_arg("ref_abc"))
        self.assertIsNone(common.parse_referral_arg("ref_0"))

    def test_invite_text_contains_link_and_earnings(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        store.ensure_user(12345, "ali", "Ali")
        store.ensure_user(12346, "vali", "Vali")
        store.register_referral(12345, 12346)
        account = store.get_user(12345)

        text = common.invite_text(account, "revilend_gamesbot")
        self.assertIn(
            "https://t.me/revilend_gamesbot?start=ref_12345", text
        )
        self.assertIn("+50 tanga", text)
        self.assertIn("taklif qilganlar: <b>1</b> kişi", text)
        self.assertIn("Işlangan tangalar: <b>50</b> tanga", text)

        keyboard = common.invite_keyboard(account, "revilend_gamesbot")
        button = keyboard.inline_keyboard[0][0]
        self.assertIn("Döstlarga yuboriş", button.text)
        self.assertIn("t.me/share/url", button.url)
        self.assertIn("ref_12345", button.url)


class EconomyReferralTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EconomyStore(url="", key="", client=None)
        self.store.ensure_user(500, "inviter", "Inviter")
        self.start_balance = self.store.get_user(500).coins

    def test_referral_gives_bonus_and_count(self) -> None:
        result = self.store.register_referral(500, 501)
        self.assertIsNotNone(result)
        self.assertEqual(result.inviter_id, 500)
        self.assertEqual(result.bonus, REFERRAL_BONUS)

        account = self.store.get_user(500)
        self.assertEqual(account.coins, self.start_balance + REFERRAL_BONUS)
        self.assertEqual(account.referral_count, 1)
        self.assertEqual(referral_earnings(account), REFERRAL_BONUS)

    def test_duplicate_referral_is_ignored(self) -> None:
        self.store.register_referral(500, 501)
        balance = self.store.get_user(500).coins
        self.assertIsNone(self.store.register_referral(500, 501))
        self.assertEqual(self.store.get_user(500).coins, balance)
        self.assertEqual(self.store.get_user(500).referral_count, 1)

    def test_self_referral_is_ignored(self) -> None:
        self.assertIsNone(self.store.register_referral(500, 500))
        self.assertEqual(self.store.get_user(500).referral_count, 0)

    def test_unknown_inviter_is_ignored(self) -> None:
        self.assertIsNone(self.store.register_referral(999, 502))
        self.assertFalse(self.store.has_user(999))

    def test_has_user_does_not_create(self) -> None:
        self.assertFalse(self.store.has_user(700))
        self.assertFalse(self.store.has_user(700))
        self.assertEqual(self.store.list_user_ids(), [500])


class StartReferralFlowTest(unittest.TestCase):
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
        self.store.ensure_user(72000, "inviter", "Inviter")
        self.inviter_balance = self.store.get_user(72000).coins
        self.economy_patch = patch.object(
            common, "get_economy", return_value=self.store
        )
        self.economy_patch.start()
        self.addCleanup(self.economy_patch.stop)

    def _start(self, user_id: int, args: str | None) -> FakeMessage:
        message = FakeMessage(user_id=user_id)
        command = CommandObject(args=args) if args else None
        asyncio.run(common.start_command(message, command))
        return message

    def test_new_user_via_referral_pays_inviter(self) -> None:
        message = self._start(72001, "ref_72000")

        # Yangi foydalanuvchi 100 tanga xush kelibsiz sovg'asini oladi.
        self.assertEqual(self.store.get_user(72001).coins, START_COINS)
        # Taklif qiluvchi +50 tanga va 1 taklif oladi.
        inviter = self.store.get_user(72000)
        self.assertEqual(inviter.coins, self.inviter_balance + REFERRAL_BONUS)
        self.assertEqual(inviter.referral_count, 1)

        # /start xabari va menyu yuborilgan.
        self.assertIn("Salom", message.answers[-1])
        self.assertIsNotNone(message.markups[-1])

        # Taklif qilganga shaxsiy xabarnoma ketgan.
        notified = [text for chat_id, text in message.bot.messages if chat_id == 72000]
        self.assertTrue(notified)
        self.assertIn("Ali Valiyev", notified[0])
        self.assertIn("+50 tanga", notified[0])

    def test_second_start_does_not_pay_again(self) -> None:
        self._start(72002, "ref_72000")
        self._start(72002, "ref_72000")
        inviter = self.store.get_user(72000)
        self.assertEqual(inviter.coins, self.inviter_balance + REFERRAL_BONUS)
        self.assertEqual(inviter.referral_count, 1)

    def test_self_referral_is_not_counted(self) -> None:
        self._start(72000, "ref_72000")
        self.assertEqual(self.store.get_user(72000).referral_count, 0)
        self.assertEqual(self.store.get_user(72000).coins, self.inviter_balance)

    def test_start_without_referral_still_works(self) -> None:
        message = self._start(72003, None)
        self.assertIn("Salom", message.answers[-1])
        self.assertEqual(self.store.get_user(72003).coins, START_COINS)
        self.assertEqual(self.store.get_user(72000).referral_count, 0)

    def test_broken_economy_does_not_break_start(self) -> None:
        class BrokenStore:
            def has_user(self, user_id: int) -> bool:
                raise RuntimeError("baza ishlamayapti")

        with patch.object(common, "get_economy", return_value=BrokenStore()):
            message = FakeMessage(user_id=72004)
            asyncio.run(common.start_command(message, None))
        self.assertIn("Salom", message.answers[-1])
        self.assertIsNotNone(message.markups[-1])


if __name__ == "__main__":
    unittest.main()
