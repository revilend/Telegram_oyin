"""Mega Store API: buyumlar, xarid, omad ğildiragi va jihozlash testlari."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.server import app
from core.economy import START_COINS, get_economy
from core.rate_limit import reset_rate_limits
from core.shop import InventoryEntry, ShopStore, get_shop_store, set_shop_store


class ShopApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "ALLOW_GUEST_AUTH": "true",
                "SUPABASE_URL": "",
                "SUPABASE_KEY": "",
                "BOT_TOKEN": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.economy = get_economy()
        set_shop_store(ShopStore(economy=self.economy))
        self.addCleanup(set_shop_store, None)
        reset_rate_limits()
        self.addCleanup(reset_rate_limits)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def _coins(self, user_id: int) -> int:
        return self.economy.get_user(user_id).coins

    def test_items_endpoint_groups_all_sections(self) -> None:
        response = self.client.get("/api/shop/items")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        sections = [section["key"] for section in payload["sections"]]
        self.assertEqual(
            sections, ["BOOSTER", "FRAME", "TITLE", "SPECIAL"]
        )
        cosmetic = next(
            section for section in payload["sections"] if section["key"] == "FRAME"
        )
        slugs = [item["slug"] for item in cosmetic["items"]]
        self.assertIn("frame_gold", slugs)
        titles = next(
            section for section in payload["sections"] if section["key"] == "TITLE"
        )
        self.assertIn("title_don", [item["slug"] for item in titles["items"]])
        specials = next(
            section for section in payload["sections"] if section["key"] == "SPECIAL"
        )
        special_slugs = [item["slug"] for item in specials["items"]]
        self.assertIn("lootbox", special_slugs)
        self.assertIn("spin_extra", special_slugs)
        self.assertEqual(payload["wheel"]["cost"], 20)
        self.assertGreaterEqual(len(payload["wheel"]["segments"]), 8)
        self.assertIn("sections", payload)

    def test_buy_adds_inventory_and_records_transaction(self) -> None:
        store = get_shop_store()
        before = self._coins(97011)

        response = self.client.post(
            "/api/shop/buy",
            json={"user_id": 97011, "item_slug": "booster_double_vote"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["coins"], before - 15)
        self.assertEqual(payload["quantity"], 1)
        inventory = {entry["slug"]: entry for entry in payload["inventory"]}
        self.assertEqual(inventory["booster_double_vote"]["quantity"], 1)
        self.assertEqual(len(store.transactions()), 1)
        transaction = store.transactions()[0]
        self.assertEqual(transaction["item_id"], "booster_double_vote")
        self.assertEqual(transaction["item_title"], "2x Ovoz")
        self.assertEqual(transaction["price_coins"], 15)

        self.client.post(
            "/api/shop/buy",
            json={"user_id": 97011, "item_slug": "booster_double_vote"},
        )
        self.assertEqual(store.entry(97011, "booster_double_vote").quantity, 2)

    def test_buy_without_coins_returns_402(self) -> None:
        self.economy.spend_coins(97012, self._coins(97012))
        response = self.client.post(
            "/api/shop/buy",
            json={"user_id": 97012, "item_slug": "frame_neon"},
        )
        self.assertEqual(response.status_code, 402)
        self.assertIn("yetarli tanga", response.json()["detail"])
        self.assertEqual(get_shop_store().entry(97012, "frame_neon").quantity, 0)

    def test_unknown_item_returns_404(self) -> None:
        response = self.client.post(
            "/api/shop/buy",
            json={"user_id": 97013, "item_slug": "yoq_buyum"},
        )
        self.assertEqual(response.status_code, 404)

    def test_spin_is_free_once_then_requires_coins(self) -> None:
        first = self.client.post("/api/spin/wheel", json={"user_id": 97014})
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["free"])
        self.assertFalse(first.json()["spin"]["free"])
        self.assertGreaterEqual(first.json()["coins"], START_COINS)

        reset_rate_limits()
        second = self.client.post("/api/spin/wheel", json={"user_id": 97014})
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["free"])

        self.economy.spend_coins(97014, self._coins(97014))
        reset_rate_limits()
        blocked = self.client.post("/api/spin/wheel", json={"user_id": 97014})
        self.assertEqual(blocked.status_code, 402)
        self.assertIn("Çipta yöq", blocked.json()["detail"])

    def test_spin_uses_ticket_when_balance_is_empty(self) -> None:
        # Bepul aylantirişni avval işlatib qöyamiz.
        self.client.post("/api/spin/wheel", json={"user_id": 97015})
        self.economy.spend_coins(97015, self._coins(97015))
        store = get_shop_store()
        store._save_entry(
            97015, InventoryEntry(item_slug="spin_extra", quantity=1)
        )
        reset_rate_limits()
        response = self.client.post("/api/spin/wheel", json={"user_id": 97015})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ticket_used"])
        self.assertEqual(store.entry(97015, "spin_extra").quantity, 0)

    def test_equip_frame_and_title_reflected_in_profile(self) -> None:
        self.economy.add_coins(97016, 600)
        for slug in ("frame_gold", "title_don"):
            bought = self.client.post(
                "/api/shop/buy",
                json={"user_id": 97016, "item_slug": slug},
            )
            self.assertEqual(bought.status_code, 200)

        frame = self.client.post(
            "/api/profile/equip",
            json={"user_id": 97016, "item_slug": "frame_gold"},
        )
        self.assertEqual(frame.status_code, 200)
        self.assertEqual(frame.json()["equipped"]["frame"], "frame_gold")

        title = self.client.post(
            "/api/profile/equip",
            json={"user_id": 97016, "item_slug": "title_don"},
        )
        self.assertEqual(title.json()["equipped"]["title"], "title_don")

        me = self.client.get("/api/me?user_id=97016")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["equipped"]["frame"], "frame_gold")
        self.assertEqual(me.json()["equipped"]["title"], "title_don")
        self.assertIn("spin", me.json())

        removed = self.client.post(
            "/api/profile/equip",
            json={"user_id": 97016, "item_slug": "frame_gold", "equip": False},
        )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json()["equipped"]["frame"], "")

    def test_equip_requires_ownership(self) -> None:
        response = self.client.post(
            "/api/profile/equip",
            json={"user_id": 97017, "item_slug": "frame_fire"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("sotib oling", response.json()["detail"])

    def test_equip_rejects_booster(self) -> None:
        self.client.post(
            "/api/shop/buy",
            json={"user_id": 97018, "item_slug": "booster_shield"},
        )
        response = self.client.post(
            "/api/profile/equip",
            json={"user_id": 97018, "item_slug": "booster_shield"},
        )
        self.assertEqual(response.status_code, 400)

    def test_equip_alias_endpoint_accepts_item_id_and_type(self) -> None:
        self.economy.add_coins(97019, 800)
        for slug in ("frame_cyber", "title_boss"):
            self.client.post(
                "/api/shop/buy", json={"user_id": 97019, "item_slug": slug}
            )
        frame = self.client.post(
            "/api/user/equip",
            json={
                "user_id": 97019,
                "item_id": "frame_cyber",
                "item_type": "frame",
            },
        )
        self.assertEqual(frame.status_code, 200)
        self.assertEqual(frame.json()["equipped"]["frame"], "frame_cyber")
        self.assertEqual(frame.json()["equipped_slugs"]["frame"], "frame_cyber")
        entries = {entry["slug"]: entry for entry in frame.json()["inventory"]}
        self.assertTrue(entries["frame_cyber"]["is_equipped"])

        title = self.client.post(
            "/api/user/equip",
            json={"user_id": 97019, "item_id": "title_boss", "item_type": "title"},
        )
        self.assertEqual(title.status_code, 200)
        self.assertEqual(title.json()["equipped"]["title"], "title_boss")

        missing = self.client.post("/api/user/equip", json={"user_id": 97019})
        self.assertEqual(missing.status_code, 422)

    def test_leaderboard_cosmetics_expose_frame_and_title_slugs(self) -> None:
        from core.leaderboard import _cosmetics

        self.economy.add_coins(97020, 800)
        for slug in ("frame_fire", "title_boss"):
            self.client.post(
                "/api/shop/buy", json={"user_id": 97020, "item_slug": slug}
            )
        self.client.post(
            "/api/profile/equip",
            json={"user_id": 97020, "item_slug": "frame_fire"},
        )
        self.client.post(
            "/api/profile/equip",
            json={"user_id": 97020, "item_slug": "title_boss"},
        )
        cosmetics = _cosmetics(97020)
        self.assertEqual(cosmetics["frame"], "fire")
        self.assertEqual(cosmetics["frame_slug"], "frame_fire")
        self.assertEqual(cosmetics["title"], "Daxlsiz")
        self.assertEqual(cosmetics["title_slug"], "title_boss")


if __name__ == "__main__":
    unittest.main()


class _FakeQuery:
    """Supabase so'rov zanjirini taqlid qiladi (select/eq/order/limit/execute)."""

    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.filters: list[tuple[str, object]] = []
        self.order_key: str | None = None
        self.descending = False
        self.limit_value: int | None = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column, desc=False, **_kwargs):
        self.order_key = column
        self.descending = bool(desc)
        return self

    def limit(self, value):
        self.limit_value = int(value)
        return self

    def execute(self):
        if self.client.fail:
            raise RuntimeError("supabase ishlamayapti")
        rows = [row for row in self.client.rows if row.get("_table", self.table_name) == self.table_name]
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        if self.order_key:
            rows.sort(key=lambda row: str(row.get(self.order_key) or ""), reverse=self.descending)
        if self.limit_value is not None:
            rows = rows[: self.limit_value]
        return type("Result", (), {"data": [dict(row) for row in rows]})()


