"""Guruh Mafiya handlerlari va o'yinlar vitrinasi testlari."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("MINI_APP_URL", "https://revilend.games")
os.environ.setdefault("BOT_USERNAME", "revilend_gamesbot")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")

from bot import main as bot_main
from bot.handlers import games_catalog, mafia_group
from bot.handlers.mafia_group import MafiaGame, MafiaLobbyManager
from bot.main import BOT_COMMANDS
from core.economy import MAFIA_WIN_REWARD, START_COINS, EconomyStore
from games.mafia.engine import (
    GamePhase,
    MafiaError,
    MafiaPlayer,
    MafiaRoom,
    Winner,
    resolve_night,
)
from games.mafia.generator import MIN_PLAYERS
from games.mafia.images import (
    image_path,
    role_image_path,
    role_image_url,
    victory_image_path,
)
from games.mafia.roles import MafiaRole

BOT_USERNAME = "revilend_gamesbot"
CHAT_ID = -100123456


class FakeBot:
    def __init__(self, fail_for: set[int] | None = None) -> None:
        self.fail_for = set(fail_for or ())
        self.messages: list[tuple[int, str, object]] = []
        self.photos: list[tuple[int, str, str, object]] = []

    async def send_message(
        self, chat_id: int, text: str, reply_markup=None, **kwargs
    ):
        if int(chat_id) in self.fail_for:
            raise RuntimeError("bot blocked")
        self.messages.append((int(chat_id), text, reply_markup))
        return SimpleNamespace(message_id=len(self.messages))

    async def send_photo(
        self, chat_id: int, photo, caption: str = "", reply_markup=None, **kwargs
    ):
        if int(chat_id) in self.fail_for:
            raise RuntimeError("bot blocked")
        path = str(getattr(photo, "path", photo))
        self.photos.append((int(chat_id), path, caption, reply_markup))
        self.messages.append((int(chat_id), caption, reply_markup))
        return SimpleNamespace(message_id=len(self.messages))

    def texts_for(self, chat_id: int) -> list[str]:
        return [text for cid, text, _ in self.messages if cid == chat_id]


class FakeMessage:
    def __init__(
        self,
        user_id: int = 501,
        chat_type: str = "supergroup",
        text: str = "",
        chat_id: int = CHAT_ID,
        bot: FakeBot | None = None,
    ) -> None:
        self.chat = SimpleNamespace(id=chat_id, type=chat_type)
        self.from_user = SimpleNamespace(
            id=user_id, full_name="Ali Valiyev", username="ali"
        )
        self.text = text
        self.bot = bot or FakeBot()
        self.photo = None
        self.photos: list[tuple[str, str, object]] = []
        self.answers: list[tuple[str, object]] = []
        self.edits: list[tuple[str, object]] = []
        self.replies: list[str] = []

    async def answer(self, text: str, reply_markup=None, **kwargs):
        self.answers.append((text, reply_markup))
        return SimpleNamespace(message_id=321)

    async def answer_photo(
        self, photo, caption: str = "", reply_markup=None, **kwargs
    ):
        self.photo = photo
        self.photos.append(
            (str(getattr(photo, "path", photo)), caption, reply_markup)
        )
        self.answers.append((caption, reply_markup))
        return SimpleNamespace(message_id=322)

    async def edit_caption(
        self, caption: str, reply_markup=None, **kwargs
    ):
        self.edits.append((caption, reply_markup))
        return SimpleNamespace(message_id=321)

    async def edit_text(self, text: str, reply_markup=None, **kwargs):
        self.edits.append((text, reply_markup))
        return SimpleNamespace(message_id=321)

    async def reply(self, text: str, **kwargs):
        self.replies.append(text)


class FakeCallback:
    def __init__(
        self,
        user_id: int,
        data: str,
        message: FakeMessage | None = None,
    ) -> None:
        self.from_user = SimpleNamespace(
            id=user_id, full_name="Ali Valiyev", username="ali"
        )
        self.data = data
        self.message = message or FakeMessage(user_id=user_id)
        self.bot = self.message.bot
        self.answers: list[tuple[str, bool]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False, **kwargs):
        self.answers.append((text or "", show_alert))


def make_game(
    roles: dict[int, MafiaRole],
    *,
    usernames: dict[int, str] | None = None,
    host_id: int = 1,
) -> MafiaGame:
    """Belgilangan rollar bilan guruh o'yinini yasaydi."""
    room = MafiaRoom(
        [
            MafiaPlayer(user_id, f"P{user_id}", role=role)
            for user_id, role in sorted(roles.items())
        ],
        room_id="MAF777",
    )
    room.phase = GamePhase.NIGHT
    room.round = 1
    game = MafiaGame(
        code="MAF777", chat_id=-100777, host_id=host_id, room=room
    )
    game.usernames = dict(usernames or {})
    return game


class LobbyManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = MafiaLobbyManager(seed=2026)

    def test_codes_are_unique_and_prefixed(self) -> None:
        codes = {
            self.manager.create_game(CHAT_ID, 1, "Ali", "ali").code
            for _ in range(40)
        }
        self.assertEqual(len(codes), 40)
        for code in codes:
            self.assertRegex(code, r"^MAF\d{3}$")

    def test_join_tracks_players_and_rejects_duplicates(self) -> None:
        game = self.manager.create_game(CHAT_ID, 501, "Ali", "ali")
        player = self.manager.join(game.code, 502, "Vali", "vali")

        self.assertEqual(player.user_id, 502)
        self.assertIn(502, game.room.players)
        self.assertEqual(game.usernames[502], "vali")
        with self.assertRaises(mafia_group.MafiaGameError):
            self.manager.join(game.code, 502, "Vali", "vali")
        with self.assertRaises(mafia_group.MafiaGameError):
            self.manager.get_game("MAF000")

    def test_start_requires_host_and_minimum_players(self) -> None:
        game = self.manager.create_game(CHAT_ID, 501, "Ali", "ali")
        for user_id in (502, 503):
            self.manager.join(game.code, user_id, f"P{user_id}", "")

        with self.assertRaises(mafia_group.MafiaGameError) as caught:
            self.manager.start_game(game.code, 501)
        self.assertIn(f"kamida {MIN_PLAYERS}", str(caught.exception))

        self.manager.join(game.code, 504, "P504", "")
        with self.assertRaises(mafia_group.MafiaGameError) as caught:
            self.manager.start_game(game.code, 999)
        self.assertIn("faqat xona egasi", str(caught.exception))

        started = self.manager.start_game(game.code, 501)
        self.assertIs(started.room.phase, GamePhase.NIGHT)
        self.assertEqual(started.room.round, 1)
        self.assertTrue(
            all(player.role is not None for player in started.room.players.values())
        )

        with self.assertRaises(mafia_group.MafiaGameError) as caught:
            self.manager.join(game.code, 505, "P505", "")
        self.assertIn("qo'shilish", str(caught.exception))

    def test_room_add_player_rejects_started_game(self) -> None:
        room = MafiaRoom([MafiaPlayer(1, "A")])
        room.add_player(MafiaPlayer(2, "B"))
        self.assertIn(2, room.players)
        room.phase = GamePhase.NIGHT
        with self.assertRaises(MafiaError):
            room.add_player(MafiaPlayer(3, "C"))


class GroupCommandTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.manager = MafiaLobbyManager(seed=4)
        patcher = patch.object(
            mafia_group, "get_default_manager", return_value=self.manager
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_group_command_announces_room_with_buttons(self) -> None:
        message = FakeMessage()
        await mafia_group.create_mafia_game(message)

        text, keyboard = message.answers[0]
        code = keyboard.inline_keyboard[1][0].callback_data.removeprefix(
            "join_mafia_"
        )
        self.assertRegex(code, r"^MAF\d{3}$")
        self.assertIn("MAFIYA ÖYINI BOŞLANMOQDA", text)
        self.assertIn("jami 1 kişi", text)
        self.assertIn("Ali Valiyev", text)

        self.assertEqual(len(message.photos), 1)
        self.assertTrue(message.photos[0][0].endswith("cover.png"))
        self.assertEqual(len(keyboard.inline_keyboard), 3)
        join_button = keyboard.inline_keyboard[0][0]
        self.assertEqual(join_button.text, "🚪 Mafiyaga kiriş")
        self.assertEqual(
            join_button.url,
            f"https://t.me/{BOT_USERNAME}?startapp=mafia_{code}",
        )
        self.assertEqual(
            keyboard.inline_keyboard[1][0].callback_data,
            f"join_mafia_{code}",
        )
        self.assertEqual(
            keyboard.inline_keyboard[2][0].callback_data,
            f"start_mafia_{code}",
        )

    async def test_private_command_explains_group_flow(self) -> None:
        message = FakeMessage(chat_type="private")
        await mafia_group.create_mafia_game_private(message)

        text, keyboard = message.answers[0]
        self.assertIn("faqat guruhda", text)
        self.assertIn("/mafia", text)
        self.assertIn(f"{MIN_PLAYERS} kişi", text)
        self.assertIn("startgroup=true", keyboard.inline_keyboard[0][0].url)

    async def test_join_updates_announcement(self) -> None:
        game = self.manager.create_game(CHAT_ID, 501, "Ali Valiyev", "ali")
        message = FakeMessage()
        message.photo = object()
        callback = FakeCallback(502, f"join_mafia_{game.code}", message)

        await mafia_group.join_mafia_game(callback)

        self.assertIn(502, game.room.players)
        self.assertEqual(callback.answers[-1][0], "Mafiyaga qöşildingiz!")
        self.assertTrue(message.edits)
        self.assertIn("(jami 2 kişi)", message.edits[-1][0])
        self.assertEqual(len(message.edits[-1][1].inline_keyboard), 3)

    async def test_join_errors_are_shown_as_alerts(self) -> None:
        game = self.manager.create_game(CHAT_ID, 501, "Ali Valiyev", "ali")
        self.manager.join(game.code, 502, "Vali", "vali")

        duplicate = FakeCallback(502, f"join_mafia_{game.code}")
        await mafia_group.join_mafia_game(duplicate)
        self.assertTrue(duplicate.answers[-1][1])
        self.assertIn("allaqachon", duplicate.answers[-1][0])

        missing = FakeCallback(503, "join_mafia_MAF999")
        await mafia_group.join_mafia_game(missing)
        self.assertIn("topilmadi", missing.answers[-1][0])


class StartGameHandlerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.manager = MafiaLobbyManager(seed=9)
        patcher = patch.object(
            mafia_group, "get_default_manager", return_value=self.manager
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _room_with_players(self, count: int = 4) -> MafiaGame:
        game = self.manager.create_game(CHAT_ID, 501, "Ali Valiyev", "ali")
        for user_id in range(502, 502 + count - 1):
            self.manager.join(game.code, user_id, f"P{user_id}", f"user{user_id}")
        return game

    async def test_host_starts_and_players_get_roles_and_night_message(self) -> None:
        game = self._room_with_players(4)
        message = FakeMessage()
        message.photo = object()
        callback = FakeCallback(501, f"start_mafia_{game.code}", message)

        await mafia_group.start_mafia_game(callback)

        self.assertIs(game.room.phase, GamePhase.NIGHT)
        self.assertEqual(callback.answers[-1][0], "Öyin boşlandi!")
        self.assertTrue(message.edits)
        self.assertIn("BOŞLANDI", message.edits[0][0])
        self.assertIsNotNone(game.phase_deadline)
        self.assertGreater(game.phase_seconds_left(), 50)

        group_texts = message.bot.texts_for(game.chat_id)
        self.assertTrue(
            any("ŞAHARGA TUN ÇÖKDI" in text for text in group_texts)
        )
        role_dms = {
            chat_id
            for chat_id, text, _ in message.bot.messages
            if "Sizning rolingiz" in text
        }
        self.assertEqual(role_dms, set(game.room.players))

        night_message = next(
            item
            for item in message.bot.messages
            if "ŞAHARGA TUN ÇÖKDI" in item[1]
        )
        night_photo = next(
            item
            for item in message.bot.photos
            if "ŞAHARGA TUN ÇÖKDI" in item[2]
        )
        self.assertTrue(night_photo[1].endswith("night.png"))
        keyboard = night_message[2]
        self.assertEqual(
            keyboard.inline_keyboard[0][0].url,
            f"https://t.me/{BOT_USERNAME}?startapp=mafia_{game.code}",
        )
        self.assertEqual(
            keyboard.inline_keyboard[1][0].callback_data,
            f"end_night_mafia_{game.code}",
        )

    async def test_non_host_cannot_start(self) -> None:
        game = self._room_with_players(4)
        callback = FakeCallback(999, f"start_mafia_{game.code}")

        await mafia_group.start_mafia_game(callback)

        self.assertTrue(callback.answers[-1][1])
        self.assertIn("faqat xona egasi", callback.answers[-1][0])
        self.assertIs(game.room.phase, GamePhase.LOBBY)

    async def test_too_few_players_are_rejected(self) -> None:
        game = self._room_with_players(3)
        callback = FakeCallback(501, f"start_mafia_{game.code}")

        await mafia_group.start_mafia_game(callback)

        self.assertIn(f"kamida {MIN_PLAYERS}", callback.answers[-1][0])
        self.assertIs(game.room.phase, GamePhase.LOBBY)

    async def test_failed_role_dm_is_reported_in_group(self) -> None:
        bot = FakeBot(fail_for={504})
        game = self._room_with_players(4)
        message = FakeMessage(bot=bot)
        callback = FakeCallback(501, f"start_mafia_{game.code}", message)

        await mafia_group.start_mafia_game(callback)

        group_texts = bot.texts_for(game.chat_id)
        self.assertTrue(any("şaxsiy" in text for text in group_texts))
        self.assertTrue(any("P504" in text for text in group_texts))


class AnnouncementTest(unittest.IsolatedAsyncioTestCase):
    async def test_lobby_night_and_execution_texts(self) -> None:
        game = make_game(
            {
                1: MafiaRole.SHERIFF,
                2: MafiaRole.MAFIA,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.CITIZEN,
            },
            usernames={1: "ali"},
        )

        lobby = mafia_group.lobby_text(game)
        self.assertIn("MAFIYA ÖYINI BOŞLANMOQDA", lobby)
        self.assertIn("@ali", lobby)
        self.assertIn("jami 4 kişi", lobby)

        night = mafia_group.night_text(game)
        self.assertIn("ŞAHARGA TUN ÇÖKDI", night)

        execution = mafia_group.execution_text(game, game.room.get_player(1))
        self.assertIn("@ali", execution)
        self.assertIn("Sherif", execution)
        self.assertIn("qatl qilindi", execution)

        bot = FakeBot()
        await mafia_group.announce_execution(
            bot, game, game.room.get_player(1)
        )
        self.assertEqual(bot.messages[0][1], execution)
        self.assertTrue(bot.photos[0][1].endswith("eliminated.jpg"))

    async def test_day_text_for_peaceful_night_and_death(self) -> None:
        peaceful = make_game(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.CITIZEN,
            }
        )
        resolve_night(peaceful.room)
        self.assertIn(
            "Tunda heç kim halok bölmadi.",
            mafia_group.day_text(peaceful),
        )

        deadly = make_game(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.CITIZEN,
            }
        )
        deadly.room.submit_night_action(1, 3)
        resolve_night(deadly.room)
        text = mafia_group.day_text(deadly)
        self.assertIn("Tunda halok böldilar: P3.", text)
        self.assertIn("TONG OTDI", text)

    async def test_day_announcement_includes_finish_when_game_is_over(self) -> None:
        game = make_game(
            {
                1: MafiaRole.DON,
                2: MafiaRole.MAFIA,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
            }
        )
        game.room.submit_night_action(1, 4)
        resolve_night(game.room)
        self.assertIs(game.room.winner, Winner.MAFIA)

        bot = FakeBot()
        await mafia_group.announce_day(bot, game)

        texts = bot.texts_for(game.chat_id)
        self.assertEqual(len(texts), 2)
        self.assertIn("TONG OTDI", texts[0])
        self.assertIn("MAFIYA ğalaba qozondi", texts[1])
        self.assertTrue(bot.photos[0][1].endswith("day.png"))
        self.assertTrue(bot.photos[1][1].endswith("mafia_victory.png"))

        vote_button = bot.messages[0][2].inline_keyboard[0][0]
        self.assertEqual(vote_button.text, "🗳 Ovoz beriş")
        self.assertIn(f"startapp=mafia_{game.code}", vote_button.url)

    async def test_finish_labels(self) -> None:
        expected = {
            Winner.TOWN: "ŞAHAR",
            Winner.MAFIA: "MAFIYA",
            Winner.MANIAC: "MANIAK",
            Winner.JESTER: "JESTER",
        }
        for winner, label in expected.items():
            text = mafia_group.finish_text(winner)
            self.assertIn("ÖYIN YAKUNLANDI", text)
            self.assertIn(label, text)

    async def test_role_card_contains_role_and_action(self) -> None:
        game = make_game(
            {
                1: MafiaRole.SHERIFF,
                2: MafiaRole.MAFIA,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.CITIZEN,
            }
        )
        text = mafia_group.role_text(game, game.room.get_player(1))
        self.assertIn("Sherif", text)
        self.assertIn("Şahar aholisi", text)
        self.assertIn("Tunda harakat qilasiz", text)
        self.assertIn(game.code, text)

    async def test_host_ends_night_and_gets_day_report(self) -> None:
        game = make_game(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.CITIZEN,
            }
        )

        class StubManager:
            def get_game(self, code: str) -> MafiaGame:
                return game

        callback = FakeCallback(1, f"end_night_mafia_{game.code}")
        with patch.object(
            mafia_group, "get_default_manager", return_value=StubManager()
        ):
            await mafia_group.end_mafia_night(callback)

        self.assertEqual(callback.answers[-1][0], "Tun yakunlandi.")
        self.assertIs(game.room.phase, GamePhase.DAY_REPORT)
        self.assertIsNotNone(game.phase_deadline)
        self.assertTrue(
            any(
                "TONG OTDI" in text
                for text in callback.bot.texts_for(game.chat_id)
            )
        )

    async def test_night_sends_kevlar_offers_and_saved_notice(self) -> None:
        game = make_game(
            {
                1: MafiaRole.DON,
                2: MafiaRole.MAFIA,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
                5: MafiaRole.CITIZEN,
            }
        )
        bot = FakeBot()
        await mafia_group.announce_night(bot, game)

        offers = [
            (chat_id, text)
            for chat_id, text, _ in bot.messages
            if "omon qolasizmi" in text
        ]
        self.assertEqual({chat_id for chat_id, _ in offers}, {1, 2, 3, 4, 5})
        self.assertTrue(any("40 tanga" in text for _, text in offers))

        game.room.get_player(4).kevlar_active = True
        game.room.submit_night_action(1, 4)
        resolve_night(game.room)
        await mafia_group.notify_kevlar_saved(bot, game)
        self.assertTrue(
            any(
                chat_id == 4 and "saqlab qoldi" in text
                for chat_id, text, _ in bot.messages
            )
        )

    async def test_finish_awards_winners_once(self) -> None:
        game = make_game(
            {
                1: MafiaRole.DON,
                2: MafiaRole.MAFIA,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
            }
        )
        game.room.submit_night_action(1, 4)
        resolve_night(game.room)
        self.assertIs(game.room.winner, Winner.MAFIA)

        store = EconomyStore(url="", key="", client=None)
        bot = FakeBot()
        with patch.object(mafia_group, "get_economy", return_value=store):
            await mafia_group.announce_finish(bot, game)
            caption = bot.messages[-1][1]
            self.assertIn(f"+{MAFIA_WIN_REWARD} tanga", caption)
            self.assertEqual(
                store.get_user(1).coins, START_COINS + MAFIA_WIN_REWARD
            )
            self.assertEqual(
                store.get_user(2).coins, START_COINS + MAFIA_WIN_REWARD
            )
            self.assertEqual(store.get_user(3).coins, START_COINS)

            await mafia_group.announce_finish(bot, game)
            self.assertEqual(
                store.get_user(1).coins, START_COINS + MAFIA_WIN_REWARD
            )

    async def test_non_host_cannot_end_night(self) -> None:
        game = make_game(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.CITIZEN,
            }
        )

        class StubManager:
            def get_game(self, code: str) -> MafiaGame:
                return game

        callback = FakeCallback(999, f"end_night_mafia_{game.code}")
        with patch.object(
            mafia_group, "get_default_manager", return_value=StubManager()
        ):
            await mafia_group.end_mafia_night(callback)

        self.assertIn("faqat xona egasi", callback.answers[-1][0])
        self.assertIs(game.room.phase, GamePhase.NIGHT)


