"""Production API endpoints must reject caller-supplied Telegram IDs."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.server import app


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

    def test_read_endpoints_reject_forged_user_id(self) -> None:
        urls = (
            "/api/me?user_id=7001",
            "/api/bonus?user_id=7001",
            "/api/missions?user_id=7001",
            "/api/top?user_id=7001",
            "/api/room/BNK000/me?user_id=7001",
            "/api/mafia/MAF000/me?user_id=7001",
            "/api/spy/SPY000?user_id=7001",
        )
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 401, response.text)

    def test_write_endpoints_reject_forged_user_id(self) -> None:
        requests = (
            ("POST", "/api/bonus", {"user_id": 7001}),
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
                self.assertEqual(response.status_code, 401, response.text)

    def test_invalid_telegram_init_data_is_rejected(self) -> None:
        response = self.client.get(
            "/api/me?user_id=7001",
            headers={"X-Telegram-Init-Data": "user=%7B%22id%22%3A7001%7D&hash=bad"},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
