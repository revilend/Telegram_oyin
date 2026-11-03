"""Admin panel: inline tugmalar, karta sozlash, cheklar va xabar testlari."""

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.config import get_config
from bot.handlers import admin
from core.economy import START_COINS, EconomyStore
from core.settings import SettingsStore


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, object]] = []
        self.photos: list[tuple[int, str, str, object]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append((chat_id, text, kwargs.get("reply_markup")))

    async def send_photo(
        self, chat_id: int, photo: str, caption: str = "", **kwargs
    ) -> None:
        self.photos.append((chat_id, photo, caption, kwargs.get("reply_markup")))


class FakeMessage:
    def __init__(self, user_id: int = 424242, text: str = "") -> None:
        self.from_user = SimpleNamespace(
            id=user_id, username="admin", full_name="Admin Adminov"
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


class FakeCallback:
    def __init__(self, user_id: int = 424242, data: str = "") -> None:
        self.from_user = SimpleNamespace(
            id=user_id, username="admin", full_name="Admin Adminov"
        )
        self.data = data
        self.bot = FakeBot()
        self.answers: list[str] = []
        self.message = None

    async def answer(self, text: str = "", **kwargs) -> None:
        self.answers.append(text)


class FakeState:
    def __init__(self) -> None:
        self.state = None
        self.data: dict[str, object] = {}

    async def set_state(self, state) -> None:
        self.state = state

    async def clear(self) -> None:
        self.state = None
        self.data = {}

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)


def empty_stats(**kwargs) -> dict[str, int]:
    return {
        "users": 0,
        "coins_purchased": 0,
        "coins_in_balance": 0,
        "active_rooms": 0,
        "total_rooms": 0,
    }


class AdminPanelTest(unittest.TestCase):
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

        self.settings = SettingsStore(url="", key="", client=None)
        self.settings_patch = patch.object(
            admin, "get_settings_store", return_value=self.settings
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def test_panel_keyboard_has_all_actions(self) -> None:
        keyboard = admin.panel_keyboard()
        rows = [[button.text for button in row] for row in keyboard.inline_keyboard]
        self.assertEqual(
            rows,
            [
                ["💳 Karta raqamini sozlash"],
                ["📥 Kutilayotgan to'lovlar (Cheklar)"],
                ["➕ Foydalanuvchiga tanga berish"],
                ["🎟 Promo kod yaratish"],
                ["📢 Hammaga xabar (Broadcast)"],
            ],
        )
        callbacks = [
            row[0].callback_data for row in keyboard.inline_keyboard
        ]
        self.assertEqual(
            callbacks,
            [
                "admin_card",
                "admin_pending",
                "admin_give",
                "admin_promo",
                "admin_broadcast",
            ],
        )

    def test_panel_shows_stats_and_buttons(self) -> None:
        message = FakeMessage()
        asyncio.run(admin.admin_panel(message))
        self.assertIn("Admin panel", message.answers[-1])
        self.assertIn("hali sozlanmagan", message.answers[-1])
        self.assertIsNotNone(message.markups[-1])

    def test_panel_is_denied_for_players(self) -> None:
        message = FakeMessage(user_id=999)
        asyncio.run(admin.admin_panel(message))
        self.assertIn("faqat administrator", message.answers[-1])

    def test_card_setup_flow_saves_to_system_settings(self) -> None:
        callback = FakeCallback()
        state = FakeState()
        asyncio.run(admin.ask_card(callback, state))
        self.assertIs(state.state, admin.AdminStates.waiting_card)
        self.assertIn("Karta raqami va egasining ismini yuboring", callback.bot.messages[-1][1])
        self.assertIn("9860123456789012", callback.bot.messages[-1][1])

        message = FakeMessage(text="9860 1234 5678 9012 Ali Valiyev")
        asyncio.run(admin.save_card(message, state))
        self.assertIsNone(state.state)
        self.assertIn("Karta saqlandi", message.answers[-1])
        self.assertEqual(
            self.settings.payment_card(), ("9860123456789012", "Ali Valiyev")
        )
        self.assertIn("9860 1234 5678 9012", message.answers[-1])
        self.assertIsNotNone(message.markups[-1])

    def test_card_setup_rejects_invalid_input(self) -> None:
        state = FakeState()
        asyncio.run(admin.ask_card(FakeCallback(), state))
        message = FakeMessage(text="12345 Ali")
        asyncio.run(admin.save_card(message, state))
        self.assertIn("16-19 xonali", message.answers[-1])
        self.assertIsNotNone(state.state)  # holat saqlanib qoladi
        self.assertEqual(self.settings.payment_card(), ("", ""))

    def test_pending_payments_are_listed_with_review_buttons(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        first = store.create_payment(95001, "ali", "Ali", 500, "photo-1")
        store.create_payment(95002, "vali", "Vali", 1500, "photo-2")

        callback = FakeCallback()
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(admin.show_pending_payments(callback))

        self.assertEqual(len(callback.bot.photos), 2)
        chat_id, photo, caption, keyboard = callback.bot.photos[0]
        self.assertEqual(chat_id, 424242)
        self.assertEqual(photo, "photo-1")
        self.assertIn("Ali", caption)
        self.assertEqual(
            [button.callback_data for button in keyboard.inline_keyboard[0]],
            [f"pay_ok_{first.id}", f"pay_no_{first.id}"],
        )

        # Tasdiqlangandan keyin ro'yxatdan yo'qoladi.
        store.approve_payment(first.id, 424242)
        callback = FakeCallback()
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(admin.show_pending_payments(callback))
        self.assertEqual(len(callback.bot.photos), 1)

    def test_pending_payments_empty_message(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        callback = FakeCallback()
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(admin.show_pending_payments(callback))
        self.assertEqual(callback.bot.photos, [])
        self.assertIn(
            "Hozircha kutilayotgan to'lovlar yo'q", callback.bot.messages[-1][1]
        )

    def test_pending_payments_denied_for_players(self) -> None:
        callback = FakeCallback(user_id=999)
        asyncio.run(admin.show_pending_payments(callback))
        self.assertEqual(callback.bot.messages, [])
        self.assertIn("faqat admin", callback.answers[-1])

    def test_give_coins_from_panel(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        callback = FakeCallback()
        state = FakeState()
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(admin.ask_give_coins(callback, state))
            self.assertIs(state.state, admin.AdminStates.waiting_give)

            message = FakeMessage(text="88010 300")
            asyncio.run(admin.give_coins_from_panel(message, state))
        self.assertIn("+300", message.answers[-1])
        self.assertEqual(store.get_user(88010).coins, START_COINS + 300)
        self.assertIsNone(state.state)

    def test_broadcast_from_panel(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        store.ensure_user(88011, "u", "User")
        store.ensure_user(88012, "v", "User 2")
        callback = FakeCallback()
        state = FakeState()
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(admin.ask_broadcast(callback, state))
            self.assertIs(state.state, admin.AdminStates.waiting_broadcast)

            message = FakeMessage(text="Yangi yangilik")
            asyncio.run(admin.broadcast_from_panel(message, state))
        self.assertIn("<b>2</b> ta yuborildi", message.answers[-1])
        self.assertEqual(
            [chat_id for chat_id, _, _ in message.bot.messages], [88011, 88012]
        )

    def test_promo_code_creation_flow(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        callback = FakeCallback()
        state = FakeState()
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(admin.ask_promo(callback, state))
            self.assertIs(state.state, admin.AdminStates.waiting_promo)
            self.assertIn("Promo kod yaratish", callback.bot.messages[-1][1])

            message = FakeMessage(text="YANGIYIL 500 20")
            asyncio.run(admin.save_promo(message, state))
        self.assertIn("Promo kod yaratildi", message.answers[-1])
        self.assertIn("YANGIYIL", message.answers[-1])
        self.assertIsNone(state.state)
        promo = store.get_promo_code("YANGIYIL")
        self.assertIsNotNone(promo)
        self.assertEqual(promo.coins, 500)
        self.assertEqual(promo.max_uses, 20)

    def test_promo_code_invalid_input_keeps_state(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        state = FakeState()
        callback = FakeCallback()
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(admin.ask_promo(callback, state))
            message = FakeMessage(text="YANGIYIL")
            asyncio.run(admin.save_promo(message, state))
        self.assertIn("Format", message.answers[-1])
        self.assertIsNotNone(state.state)

    def test_back_button_returns_to_panel(self) -> None:
        callback = FakeCallback()
        state = FakeState()
        asyncio.run(admin.ask_card(callback, state))
        asyncio.run(admin.back_to_panel(callback, state))
        self.assertIsNone(state.state)
        self.assertIn("Admin panel", callback.bot.messages[-1][1])
        self.assertIsNotNone(callback.bot.messages[-1][2])


if __name__ == "__main__":
    unittest.main()
