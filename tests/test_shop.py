"""Do'kon, karta matni va admin panel handlerlari testlari."""

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiogram.filters import CommandObject

from bot.config import get_config
from bot.handlers import admin, shop
from core.economy import START_COINS, EconomyStore, get_economy
from core.settings import SettingsStore


def make_settings() -> SettingsStore:
    """Karta ma'lumotlari saqlangan xotiradagi sozlamalar ombori."""
    settings = SettingsStore(url="", key="", client=None)
    settings.set_payment_card("9860 0000 0000 0000", "Falonchi Pistonchiyev")
    return settings


class ShopPresentationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "BOT_TOKEN": "123456:TEST",
                "ADMIN_ID": "424242",
                "CARD_NUMBER": "9860 0000 0000 0000",
                "CARD_HOLDER": "Falonchi Pistonchiyev",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        get_config.cache_clear()
        self.addCleanup(get_config.cache_clear)

        # Do'kon kartani `system_settings`dan oladi.
        self.settings = make_settings()
        settings_patch = patch.object(
            shop, "get_settings_store", return_value=self.settings
        )
        settings_patch.start()
        self.addCleanup(settings_patch.stop)

    def test_config_reads_payment_settings(self) -> None:
        config = get_config()
        self.assertEqual(config.admin_id, 424242)
        self.assertEqual(config.card_number, "9860 0000 0000 0000")
        self.assertEqual(config.card_holder, "Falonchi Pistonchiyev")

    def test_packages_keyboard_has_all_packages(self) -> None:
        keyboard = shop.packages_keyboard()
        callbacks = [row[0].callback_data for row in keyboard.inline_keyboard]
        self.assertEqual(
            callbacks,
            ["shop_pack_500", "shop_pack_1500", "shop_pack_4000", "shop_cancel"],
        )
        self.assertIn("10 000 so'm", keyboard.inline_keyboard[0][0].text)
        self.assertIn("25 000 so'm", keyboard.inline_keyboard[1][0].text)
        self.assertIn("60 000 so'm", keyboard.inline_keyboard[2][0].text)

    def test_payment_text_contains_card_and_price(self) -> None:
        text = shop.payment_text(1500, 25000)
        self.assertIn("9860 0000 0000 0000", text)
        self.assertIn("Falonchi Pistonchiyev", text)
        self.assertIn("25 000 so'm", text)
        self.assertIn("chek", text.lower())

    def test_receipt_caption_and_review_buttons(self) -> None:
        payment = SimpleNamespace(
            id="abc123",
            user_id=700,
            package_coins=500,
            price_uzs=10000,
        )
        caption = shop.receipt_caption(payment, "ali", "Ali Valiyev")
        self.assertIn("Ali Valiyev", caption)
        self.assertIn("500", caption)
        self.assertIn("10 000", caption)
        keyboard = shop.review_keyboard("abc123")
        self.assertEqual(
            keyboard.inline_keyboard[0][0].callback_data, "pay_ok_abc123"
        )
        self.assertEqual(
            keyboard.inline_keyboard[0][1].callback_data, "pay_no_abc123"
        )


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append((chat_id, text))


class FakeMessage:
    def __init__(self, user_id: int = 424242) -> None:
        self.from_user = SimpleNamespace(id=user_id, username="admin")
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.bot = FakeBot()
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)


class AdminHandlerTest(unittest.TestCase):
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

    def test_admin_panel_and_give_and_user(self) -> None:
        message = FakeMessage()
        asyncio.run(admin.admin_panel(message))
        self.assertIn("Admin panel", message.answers[-1])

        give = CommandObject(args="88001 250")
        asyncio.run(admin.give_coins(message, give))
        self.assertIn("+250", message.answers[-1])
        self.assertEqual(
            get_economy().get_user(88001).coins, START_COINS + 250
        )

        user = CommandObject(args="88001")
        asyncio.run(admin.user_info(message, user))
        self.assertIn("88001", message.answers[-1])
        self.assertIn(str(START_COINS + 250), message.answers[-1])

    def test_non_admin_is_rejected(self) -> None:
        message = FakeMessage(user_id=999)
        asyncio.run(admin.admin_panel(message))
        self.assertIn("faqat administrator", message.answers[-1])

    def test_role_admin_from_users_table_is_allowed(self) -> None:
        message = FakeMessage(user_id=777)
        store = SimpleNamespace(
            is_admin_user=lambda uid: int(uid) == 777,
            stats=lambda **kwargs: {
                "users": 0,
                "coins_purchased": 0,
                "coins_in_balance": 0,
                "active_rooms": 0,
                "total_rooms": 0,
            },
        )
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(admin.admin_panel(message))
        self.assertIn("Admin panel", message.answers[-1])

    def test_broadcast_sends_to_registered_users(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        store.ensure_user(88002, "u", "User")
        message = FakeMessage()
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(
                admin.broadcast(message, CommandObject(args="Yangi yangilik"))
            )
        self.assertEqual(len(message.bot.messages), 1)
        self.assertEqual(message.bot.messages[0][0], 88002)
        self.assertIn("Yangi yangilik", message.bot.messages[0][1])
        self.assertIn("<b>1</b> ta yuborildi", message.answers[-1])


if __name__ == "__main__":
    unittest.main()
