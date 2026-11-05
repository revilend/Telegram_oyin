"""Mega Store API: buyumlar, xarid, omad ğildiragi va jihozlash testlari."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.server import app
from core.economy import START_COINS, get_economy
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
            sections, ["SPIN", "COSMETIC", "BOOSTER", "CLAN", "TICKET"]
        )
        cosmetic = next(
            section for section in payload["sections"] if section["key"] == "COSMETIC"
        )
        slugs = [item["slug"] for item in cosmetic["items"]]
        self.assertIn("frame_gold", slugs)
        self.assertIn("title_don", slugs)
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

        second = self.client.post("/api/spin/wheel", json={"user_id": 97014})
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["free"])

        self.economy.spend_coins(97014, self._coins(97014))
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


if __name__ == "__main__":
    unittest.main()
