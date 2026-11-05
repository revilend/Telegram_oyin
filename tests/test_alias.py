"""«Alias / Krokodil» dvigateli va guruh handlerlari testlari."""

from __future__ import annotations

import asyncio
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("MINI_APP_URL", "https://revilend.games")
os.environ.setdefault("BOT_USERNAME", "revilend_gamesbot")

from bot.handlers import alias_group, games_catalog
from core.economy import EconomyStore
from core.orthography import to_new_alphabet
from games.alias.engine import (
    AliasError,
    AliasManager,
    AliasStatus,
    AliasWord,
    WordBook,
    normalize_word,
)

CONFIG = SimpleNamespace(bot_username="revilend_gamesbot")


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **_kwargs) -> None:
        self.messages.append((int(chat_id), text))


class FakeMessage:
    def __init__(
        self,
        user_id: int = 701,
        name: str = "Ali Valiyev",
        username: str = "ali",
        chat_id: int = -100777,
        chat_type: str = "group",
        text: str = "",
    ) -> None:
        self.from_user = SimpleNamespace(
            id=user_id, full_name=name, username=username
        )
        self.chat = SimpleNamespace(id=chat_id, type=chat_type)
        self.bot = FakeBot()
        self.text = text
        self.answers: list[tuple[str, object]] = []
        self.replies: list[str] = []
        self.message_id = 10

    async def answer(self, text: str, **kwargs):
        self.answers.append((text, kwargs.get("reply_markup")))
        return SimpleNamespace(message_id=11)

    async def reply(self, text: str, **_kwargs) -> None:
        self.replies.append(text)

    async def edit_text(self, text: str, **_kwargs) -> None:
        self.answers.append((text, None))


class FakeCallback:
    def __init__(
        self, data: str, user_id: int = 701, name: str = "Ali", username: str = "ali"
    ) -> None:
        self.data = data
        self.from_user = SimpleNamespace(
            id=user_id, full_name=name, username=username
        )
        self.message = FakeMessage(user_id=user_id, name=name, username=username)
        self.bot = self.message.bot
        self.answered: list[str] = []

    async def answer(self, text: str = "", **_kwargs) -> None:
        self.answered.append(text)


def _discard(coro):
    """Fon vazifalarini testda ishga tushirmasdan yopadi."""
    coro.close()
    return None


class AliasEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        words = [
            AliasWord("Kitob", ("varaq", "o'qish", "muqova")),
            AliasWord("Şahar", ("ko'cha", "uy", "aholi")),
            AliasWord("Özbekiston", ("mamlakat", "Toshkent", "bayroq")),
        ]
        self.manager = AliasManager(seed=3, wordbook=WordBook(words))

    def _room(self, players: int = 3):
        room = self.manager.create_room(-100, 1, "Ali", "ali")
        for index in range(2, players + 1):
            self.manager.join(room.code, index, f"P{index}", f"p{index}")
        return room

    def test_start_requires_two_players(self) -> None:
        room = self.manager.create_room(-100, 1, "Ali", "ali")
        with self.assertRaises(AliasError):
            self.manager.start_game(room.code, 1)

    def test_only_host_can_start(self) -> None:
        room = self._room()
        with self.assertRaises(AliasError):
            self.manager.start_game(room.code, 2)
        started = self.manager.start_game(room.code, 1)
        self.assertIs(started.status, AliasStatus.PLAYING)
        self.assertIsNotNone(started.current_round)

    def test_explainer_changes_each_round(self) -> None:
        room = self._room(players=4)
        seen = set()
        for _ in range(6):
            room = self.manager.next_round(room.code)
            current = room.current_round
            self.assertIsNotNone(current)
            seen.add(current.explainer_id)
        self.assertGreater(len(seen), 1)

    def test_guess_normalizes_new_alphabet(self) -> None:
        room = self._room()
        self.manager.start_game(room.code, 1)
        current = room.current_round
        self.assertIsNotNone(current)
        guesser = next(uid for uid in room.players if uid != current.explainer_id)
        guess = current.word.word.lower().replace("ş", "sh").replace("ö", "o'")
        outcome = self.manager.submit_guess(room.chat_id, guesser, guess)
        self.assertIsNotNone(outcome)
        found_room, result = outcome
        self.assertTrue(result.correct)
        self.assertEqual(result.winner_id, guesser)
        self.assertEqual(found_room.players[guesser].score, 1)

    def test_wrong_and_explainer_guesses_are_ignored(self) -> None:
        room = self._room()
        self.manager.start_game(room.code, 1)
        current = room.current_round
        self.assertIsNotNone(current)
        other = next(uid for uid in room.players if uid != current.explainer_id)
        self.assertIsNone(self.manager.submit_guess(room.chat_id, other, "noto'g'ri"))
        self.assertIsNone(
            self.manager.submit_guess(
                room.chat_id, current.explainer_id, current.word.word
            )
        )
        second = self.manager.submit_guess(room.chat_id, other, current.word.word)
        self.assertIsNotNone(second)
        self.assertTrue(second[1].correct)
        # Ikkinchi marta topib bo'lmaydi: raund yopilgan.
        third = self.manager.submit_guess(room.chat_id, other, current.word.word)
        self.assertIsNotNone(third)
        self.assertFalse(third[1].correct)

    def test_each_player_explains_twice_and_game_completes(self) -> None:
        room = self._room(players=3)
        self.manager.start_game(room.code, 1)
        self.assertEqual(room.total_rounds, 6)
        for _ in range(room.total_rounds - 1):
            room = self.manager.next_round(room.code)
        self.assertTrue(room.is_complete)
        self.assertEqual(room.rounds_played, 6)
        self.assertEqual(sorted(room.explainer_counts.values()), [2, 2, 2])
        with self.assertRaises(AliasError):
            self.manager.next_round(room.code)

    def test_two_consecutive_misses_stop_the_game(self) -> None:
        room = self._room(players=3)
        self.manager.start_game(room.code, 1, now=1000.0)
        current = room.current_round
        self.assertIsNotNone(current)
        room.expire_round(now=1000.0 + current.duration + 1)
        self.assertFalse(room.should_stop_for_inactivity())
        room = self.manager.next_round(room.code, now=1100.0)
        room.abort_round()
        self.assertTrue(room.should_stop_for_inactivity())

    def test_correct_guess_resets_miss_counter(self) -> None:
        room = self._room(players=3)
        self.manager.start_game(room.code, 1, now=1000.0)
        current = room.current_round
        self.assertIsNotNone(current)
        room.expire_round(now=1000.0 + current.duration + 1)
        room = self.manager.next_round(room.code, now=1100.0)
        current = room.current_round
        self.assertIsNotNone(current)
        guesser = next(uid for uid in room.players if uid != current.explainer_id)
        room.submit_guess(guesser, current.word.word, now=1101.0)
        self.assertEqual(room.consecutive_misses, 0)

    def test_round_expires_after_duration(self) -> None:
        room = self._room()
        self.manager.start_game(room.code, 1, now=1000.0)
        current = room.current_round
        self.assertIsNotNone(current)
        self.assertFalse(room.expire_round(now=1000.0 + current.duration - 1))
        self.assertTrue(room.expire_round(now=1000.0 + current.duration + 1))

    def test_expire_stale_removes_idle_rooms(self) -> None:
        room = self._room()
        self.manager._times[room.code] = time.time() - 3600
        report = self.manager.expire_stale(lobby_idle_seconds=60)
        self.assertEqual(report["expired"], 1)
        self.assertEqual(self.manager.room_count, 0)

    def test_wordbook_picks_unused_words(self) -> None:
        book = WordBook([AliasWord("A"), AliasWord("B")])
        import random as _random

        rng = _random.Random(1)
        used: set[str] = set()
        first = book.pick(rng, used)
        used.add(normalize_word(first.word))
        second = book.pick(rng, used)
        self.assertNotEqual(first.word, second.word)

    def test_wordbook_loads_rows_from_client(self) -> None:
        rows = [
            {"word": "Çoy", "forbidden": ["piyola", "qaynoq", "damlama"], "category": "ichimlik"},
            {"word": "O'chirilgan", "forbidden": [], "is_active": False},
        ]

        class FakeTable:
            def select(self, *_args):
                return self

            def execute(self):
                return SimpleNamespace(data=rows)

        class FakeClient:
            def table(self, name):
                assert name == "alias_words"
                return FakeTable()

        book = WordBook([])
        count = book.load_from_client(FakeClient())
        self.assertEqual(count, 1)
        self.assertEqual(book.words[0].word, "Çoy")


