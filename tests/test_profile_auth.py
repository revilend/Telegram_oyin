"""Mini App profil endpointining Telegram autentifikatsiyasi."""

import hashlib
import hmac
import json
import os
import time
import unittest
from urllib.parse import urlencode
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.server import app
from core.economy import START_COINS

BOT_TOKEN = "123456:TESTTOKEN"


def signed_init_data(user: dict) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "profile-test",
        "user": json.dumps(user, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class ProfileAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "BOT_TOKEN": BOT_TOKEN,
                "ALLOW_GUEST_AUTH": "false",
                "SUPABASE_URL": "",
                "SUPABASE_KEY": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_profile_uses_verified_telegram_identity(self) -> None:
        user = {
            "id": 81001,
            "first_name": "Ali",
            "last_name": "Valiyev",
            "username": "ali_test",
        }
        response = self.client.get(
            "/api/me?user_id=99999",
            headers={"X-Telegram-Init-Data": signed_init_data(user)},
        )
        self.assertEqual(response.status_code, 200, response.text)
        profile = response.json()["user"]
        self.assertEqual(profile["user_id"], 81001)
        self.assertEqual(profile["username"], "ali_test")
        self.assertEqual(profile["full_name"], "Ali Valiyev")

    def test_profile_uses_user_id_without_init_data(self) -> None:
        """Botning pastki klaviaturasidan ochilganda initData bo'lmaydi."""
        response = self.client.get(
            "/api/me?user_id=81002&username=vali_test&full_name=Vali%20Valiyev"
        )
        self.assertEqual(response.status_code, 200, response.text)
        profile = response.json()["user"]
        self.assertEqual(profile["user_id"], 81002)
        self.assertEqual(profile["username"], "vali_test")
        self.assertEqual(profile["full_name"], "Vali Valiyev")
        self.assertEqual(profile["coins"], START_COINS)

    def test_profile_rejects_missing_identity(self) -> None:
        response = self.client.get("/api/me")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
