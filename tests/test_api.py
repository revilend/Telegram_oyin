"""FastAPI Mini App API'si uchun testlar."""

import asyncio
import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from api import server as server_module
from api.server import app
from engine.game_manager import get_default_manager


class ApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"ALLOW_GUEST_AUTH": "true"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(app)
        self.manager = get_default_manager()
        self.room = self.manager.create_room(
            host_id=1001,
            host_name="Ali Valiyev",
            host_username="ali",
            bunker_capacity=2,
        )
        self.code = self.room.code
        self.manager.join_room(self.code, 1002, "Vali Karimov", "vali")
        self.manager.join_room(self.code, 1003, "Zilola Yusupova", "zilola")
        self.manager.start_game(self.code)

    def tearDown(self) -> None:
        self.client.close()

    def _reveal(self, user_id: int, card_type: str = "profession"):
        return self.client.post(
            f"/api/room/{self.code}/action",
            json={"user_id": user_id, "action": "reveal", "card_type": card_type},
        )


class GamesApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()

    def test_games_list(self) -> None:
        response = self.client.get("/api/games")
        self.assertEqual(response.status_code, 200)
        games = response.json()["games"]
        self.assertEqual([game["slug"] for game in games], ["bunker", "mafia", "spyfall"])
        self.assertEqual(games[0]["status"], "active")
        self.assertEqual(games[1]["status"], "coming_soon")

    def test_health_and_meta(self) -> None:
        self.assertEqual(self.client.get("/api/health").json()["status"], "ok")
        card_types = self.client.get("/api/meta/cards").json()["card_types"]
        keys = [item["key"] for item in card_types]
        self.assertIn("profession", keys)
        self.assertIn("special", keys)

    def test_static_index(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Revilend Games", response.text)
        self.assertIn("/api/room/", response.text)


class RoomApiTest(ApiTestCase):
    def test_room_state_is_public(self) -> None:
        response = self.client.get(f"/api/room/{self.code}?user_id=1001")
        self.assertEqual(response.status_code, 200)
        state = response.json()["state"]
        self.assertEqual(state["game_type"], "bunker")
        self.assertEqual(state["status"], "PLAYING")
        self.assertEqual(state["current_round"], 1)
        self.assertEqual(len(state["players"]), 3)
        self.assertEqual(state["alive_count"], 3)
        self.assertIn("name", state["catastrophe"])
        for player in state["players"]:
            self.assertEqual(player["revealed_cards"], {})
            self.assertGreaterEqual(player["hidden_count"], 6)

    def test_private_cards(self) -> None:
        response = self.client.get(f"/api/room/{self.code}/me?user_id=1001")
        self.assertEqual(response.status_code, 200)
        me = response.json()["me"]
        self.assertEqual(me["user_id"], 1001)
        self.assertTrue(me["is_host"])
        self.assertTrue(me["is_alive"])
        self.assertIn("profession", me["cards"])
        self.assertIn("health", me["cards"])
        self.assertFalse(any(card["is_revealed"] for card in me["cards"].values()))

    def test_unknown_room_and_player(self) -> None:
        self.assertEqual(self.client.get("/api/room/BNK000").status_code, 404)
        self.assertEqual(
            self.client.get(f"/api/room/{self.code}/me?user_id=9999").status_code,
            404,
        )
        self.assertEqual(
            self._reveal(9999).status_code,
            404,
        )

    def test_reveal_card(self) -> None:
        response = self._reveal(1001, "profession")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["me"]["cards"]["profession"]["is_revealed"])
        player = next(p for p in payload["state"]["players"] if p["user_id"] == 1001)
        self.assertIn("profession", player["revealed_cards"])
        self.assertGreaterEqual(player["hidden_count"], 5)

        state = self.client.get(f"/api/room/{self.code}?user_id=1002").json()["state"]
        player = next(p for p in state["players"] if p["user_id"] == 1001)
        self.assertEqual(player["revealed_cards"]["profession"]["type"], "profession")

    def test_reveal_validation(self) -> None:
        self.assertEqual(self._reveal(1001, "catastrophe").status_code, 400)
        self.assertEqual(self._reveal(1001, "nomalum").status_code, 400)
        self.assertEqual(
            self.client.post(
                f"/api/room/{self.code}/action",
                json={"user_id": 1001, "action": "nomalum"},
            ).status_code,
            422,
        )

    def test_vote_and_tally(self) -> None:
        response = self.client.post(
            f"/api/room/{self.code}/action",
            json={"user_id": 1001, "action": "vote", "target_id": 1002},
        )
        self.assertEqual(response.status_code, 200)
        state = response.json()["state"]
        self.assertEqual(state["status"], "VOTING")
        target = next(p for p in state["players"] if p["user_id"] == 1002)
        self.assertEqual(target["votes_against"], 1)

        forbidden = self.client.post(
            f"/api/room/{self.code}/action",
            json={"user_id": 1002, "action": "tally"},
        )
        self.assertEqual(forbidden.status_code, 403)

        tally = self.client.post(
            f"/api/room/{self.code}/action",
            json={"user_id": 1001, "action": "tally"},
        )
        self.assertEqual(tally.status_code, 200)
        result = tally.json()["result"]
        self.assertEqual(result["eliminated"]["user_id"], 1002)
        self.assertEqual(tally.json()["state"]["status"], "FINISHED")
        self.assertEqual(tally.json()["state"]["eliminated_players"], [1002])

    def test_vote_rules(self) -> None:
        response = self.client.post(
            f"/api/room/{self.code}/action",
            json={"user_id": 1001, "action": "vote", "target_id": 1001},
        )
        self.assertEqual(response.status_code, 400)

    def test_join_cards_start_flow(self) -> None:
        lobby = self.manager.create_room(2001, "Host", "host")
        code = lobby.code
        self.assertEqual(
            self.client.get(f"/api/room/{code}/me?user_id=2002").status_code,
            404,
        )

        join = self.client.post(
            f"/api/room/{code}/action",
            json={
                "user_id": 2002,
                "action": "join",
                "full_name": "Yangi O'yinchi",
                "username": "yangi",
            },
        )
        self.assertEqual(join.status_code, 200)
        self.assertEqual(join.json()["state"]["status"], "LOBBY")
        self.assertEqual(len(join.json()["state"]["players"]), 2)

        not_host = self.client.post(
            f"/api/room/{code}/action",
            json={"user_id": 2002, "action": "start"},
        )
        self.assertEqual(not_host.status_code, 403)

        started = self.client.post(
            f"/api/room/{code}/action",
            json={"user_id": 2001, "action": "start"},
        )
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json()["state"]["status"], "PLAYING")
        self.assertEqual(started.json()["state"]["current_round"], 1)
        self.assertIn("profession", started.json()["me"]["cards"])


