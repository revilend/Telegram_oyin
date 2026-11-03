"""Mini App iqtisod API'lari va booster actionlari testlari."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.server import app
from core.economy import get_economy
from engine.game_manager import get_default_manager


class EconomyApiTest(unittest.TestCase):
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
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.manager = get_default_manager()
        self.addCleanup(self.manager.set_coin_balance_reader, None)

    def test_shop_and_profile(self) -> None:
        shop = self.client.get("/api/shop")
        self.assertEqual(shop.status_code, 200)
        payload = shop.json()
        self.assertEqual(
            [pack["coins"] for pack in payload["shop"]["packages"]],
            [500, 1500, 4000],
        )
        self.assertEqual(
            [pack["price"] for pack in payload["shop"]["packages"]],
            [10000, 25000, 60000],
        )
        self.assertIn("shield", [item["key"] for item in payload["boosters"]])

        me = self.client.get("/api/me?user_id=99001")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["coins"], 0)
        self.assertIn("shop", me.json())

    def test_double_vote_booster(self) -> None:
        room = self.manager.create_room(99101, "Ali", "ali", bunker_capacity=2)
        self.manager.join_room(room.code, 99102, "Vali", "vali")
        self.manager.join_room(room.code, 99103, "Zilola", "zilola")
        self.manager.start_game(room.code)
        get_economy().add_coins(99101, 15)

        purchase = self.client.post(
            f"/api/room/{room.code}/action",
            json={"user_id": 99101, "action": "booster", "booster": "double_vote"},
        )
        self.assertEqual(purchase.status_code, 200, purchase.text)
        self.assertEqual(purchase.json()["coins"], 0)

        vote = self.client.post(
            f"/api/room/{room.code}/action",
            json={"user_id": 99101, "action": "vote", "target_id": 99102},
        )
        self.assertEqual(vote.status_code, 200)
        target = next(
            player
            for player in vote.json()["state"]["players"]
            if player["user_id"] == 99102
        )
        self.assertEqual(target["votes_against"], 2)

    def test_insufficient_coins_returns_402(self) -> None:
        room = self.manager.create_room(99201, "Ali", "ali", bunker_capacity=2)
        self.manager.join_room(room.code, 99202, "Vali", "vali")
        self.manager.start_game(room.code)
        response = self.client.post(
            f"/api/room/{room.code}/action",
            json={"user_id": 99201, "action": "booster", "booster": "double_vote"},
        )
        self.assertEqual(response.status_code, 402, response.text)
        self.assertIn("yetarli tanga", response.json()["detail"])

    def test_shield_offer_and_accept_via_api(self) -> None:
        economy = get_economy()
        room = self.manager.create_room(99300, "Host", "host", bunker_capacity=2)
        for user_id in (99301, 99302, 99303):
            self.manager.join_room(room.code, user_id, f"P{user_id}", f"p{user_id}")
        self.manager.start_game(room.code)
        economy.add_coins(99301, 100)
        self.manager.set_coin_balance_reader(
            lambda uid: economy.get_user(uid).coins
        )

        for voter, target in ((99300, 99301), (99302, 99301), (99303, 99302)):
            self.manager.cast_vote(room.code, voter, target)

        tally = self.client.post(
            f"/api/room/{room.code}/action",
            json={"user_id": 99300, "action": "tally"},
        )
        self.assertEqual(tally.status_code, 200, tally.text)
        self.assertEqual(tally.json()["state"]["status"], "SHIELD_OFFER")
        self.assertEqual(tally.json()["result"]["shield_offer"]["user_id"], 99301)

        accepted = self.client.post(
            f"/api/room/{room.code}/action",
            json={"user_id": 99301, "action": "booster", "booster": "shield"},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        payload = accepted.json()
        self.assertEqual(payload["coins"], 50)
        self.assertEqual(payload["result"]["eliminated"]["user_id"], 99302)
        self.assertEqual(payload["state"]["status"], "PLAYING")


if __name__ == "__main__":
    unittest.main()
