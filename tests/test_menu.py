"""Doimiy pastki menyu klaviaturasi va tugma handlerlari testlari."""

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiogram.types import ReplyKeyboardMarkup

from aiogram.exceptions import TelegramBadRequest

from bot.config import get_config
from bot.handlers import admin, common, leaderboard, menu, profile
from bot.keyboards import main_menu
from core.economy import START_COINS, EconomyStore


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append((chat_id, text))


class FakeMessage:
    def __init__(
        self,
        user_id: int = 424242,
        text: str = "",
        chat_type: str = "private",
    ) -> None:
        self.from_user = SimpleNamespace(
            id=user_id, username="ali", full_name="Ali Valiyev"
        )
        self.chat = SimpleNamespace(id=user_id, type=chat_type)
        self.text = text
        self.bot = FakeBot()
        self.answers: list[str] = []
        self.markups: list[object] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)
        self.markups.append(kwargs.get("reply_markup"))

    async def reply(self, text: str, **kwargs) -> None:
        await self.answer(text, **kwargs)


class FakeState:
    def __init__(self) -> None:
        self.cleared = False

    async def clear(self) -> None:
        self.cleared = True


class MenuTestCase(unittest.TestCase):
    """Har bir test uchun `.env` o'rniga xavfsiz muhit beradi."""

    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "BOT_TOKEN": "123456:TEST",
                "ADMIN_ID": "424242",
                "CARD_NUMBER": "9860 0000 0000 0000",
                "CARD_HOLDER": "Falonchi Pistonchiyev",
                "SUPABASE_URL": "",
                "SUPABASE_KEY": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        get_config.cache_clear()
        self.addCleanup(get_config.cache_clear)


class MainMenuKeyboardTest(MenuTestCase):
    def test_menu_is_persistent_two_columns(self) -> None:
        markup = main_menu.build_main_menu()
        rows = [[button.text for button in row] for row in markup.keyboard]
        self.assertEqual(rows[0], ["🎮 Tezkor öyin", "📋 Öyinlar"])
        self.assertEqual(rows[1], ["🎯 Missiyalar", "🎁 Kunlik bonus"])
        self.assertEqual(rows[2], ["🛍️ Dökon", "🏆 Turnirlar"])
        self.assertEqual(rows[3], ["👤 Profilim", "👑 Reyting"])
        self.assertEqual(rows[4], ["🎟️ Promo kod"])
        self.assertEqual(rows[5], ["🌐 Tilni özgartiriş", "👥 Döstlar"])
        self.assertEqual(rows[6], ["🌐 Mini App (Portal)"])
        self.assertEqual(len(rows), 7)
        self.assertTrue(markup.resize_keyboard)
        self.assertTrue(markup.is_persistent)
        for row in markup.keyboard[2:4]:
            self.assertEqual(len(row), 2)
        self.assertEqual(len(markup.keyboard[4]), 1)
        self.assertEqual(len(markup.keyboard[5]), 2)
        self.assertEqual(len(markup.keyboard[6]), 1)

    def test_games_button_opens_mini_app(self) -> None:
        markup = main_menu.build_main_menu()
        games = markup.keyboard[6][0]
        self.assertIsNotNone(games.web_app)
        self.assertEqual(games.web_app.url, get_config().mini_app_url)

    def test_web_app_button_can_be_disabled(self) -> None:
        # Telegram noto'g'ri HTTPS manzilni rad etadi: zaxira menyuda oddiy tugma.
        markup = main_menu.build_main_menu(include_web_app=False)
        self.assertIsNone(markup.keyboard[6][0].web_app)
        self.assertEqual(markup.keyboard[6][0].text, "🌐 Mini App (Portal)")

    def test_admin_button_is_only_for_admins(self) -> None:
        for_admin = main_menu.build_main_menu(is_admin=True)
        texts = [button.text for button in for_admin.keyboard[6]]
        self.assertEqual(texts, ["👑 Admin panel"])
        self.assertEqual(len(for_admin.keyboard), 8)
        # Portal eng oxirgi qatorda qoladi.
        self.assertEqual(
            [button.text for button in for_admin.keyboard[-1]],
            ["🌐 Mini App (Portal)"],
        )

        for_player = main_menu.build_main_menu(is_admin=False)
        self.assertNotIn(
            "👑 Admin panel",
            [button.text for row in for_player.keyboard for button in row],
        )