class GamesCatalogTest(unittest.IsolatedAsyncioTestCase):
    async def test_games_command_lists_both_games(self) -> None:
        message = FakeMessage(chat_type="private")

        await games_catalog.games_command(message)

        text, keyboard = message.answers[0]
        self.assertIn("Bunker", text)
        self.assertIn("Mafiya", text)
        self.assertIn("Josus", text)
        buttons = [row[0] for row in keyboard.inline_keyboard[:3]]
        self.assertEqual(
            [button.text for button in buttons],
            [
                "🛡️ Bunker — /bunker",
                "🕵️ Mafiya — /mafia",
                "🔍 Josus (Spyfall) — /spy",
            ],
        )
        self.assertEqual(
            [button.callback_data for button in buttons],
            [
                games_catalog.BUNKER_CALLBACK,
                games_catalog.MAFIA_CALLBACK,
                games_catalog.SPY_CALLBACK,
            ],
        )

    async def test_games_button_opens_catalog(self) -> None:
        message = FakeMessage(text="🎲 Öyinlar röyxati")

        await games_catalog.games_command(message)

        self.assertIn("Öyinlar", message.answers[0][0])

    async def test_bunker_and_mafia_details_show_group_instructions(self) -> None:
        bunker_callback = FakeCallback(1, games_catalog.BUNKER_CALLBACK)
        await games_catalog.show_bunker(bunker_callback)
        bunker_text = bunker_callback.message.edits[0][0]
        self.assertIn("/bunker", bunker_text)
        self.assertIn("guruh", bunker_text.lower())
        buttons = bunker_callback.message.edits[0][1].inline_keyboard
        self.assertIn("startgroup=true", buttons[0][0].url)
        self.assertEqual(buttons[1][0].callback_data, games_catalog.BACK_CALLBACK)

        mafia_callback = FakeCallback(1, games_catalog.MAFIA_CALLBACK)
        await games_catalog.show_mafia(mafia_callback)
        mafia_text = mafia_callback.message.edits[0][0]
        self.assertIn("/mafia", mafia_text)
        self.assertIn("4 kişi", mafia_text)

    async def test_back_returns_to_catalog(self) -> None:
        callback = FakeCallback(1, games_catalog.BACK_CALLBACK)

        await games_catalog.back_to_catalog(callback)

        text, keyboard = callback.message.edits[0]
        self.assertIn("Öyinlar röyxati", text)
        self.assertEqual(len(keyboard.inline_keyboard), 7)
        labels = [row[0].text for row in keyboard.inline_keyboard]
        self.assertTrue(any("Alias" in label for label in labels))
        self.assertTrue(any("turnirlar" in label.lower() for label in labels))


