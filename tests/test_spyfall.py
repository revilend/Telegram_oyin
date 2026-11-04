"""Josus (Spyfall) API autentifikatsiyasi va o'yin oqimi testlari."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.server import app
from games import spyfall_api


class SpyfallApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"ALLOW_GUEST_AUTH": "true"})
        self.env.start()
        self.addCleanup(self.env.stop)
        with spyfall_api._lock:
            spyfall_api._rooms.clear()
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def player(self, user_id: int, name: str):
        return {"user_id": user_id, "name": name}

    def test_create_join_start_and_vote(self) -> None:
        created = self.client.post("/api/spy/create", json=self.player(101, "Ali"))
        self.assertEqual(created.status_code, 200, created.text)
        code = created.json()["state"]["code"]

        for user_id, name in ((102, "Vali"), (103, "Zilola")):
            joined = self.client.post(
                f"/api/spy/{code}/join", json=self.player(user_id, name)
            )
            self.assertEqual(joined.status_code, 200, joined.text)

        started = self.client.post(
            f"/api/spy/{code}/start", json=self.player(101, "Ali")
        )
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(started.json()["state"]["status"], "PLAYING")

        state = self.client.get(f"/api/spy/{code}?user_id=101")
        self.assertEqual(state.status_code, 200, state.text)
        self.assertIn(state.json()["me"]["role"], {"spy", "player"})

        voted = self.client.post(
            f"/api/spy/{code}/vote",
            json={"user_id": 101, "name": "Ali", "target_id": 102},
        )
        self.assertEqual(voted.status_code, 200, voted.text)

        duplicate = self.client.post(
            f"/api/spy/{code}/vote",
            json={"user_id": 101, "name": "Ali", "target_id": 103},
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("allaqachon", duplicate.json()["detail"])

    def test_cannot_vote_for_self(self) -> None:
        self.client.post("/api/spy/create", json=self.player(201, "Ali"))
        code = next(iter(spyfall_api._rooms))
        for user_id in (202, 203):
            self.client.post(
                f"/api/spy/{code}/join",
                json=self.player(user_id, f"Player {user_id}"),
            )
        self.client.post(
            f"/api/spy/{code}/start", json=self.player(201, "Ali")
        )
        response = self.client.post(
            f"/api/spy/{code}/vote",
            json={"user_id": 201, "target_id": 201},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("O'zingizga", response.json()["detail"])

    def test_unauthenticated_guest_is_rejected(self) -> None:
        with patch.dict(os.environ, {"ALLOW_GUEST_AUTH": "false"}):
            response = self.client.post(
                "/api/spy/create", json=self.player(301, "Guest")
            )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
