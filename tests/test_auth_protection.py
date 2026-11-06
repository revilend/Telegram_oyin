"""Production API: o'qishlar user_id bilan, yozishlar initData bilan ishlaydi."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.server import app
from core.economy import START_COINS


class ProtectedApiAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "ALLOW_GUEST_AUTH": "false",
                "BOT_TOKEN": "123456:TESTTOKEN",
                "SUPABASE_URL": "",
                "SUPABASE_KEY": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_activity_reads_accept_user_id_without_init_data(self) -> None:
        """Missiyalar, streak va reyting initData'siz ham yuklanadi."""
        missions = self.client.get("/api/missions?user_id=7001")
        self.assertEqual(missions.status_code, 200, missions.text)
        self.assertIn("missions", missions.json())

        activity = self.client.get("/api/activity?user_id=7001")
        self.assertEqual(activity.status_code, 200, activity.text)
        payload = activity.json()
        self.assertIn("bonus", payload)
        self.assertIn("missions", payload)
        self.assertIn("top", payload)
        self.assertIn("week", payload)
        self.assertIn("coins", payload)

    def test_room_reads_accept_user_id_without_init_data(self) -> None:
        """Xona endpointlari user_id bilan initData'siz ham javob beradi."""
        urls = (
            "/api/room/BNK000/me?user_id=7001",
            "/api/mafia/MAF000/me?user_id=7001",
            "/api/spy/SPY000?user_id=7001",
        )
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertNotEqual(response.status_code, 401, response.text)

    def test_profile_reads_accept_user_id_without_init_data(self) -> None:
        """Pastki klaviaturasidan ochilgan Mini App initData'siz ishlaydi."""
        urls = (
            "/api/me?user_id=7001",
            "/api/bonus?user_id=7001",
            "/api/top?limit=5&user_id=7001",
        )
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, response.text)

        profile = self.client.get("/api/me?user_id=7001").json()["user"]
        self.assertEqual(profile["user_id"], 7001)
        # Yangi o'yinchi boshlang'ich tangalar bilan yaratiladi, ya'ni
        # balans haqiqiy hisobdan olinadi (0 emas).
        self.assertEqual(profile["coins"], START_COINS)
        self.assertIn("games_played", profile)
        self.assertIn("bunker_wins", profile)
        self.assertIn("mafia_wins", profile)

    def test_write_endpoints_reject_forged_user_id(self) -> None:
        response = self.client.post("/api/bonus", json={"user_id": 7001})
        self.assertEqual(response.status_code, 401, response.text)

    def test_room_writes_accept_user_id_without_init_data(self) -> None:
        """Xonaga qo'shilish va xona amallari initData'siz ishlaydi."""
        requests = (
            ("POST", "/api/spy/create", {"user_id": 7001, "name": "Guest"}),
            (
                "POST",
                "/api/room/BNK000/action",
                {"user_id": 7001, "action": "join", "full_name": "Guest"},
            ),
            (
                "POST",
                "/api/mafia/MAF000/booster",
                {"user_id": 7001, "booster": "kevlar"},
            ),
        )
        for method, url, payload in requests:
            with self.subTest(url=url):
                response = self.client.request(method, url, json=payload)
                self.assertNotEqual(response.status_code, 401, response.text)

    def test_invalid_telegram_init_data_is_rejected(self) -> None:
        response = self.client.get(
            "/api/me?user_id=7001",
            headers={"X-Telegram-Init-Data": "user=%7B%22id%22%3A7001%7D&hash=bad"},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