class MenuHandlerTest(MenuTestCase):
    def test_start_shows_persistent_menu(self) -> None:
        message = FakeMessage()
        asyncio.run(common.start_command(message))
        markup = message.markups[-1]
        self.assertIsInstance(markup, ReplyKeyboardMarkup)
        self.assertTrue(markup.is_persistent)
        self.assertIn("Salom", message.answers[-1])

    def test_start_menu_includes_admin_button_for_admin(self) -> None:
        message = FakeMessage()
        asyncio.run(common.start_command(message))
        texts = [button.text for row in message.markups[-1].keyboard for button in row]
        self.assertIn("👑 Admin panel", texts)

    def test_shop_button_opens_shop(self) -> None:
        message = FakeMessage(text=main_menu.SHOP_BUTTON)
        state = FakeState()
        asyncio.run(menu.menu_shop(message, state))
        self.assertTrue(state.cleared)
        callbacks = [
            row[0].callback_data for row in message.markups[-1].inline_keyboard
        ]
        self.assertEqual(
            callbacks,
            ["shopsection_pay", "shopsection_items"],
        )

    def test_profile_button_shows_profile_card(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        store.add_coins(90001, 500)
        store.record_finished_game("BNK900", [90001], [90001])
        message = FakeMessage(user_id=90001)
        with patch.object(profile, "get_economy", return_value=store):
            asyncio.run(profile.show_profile(message))
        answer = message.answers[-1]
        self.assertIn("Mening profilim", answer)
        self.assertIn(str(START_COINS + 500), answer)
        self.assertIn("90001", answer)
        self.assertIn("Reyting", answer)
        self.assertIn("1 050", answer)

    def test_profile_creates_missing_user_with_bonus(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        message = FakeMessage(user_id=90009)
        with patch.object(profile, "get_economy", return_value=store):
            asyncio.run(profile.show_profile(message))
        answer = message.answers[-1]
        self.assertIn("Mening profilim", answer)
        self.assertIn(f"{START_COINS}", answer)
        self.assertIn("1 000", answer)  # yangi o'yinchining reytingi
        self.assertEqual(store.get_user(90009).coins, START_COINS)

    def test_leaderboard_orders_by_wins(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        store.record_finished_game("BNK901", [90002, 90003], [90002])
        store.record_finished_game("BNK902", [90002, 90003], [90002, 90003])
        message = FakeMessage(user_id=90003)
        with patch.object(leaderboard, "get_economy", return_value=store):
            asyncio.run(leaderboard.show_leaderboard(message))
        answer = message.answers[-1]
        self.assertIn("Reyting va Top", answer)
        self.assertLess(answer.index("90002"), answer.index("90003"))
        self.assertIn("Sizning reytingingiz", answer)

    def test_leaderboard_shows_friendly_empty_message(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        message = FakeMessage(user_id=90010)
        with patch.object(leaderboard, "get_economy", return_value=store):
            asyncio.run(leaderboard.show_leaderboard(message))
        answer = message.answers[-1]
        self.assertIn("Hozirça reyting böş", answer)

    def test_game_list_button_shows_every_game(self) -> None:
        message = FakeMessage(text=main_menu.GAME_LIST_BUTTON)
        asyncio.run(menu.menu_game_list(message))
        answer = message.answers[-1]
        self.assertIn("Öyinlar röyxati", answer)
        for name in ("Bunker", "Mafiya", "Josus", "Alias", "Bomba"):
            self.assertIn(name, answer)
        self.assertIn("guruh", answer.lower())
        keyboard = message.markups[-1].inline_keyboard
        self.assertEqual(len(keyboard), 7)
        self.assertIn("startgroup=true", keyboard[-1][0].url)

    def test_missions_button_shows_tasks(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        message = FakeMessage(text=main_menu.MISSIONS_BUTTON)
        with patch.object(menu.missions, "get_economy", return_value=store):
            asyncio.run(menu.menu_missions(message))
        answer = message.answers[-1]
        self.assertIn("Missiyalar", answer)
        self.assertIn("5", answer)

    def test_rules_sections_cover_all_games(self) -> None:
        message = FakeMessage(text=main_menu.RULES_BUTTON)
        asyncio.run(common.menu_rules(message))
        text = message.answers[-1]
        keyboard = message.markups[-1].inline_keyboard
        buttons = [button.text for row in keyboard for button in row]
        self.assertTrue(any("Bunker" in item for item in buttons))
        self.assertTrue(any("Mafiya" in item for item in buttons))
        self.assertTrue(any("Josus" in item for item in buttons))
        self.assertTrue(any("Alias" in item for item in buttons))
        self.assertTrue(any("Tangalar" in item for item in buttons))
        self.assertEqual(
            [button.callback_data for row in keyboard for button in row],
            [
                common.RULES_BUNKER,
                common.RULES_MAFIA,
                common.RULES_SPY,
                common.RULES_ALIAS,
                common.RULES_ECONOMY,
            ],
        )
        self.assertIn("Qoidalar", text)

    def test_rules_button_shows_rules(self) -> None:
        message = FakeMessage(text=main_menu.RULES_BUTTON)
        asyncio.run(common.menu_rules(message))
        self.assertIn("Qoidalar", message.answers[-1])

    def test_help_command_shows_rules_menu(self) -> None:
        message = FakeMessage(text="/help")
        asyncio.run(common.menu_rules(message))
        self.assertIn("Qoidalar", message.answers[-1])

    def test_start_falls_back_when_web_app_button_is_rejected(self) -> None:
        class StrictMessage(FakeMessage):
            async def answer(self, text: str, **kwargs) -> None:
                markup = kwargs.get("reply_markup")
                rows = getattr(markup, "keyboard", None)
                if rows and rows[-1][0].web_app is not None:
                    raise TelegramBadRequest(
                        method=None, message="BUTTON_TYPE_INVALID"
                    )
                await super().answer(text, **kwargs)

        message = StrictMessage()
        asyncio.run(common.start_command(message, None))
        self.assertIn("Salom", message.answers[-1])
        self.assertIsNone(message.markups[-1].keyboard[-1][0].web_app)

    def test_games_button_sends_web_app_with_identity(self) -> None:
        config = SimpleNamespace(
            mini_app_url="https://revilend.games", bot_username="revilend_gamesbot"
        )
        message = FakeMessage(user_id=424242)
        with patch.object(menu, "get_config", return_value=config):
            asyncio.run(menu.menu_games(message))
        markup = message.markups[-2]
        button = markup.inline_keyboard[0][0]
        self.assertEqual(button.text, "🚀 Öyinlar portaliga kiriş")
        self.assertIn("uid=424242", button.web_app.url)
        # Mini App initData'siz ochilsa ham kiradigan kod yuboriladi.
        self.assertIn("Kiriş kodingiz", message.answers[-1])
        login_button = message.markups[-1].inline_keyboard[0][0]
        self.assertEqual(login_button.text, "🎮 Profilingiz bilan kiriş")
        self.assertIn("uid=424242", login_button.web_app.url)

    def test_start_login_sends_code_and_automatic_button(self) -> None:
        config = SimpleNamespace(
            mini_app_url="https://revilend.games",
            bot_username="revilend_gamesbot",
            admin_id=0,
        )
        store = EconomyStore(url="", key="", client=None)
        message = FakeMessage(user_id=424250)
        with patch.object(common, "get_config", return_value=config), patch.object(
            common, "get_economy", return_value=store
        ), patch.object(main_menu, "get_config", return_value=config):
            asyncio.run(
                common.start_command(message, SimpleNamespace(args="login"))
            )
        answer = message.answers[-1]
        self.assertIn("Profilingizga kiriş tayyor", answer)
        self.assertIn("Kiriş kodingiz", answer)
        button = message.markups[-1].inline_keyboard[0][0]
        self.assertEqual(button.text, "🎮 Profilingiz bilan kiriş")
        self.assertIn("uid=424250", button.web_app.url)
        self.assertTrue(store.has_user(424250))

    def test_login_command_creates_code(self) -> None:
        config = SimpleNamespace(
            mini_app_url="https://revilend.games",
            bot_username="revilend_gamesbot",
            admin_id=0,
        )
        store = EconomyStore(url="", key="", client=None)
        message = FakeMessage(user_id=424251)
        with patch.object(common, "get_config", return_value=config), patch.object(
            common, "get_economy", return_value=store
        ), patch.object(main_menu, "get_config", return_value=config):
            asyncio.run(common.login_command(message))
        self.assertIn("Kiriş kodingiz", message.answers[-1])
        button = message.markups[-1].inline_keyboard[0][0]
        self.assertEqual(button.text, "🎮 Profilingiz bilan kiriş")
        self.assertIn("uid=424251", button.web_app.url)

    def test_admin_button_opens_panel_for_admin(self) -> None:
        message = FakeMessage()
        asyncio.run(menu.menu_admin(message))
        self.assertIn("Admin panel", message.answers[-1])

    def test_admin_button_is_rejected_for_players(self) -> None:
        message = FakeMessage(user_id=999)
        asyncio.run(menu.menu_admin(message))
        self.assertIn("faqat administrator", message.answers[-1])


class MiniAppUrlTest(unittest.TestCase):
    """Pastki menyu web_app havolasi foydalanuvchi ma'lumotini olib yurishi."""

    def test_url_contains_user_identity(self) -> None:
        url = main_menu.mini_app_url_for(
            "https://revilend.games",
            user_id=42,
            username="ali_dev",
            full_name="Ali Valiyev",
        )
        self.assertTrue(url.startswith("https://revilend.games?"))
        self.assertIn("uid=42", url)
        self.assertIn("uname=ali_dev", url)
        self.assertIn("fname=Ali%20Valiyev", url)

    def test_existing_query_is_preserved(self) -> None:
        url = main_menu.mini_app_url_for("https://x.dev/app?lang=uz", user_id=7)
        self.assertIn("?lang=uz&uid=7", url)

    def test_url_without_user_is_unchanged(self) -> None:
        self.assertEqual(
            main_menu.mini_app_url_for("https://revilend.games"), "https://revilend.games"
        )

    def test_keyboard_web_app_button_has_identity(self) -> None:
        config = SimpleNamespace(mini_app_url="https://revilend.games")
        with patch.object(main_menu, "get_config", return_value=config):
            markup = main_menu.build_main_menu(
                user_id=555, username="vali", full_name="Vali Karimov"
            )
        button = markup.keyboard[6][0]
        self.assertIsNotNone(button.web_app)
        self.assertIn("uid=555", button.web_app.url)
        self.assertIn("uname=vali", button.web_app.url)

    def test_start_menu_carries_user_id(self) -> None:
        config = SimpleNamespace(mini_app_url="https://revilend.games", admin_id=0)
        message = FakeMessage(user_id=424242)
        with patch.object(common, "get_config", return_value=config), patch.object(
            main_menu, "get_config", return_value=config
        ), patch.object(admin, "get_config", return_value=config):
            asyncio.run(common.start_command(message, None))
        button = message.markups[-1].keyboard[-1][0]
        self.assertIn("uid=424242", button.web_app.url)



if __name__ == "__main__":
    unittest.main()