class _FakeClient:
    """Faqat `transactions` jadvalini o'qiydigan minimal fake."""

    def __init__(self, rows, fail: bool = False):
        self.rows = [dict(row) for row in rows]
        self.fail = fail

    def table(self, name):
        return _FakeQuery(self, name)


class ShopPurchaseHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "ALLOW_GUEST_AUTH": "true",
                "SUPABASE_URL": "",
                "SUPABASE_KEY": "",
                "BOT_TOKEN": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.economy = get_economy()
        self.store = ShopStore(economy=self.economy)
        set_shop_store(self.store)
        self.addCleanup(set_shop_store, None)
        reset_rate_limits()
        self.addCleanup(reset_rate_limits)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def _buy(self, user_id: int, slug: str) -> None:
        self.economy.ensure_user(user_id)
        self.store.buy(user_id, slug)

    def test_history_endpoint_returns_latest_purchase_first(self) -> None:
        self._buy(4242, "booster_shield")
        self._buy(4242, "booster_double_vote")
        self.economy.ensure_user(5151)
        self._buy(5151, "booster_kevlar")

        response = self.client.get("/api/shop/history", params={"user_id": 4242})
        self.assertEqual(response.status_code, 200)
        history = response.json()["history"]
        self.assertEqual([row["item_slug"] for row in history], ["booster_double_vote", "booster_shield"])
        self.assertEqual(history[0]["title"], "2x Ovoz")
        self.assertEqual(history[0]["total_price"], 15)
        self.assertEqual(history[1]["total_price"], 50)
        self.assertTrue(history[0]["created_at"])
        self.assertEqual(history[0]["kind"], "booster")

    def test_history_date_filter_and_pagination(self) -> None:
        self.store._transactions.extend(
            [
                {
                    "user_id": 4242,
                    "item_slug": "booster_shield",
                    "quantity": 1,
                    "unit_price": 50,
                    "total_price": 50,
                    "created_at": "2026-11-01T10:00:00+00:00",
                },
                {
                    "user_id": 4242,
                    "item_slug": "frame_gold",
                    "quantity": 1,
                    "unit_price": 150,
                    "total_price": 150,
                    "created_at": "2026-11-02T10:00:00+00:00",
                },
                {
                    "user_id": 4242,
                    "item_slug": "title_don",
                    "quantity": 1,
                    "unit_price": 100,
                    "total_price": 100,
                    "created_at": "2026-11-03T10:00:00+00:00",
                },
            ]
        )
        first = self.client.get(
            "/api/shop/history",
            params={
                "user_id": 4242,
                "from_date": "2026-11-02",
                "to_date": "2026-11-03",
                "limit": 1,
                "offset": 0,
            },
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual([row["item_slug"] for row in first.json()["history"]], ["title_don"])
        self.assertTrue(first.json()["has_more"])

        second = self.client.get(
            "/api/shop/history",
            params={
                "user_id": 4242,
                "from_date": "2026-11-02",
                "to_date": "2026-11-03",
                "limit": 1,
                "offset": 1,
            },
        )
        self.assertEqual([row["item_slug"] for row in second.json()["history"]], ["frame_gold"])
        self.assertFalse(second.json()["has_more"])

    def test_history_reads_supabase_rows_when_enabled(self) -> None:
        fake = _FakeClient(
            [
                {"user_id": 7, "item_slug": "frame_gold", "quantity": 1, "unit_price": 150,
                 "total_price": 150, "created_at": "2026-01-02T10:00:00+00:00"},
                {"user_id": 7, "item_slug": "booster_shield", "quantity": 1, "unit_price": 50,
                 "total_price": 50, "created_at": "2026-01-01T09:00:00+00:00"},
                {"user_id": 8, "item_slug": "booster_shield", "quantity": 1, "unit_price": 50,
                 "total_price": 50, "created_at": "2026-01-01T09:00:00+00:00"},
            ]
        )
        store = ShopStore(economy=self.economy, client=fake)
        self.assertTrue(store.enabled)
        rows = store.transactions_for_user(7, 5)
        self.assertEqual([row["item_slug"] for row in rows], ["frame_gold", "booster_shield"])

    def test_history_reads_alternate_supabase_columns(self) -> None:
        fake = _FakeClient(
            [
                {
                    "user_id": 7,
                    "item_id": "frame_fire",
                    "item_title": "Olovli Ajdaho",
                    "price_coins": 260,
                    "quantity": 1,
                    "created_at": "2026-01-03T10:00:00+00:00",
                }
            ]
        )
        store = ShopStore(economy=self.economy, client=fake)
        set_shop_store(store)
        response = self.client.get("/api/shop/history", params={"user_id": 7})
        self.assertEqual(response.status_code, 200)
        history = response.json()["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["item_slug"], "frame_fire")
        self.assertEqual(history[0]["title"], "Olovli Ajdaho")
        self.assertEqual(history[0]["total_price"], 260)
        self.assertTrue(history[0]["created_at"])

    def test_history_falls_back_to_memory_when_supabase_fails(self) -> None:
        store = ShopStore(economy=self.economy, client=_FakeClient([], fail=True))
        store._transactions.append(
            {
                "user_id": 9,
                "item_slug": "booster_shield",
                "quantity": 1,
                "unit_price": 50,
                "total_price": 50,
                "created_at": "2026-02-01T08:00:00+00:00",
            }
        )
        rows = store.transactions_for_user(9, 5)
        self.assertEqual([row["item_slug"] for row in rows], ["booster_shield"])