class MafiaImageTest(unittest.TestCase):
    """Rasm fayllari va ularning URL mosligi."""

    def test_every_role_has_existing_image(self) -> None:
        for role in MafiaRole:
            path = role_image_path(role)
            self.assertTrue(path.is_file(), f"{role.value}: {path}")
            self.assertEqual(
                role_image_url(role), f"/assets/images/mafia/{path.name}"
            )

    def test_scene_and_victory_images_exist(self) -> None:
        for name in ("cover.png", "night.png", "day.png", "eliminated.jpg"):
            self.assertTrue(image_path(name).is_file(), name)
        for winner in Winner:
            self.assertTrue(victory_image_path(winner).is_file(), winner)

    def test_special_role_mappings(self) -> None:
        self.assertEqual(role_image_path(MafiaRole.MAFIA).name, "mobster.png")
        self.assertEqual(
            role_image_path(MafiaRole.AMNESIAC).name, "citizen.png"
        )


class RouterRegistrationTest(unittest.TestCase):
    def test_routers_and_commands_are_registered(self) -> None:
        included: list[str | None] = []

        class RecordingDispatcher:
            """Global routerlarni bog'lamay, faqat ulanish tartibini yozadi."""

            def __init__(self, storage=None) -> None:
                self.storage = storage

            def include_router(self, router) -> None:
                included.append(router.name)

        with patch.object(bot_main, "Dispatcher", RecordingDispatcher):
            bot_main.build_dispatcher()

        names = included

        self.assertIn("mafia_group", names)
        self.assertIn("games_catalog", names)
        self.assertLess(
            names.index("mafia_group"),
            names.index("bunker_group"),
            "Mafiya callbacklari Bunker'dan oldin ushlanishi kerak",
        )
        commands = {command.command for command in BOT_COMMANDS}
        self.assertIn("mafia", commands)
        self.assertIn("games", commands)


if __name__ == "__main__":
    unittest.main()
