"""Do'kon, karta matni va admin panel handlerlari testlari."""

import asyncio
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiogram.filters import CommandObject

from bot.config import get_config
from bot.handlers import admin, shop
from core.economy import START_COINS, EconomyStore, get_economy
from core.settings import SettingsStore
from core.shop import InventoryEntry, ShopStore


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
            [
                "shop_pack_500",
                "shop_pack_1500",
                "shop_pack_4000",
                "shop_home",
                "shop_cancel",
            ],
        )
        self.assertIn("10 000 söm", keyboard.inline_keyboard[0][0].text)
        self.assertIn("25 000 söm", keyboard.inline_keyboard[1][0].text)
        self.assertIn("60 000 söm", keyboard.inline_keyboard[2][0].text)

    def test_payment_text_contains_card_and_price(self) -> None:
        text = shop.payment_text(1500, 25000)
        self.assertIn("9860 0000 0000 0000", text)
        self.assertIn("Falonchi Pistonchiyev", text)
        self.assertIn("25 000 söm", text)
        self.assertIn("çek", text.lower())

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


class FakeCallback:
    """Inline tugma bosilishini imitatsiya qiladi."""

    def __init__(self, data: str, user_id: int = 88001) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, username="player")
        self.message = None
        self.bot = FakeBot()
        self.answers: list[str] = []

    async def answer(self, text: str | None = None, **kwargs) -> None:
        self.answers.append(text or "")


class MegaStoreTest(unittest.TestCase):
    """Ikki bölumli do'kon, xarid va omad ğildiragi."""

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
        self.economy = get_economy()
        self.store = ShopStore(economy=self.economy)
        store_patch = patch.object(shop, "get_shop_store", return_value=self.store)
        store_patch.start()
        self.addCleanup(store_patch.stop)

    def test_home_menu_has_two_sections(self) -> None:
        keyboard = shop.shop_keyboard()
        self.assertEqual(len(keyboard.inline_keyboard), 2)
        self.assertIn("Tangalar xarid qiliş", keyboard.inline_keyboard[0][0].text)
        self.assertIn("Buyumlar", keyboard.inline_keyboard[1][0].text)
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "shopsection_pay")
        self.assertEqual(keyboard.inline_keyboard[1][0].callback_data, "shopsection_items")
        self.assertIn("Kerakli bölumni tanlang", shop.shop_text())

    def test_items_menu_lists_every_section(self) -> None:
        callbacks = [row[0].callback_data for row in shop.items_keyboard().inline_keyboard]
        self.assertEqual(
            callbacks,
            [
                "shopsec_BOOSTER",
                "shopsec_FRAME",
                "shopsec_TITLE",
                "shopsec_SPECIAL",
                "shop_home",
            ],
        )

    def test_section_view_lists_prices_and_buy_buttons(self) -> None:
        text = shop.section_text(88003, "FRAME")
        self.assertIn("Ramkalar", text)
        self.assertIn("Oltin", text)
        self.assertIn("150 tanga", text)
        self.assertIn("Olovli Ajdaho", text)
        callbacks = [
            row[0].callback_data for row in shop.section_keyboard("FRAME").inline_keyboard
        ]
        self.assertIn("shopbuy_frame_gold", callbacks)
        self.assertIn("shopbuy_frame_diamond", callbacks)
        text = shop.section_text(88003, "TITLE")
        self.assertIn("Mafiya Otaxoni", text)
        title_callbacks = [
            row[0].callback_data for row in shop.section_keyboard("TITLE").inline_keyboard
        ]
        self.assertIn("shopbuy_title_don", title_callbacks)
        self.assertEqual(callbacks[-1], "shopsection_items")

    def test_spin_section_has_wheel_button(self) -> None:
        callbacks = [
            row[0].callback_data for row in shop.section_keyboard("SPECIAL").inline_keyboard
        ]
        self.assertIn("shopbuy_spin_extra", callbacks)
        self.assertIn("shop_spin_wheel", callbacks)

    def test_buy_button_spends_coins_and_adds_inventory(self) -> None:
        self.economy.add_coins(88001, 400)
        before = self.economy.get_user(88001).coins
        callback = FakeCallback("shopbuy_frame_gold")

        asyncio.run(shop.shop_buy_item(callback))

        self.assertEqual(self.economy.get_user(88001).coins, before - 150)
        self.assertEqual(self.store.entry(88001, "frame_gold").quantity, 1)
        self.assertIn("sotib olindi", callback.answers[-1])
        self.assertIn("tanga", callback.bot.messages[-1][1])
        self.assertIn("Oltin", callback.bot.messages[-1][1])

    def test_buy_without_coins_shows_warning(self) -> None:
        self.economy.spend_coins(88004, self.economy.get_user(88004).coins)
        callback = FakeCallback("shopbuy_frame_neon", user_id=88004)

        asyncio.run(shop.shop_buy_item(callback))

        self.assertIn("yetarli tanga yöq", callback.answers[-1])
        self.assertEqual(self.store.entry(88004, "frame_neon").quantity, 0)

    def test_free_spin_reward_and_second_spin_costs_coins(self) -> None:
        callback = FakeCallback("shop_spin_wheel", user_id=88005)
        asyncio.run(shop.shop_spin_wheel(callback))
        self.assertIn("🎰", callback.answers[-1])
        self.assertIn("bepul aylantiriş", callback.answers[-1])

        after_free = self.economy.get_user(88005).coins
        asyncio.run(shop.shop_spin_wheel(callback))
        # Ikkinchi aylantiriş bepul emas: 20 tanga yechiladi yoki çipta ketadi.
        self.assertLessEqual(self.economy.get_user(88005).coins, after_free + 500)
        self.assertFalse(self.store.spin_status(88005)["free"])

    def test_legacy_frame_slug_maps_to_current_catalog(self) -> None:
        """Eski `frame_cyber_glitch` yozuvi joriy ramka sifatida taqiladi."""
        self.store._save_entry(
            88010, InventoryEntry("frame_cyber_glitch", 1, True)
        )
        self.assertEqual(self.store.equipped(88010)["frame"], "frame_cyber")
        self.assertTrue(self.store.entry(88010, "frame_cyber").is_equipped)
        self.assertEqual(
            [entry.item_slug for entry in self.store.inventory(88010)],
            ["frame_cyber"],
        )

    def test_equipping_current_frame_clears_legacy_flag(self) -> None:
        self.economy.add_coins(88011, 600)
        self.store._save_entry(
            88011, InventoryEntry("frame_cyber_glitch", 1, True)
        )
        self.store.buy(88011, "frame_diamond")
        self.store.equip(88011, "frame_diamond")
        self.assertEqual(self.store.equipped(88011)["frame"], "frame_diamond")
        self.assertFalse(self.store.entry(88011, "frame_cyber").is_equipped)


