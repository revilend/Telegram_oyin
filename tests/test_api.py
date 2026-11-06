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
from bot.handlers import mafia_group as mafia_bot
from core.economy import START_COINS, EconomyStore
from engine.game_manager import get_default_manager
from games.mafia.images import role_image_url
from games.mafia.roles import Faction


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
        self.manager.join_room(self.code, 1004, "Sardor Tolipov", "sardor")
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
        self.assertEqual(
            [game["slug"] for game in games],
            ["bunker", "mafia", "spyfall", "alias", "bomb"],
        )
        self.assertEqual(games[0]["status"], "active")
        self.assertEqual(games[1]["status"], "active")

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
        self.assertIn("tarot-card", response.text)
        self.assertIn("/assets/images/mafia/cover.png", response.text)

    def test_mafia_assets_are_served(self) -> None:
        response = self.client.get("/assets/images/mafia/sheriff.png")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("image/"))


class MafiaRoleApiTest(unittest.TestCase):
    """Mini App uchun Mafiya roli endpointi."""

    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"ALLOW_GUEST_AUTH": "true"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(app)
        self.manager = mafia_bot.MafiaLobbyManager(seed=12)
        patcher = patch.object(
            mafia_bot, "get_default_manager", return_value=self.manager
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.economy = EconomyStore(url="", key="", client=None)
        economy_patch = patch.object(
            server_module, "get_economy", return_value=self.economy
        )
        economy_patch.start()
        self.addCleanup(economy_patch.stop)

        self.game = self.manager.create_game(-1001, 3001, "Ali", "ali")
        for user_id in (3002, 3003, 3004):
            self.manager.join(self.game.code, user_id, f"P{user_id}")
        self.manager.start_game(self.game.code, 3001)

    def tearDown(self) -> None:
        self.client.close()

    def test_player_role_payload(self) -> None:
        response = self.client.get(
            f"/api/mafia/{self.game.code}/me?user_id=3001"
        )
        self.assertEqual(response.status_code, 200)
        me = response.json()["me"]
        role = self.game.room.players[3001].role
        self.assertEqual(me["code"], self.game.code)
        self.assertEqual(me["role"], role.value)
        self.assertEqual(me["photo"], role_image_url(role))
        self.assertIn(me["phase"], {"NIGHT", "DAY_REPORT", "VOTING"})
        self.assertEqual(me["players_count"], 4)
        self.assertTrue(me["is_host"])
        self.assertEqual(me["phase_duration"], 60)
        self.assertGreater(me["phase_deadline"], 0)
        self.assertGreater(me["phase_seconds_left"], 0)
        self.assertEqual(me["coins"], START_COINS)
        self.assertEqual(
            {item["key"] for item in me["boosters"]},
            {"kevlar", "reroll", "double_vote"},
        )

    def test_mafia_team_is_visible_only_to_mafia(self) -> None:
        players = list(self.game.room.players.values())
        mafia = [p for p in players if p.faction is Faction.MAFIA]
        town = [p for p in players if p.faction is Faction.TOWN]
        self.assertTrue(mafia)
        self.assertTrue(town)

        mafia_payload = self.client.get(
            f"/api/mafia/{self.game.code}/me?user_id={mafia[0].user_id}"
        ).json()["me"]
        expected = {
            player.user_id for player in mafia if player.user_id != mafia[0].user_id
        }
        self.assertEqual(
            {mate["user_id"] for mate in mafia_payload["teammates"]},
            expected,
        )

        town_payload = self.client.get(
            f"/api/mafia/{self.game.code}/me?user_id={town[0].user_id}"
        ).json()["me"]
        self.assertEqual(town_payload["teammates"], [])

    def test_buy_kevlar_and_reroll_boosters(self) -> None:
        kevlar = self.client.post(
            f"/api/mafia/{self.game.code}/booster",
            json={"user_id": 3001, "booster": "kevlar"},
        )
        self.assertEqual(kevlar.status_code, 200, kevlar.text)
        payload = kevlar.json()
        self.assertEqual(payload["coins"], START_COINS - 40)
        options = {item["key"]: item for item in payload["me"]["boosters"]}
        self.assertTrue(options["kevlar"]["active"])
        self.assertFalse(options["kevlar"]["available"])

        again = self.client.post(
            f"/api/mafia/{self.game.code}/booster",
            json={"user_id": 3001, "booster": "kevlar"},
        )
        self.assertEqual(again.status_code, 400, again.text)

        old_role = self.game.room.players[3001].role
        reroll = self.client.post(
            f"/api/mafia/{self.game.code}/booster",
            json={"user_id": 3001, "booster": "reroll"},
        )
        self.assertEqual(reroll.status_code, 200, reroll.text)
        self.assertNotEqual(self.game.room.players[3001].role, old_role)
        self.assertIn("Yangi rolingiz", reroll.json()["message"])

    def test_double_vote_requires_day_phase(self) -> None:
        response = self.client.post(
            f"/api/mafia/{self.game.code}/booster",
            json={"user_id": 3002, "booster": "double_vote"},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("kunduzgi", response.json()["detail"])

    def test_non_player_and_unknown_room_are_rejected(self) -> None:
        self.assertEqual(
            self.client.get(
                f"/api/mafia/{self.game.code}/me?user_id=9999"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get("/api/mafia/MAF000/me?user_id=3001").status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                f"/api/mafia/{self.game.code}/booster",
                json={"user_id": 9999, "booster": "kevlar"},
            ).status_code,
            404,
        )


class RoomApiTest(ApiTestCase):
    def test_room_state_is_public(self) -> None:
        response = self.client.get(f"/api/room/{self.code}?user_id=1001")
        self.assertEqual(response.status_code, 200)
        state = response.json()["state"]
        self.assertEqual(state["game_type"], "bunker")
        self.assertEqual(state["status"], "PLAYING")
        self.assertEqual(state["current_round"], 1)
        self.assertEqual(len(state["players"]), 4)
        self.assertEqual(state["alive_count"], 4)
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
        self.assertEqual(tally.json()["state"]["status"], "PLAYING")
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

        for user_id, name in ((2003, "Uchinchi"), (2004, "To'rtinchi")):
            extra = self.client.post(
                f"/api/room/{code}/action",
                json={
                    "user_id": user_id,
                    "action": "join",
                    "full_name": name,
                    "username": f"p{user_id}",
                },
            )
            self.assertEqual(extra.status_code, 200)
        self.assertEqual(len(extra.json()["state"]["players"]), 4)

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
            with (
                patch.object(server_module, "Bot", return_value=fake_bot),
                patch.object(server_module, "LocalizedBot", return_value=fake_bot),
                patch.object(server_module, "build_dispatcher", return_value=fake_dispatcher),
                patch.object(server_module, "set_commands", new=AsyncMock()),
            ):
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