class AliasAlphabetTest(unittest.TestCase):
    """Guruh xabarlari yangi o'zbek alifbosida ko'rinishini tekshiradi."""

    def test_round_messages_use_new_alphabet(self) -> None:
        manager = AliasManager(seed=9)
        room = manager.create_room(-100, 1, "Ali", "ali")
        manager.join(room.code, 2, "Vali", "vali")
        manager.start_game(room.code, 1)
        current = room.current_round
        self.assertIsNotNone(current)

        announcement = to_new_alphabet(
            alias_group.round_announcement(room, current)
        )
        self.assertIn("ALIAS ÖYINI BOŞLANDI", announcement)
        self.assertIn("söz tuşuntirmoqda", announcement)
        self.assertIn("birinçi bölib", announcement)
        self.assertNotIn("sh", announcement.lower())
        self.assertNotIn("ch", announcement.lower())
        self.assertNotIn("o'", announcement.lower())

        private = to_new_alphabet(alias_group.explainer_message(room, current))
        self.assertIn("Sizning sözingiz", private)
        self.assertIn("Taqiqlangan sözlar", private)
        self.assertNotIn("sh", private.lower())
        self.assertNotIn("o'", private.lower())

    def test_lobby_buttons_use_new_alphabet(self) -> None:
        manager = AliasManager(seed=9)
        room = manager.create_room(-100, 1, "Ali", "ali")
        labels = [
            button.text
            for row in alias_group.lobby_keyboard(room).inline_keyboard
            for button in row
        ]
        converted = [to_new_alphabet(label) for label in labels]
        self.assertIn("➕ Qöşiliş", converted)
        self.assertIn("▶️ Boşlaş", converted)


class AliasHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = AliasManager(seed=5)
        patcher = patch.object(
            alias_group, "get_default_manager", return_value=self.manager
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        config_patcher = patch.object(
            alias_group, "get_config", return_value=CONFIG
        )
        config_patcher.start()
        self.addCleanup(config_patcher.stop)
        spawn_patcher = patch.object(alias_group, "_spawn", side_effect=_discard)
        spawn_patcher.start()
        self.addCleanup(spawn_patcher.stop)

        self.economy = EconomyStore(url="", key="", client=None)
        economy_patcher = patch.object(
            alias_group, "get_economy", return_value=self.economy
        )
        economy_patcher.start()
        self.addCleanup(economy_patcher.stop)

    def _lobby(self) -> tuple[object, FakeMessage]:
        message = FakeMessage()
        asyncio.run(alias_group.create_alias_game(message))
        room = self.manager.room_by_chat(message.chat.id)
        return room, message

    def test_alias_command_opens_lobby_with_buttons(self) -> None:
        room, message = self._lobby()
        self.assertIsNotNone(room)
        text, markup = message.answers[-1]
        self.assertIn("ALIAS / KROKODIL", text)
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertIn(f"alias_join_{room.code}", callbacks)
        self.assertIn(f"alias_start_{room.code}", callbacks)
        self.assertIn(f"alias_end_{room.code}", callbacks)

    def test_join_and_start_send_word_privately(self) -> None:
        room, _message = self._lobby()
        callback = FakeCallback(f"alias_join_{room.code}", user_id=702, name="Vali")
        asyncio.run(alias_group.join_alias_game(callback))
        self.assertIn(702, room.players)

        start = FakeCallback(f"alias_start_{room.code}", user_id=701)
        asyncio.run(alias_group.start_alias_game(start))
        self.assertIs(start.message.bot.messages and True, True)
        texts = [text for _chat, text in start.bot.messages]
        self.assertTrue(any("ALIAS ÖYINI BOŞLANDI" in text for text in texts))
        current = room.current_round
        self.assertIsNotNone(current)
        private = [
            text
            for chat_id, text in start.bot.messages
            if chat_id == current.explainer_id
        ]
        self.assertTrue(private, "Tushuntiruvchiga shaxsiy xabar yuborilmadi")
        self.assertIn(current.word.word, private[0])
        for forbidden in current.word.forbidden:
            self.assertIn(forbidden, private[0])
        # Guruh xabarida yashirin so'z bo'lmasligi kerak.
        group_texts = [
            text for chat_id, text in start.bot.messages if chat_id == room.chat_id
        ]
        self.assertFalse(any(current.word.word in text for text in group_texts))

    def test_non_host_cannot_start(self) -> None:
        room, _message = self._lobby()
        join = FakeCallback(f"alias_join_{room.code}", user_id=702)
        asyncio.run(alias_group.join_alias_game(join))
        start = FakeCallback(f"alias_start_{room.code}", user_id=702)
        asyncio.run(alias_group.start_alias_game(start))
        self.assertTrue(start.answered)
        self.assertIn("ega", start.answered[-1])
        self.assertIsNone(room.current_round)

    def test_correct_guess_awards_coins_once(self) -> None:
        room, _message = self._lobby()
        join = FakeCallback(f"alias_join_{room.code}", user_id=702, name="Vali")
        asyncio.run(alias_group.join_alias_game(join))
        start = FakeCallback(f"alias_start_{room.code}", user_id=701)
        asyncio.run(alias_group.start_alias_game(start))

        current = room.current_round
        self.assertIsNotNone(current)
        guesser = next(uid for uid in room.players if uid != current.explainer_id)
        guess = FakeMessage(user_id=guesser, text=current.word.word)
        asyncio.run(alias_group.alias_guess_watcher(guess))
        self.assertTrue(guess.answers)
        self.assertIn("Töğri javob", guess.answers[-1][0])
        self.assertEqual(self.economy.get_user(guesser).coins, 100 + 10)
        self.assertEqual(
            self.economy.get_user(current.explainer_id).coins, 100 + 5
        )

        again = FakeMessage(user_id=guesser, text=current.word.word)
        asyncio.run(alias_group.alias_guess_watcher(again))
        self.assertFalse(again.answers, "Ikkinchi javob e'lon qilinmasligi kerak")
        self.assertEqual(self.economy.get_user(guesser).coins, 100 + 10)

    def test_guess_watcher_ignores_other_chats(self) -> None:
        message = FakeMessage(chat_id=-100999, text="Kitob")
        asyncio.run(alias_group.alias_guess_watcher(message))
        self.assertFalse(message.answers)

    def _three_player_game(self):
        room, _message = self._lobby()
        for user_id, name in ((702, "Vali"), (703, "Zilola")):
            asyncio.run(
                alias_group.join_alias_game(
                    FakeCallback(
                        f"alias_join_{room.code}", user_id=user_id, name=name
                    )
                )
            )
        self.manager.start_game(room.code, 701)
        return room

    def test_completed_game_awards_winner_and_closes_room(self) -> None:
        room = self._three_player_game()
        room.players[702].score = 3
        bot = FakeBot()

        asyncio.run(alias_group._stop_game(bot, room, reason="completed"))

        self.assertEqual(room.status.value, "FINISHED")
        self.assertEqual(
            self.economy.get_user(702).coins,
            100 + alias_group.WINNER_REWARD,
        )
        self.assertEqual(self.economy.get_user(703).coins, 100)
        self.assertIsNone(self.manager.room_by_chat(room.chat_id))
        self.assertTrue(
            any("Ğolib" in text for _chat_id, text in bot.messages), bot.messages
        )

    def test_inactive_game_closes_room_with_message(self) -> None:
        room = self._three_player_game()
        room.consecutive_misses = 2
        bot = FakeBot()

        asyncio.run(alias_group._stop_game(bot, room, reason="inactive"))

        self.assertEqual(room.status.value, "FINISHED")
        self.assertEqual(bot.messages[-1][1], alias_group.INACTIVE_TEXT)
        self.assertIn("Guruhda faollik bölmagani sababli", bot.messages[-1][1])
        self.assertIsNone(self.manager.room_by_chat(room.chat_id))

    def test_host_stop_command_ends_game(self) -> None:
        room = self._three_player_game()
        message = FakeMessage(text="/stop")

        with patch.object(alias_group, "is_admin", return_value=False):
            asyncio.run(alias_group.stop_alias_command(message))

        self.assertEqual(room.status.value, "FINISHED")
        self.assertIsNone(self.manager.room_by_chat(room.chat_id))
        self.assertTrue(message.bot.messages)

    def test_non_host_stop_command_is_rejected(self) -> None:
        room = self._three_player_game()
        message = FakeMessage(user_id=702, text="/stopalias")

        with patch.object(alias_group, "is_admin", return_value=False):
            asyncio.run(alias_group.stop_alias_command(message))

        self.assertEqual(room.status.value, "PLAYING")
        self.assertTrue(
            any("faqat xona egasi" in text for _chat_id, text in message.bot.messages)
        )

    def test_cancel_in_group_stops_active_alias(self) -> None:
        from bot.handlers import common

        room = self._three_player_game()

        class State:
            async def clear(self) -> None:
                return None

        message = FakeMessage(text="/cancel")
        asyncio.run(common.cancel_process(message, State()))

        self.assertEqual(room.status.value, "FINISHED")
        self.assertIsNone(self.manager.room_by_chat(room.chat_id))

    def test_catalog_has_alias_button(self) -> None:
        markup = games_catalog.catalog_keyboard()
        texts = [button.text for row in markup.inline_keyboard for button in row]
        self.assertTrue(any("Alias" in text for text in texts))
        self.assertIn("Alias", games_catalog.CATALOG_TEXT)
        self.assertIn("/alias", games_catalog.ALIAS_TEXT)


if __name__ == "__main__":
    unittest.main()