class EquipResilienceTest(unittest.TestCase):
    """Supabase yozuvi yiqilsa ham taqish jarayoni davom etishini tekshiradi."""

    def test_equip_keeps_new_frame_when_inventory_write_fails(self) -> None:
        class FailingQuery:
            def __init__(self, table: str) -> None:
                self.table = table
                self.operation = "select"

            def select(self, *_args, **_kwargs):
                self.operation = "select"
                return self

            def eq(self, *_args, **_kwargs):
                return self

            def update(self, *_args, **_kwargs):
                self.operation = "update"
                return self

            def upsert(self, *_args, **_kwargs):
                self.operation = "upsert"
                return self

            def execute(self):
                if self.operation == "select" and self.table == "user_inventory":
                    return SimpleNamespace(
                        data=[
                            {
                                "user_id": 777,
                                "item_slug": "frame_fire",
                                "quantity": 1,
                                "is_equipped": True,
                            },
                            {
                                "user_id": 777,
                                "item_slug": "frame_gold",
                                "quantity": 1,
                                "is_equipped": False,
                            },
                        ]
                    )
                if self.operation == "upsert":
                    raise RuntimeError("supabase ishlamayapti")
                return SimpleNamespace(data=[])

        class FailingClient:
            def table(self, name: str):
                return FailingQuery(name)

        store = ShopStore(client=FailingClient())
        result = store.equip(777, "frame_gold")
        self.assertTrue(result["ok"])
        self.assertEqual(result["equipped"]["frame"], "frame_gold")
        self.assertEqual(store.equipped(777)["frame"], "frame_gold")
        self.assertFalse(store.entry(777, "frame_fire").is_equipped)
        self.assertTrue(store.entry(777, "frame_gold").is_equipped)


class CosmeticsUiWiringTest(unittest.TestCase):
    """Mini App ramka/unvon oqimi backend bilan bog'langanini tekshiradi."""

    def test_equip_contract_is_wired(self) -> None:
        html = (
            Path(__file__).resolve().parent.parent / "webapp" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn("function equipItem(itemId, itemType)", html)
        self.assertIn('window.localStorage.setItem("equipped_frame"', html)
        self.assertIn('window.localStorage.setItem("equipped_title"', html)
        self.assertIn("/api/profile/equip", html)
        self.assertIn(".avatar-frame.frame-cyber", html)
        self.assertIn(".avatar-frame.frame-diamond", html)
        self.assertIn(".avatar-frame.frame-gold", html)
        self.assertIn("Taqilgan ✅", html)
        self.assertIn("title_slug", html)
        self.assertIn("text-white font-extrabold text-sm sm:text-base", html)
        self.assertIn("text-purple-200 text-xs font-medium", html)
        self.assertIn("5 ta öyin mavjud", html)
        self.assertIn("Faol (5)", html)
        self.assertIn("hub-main pb-28", html)
        self.assertIn("card-glass overflow-hidden w-full p-4 join-card", html)
        self.assertIn("Sinxronlash keyinroq bajariladi", html)


if __name__ == "__main__":
    unittest.main()
