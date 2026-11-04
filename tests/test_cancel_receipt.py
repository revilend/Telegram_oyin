"""Global /cancel va chek qabul qilish oqimi testlari."""

import asyncio
import inspect
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiogram.types import ReplyKeyboardMarkup

from bot.config import get_config
from bot.handlers import common, leaderboard, profile, shop
from bot.main import build_dispatcher
from core.economy import EconomyStore


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, object]] = []
        self.photos: list[tuple[int, str, str, object]] = []
        self.documents: list[tuple[int, str, str, object]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append((chat_id, text, kwargs.get("reply_markup")))

    async def send_photo(
        self, chat_id: int, photo: str, caption: str = "", **kwargs
    ) -> None:
        self.photos.append((chat_id, photo, caption, kwargs.get("reply_markup")))

    async def send_document(
        self, chat_id: int, document: str, caption: str = "", **kwargs
    ) -> None:
        self.documents.append(
            (chat_id, document, caption, kwargs.get("reply_markup"))
        )


class FakeMessage:
    def __init__(
        self,
        user_id: int = 73001,
        text: str = "",
        photo: list | None = None,
        document: object | None = None,
    ) -> None:
        self.from_user = SimpleNamespace(
            id=user_id, username="ali", full_name="Ali Valiyev"
        )
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.text = text
        self.photo = photo
        self.document = document
        self.bot = FakeBot()
        self.answers: list[str] = []
        self.markups: list[object] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)
        self.markups.append(kwargs.get("reply_markup"))

    async def reply(self, text: str, **kwargs) -> None:
        await self.answer(text, **kwargs)


class FakeState:
    def __init__(self, state=None, data: dict | None = None) -> None:
        self.state = state
        self.data = dict(data or {})

    async def set_state(self, state) -> None:
        self.state = state

    async def clear(self) -> None:
        self.state = None
        self.data = {}

    async def get_data(self) -> dict:
        return dict(self.data)


class BotTestCase(unittest.TestCase):
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


class CancelHandlerTest(BotTestCase):
    def test_cancel_router_is_registered_first(self) -> None:
        # Dispatcher'ni qayta qurish aiogram'da taqiqlangan, shuning uchun
        # routerlar tartibini `build_dispatcher` kodidan tekshiramiz.
        source = inspect.getsource(build_dispatcher)
        self.assertLess(
            source.index("cancel_router"), source.index("shop.router")
        )
        self.assertEqual(common.cancel_router.name, "cancel")
        self.assertEqual(len(common.cancel_router.message.handlers), 2)

    def test_cancel_command_clears_state_and_restores_menu(self) -> None:
        message = FakeMessage(text="/cancel")
        state = FakeState(state=shop.ShopStates.waiting_receipt)
        asyncio.run(common.cancel_process(message, state))
        self.assertIsNone(state.state)
        self.assertIn("Jarayon bekor qilindi", message.answers[-1])
        self.assertIsInstance(message.markups[-1], ReplyKeyboardMarkup)

    def test_cancel_texts_also_clear_state(self) -> None:
        for text in (
            "❌ Bekor qilish",
            "Bekor qilish",
            "❌ To'lov bekor qilindi.",
        ):
            with self.subTest(text=text):
                message = FakeMessage(text=text)
                state = FakeState(state=shop.ShopStates.waiting_receipt)
                asyncio.run(common.cancel_process(message, state))
                self.assertIsNone(state.state)
                self.assertIn("Jarayon bekor qilindi", message.answers[-1])

    def test_cancel_works_without_active_state(self) -> None:
        message = FakeMessage()
        state = FakeState()
        asyncio.run(common.cancel_process(message, state))
        self.assertIn("Jarayon bekor qilindi", message.answers[-1])


