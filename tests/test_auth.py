"""Telegram initData imzo tekshiruvi testlari."""

import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from api.auth import InitDataError, validate_init_data
from api.server import app
from engine.game_manager import get_default_manager

BOT_TOKEN = "123456:TESTTOKEN"
USER = {
    "id": 7001,
    "first_name": "Ali",
    "last_name": "Valiyev",
    "username": "ali",
}


def build_init_data(
    token: str = BOT_TOKEN,
    user: dict | None = None,
    auth_date: int | None = None,
) -> str:
    fields = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "query_id": "AAExampleQuery",
        "user": json.dumps(user or USER, separators=(",", ":"), ensure_ascii=False),
    }
    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(
        secret_key, check_string.encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(fields)


class ValidateInitDataTest(unittest.TestCase):
    def test_valid_signature(self) -> None:
        user = validate_init_data(build_init_data(), BOT_TOKEN)
        self.assertEqual(user.id, 7001)
        self.assertEqual(user.first_name, "Ali")
        self.assertEqual(user.full_name, "Ali Valiyev")
        self.assertEqual(user.username, "ali")

    def test_wrong_bot_token(self) -> None:
        with self.assertRaises(InitDataError):
            validate_init_data(build_init_data(), "999:WRONG")

    def test_tampered_payload(self) -> None:
        init_data = build_init_data().replace("Ali", "Vali")
        with self.assertRaises(InitDataError):
            validate_init_data(init_data, BOT_TOKEN)

    def test_expired(self) -> None:
        init_data = build_init_data(auth_date=int(time.time()) - 10000)
        with self.assertRaises(InitDataError):
            validate_init_data(init_data, BOT_TOKEN, max_age_seconds=3600)

    def test_future_auth_date(self) -> None:
        init_data = build_init_data(auth_date=int(time.time()) + 3600)
        with self.assertRaises(InitDataError):
            validate_init_data(init_data, BOT_TOKEN)

    def test_missing_hash_and_user(self) -> None:
        with self.assertRaises(InitDataError):
            validate_init_data("auth_date=1&user=%7B%7D", BOT_TOKEN)
        with self.assertRaises(InitDataError):
            validate_init_data("auth_date=1&hash=abc", BOT_TOKEN)

    def test_empty_input(self) -> None:
        with self.assertRaises(InitDataError):
            validate_init_data("", BOT_TOKEN)


class AuthApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "BOT_TOKEN": BOT_TOKEN,
                "ALLOW_GUEST_AUTH": "false",
                "INIT_DATA_MAX_AGE": "86400",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.manager = get_default_manager()
        self.room = self.manager.create_room(7001, "Ali Valiyev", "ali", bunker_capacity=2)
        self.manager.join_room(self.room.code, 7002, "Vali Karimov", "vali")
        self.manager.start_game(self.room.code)

    def test_authenticated_me_ignores_query_id(self) -> None:
        headers = {"X-Telegram-Init-Data": build_init_data()}
        response = self.client.get(
            f"/api/room/{self.room.code}/me?user_id=9999", headers=headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["me"]["user_id"], 7001)

    def test_missing_or_invalid_init_data(self) -> None:
        self.assertEqual(
            self.client.get(f"/api/room/{self.room.code}/me?user_id=7001").status_code,
            401,
        )
        self.assertEqual(
            self.client.get(
                f"/api/room/{self.room.code}/me?user_id=7001",
                headers={"X-Telegram-Init-Data": "user=%7B%7D&hash=bad"},
            ).status_code,
            401,
        )

    def test_action_uses_authenticated_identity(self) -> None:
        headers = {"X-Telegram-Init-Data": build_init_data()}
        response = self.client.post(
            f"/api/room/{self.room.code}/action",
            json={
                "user_id": 9999,
                "action": "reveal",
                "card_type": "profession",
            },
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["me"]["user_id"], 7001)
        self.assertTrue(payload["me"]["cards"]["profession"]["is_revealed"])

    def test_join_uses_telegram_name(self) -> None:
        lobby = self.manager.create_room(7101, "Host", "host")
        headers = {
            "X-Telegram-Init-Data": build_init_data(
                user={
                    "id": 7102,
                    "first_name": "Dilnoza",
                    "last_name": "Rahimova",
                    "username": "dilnoza",
                }
            )
        }
        response = self.client.post(
            f"/api/room/{lobby.code}/action",
            json={"user_id": 9999, "action": "join"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["me"]["user_id"], 7102)
        self.assertEqual(response.json()["me"]["full_name"], "Dilnoza Rahimova")


if __name__ == "__main__":
    unittest.main()
