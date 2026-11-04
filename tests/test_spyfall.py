"""«Josus» (Spyfall) katalogi, dvigateli va API testlari."""

from __future__ import annotations

import os
import random
import unittest
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("MINI_APP_URL", "https://revilend.games")
os.environ.setdefault("BOT_USERNAME", "revilend_gamesbot")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")

from fastapi.testclient import TestClient

from api.server import app
from core.economy import START_COINS, EconomyStore, get_economy
from games.spyfall.engine import (
    DEFAULT_ROUND_SECONDS,
    DOUBLE_SPY_MIN_PLAYERS,
    HINT_ELIMINATIONS,
    HINT_PRICE,
    PLAYER_WIN_REWARD,
    SPY_WIN_REWARD,
    Phase,
    SpyfallError,
    SpyfallRoom,
    Winner,
)
from games.spyfall.locations import LOCATIONS, LOCATIONS_BY_KEY, get_location
from games.spyfall.manager import SpyfallManager, get_default_manager


class LocationCatalogTest(unittest.TestCase):
    def test_catalog_is_rich_enough(self) -> None:
        self.assertGreaterEqual(len(LOCATIONS), 25)
        for location in LOCATIONS:
            with self.subTest(location=location.key):
                self.assertGreaterEqual(len(location.roles), 6)
                self.assertLessEqual(len(location.roles), 8)
                self.assertEqual(len(set(location.roles)), len(location.roles))
                self.assertTrue(location.name.strip())
                self.assertTrue(location.emoji.strip())
        keys = [location.key for location in LOCATIONS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_required_locations_exist(self) -> None:
        names = {location.name for location in LOCATIONS}
        for name in (
            "Samolyot",
            "Shifoxona",
            "Harbiy baza",
            "Bank",
            "To'yxona",
            "Choyxona",
            "Kosmik stantsiya",
            "Bozor (Chorsu)",
        ):
            self.assertIn(name, names)

    def test_get_location_by_key_and_name(self) -> None:
        self.assertEqual(get_location("toyxona").name, "To'yxona")
        self.assertEqual(get_location("To'yxona").key, "toyxona")
        with self.assertRaises(KeyError):
            get_location("bunday_joy_yoq")


class SpyfallEngineTest(unittest.TestCase):
    def _room(self, count: int = 3) -> SpyfallRoom:
        room = SpyfallRoom("SPY101", host_id=1)
        for uid in range(1, count + 1):
            room.add_player(uid, f"Player {uid}", is_host=uid == 1)
        return room

    def test_start_requires_three_players(self) -> None:
        room = SpyfallRoom("SPY102", host_id=1)
        room.add_player(1, "Ali")
        with self.assertRaises(SpyfallError):
            room.start(rng=random.Random(1))

    def test_single_spy_for_small_games(self) -> None:
        room = self._room(6)
        room.start(now=1000, rng=random.Random(3))
        self.assertEqual(room.phase, Phase.PLAYING)
        self.assertEqual(len(room.spy_ids), 1)
        self.assertIsNotNone(room.location)
        self.assertEqual(room.deadline, 1000 + DEFAULT_ROUND_SECONDS)

        spy_id = sorted(room.spy_ids)[0]
        spy_view = room.player_view(spy_id)
        self.assertTrue(spy_view["is_spy"])
        self.assertIsNone(spy_view["location"])
        self.assertIn("JOSUSSIZ", spy_view["spy_warning"])

        for uid in room.players:
            if uid == spy_id:
                continue
            view = room.player_view(uid)
            self.assertFalse(view["is_spy"])
            self.assertEqual(view["location"], room.location.key)
            self.assertIn(view["role_name"], room.location.roles)

    def test_two_spies_for_large_games(self) -> None:
        room = self._room(DOUBLE_SPY_MIN_PLAYERS)
        room.start(now=0, rng=random.Random(5))
        self.assertEqual(len(room.spy_ids), 2)
        spy_id = sorted(room.spy_ids)[0]
        teammates = room.player_view(spy_id)["teammates"]
        self.assertEqual(len(teammates), 1)
        self.assertIn(teammates[0]["user_id"], room.spy_ids)

    def test_teammates_hidden_after_finish(self) -> None:
        room = self._room(8)
        room.start(now=0, rng=random.Random(9))
        spy_id = sorted(room.spy_ids)[0]
        room.finish(Winner.PLAYERS, "test")
        self.assertEqual(room.player_view(spy_id)["teammates"], [])

    def test_correct_guess_wins_for_spies(self) -> None:
        room = self._room(4)
        room.start(now=0, rng=random.Random(11))
        spy_id = sorted(room.spy_ids)[0]
        outcome = room.guess(spy_id, room.location.key)
        self.assertTrue(outcome.correct)
        self.assertEqual(outcome.winner, Winner.SPIES)
        self.assertEqual(room.phase, Phase.FINISHED)
        self.assertEqual(room.winner, Winner.SPIES)
        self.assertEqual(room.winner_ids, sorted(room.spy_ids))
        self.assertEqual(room.reward_per_winner, SPY_WIN_REWARD)

    def test_wrong_guess_wins_for_players(self) -> None:
        room = self._room(4)
        room.start(now=0, rng=random.Random(13))
        spy_id = sorted(room.spy_ids)[0]
        wrong = next(
            location.key for location in LOCATIONS if location.key != room.location.key
        )
        outcome = room.guess(spy_id, wrong)
        self.assertFalse(outcome.correct)
        self.assertEqual(room.winner, Winner.PLAYERS)
        self.assertIn(room.location.name, outcome.reason)
        self.assertTrue(set(room.winner_ids).isdisjoint(room.spy_ids))
        self.assertEqual(room.reward_per_winner, PLAYER_WIN_REWARD)

    def test_only_spy_can_guess(self) -> None:
        room = self._room(4)
        room.start(now=0, rng=random.Random(15))
        civilian = next(uid for uid in room.players if uid not in room.spy_ids)
        with self.assertRaises(SpyfallError):
            room.guess(civilian, LOCATIONS[0].key)

    def test_vote_for_spy_wins_for_players(self) -> None:
        room = self._room(4)
        room.start(now=0, rng=random.Random(17))
        spy_id = sorted(room.spy_ids)[0]
        for uid in room.players:
            if uid != spy_id:
                room.cast_vote(uid, spy_id)
        room.cast_vote(spy_id, next(uid for uid in room.players if uid != spy_id))
        self.assertTrue(room.all_voted)
        outcome = room.tally()
        self.assertFalse(outcome.tie)
        self.assertEqual(outcome.winner, Winner.PLAYERS)
        self.assertEqual(outcome.accused_id, spy_id)
        self.assertEqual(outcome.spies, tuple(sorted(room.spy_ids)))

    def test_vote_for_innocent_wins_for_spies(self) -> None:
        room = self._room(4)
        room.start(now=0, rng=random.Random(19))
        spy_id = sorted(room.spy_ids)[0]
        civilian = next(uid for uid in room.players if uid not in room.spy_ids)
        for uid in room.players:
            room.cast_vote(uid, civilian if uid != civilian else spy_id)
        outcome = room.tally()
        self.assertEqual(outcome.winner, Winner.SPIES)
        self.assertEqual(outcome.accused_id, civilian)

    def test_tie_wins_for_spies(self) -> None:
        room = self._room(4)
        room.start(now=0, rng=random.Random(23))
        ids = sorted(room.players)
        room.cast_vote(ids[0], ids[1])
        room.cast_vote(ids[1], ids[0])
        room.cast_vote(ids[2], ids[3])
        room.cast_vote(ids[3], ids[2])
        outcome = room.tally()
        self.assertTrue(outcome.tie)
        self.assertEqual(outcome.winner, Winner.SPIES)
        self.assertIsNone(outcome.accused_id)

    def test_vote_rules(self) -> None:
        room = self._room(4)
        room.start(now=0, rng=random.Random(29))
        ids = sorted(room.players)
        with self.assertRaises(SpyfallError):
            room.cast_vote(ids[0], ids[0])
        room.cast_vote(ids[0], ids[1])
        with self.assertRaises(SpyfallError):
            room.cast_vote(ids[0], ids[2])

    def test_timer_switches_to_voting(self) -> None:
        room = self._room(4)
        room.start(now=100, rng=random.Random(31))
        self.assertEqual(room.phase, Phase.PLAYING)
        self.assertEqual(room.seconds_left(now=100), DEFAULT_ROUND_SECONDS)
        self.assertEqual(
            room.ensure_phase(now=100 + DEFAULT_ROUND_SECONDS + 1), Phase.VOTING
        )
        self.assertEqual(room.seconds_left(now=100 + DEFAULT_ROUND_SECONDS + 5), 0)

    def test_hint_excludes_three_wrong_locations(self) -> None:
        room = self._room(4)
        room.start(now=0, rng=random.Random(37))
        spy_id = sorted(room.spy_ids)[0]
        excluded = room.add_hint(spy_id, rng=random.Random(41))
        self.assertEqual(len(excluded), HINT_ELIMINATIONS)
        self.assertNotIn(room.location.key, excluded)
        self.assertEqual(len(set(excluded)), HINT_ELIMINATIONS)
        self.assertTrue(all(key in LOCATIONS_BY_KEY for key in excluded))
        self.assertEqual(room.add_hint(spy_id), excluded)

        civilian = next(uid for uid in room.players if uid not in room.spy_ids)
        with self.assertRaises(SpyfallError):
            room.add_hint(civilian)

    def test_state_roundtrip(self) -> None:
        room = self._room(5)
        room.start(now=500, rng=random.Random(43))
        spy_id = sorted(room.spy_ids)[0]
        room.add_hint(spy_id, rng=random.Random(47))
        restored = SpyfallRoom.from_state(room.to_state())
        self.assertEqual(restored.code, room.code)
        self.assertEqual(restored.phase, room.phase)
        self.assertEqual(restored.chat_id, room.chat_id)
        self.assertEqual(restored.location.key, room.location.key)
        self.assertEqual(restored.spy_ids, room.spy_ids)
        self.assertEqual(restored.deadline, room.deadline)
        self.assertEqual(
            restored.players[spy_id].hint_exclusions,
            room.players[spy_id].hint_exclusions,
        )


class SpyfallManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = SpyfallManager(seed=7)
        self.economy = EconomyStore(url="", key="", client=None)

    def _started_room(self) -> SpyfallRoom:
        room = self.manager.create_room(91001, "Ali")
        self.manager.join(room.code, 91002, "Vali")
        self.manager.join(room.code, 91003, "Zilola")
        return self.manager.start(room.code, 91001)

    def test_rewards_are_granted_once(self) -> None:
        room = self._started_room()
        spy_id = sorted(room.spy_ids)[0]
        wrong = next(
            location.key for location in LOCATIONS if location.key != room.location.key
        )
        before = {
            uid: self.economy.get_user(uid).coins for uid in room.players
        }
        self.manager.guess(room.code, spy_id, wrong, economy=self.economy)

        for uid in room.players:
            expected = before[uid]
            if uid not in room.spy_ids:
                expected += PLAYER_WIN_REWARD
            self.assertEqual(self.economy.get_user(uid).coins, expected)

        self.manager._award(room, self.economy)
        for uid in room.players:
            expected = before[uid] + (0 if uid in room.spy_ids else PLAYER_WIN_REWARD)
            self.assertEqual(self.economy.get_user(uid).coins, expected)

    def test_hint_costs_coins_once(self) -> None:
        room = self._started_room()
        spy_id = sorted(room.spy_ids)[0]
        before = self.economy.get_user(spy_id).coins
        _, excluded, coins = self.manager.buy_hint(
            room.code, spy_id, economy=self.economy
        )
        self.assertEqual(len(excluded), HINT_ELIMINATIONS)
        self.assertEqual(coins, before - HINT_PRICE)

        _, again, coins_again = self.manager.buy_hint(
            room.code, spy_id, economy=self.economy
        )
        self.assertEqual(again, excluded)
        self.assertEqual(coins_again, coins)

    def test_only_host_can_start(self) -> None:
        room = self.manager.create_room(92001, "Ali")
        self.manager.join(room.code, 92002, "Vali")
        self.manager.join(room.code, 92003, "Zilola")
        with self.assertRaises(SpyfallError):
            self.manager.start(room.code, 92002)


class SpyfallApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "ALLOW_GUEST_AUTH": "true",
                "SUPABASE_URL": "",
                "SUPABASE_KEY": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        get_default_manager().clear()
        self.addCleanup(get_default_manager().clear)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    @staticmethod
    def player(user_id: int, name: str) -> dict[str, object]:
        return {"user_id": user_id, "name": name}

    def _room_with_players(self, ids: tuple[int, ...]) -> str:
        created = self.client.post(
            "/api/spy/create", json=self.player(ids[0], f"Player {ids[0]}")
        )
        self.assertEqual(created.status_code, 200, created.text)
        code = created.json()["state"]["code"]
        for user_id in ids[1:]:
            joined = self.client.post(
                f"/api/spy/{code}/join",
                json=self.player(user_id, f"Player {user_id}"),
            )
            self.assertEqual(joined.status_code, 200, joined.text)
        started = self.client.post(
            f"/api/spy/{code}/start", json=self.player(ids[0], "host")
        )
        self.assertEqual(started.status_code, 200, started.text)
        return code

    def _views(self, code: str, ids: tuple[int, ...]) -> dict[int, dict]:
        views = {}
        for user_id in ids:
            response = self.client.get(f"/api/spy/{code}?user_id={user_id}")
            self.assertEqual(response.status_code, 200, response.text)
            views[user_id] = response.json()
        return views

    def test_room_code_format_and_locations_payload(self) -> None:
        created = self.client.post(
            "/api/spy/create", json=self.player(93001, "Ali")
        )
        payload = created.json()
        self.assertRegex(payload["state"]["code"], r"^SPY\d{3}$")
        self.assertEqual(len(payload["locations"]), len(LOCATIONS))
        self.assertIn("name", payload["locations"][0])

    def test_spy_view_hides_location_until_finish(self) -> None:
        ids = (93101, 93102, 93103)
        code = self._room_with_players(ids)
        views = self._views(code, ids)
        spies = [
            user_id
            for user_id, data in views.items()
            if data["me"]["role"] == "spy"
        ]
        self.assertEqual(len(spies), 1)
        spy_id = spies[0]
        self.assertIsNone(views[spy_id]["me"]["location"])
        for user_id, data in views.items():
            if user_id == spy_id:
                continue
            self.assertIsNotNone(data["me"]["location"])
            self.assertTrue(data["me"]["role_name"])

        actual = next(
            data["me"]["location"]
            for data in views.values()
            if data["me"]["location"]
        )
        wrong = next(
            location.key for location in LOCATIONS if location.key != actual
        )
        guessed = self.client.post(
            f"/api/spy/{code}/guess",
            json={"user_id": spy_id, "location": wrong},
        )
        self.assertEqual(guessed.status_code, 200, guessed.text)
        result = guessed.json()["result"]
        self.assertFalse(result["correct"])
        self.assertEqual(result["winner"], "players")
        self.assertEqual(guessed.json()["state"]["status"], "FINISHED")
        self.assertIsNotNone(guessed.json()["state"]["location"])

    def test_voting_all_players_finishes_game(self) -> None:
        ids = (93201, 93202, 93203)
        code = self._room_with_players(ids)
        views = self._views(code, ids)
        spy_id = next(
            user_id for user_id, data in views.items() if data["me"]["role"] == "spy"
        )
        before = {user_id: get_economy().get_user(user_id).coins for user_id in ids}
        for index, user_id in enumerate(ids):
            response = self.client.post(
                f"/api/spy/{code}/vote",
                json={
                    "user_id": user_id,
                    "name": f"Player {user_id}",
                    "target_id": spy_id if user_id != spy_id
                    else next(uid for uid in ids if uid != spy_id),
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["state"]["status"], "FINISHED")
        self.assertEqual(payload["result"]["winner"], "players")
        self.assertEqual(payload["result"]["accused_id"], spy_id)
        for user_id in ids:
            expected = before[user_id]
            if user_id != spy_id:
                expected += PLAYER_WIN_REWARD
            self.assertEqual(get_economy().get_user(user_id).coins, expected)

    def test_hint_booster_costs_coins(self) -> None:
        ids = (93301, 93302, 93303)
        code = self._room_with_players(ids)
        views = self._views(code, ids)
        spy_id = next(
            user_id for user_id, data in views.items() if data["me"]["role"] == "spy"
        )
        before = get_economy().get_user(spy_id).coins
        response = self.client.post(
            f"/api/spy/{code}/hint", json=self.player(spy_id, "spy")
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["excluded"]), HINT_ELIMINATIONS)
        self.assertEqual(payload["coins"], before - HINT_PRICE)
        self.assertEqual(
            payload["me"]["hint_exclusions"], payload["excluded"]
        )

    def test_non_member_cannot_read_room(self) -> None:
        ids = (93401, 93402, 93403)
        code = self._room_with_players(ids)
        response = self.client.get(f"/api/spy/{code}?user_id=99999")
        self.assertEqual(response.status_code, 403)

    def test_unknown_room_returns_404(self) -> None:
        response = self.client.get("/api/spy/SPY999?user_id=1")
        self.assertEqual(response.status_code, 404)

    def test_requires_identity_outside_guest_mode(self) -> None:
        with patch.dict(os.environ, {"ALLOW_GUEST_AUTH": "false"}):
            response = self.client.post(
                "/api/spy/create", json=self.player(93501, "Guest")
            )
        self.assertEqual(response.status_code, 401)

    def test_new_player_has_start_coins(self) -> None:
        created = self.client.post(
            "/api/spy/create", json=self.player(93601, "Ali")
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["coins"], START_COINS)


if __name__ == "__main__":
    unittest.main()