class LifespanTest(unittest.TestCase):
    def test_server_starts_without_bot_token(self) -> None:
        with patch.dict(
            os.environ,
            {"BOT_TOKEN": "", "ALLOW_GUEST_AUTH": "true"},
        ):
            with TestClient(app) as client:
                response = client.get("/api/health")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "ok")

    def test_bot_polling_runs_in_background_and_is_cancelled(self) -> None:
        started = threading.Event()
        cancelled = threading.Event()

        async def fake_polling(bot) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        fake_bot = MagicMock()
        fake_bot.session.close = AsyncMock()
        fake_dispatcher = SimpleNamespace(start_polling=fake_polling)

        with patch.dict(
            os.environ,
            {"BOT_TOKEN": "123456:TEST", "ALLOW_GUEST_AUTH": "true"},
        ):
            with patch.object(server_module, "Bot", return_value=fake_bot), patch.object(
                server_module, "build_dispatcher", return_value=fake_dispatcher
            ), patch.object(server_module, "set_commands", new=AsyncMock()):
                with TestClient(app) as client:
                    self.assertTrue(started.wait(2), "Polling fonda boshlanmadi")
                    self.assertEqual(client.get("/api/health").status_code, 200)

        self.assertTrue(cancelled.wait(2), "Shutdown'da polling bekor qilinmadi")
        fake_bot.session.close.assert_awaited_once()


class WebSocketTest(ApiTestCase):
    def test_websocket_state_and_broadcast(self) -> None:
        with self.client.websocket_connect(f"/ws/{self.code}") as socket:
            initial = socket.receive_json()
            self.assertEqual(initial["type"], "state")
            self.assertEqual(initial["state"]["code"], self.code)

            reveal = self._reveal(1001, "health")
            self.assertEqual(reveal.status_code, 200)

            update = socket.receive_json()
            self.assertEqual(update["type"], "state")
            player = next(
                p for p in update["state"]["players"] if p["user_id"] == 1001
            )
            self.assertIn("health", player["revealed_cards"])


if __name__ == "__main__":
    unittest.main()
