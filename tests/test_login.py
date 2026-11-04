"""Mini App kirish kodlari va ``POST /api/auth/login`` testlari."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.server import app
from core.economy import START_COINS, get_economy
from core.login_codes import (
    LOGIN_CODE_TTL_SECONDS,
    issue_login_code,
    reset_login_codes,
    verify_login_code,
)


class LoginCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_login_codes()
        self.addCleanup(reset_login_codes)

    def test_code_is_six_digits_and_single_use(self) -> None:
        code = issue_login_code(88001, now=1000)
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())
        self.assertEqual(verify_login_code(code, now=1001), 88001)
        self.assertIsNone(verify_login_code(code, now=1002))

    def test_new_code_invalidates_previous(self) -> None:
        first = issue_login_code(88002, now=1000)
        second = issue_login_code(88002, now=1001)
        self.assertNotEqual(first, second)
        self.assertIsNone(verify_login_code(first, now=1002))
        self.assertEqual(verify_login_code(second, now=1002), 88002)

    def test_expired_code_is_rejected(self) -> None:
        code = issue_login_code(88003, now=1000)
        self.assertIsNone(
            verify_login_code(code, now=1000 + LOGIN_CODE_TTL_SECONDS)
        )

    def test_invalid_format_is_rejected(self) -> None:
        self.assertIsNone(verify_login_code("12ab", now=1000))
        self.assertIsNone(verify_login_code("", now=1000))


class LoginApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "ALLOW_GUEST_AUTH": "false",
                "SUPABASE_URL": "",
                "SUPABASE_KEY": "",
                "BOT_TOKEN": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        reset_login_codes()
        self.addCleanup(reset_login_codes)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def _create_user(
        self, user_id: int, username: str = "login_user", full_name: str = "Ali Valiyev"
    ) -> None:
        get_economy().ensure_user(user_id, username, full_name)

    def test_login_with_code_returns_full_profile(self) -> None:
        self._create_user(88011, "ali_login", "Ali Valiyev")
        code = issue_login_code(88011)
        response = self.client.post("/api/auth/login", json={"login": code})
        self.assertEqual(response.status_code, 200, response.text)
        profile = response.json()["user"]
        self.assertEqual(profile["user_id"], 88011)
        self.assertEqual(profile["username"], "ali_login")
        self.assertEqual(profile["full_name"], "Ali Valiyev")
        self.assertEqual(profile["coins"], START_COINS)
        self.assertEqual(profile["games_played"], 0)
        self.assertEqual(profile["wins"], 0)
        self.assertEqual(profile["bunker_wins"], 0)
        self.assertEqual(profile["mafia_wins"], 0)

        again = self.client.post("/api/auth/login", json={"code": code})
        self.assertEqual(again.status_code, 401)

    def test_explicit_code_field(self) -> None:
        self._create_user(88013)
        code = issue_login_code(88013)
        response = self.client.post("/api/auth/login", json={"code": code})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user"]["user_id"], 88013)

    def test_login_with_telegram_id(self) -> None:
        self._create_user(88012)
        response = self.client.post(
            "/api/auth/login", json={"user_id": 88012}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user"]["user_id"], 88012)

    def test_six_digit_login_falls_back_to_existing_id(self) -> None:
        self._create_user(654321, "id_user", "ID User")
        response = self.client.post(
            "/api/auth/login", json={"login": "654321"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user"]["user_id"], 654321)

    def test_unknown_user_is_rejected(self) -> None:
        response = self.client.post(
            "/api/auth/login", json={"user_id": 88099}
        )
        self.assertEqual(response.status_code, 404)

    def test_bad_code_is_rejected(self) -> None:
        response = self.client.post(
            "/api/auth/login", json={"login": "000000"}
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
