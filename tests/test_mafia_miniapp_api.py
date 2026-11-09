"""Mafia Mini App action and voting API tests."""

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
from bot.handlers.mafia_group import MafiaLobbyManager
from games.mafia.engine import GamePhase, MafiaRole

BOT_TOKEN = "123456:MAFIATEST"


def signed_init_data(user_id: int) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": f"mafia-{user_id}",
        "user": json.dumps(
            {"id": user_id, "first_name": f"Player{user_id}"},
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(
        b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256
    ).digest()
    fields["hash"] = hmac.new(
        secret, check.encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(fields)


class MafiaMiniAppApiTest(unittest.TestCase):
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

        self.manager = MafiaLobbyManager(seed=42)
        self.game = self.manager.create_game(-100123, 1, "Player1")
        for user_id in (2, 3, 4):
            self.manager.join(self.game.code, user_id, f"Player{user_id}")
        self.manager.start_game(self.game.code, 1)

        self.game.room.players[1].role = MafiaRole.DOCTOR
        self.game.room.players[2].role = MafiaRole.MAFIA
        self.game.room.players[3].role = MafiaRole.SHERIFF
        self.game.room.players[4].role = MafiaRole.CITIZEN

        self.manager_patch = patch(
            "api.server.mafia_bot.get_default_manager",
            return_value=self.manager,
        )
        self.manager_patch.start()
        self.addCleanup(self.manager_patch.stop)

        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def headers(self, user_id: int) -> dict[str, str]:
        return {
            "X-Telegram-Init-Data": signed_init_data(user_id)
        }

    def test_state_requires_verified_telegram_user(self) -> None:
        response = self.client.get(f"/api/mafia/{self.game.code}/state")
        self.assertEqual(response.status_code, 401)

    def test_state_does_not_expose_other_players_roles(self) -> None:
        response = self.client.get(
            f"/api/mafia/{self.game.code}/state",
            headers=self.headers(1),
        )
        self.assertEqual(response.status_code, 200, response.text)
        state = response.json()["state"]
        self.assertEqual(state["night_actions"][0]["key"], "heal")
        for player in state["players"]:
            self.assertNotIn("role", player)
            self.assertNotIn("faction", player)

    def test_night_action_uses_engine_validation(self) -> None:
        response = self.client.post(
            f"/api/mafia/{self.game.code}/night-action",
            headers=self.headers(1),
            json={"target_id": 2, "kind": "heal"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.game.room.night_actions[1].target_id,
            2,
        )

    def test_voting_and_self_vote_validation(self) -> None:
        self.game.room.phase = GamePhase.DAY_REPORT
        started = self.client.post(
            f"/api/mafia/{self.game.code}/begin-voting",
            headers=self.headers(1),
        )
        self.assertEqual(started.status_code, 200, started.text)
        self.assertIs(self.game.room.phase, GamePhase.VOTING)

        invalid = self.client.post(
            f"/api/mafia/{self.game.code}/vote",
            headers=self.headers(2),
            json={"target_id": 2},
        )
        self.assertEqual(invalid.status_code, 400)

        valid = self.client.post(
            f"/api/mafia/{self.game.code}/vote",
            headers=self.headers(2),
            json={"target_id": 3},
        )
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(self.game.room.votes[2], 3)

    def test_only_host_can_begin_voting(self) -> None:
        self.game.room.phase = GamePhase.DAY_REPORT
        response = self.client.post(
            f"/api/mafia/{self.game.code}/begin-voting",
            headers=self.headers(2),
        )
        self.assertEqual(response.status_code, 403)
        self.assertIs(self.game.room.phase, GamePhase.DAY_REPORT)

    def test_host_tally_eliminates_player_and_starts_next_night(self) -> None:
        self.game.room.phase = GamePhase.VOTING
        self.game.room.cast_vote(1, 4)
        self.game.room.cast_vote(2, 4)
        self.game.room.cast_vote(3, 4)

        with patch("api.server._runtime_bot", None):
            response = self.client.post(
                f"/api/mafia/{self.game.code}/tally",
                headers=self.headers(1),
                json={},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["eliminated_id"], 4)
        self.assertFalse(self.game.room.players[4].is_alive)
        self.assertIs(self.game.room.phase, GamePhase.NIGHT)

    def test_kamikaze_tally_auto_takes_a_voter(self) -> None:
        self.game.room.players[4].role = MafiaRole.KAMIKAZE
        self.game.room.phase = GamePhase.VOTING
        self.game.room.cast_vote(1, 4)
        self.game.room.cast_vote(2, 4)
        self.game.room.cast_vote(3, 4)

        response = self.client.post(
            f"/api/mafia/{self.game.code}/tally",
            headers=self.headers(1),
            json={},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["eliminated_id"], 4)
        self.assertFalse(self.game.room.players[4].is_alive)
        self.assertEqual(
            sum(1 for uid in (1, 2, 3) if not self.game.room.players[uid].is_alive),
            1,
        )


if __name__ == "__main__":
    unittest.main()