class ReceiptTest(BotTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store = EconomyStore(url="", key="", client=None)
        self.store.ensure_user(73001, "ali", "Ali Valiyev")
        self.economy_patch = patch.object(
            shop, "get_economy", return_value=self.store
        )
        self.economy_patch.start()
        self.addCleanup(self.economy_patch.stop)

    def _state(self) -> FakeState:
        return FakeState(
            state=shop.ShopStates.waiting_receipt,
            data={"package_coins": 500, "price_uzs": 10_000},
        )

    def test_photo_receipt_is_sent_to_admin(self) -> None:
        message = FakeMessage(photo=[SimpleNamespace(file_id="photo-1")])
        state = self._state()
        asyncio.run(shop.receipt_file(message, state))

        self.assertIn("Chekingiz qabul qilindi", message.answers[-1])
        self.assertIsNone(state.state)
        self.assertEqual(len(message.bot.photos), 1)
        chat_id, file_id, caption, keyboard = message.bot.photos[0]
        self.assertEqual(chat_id, 424242)
        self.assertEqual(file_id, "photo-1")
        self.assertIn("Ali Valiyev", caption)
        callbacks = [
            button.callback_data for button in keyboard.inline_keyboard[0]
        ]
        self.assertTrue(callbacks[0].startswith("pay_ok_"))
        self.assertTrue(callbacks[1].startswith("pay_no_"))
        self.assertEqual(len(self.store.list_pending_payments()), 1)

    def test_document_receipt_is_sent_to_admin(self) -> None:
        message = FakeMessage(document=SimpleNamespace(file_id="doc-1"))
        state = self._state()
        asyncio.run(shop.receipt_file(message, state))

        self.assertIn("Chekingiz qabul qilindi", message.answers[-1])
        self.assertEqual(message.bot.photos, [])
        self.assertEqual(len(message.bot.documents), 1)
        chat_id, file_id, _, keyboard = message.bot.documents[0]
        self.assertEqual(chat_id, 424242)
        self.assertEqual(file_id, "doc-1")
        self.assertIsNotNone(keyboard)

    def test_receipt_error_is_hidden_from_user(self) -> None:
        class BrokenStore:
            def create_payment(self, **kwargs):
                raise RuntimeError("baza ishlamayapti")

        with patch.object(shop, "get_economy", return_value=BrokenStore()):
            message = FakeMessage(photo=[SimpleNamespace(file_id="photo-2")])
            asyncio.run(shop.receipt_file(message, self._state()))
        answer = message.answers[-1]
        self.assertIn("vaqtincha xatolik", answer)
        self.assertNotIn("baza ishlamayapti", answer)

    def test_receipt_without_package_asks_to_restart(self) -> None:
        message = FakeMessage(photo=[SimpleNamespace(file_id="photo-3")])
        state = FakeState(state=shop.ShopStates.waiting_receipt, data={})
        asyncio.run(shop.receipt_file(message, state))
        self.assertIn("Paket aniqlanmadi", message.answers[-1])
        self.assertIsNone(state.state)


class ErrorMessageTest(BotTestCase):
    def test_profile_shows_the_real_error(self) -> None:
        class BrokenStore:
            def ensure_user(self, *args, **kwargs):
                raise RuntimeError("users jadvali topilmadi")

        with patch.object(profile, "get_economy", return_value=BrokenStore()):
            message = FakeMessage()
            asyncio.run(profile.show_profile(message))
        self.assertIn(
            "⚠️ Profil xatosi: users jadvali topilmadi", message.answers[-1]
        )

    def test_leaderboard_shows_the_real_error(self) -> None:
        class BrokenStore:
            def top_users(self, limit=10):
                raise RuntimeError("reyting olinmadi")

        with patch.object(leaderboard, "get_economy", return_value=BrokenStore()):
            message = FakeMessage()
            asyncio.run(leaderboard.show_leaderboard(message))
        self.assertIn("⚠️ Reyting xatosi: reyting olinmadi", message.answers[-1])


if __name__ == "__main__":
    unittest.main()
