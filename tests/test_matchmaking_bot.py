"""Global o'yin qidiruvi (matchmaking) bot handlerlari testlari."""

from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("MINI_APP_URL", "https://revilend.games")
os.environ.setdefault("BOT_USERNAME", "revilend_gamesbot")

from bot.config import get_config
from bot.handlers import matchmaking
from bot.keyboards import main_menu
from bot.localized import localize_markup
from core.orthography import to_new_alphabet


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, object]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append((int(chat_id), text, kwargs.get("reply_markup")))


class FakeMessage:
    def __init__(self, user_id: int = 601, text: str = "") -> None:
        self.from_user = SimpleNamespace(
            id=user_id, full_name="Ali Valiyev", username="ali"
        )
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.bot = FakeBot()
        self.text = text
        self.answers: list[tuple[str, object]] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append((text, kwargs.get("reply_markup")))


class FakeCallback:
    def __init__(self, data: str, user_id: int = 601) -> None:
        self.data = data
        self.from_user = SimpleNamespace(
            id=user_id, full_name="Ali Valiyev", username="ali"
        )
        self.message = FakeMessage(user_id=user_id)
        self.bot = self.message.bot
        self.answered: list[str] = []

    async def answer(self, text: str = "", **_kwargs) -> None:
        self.answered.append(text)


def callback_data(keyboard: object) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]


class MatchmakingKeyboardTest(unittest.TestCase):
    def test_menu_has_matchmaking_button(self) -> None:
        markup = main_menu.build_main_menu()
        labels = [button.text for row in markup.keyboard for button in row]
        self.assertIn(matchmaking.MATCHMAKING_BUTTON, labels)
        self.assertIn(matchmaking.MATCHMAKING_BUTTON, main_menu.BUTTON_TEXTS)


class MatchmakingAlphabetTest(unittest.TestCase):
    """Navbat xabarlari va tugmalari yangi alifboda chiqishini tekshiradi."""

    def test_game_menu_uses_new_alphabet(self) -> None:
        text = to_new_alphabet(matchmaking.CHOOSE_TEXT)
        self.assertIn("Global öyin qidiruvi", text)
        self.assertIn("tölişi", text)
        self.assertIn("iştirokçilarga", text)
        self.assertNotIn("o'", text.lower())

    def test_queue_text_uses_new_alphabet(self) -> None:
        text = to_new_alphabet(
            matchmaking.queue_text("bunker", {"count": 2, "need": 2})
        )
        self.assertIn("Navbatga qöşildingiz", text)
        self.assertIn("Odamlar yiğilişi", text)
        self.assertIn("Yana 2 kişi kerak", text)
        self.assertNotIn("sh", text.lower())
        self.assertNotIn("ch", text.lower())
        self.assertNotIn("o'", text.lower())

    def test_match_text_keeps_room_code(self) -> None:
        text = to_new_alphabet(
            matchmaking.match_text(
                {"game_type": "alias", "code": "MAT7", "players": 3}
            )
        )
        self.assertIn("yiğildi", text)
        self.assertIn("<code>MAT7</code>", text)
        self.assertIn("qöşiling", text)

    def test_keyboard_labels_are_localized_and_stable(self) -> None:
        # Manba satrlari allaqachon yangi alifboda; qayta o'girish ularni buzmasligi kerak.
        source = matchmaking.cancel_keyboard("mafia")
        localized = localize_markup(source)
        labels = [button.text for row in localized.inline_keyboard for button in row]
        self.assertIn("❌ Qidiruvni bekor qiliş", labels)
        self.assertIn("◀️ Boşqa öyin", labels)
        originals = [button.text for row in source.inline_keyboard for button in row]
        self.assertEqual(originals, labels)

    def test_game_keyboard_labels_are_localized(self) -> None:
        localized = localize_markup(matchmaking.game_keyboard())
        labels = [button.text for row in localized.inline_keyboard for button in row]
        self.assertIn("🛡️ Bunker", labels)
        self.assertIn("🕵️ Mafiya", labels)
        self.assertIn("🐊 Alias", labels)


class MatchmakingHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        get_config.cache_clear()
        self.addCleanup(get_config.cache_clear)
        matchmaking.router  # modul importi tekshiriladi

    def test_menu_lists_five_game_types(self) -> None:
        message = FakeMessage(text=matchmaking.MATCHMAKING_BUTTON)
        asyncio.run(matchmaking.matchmaking_menu(message))
        text, keyboard = message.answers[-1]
        self.assertIn("Global öyin qidiruvi", text)
        self.assertEqual(
            callback_data(keyboard),
            [
                "mm_game_bunker",
                "mm_game_mafia",
                "mm_game_spyfall",
                "mm_game_alias",
                "mm_game_bomb",
            ],
        )

    def test_choose_game_queues_player(self) -> None:
        callback = FakeCallback("mm_game_bunker")
        queued = {"count": 1, "need": 4, "match": None}
        with patch.object(matchmaking, "join_global_queue", return_value=queued) as join:
            asyncio.run(matchmaking.choose_game(callback))

        join.assert_called_once_with(
            601, "bunker", name="Ali Valiyev", username="ali"
        )
        self.assertEqual(callback.answered, ["Navbatga qöşildingiz!"])
        text, keyboard = callback.bot.messages[-1][1:]
        self.assertIn("Hozir navbatda: 1 kişi", text)
        self.assertIn("Yana 4 kişi kerak", text)
        data = callback_data(keyboard)
        self.assertIn("mm_leave_bunker", data)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertIn("❌ Qidiruvni bekor qiliş", labels)

    def test_choose_game_reports_ready_room_with_mini_app_url(self) -> None:
        callback = FakeCallback("mm_game_alias")
        match = {"game_type": "alias", "code": "MAT7", "players": 3}
        with patch.object(
            matchmaking, "join_global_queue", return_value={"match": match}
        ):
            asyncio.run(matchmaking.choose_game(callback))

        text, keyboard = callback.bot.messages[-1][1:]
        self.assertIn("MAT7", text)
        button = keyboard.inline_keyboard[0][0]
        self.assertEqual(button.text, "🎮 Öyinga kiriş")
        self.assertEqual(button.web_app.url, "https://revilend.games?room=MAT7")

    def test_cancel_removes_player_from_queue(self) -> None:
        callback = FakeCallback("mm_leave_bunker")
        with patch.object(
            matchmaking, "leave_global_queue", return_value={"left": True}
        ) as leave:
            asyncio.run(matchmaking.cancel_search(callback))

        leave.assert_called_once_with(601, "bunker")
        text, _keyboard = callback.bot.messages[-1][1:]
        self.assertIn("Qidiruv bekor qilindi", text)

    def test_cancel_when_not_queued(self) -> None:
        callback = FakeCallback("mm_leave_mafia")
        with patch.object(
            matchmaking, "leave_global_queue", return_value={"left": False}
        ):
            asyncio.run(matchmaking.cancel_search(callback))
        text, _keyboard = callback.bot.messages[-1][1:]
        self.assertIn("navbatda emassiz", text)

    def test_send_match_notices_to_every_player(self) -> None:
        bot = FakeBot()
        players = [{"user_id": 1}, {"user_id": 2}, {"user_id": 0}]
        match = {"game_type": "bunker", "code": "GG12", "players": 5}
        asyncio.run(matchmaking.send_match_notices(bot, players, match))

        self.assertEqual([chat_id for chat_id, _, _ in bot.messages], [1, 2])
        for _chat_id, text, keyboard in bot.messages:
            self.assertIn("GG12", text)
            self.assertEqual(
                keyboard.inline_keyboard[0][0].web_app.url,
                "https://revilend.games?room=GG12",
            )


class MatchmakingWebAppFallbackTest(unittest.TestCase):
    """Guruh chatida web_app tugmasi rad etilsa, oddiy havolaga qaytish."""

    def test_web_app_rejection_falls_back_to_url_button(self) -> None:
        from aiogram.exceptions import TelegramBadRequest

        bot = FakeBot()
        failures = {"web_app": 0}
        original = bot.send_message

        async def send_message(chat_id, text, **kwargs):
            markup = kwargs.get("reply_markup")
            button = markup.inline_keyboard[0][0] if markup else None
            if button is not None and getattr(button, "web_app", None) is not None:
                failures["web_app"] += 1
                raise TelegramBadRequest(
                    method=SimpleNamespace(), message="Bad Request: BUTTON_TYPE_INVALID"
                )
            await original(chat_id, text, **kwargs)

        bot.send_message = send_message
        match = {"game_type": "bunker", "code": "GG12", "players": 4}
        asyncio.run(matchmaking.send_match_notices(bot, [{"user_id": 77}], match))

        self.assertEqual(failures["web_app"], 1)
        button = bot.messages[-1][2].inline_keyboard[0][0]
        self.assertIsNone(getattr(button, "web_app", None))
        self.assertEqual(button.url, "https://revilend.games?room=GG12")
