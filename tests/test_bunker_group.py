"""Guruhdagi /bunker buyrug'i uchun regressiya testlari."""

import os
import re
import unittest
from datetime import datetime, timezone

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("MINI_APP_URL", "https://revilend.games")
os.environ.setdefault("BOT_USERNAME", "revilend_gamesbot")
from types import SimpleNamespace
from unittest.mock import patch

from aiogram import F
from aiogram.filters import Command
from aiogram.types import Chat, Message, User

from bot.handlers import bunker_group
from bot.main import build_dispatcher

BOT_USERNAME = "revilend_gamesbot"


class FakeBot:
    async def me(self) -> User:
        return User(
            id=999,
            is_bot=True,
            first_name="Revilend",
            username=BOT_USERNAME,
        )


class FakeMessage:
    def __init__(self, chat_type: str = "supergroup", user_id: int = 501) -> None:
        self.chat = SimpleNamespace(id=-100123456, type=chat_type)
        self.from_user = SimpleNamespace(
            id=user_id,
            full_name="Ali Valiyev",
            username="ali",
        )
        self.answers: list[tuple[str, object]] = []
        self.replies: list[str] = []

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))

    async def reply(self, text: str) -> None:
        self.replies.append(text)


def group_message(text: str, chat_type: str = "supergroup") -> Message:
    return Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=-100123456, type=chat_type, title="Test guruh"),
        from_user=User(id=501, is_bot=False, first_name="Ali", username="ali"),
        text=text,
    )


class GroupFilterTest(unittest.IsolatedAsyncioTestCase):
    async def test_command_with_bot_mention_matches(self) -> None:
        message = group_message(f"/bunker@{BOT_USERNAME}")
        result = await Command("bunker", "newgame")(message, FakeBot())
        self.assertTrue(result)
        self.assertEqual(result["command"].command, "bunker")
        self.assertEqual(result["command"].mention, BOT_USERNAME)

    async def test_chat_type_filter_accepts_supergroup(self) -> None:
        group_filter = F.chat.type.in_({"group", "supergroup"})
        self.assertTrue(group_filter.resolve(group_message("/bunker")))
        self.assertFalse(
            group_filter.resolve(group_message("/bunker", chat_type="private"))
        )

    async def test_router_is_included(self) -> None:
        dispatcher = build_dispatcher()
        self.assertIn("bunker_group", [router.name for router in dispatcher.sub_routers])
        self.assertGreaterEqual(len(bunker_group.router.message.handlers), 2)


class CreateGameHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_group_command_creates_room_and_replies(self) -> None:
        message = FakeMessage()
        await bunker_group.create_game(message)

        self.assertEqual(len(message.answers), 1)
        text, keyboard = message.answers[0]
        code_match = re.search(r"BNK\d{3}", text)
        self.assertIsNotNone(code_match)
        self.assertIn("Yangi Bunker öyini", text)
        self.assertEqual(len(keyboard.inline_keyboard), 3)
        first_button = keyboard.inline_keyboard[0][0]
        self.assertEqual(first_button.text, "🚪 Bunkerga kiriş")
        self.assertIsNone(first_button.web_app)
        self.assertEqual(
            first_button.url,
            f"https://t.me/{BOT_USERNAME}?startapp={code_match.group(0)}",
        )
        self.assertEqual(
            keyboard.inline_keyboard[1][0].callback_data,
            f"join_{code_match.group(0)}",
        )

    async def test_error_is_reported_to_group(self) -> None:
        class BrokenManager:
            def create_room(self, **kwargs):
                raise RuntimeError("Supabase ulanmadi")

        message = FakeMessage()
        with patch.object(
            bunker_group, "get_default_manager", return_value=BrokenManager()
        ):
            with self.assertLogs("bot.handlers.bunker_group", level="ERROR"):
                await bunker_group.create_game(message)

        self.assertEqual(len(message.replies), 1)
        self.assertIn("⚠️ Xatolik yuz berdi: Supabase ulanmadi", message.replies[0])
        self.assertEqual(message.answers, [])

    async def test_private_command_gets_guidance(self) -> None:
        message = FakeMessage(chat_type="private")
        await bunker_group.create_game_private(message)
        self.assertEqual(len(message.answers), 1)
        self.assertIn("faqat guruhda", message.answers[0][0])


if __name__ == "__main__":
    unittest.main()
