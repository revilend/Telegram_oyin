"""Mini App uchun yagona `/api/bootstrap` endpoint testi.

Bootstrap bitta javobda profil, bonus/streak, missiyalar, faol turnir,
inventar va o'yinlar ro'yxatini qaytarishi kerak — Mini App birinchi
ochilishda faqat shu endpointni chaqiradi.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("ADMIN_ID", "424242")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")

from fastapi.testclient import TestClient  # noqa: E402

import api.server as api_server  # noqa: E402
from core.economy import START_COINS, EconomyStore  # noqa: E402

USER_ID = 660_001


class BootstrapEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EconomyStore(url="", key="", client=None)
        self.store.ensure_user(USER_ID, "ali", "Ali Valiyev")
        self.store.add_coins(USER_ID, 25)
        patcher = patch.object(
            api_server, "get_economy", return_value=self.store
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(api_server.app)

    def _bootstrap(self, **params) -> dict:
        response = self.client.get(
            "/api/bootstrap",
            params={
                "user_id": USER_ID,
                "username": "ali",
                "full_name": "Ali Valiyev",
                **params,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_bootstrap_returns_everything_in_one_response(self) -> None:
        data = self._bootstrap()

        for key in (
            "account",
            "activity",
            "tournament",
            "games",
            "shop",
            "boosters",
        ):
            self.assertIn(key, data)

        account = data["account"]
        self.assertEqual(account["user"]["user_id"], USER_ID)
        self.assertEqual(account["user"]["coins"], START_COINS + 25)
        self.assertIn("inventory", account)
        self.assertIn("equipped", account)
        self.assertIn("spin", account)
        self.assertIn("shop", account)

        activity = data["activity"]
        self.assertIn("bonus", activity)
        self.assertIn("streak", activity["bonus"])
        self.assertTrue(activity["missions"])
        self.assertIn("week", activity)
        self.assertEqual(activity["coins"], START_COINS + 25)

        self.assertTrue(data["games"])
        self.assertIsInstance(data["tournament"], dict)

    def test_bootstrap_shares_same_payload_as_me_and_activity(self) -> None:
        data = self._bootstrap()

        me = self.client.get(
            "/api/me",
            params={"user_id": USER_ID, "username": "ali", "full_name": "Ali Valiyev"},
        ).json()
        activity = self.client.get(
            "/api/activity",
            params={"user_id": USER_ID, "username": "ali", "full_name": "Ali Valiyev"},
        ).json()

        self.assertEqual(data["account"]["user"]["coins"], me["user"]["coins"])
        self.assertEqual(
            data["activity"]["bonus"]["streak"], activity["bonus"]["streak"]
        )
        self.assertEqual(data["activity"]["coins"], activity["coins"])

    def test_bootstrap_requires_user_identity(self) -> None:
        response = self.client.get("/api/bootstrap")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
