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

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

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
                ["💳 Karta raqamini sozlaş"],
                ["📥 Kutilayotgan tölovlar (Çeklar)"],
                ["👥 Öyinçilar"],
                ["➕ Foydalanuvçiga tanga beriş"],
                ["🎟 Promo kod yaratiş"],
                ["🏆 Turnir sozlamalari"],
                ["📢 Hammaga xabar (Broadcast)"],
                ["📥 Bazadan nusxa oliş (Backup)"],
                ["📤 Bazani tiklaş (Restore)"],
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
                "admin_players",
                "admin_give",
                "admin_promo",
                "admin_tournament",
                "admin_broadcast",
                "admin_backup",
                "admin_restore",
            ],
        )

    def test_tournament_settings_text_and_keyboard(self) -> None:
        from datetime import datetime, timedelta, timezone

        from core.shop import ShopStore, set_shop_store
        from core.tournaments import TournamentStore, set_tournament_store

        economy = EconomyStore(url="", key="", client=None)
        shop = ShopStore(economy=economy)
        set_shop_store(shop)
        store = TournamentStore(economy=economy, shop=shop)
        set_tournament_store(store)
        self.addCleanup(set_tournament_store, None)
        self.addCleanup(set_shop_store, None)
        tournament = store.create(
            "bunker",
            (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            prize_pool=900,
            max_players=16,
        )
        text = admin.tournament_status_text(tournament)
        self.assertIn("Faol Turnir Holati", text)
        self.assertIn("Bunker", text)
        self.assertIn("900", text)
        self.assertIn("0 / 16", text)
        callbacks = [
            button.callback_data
            for row in admin.tournament_keyboard(tournament).inline_keyboard
            for button in row
        ]
        self.assertIn(admin.TOUR_MAX_CALLBACK, callbacks)
        self.assertIn(admin.TOUR_TIME_CALLBACK, callbacks)
        self.assertIn(admin.TOUR_PRIZE_CALLBACK, callbacks)
        self.assertIn(admin.TOUR_GAME_CALLBACK, callbacks)
        self.assertIn(admin.TOUR_ROOM_CALLBACK, callbacks)
        self.assertIn(admin.TOUR_START_CALLBACK, callbacks)

        with_room = store.set_room_link(
            tournament.id, "https://t.me/+TurnirXona"
        )
        self.assertIn("https://t.me/+TurnirXona", admin.tournament_status_text(with_room))
        callbacks = [
            button.callback_data
            for row in admin.tournament_keyboard(with_room).inline_keyboard
            for button in row
        ]
        self.assertIn(admin.TOUR_ROOM_CLEAR_CALLBACK, callbacks)

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
            "Hozirça kutilayotgan tölovlar yöq", callback.bot.messages[-1][1]
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
            self.assertIn("Promo kod yaratiş", callback.bot.messages[-1][1])

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

    def test_players_list_paginates_and_opens_search(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        for index in range(1, 13):
            store.ensure_user(88100 + index, f"user{index}", f"User {index}")
        callback = FakeCallback()
        state = FakeState()
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(admin.show_players(callback, state))
        text, keyboard = callback.bot.messages[-1][1], callback.bot.messages[-1][2]
        self.assertIn("Oxirgi röyxatdan ötgan öyinçilar", text)
        self.assertIn("@user12", text)
        self.assertIn("Level 1", text)
        self.assertIn("Sahifa: <b>1/2</b>", text)
        callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertIn("admin_players_page_2", callbacks)
        self.assertIn(admin.PLAYERS_SEARCH_CALLBACK, callbacks)

        page_callback = FakeCallback(data="admin_players_page_2")
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(admin.paginate_players(page_callback))
        page_text = page_callback.bot.messages[-1][1]
        self.assertIn("Sahifa: <b>2/2</b>", page_text)
        self.assertIn("@user2", page_text)

    def test_search_shows_full_profile_and_coin_buttons(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        store.ensure_user(88200, "ali", "Ali Valiyev")
        state = FakeState()
        message = FakeMessage(text="88200")
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(admin.search_player(message, state))
        self.assertIsNone(state.state)
        self.assertIn("Öyinçi profili", message.answers[-1])
        self.assertIn("Ali Valiyev", message.answers[-1])
        self.assertIn("Balans", message.answers[-1])
        self.assertIn("Inventar", message.answers[-1])
        callbacks = [
            button.callback_data
            for row in message.markups[-1].inline_keyboard
            for button in row
        ]
        self.assertIn("admin_player_add_88200", callbacks)
        self.assertIn("admin_player_sub_88200", callbacks)

    def test_profile_buttons_change_player_balance(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        store.ensure_user(88300, "ali", "Ali")
        state = FakeState()
        callback = FakeCallback(data="admin_player_add_88300")
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(admin.ask_add_player_coins(callback, state))
            self.assertIs(state.state, admin.AdminStates.waiting_player_amount)
            self.assertEqual(state.data["player_id"], 88300)
            self.assertIn("Tanga qöşiş", callback.bot.messages[-1][1])

            message = FakeMessage(text="250")
            asyncio.run(admin.apply_player_coins(message, state))
        self.assertEqual(store.get_user(88300).coins, START_COINS + 250)
        self.assertIn("+250", message.answers[-1])
        self.assertIsNone(state.state)

        callback = FakeCallback(data="admin_player_sub_88300")
        with patch.object(admin, "get_economy", return_value=store):
            asyncio.run(admin.ask_subtract_player_coins(callback, state))
            message = FakeMessage(text="50")
            asyncio.run(admin.apply_player_coins(message, state))
        self.assertEqual(store.get_user(88300).coins, START_COINS + 200)
        self.assertIn("−50", message.answers[-1])

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
