"""Kunlik bonus, promo kodlar, missiyalar va reyting testlari."""

from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import server as server_module
from api.server import app
from bot.handlers import rewards
from core.economy import (
    DAILY_BONUS_BASE,
    START_COINS,
    EconomyError,
    EconomyStore,
)
from core.missions import claim_mission, mission_statuses

NOW = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)


class DailyBonusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EconomyStore(url="", key="", client=None)

    def test_first_claim_gives_base_bonus(self) -> None:
        self.store.ensure_user(71001, "ali", "Ali")
        status = self.store.daily_bonus_status(71001, NOW)
        self.assertTrue(status.available)
        self.assertEqual(status.amount, DAILY_BONUS_BASE)
        self.assertEqual(status.streak, 1)
        self.assertEqual(status.seconds_left, 0)

        claim = self.store.claim_daily_bonus(71001, NOW)
        self.assertEqual(claim.amount, DAILY_BONUS_BASE)
        self.assertEqual(claim.streak, 1)
        self.assertEqual(claim.account.coins, START_COINS + DAILY_BONUS_BASE)
        self.assertTrue(claim.account.last_bonus_at)

        waiting = self.store.daily_bonus_status(71001, NOW + timedelta(hours=1))
        self.assertFalse(waiting.available)
        self.assertEqual(waiting.seconds_left, 23 * 3600)

        with self.assertRaises(EconomyError):
            self.store.claim_daily_bonus(71001, NOW + timedelta(hours=1))
        self.assertEqual(
            self.store.get_user(71001).coins, START_COINS + DAILY_BONUS_BASE
        )

    def test_streak_grows_and_is_capped(self) -> None:
        self.store.ensure_user(71002)
        amounts = [25, 35, 50, 70, 100, 150, 250, 250]
        for day, amount in enumerate(amounts):
            claim = self.store.claim_daily_bonus(71002, NOW + timedelta(days=day))
            self.assertEqual(claim.amount, amount)
            self.assertEqual(claim.streak, min(day + 1, 7))
            self.assertEqual(claim.next_amount, amounts[min(day + 1, 7)])
        account = self.store.get_user(71002)
        self.assertEqual(account.bonus_streak, 7)
        self.assertEqual(account.coins, START_COINS + sum(amounts))

    def test_streak_resets_after_long_break(self) -> None:
        self.store.ensure_user(71003)
        self.store.claim_daily_bonus(71003, NOW)
        claim = self.store.claim_daily_bonus(71003, NOW + timedelta(days=4))
        self.assertEqual(claim.streak, 1)
        self.assertEqual(claim.amount, DAILY_BONUS_BASE)

    def test_streak_alias_columns_are_synced(self) -> None:
        """``users``da ikki nom ham yoziladi va o'qiladi (streak_days / last_daily_claim)."""
        self.store.ensure_user(71005)
        claim = self.store.claim_daily_bonus(71005, NOW)
        account = self.store.get_user(71005)
        self.assertEqual(account.streak_days, account.bonus_streak)
        self.assertEqual(account.last_daily_claim, account.last_bonus_at)
        self.assertEqual(claim.streak_days, claim.streak)
        self.assertEqual(claim.last_daily_claim, claim.account.last_bonus_at)
        status = self.store.daily_bonus_status(71005, NOW + timedelta(hours=1))
        self.assertEqual(status.streak_days, status.streak)
        self.assertEqual(status.last_daily_claim, account.last_bonus_at)

    def test_bonus_fields_survive_coin_operations(self) -> None:
        self.store.ensure_user(71004)
        self.store.claim_daily_bonus(71004, NOW)
        account = self.store.add_coins(71004, 10)
        self.assertTrue(account.last_bonus_at)
        self.assertEqual(account.bonus_streak, 1)
        account = self.store.spend_coins(71004, 10)
        self.assertTrue(account.last_bonus_at)
        self.assertEqual(account.bonus_streak, 1)


class PromoCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EconomyStore(url="", key="", client=None)

    def test_code_is_normalized_and_redeemed_once(self) -> None:
        self.store.ensure_user(72001)
        promo = self.store.create_promo_code("  yangiyil  ", 300, 5, created_by=1)
        self.assertEqual(promo.code, "YANGIYIL")
        self.assertEqual(promo.max_uses, 5)

        result = self.store.redeem_promo_code(72001, "yangiYIL")
        self.assertEqual(result.code, "YANGIYIL")
        self.assertEqual(result.coins, 300)
        self.assertEqual(result.account.coins, START_COINS + 300)
        self.assertTrue(self.store.has_redeemed_promo(72001, "YANGIYIL"))
        self.assertEqual(self.store.get_promo_code("YANGIYIL").used_count, 1)

        with self.assertRaises(EconomyError):
            self.store.redeem_promo_code(72001, "YANGIYIL")

    def test_usage_limit_is_shared_between_users(self) -> None:
        for user_id in (72002, 72003, 72004):
            self.store.ensure_user(user_id)
        self.store.create_promo_code("LIMIT2", 100, 2)
        self.store.redeem_promo_code(72002, "LIMIT2")
        self.store.redeem_promo_code(72003, "LIMIT2")
        with self.assertRaises(EconomyError):
            self.store.redeem_promo_code(72004, "LIMIT2")
        self.assertEqual(self.store.get_promo_code("LIMIT2").used_count, 2)

    def test_unknown_and_invalid_codes(self) -> None:
        self.store.ensure_user(72005)
        with self.assertRaises(EconomyError):
            self.store.redeem_promo_code(72005, "NOPE123")
        with self.assertRaises(EconomyError):
            self.store.create_promo_code("AB", 100)
        with self.assertRaises(EconomyError):
            self.store.create_promo_code("VALID123", 0)
        with self.assertRaises(EconomyError):
            self.store.create_promo_code("VALID123", 100, 0)

    def test_duplicate_code_is_rejected(self) -> None:
        self.store.create_promo_code("DUPCODE", 50)
        with self.assertRaises(EconomyError):
            self.store.create_promo_code("dupcode", 100)

    def test_promo_listing_is_newest_first(self) -> None:
        self.store.create_promo_code("FIRSTCODE", 50)
        self.store.create_promo_code("SECONDCODE", 60)
        codes = [promo.code for promo in self.store.list_promo_codes(5)]
        self.assertEqual(codes, ["SECONDCODE", "FIRSTCODE"])


class MissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EconomyStore(url="", key="", client=None)

    def test_progress_and_claim(self) -> None:
        statuses = mission_statuses(self.store, 73001)
        self.assertEqual(len(statuses), 5)
        self.assertEqual(
            [item.mission.key for item in statuses],
            ["first_game", "first_win", "friend_1", "bonus_3", "games_5"],
        )
        self.assertEqual(
            [item.mission.reward for item in statuses], [50, 100, 75, 120, 200]
        )
        self.assertFalse(any(status.claimable for status in statuses))

        self.store.record_finished_game("BNKM7301", [73001, 73002], [73001])
        statuses = {item.mission.key: item for item in mission_statuses(self.store, 73001)}
        self.assertTrue(statuses["first_game"].claimable)
        self.assertTrue(statuses["first_win"].claimable)
        self.assertFalse(statuses["games_5"].claimable)
        self.assertEqual(statuses["first_game"].percent, 100)

        status, account = claim_mission(self.store, 73001, "first_win")
        self.assertTrue(status.claimed)
        self.assertEqual(account.coins, START_COINS + 100)

        with self.assertRaises(EconomyError):
            claim_mission(self.store, 73001, "first_win")
        with self.assertRaises(EconomyError):
            claim_mission(self.store, 73001, "games_5")
        with self.assertRaises(EconomyError):
            claim_mission(self.store, 73001, "nope")

    def test_bonus_streak_unlocks_mission(self) -> None:
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        for day in range(2):
            self.store.claim_daily_bonus(73005, now + timedelta(days=day))
        statuses = {
            item.mission.key: item for item in mission_statuses(self.store, 73005)
        }
        self.assertFalse(statuses["bonus_3"].claimable)

        self.store.claim_daily_bonus(73005, now + timedelta(days=2))
        statuses = {
            item.mission.key: item for item in mission_statuses(self.store, 73005)
        }
        self.assertTrue(statuses["bonus_3"].claimable)
        self.assertEqual(statuses["bonus_3"].progress, 3)

    def test_referral_progress(self) -> None:
        self.store.ensure_user(73003)
        self.store.ensure_user(73004)
        self.store.register_referral(73003, 73004)
        statuses = {item.mission.key: item for item in mission_statuses(self.store, 73003)}
        self.assertEqual(statuses["friend_1"].progress, 1)
        self.assertTrue(statuses["friend_1"].claimable)
        self.assertFalse(statuses["games_5"].claimable)
        self.assertFalse(statuses["bonus_3"].claimable)


class RewardsApiTest(unittest.TestCase):
    """Mini App endpointlari alohida xotiradagi hamyon bilan sinaladi."""

    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "ALLOW_GUEST_AUTH": "true",
                "SUPABASE_URL": "",
                "SUPABASE_KEY": "",
                "BOT_TOKEN": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

        self.economy = EconomyStore(url="", key="", client=None)
        self.economy_patch = patch.object(
            server_module, "get_economy", return_value=self.economy
        )
        self.economy_patch.start()
        self.addCleanup(self.economy_patch.stop)

        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_bonus_endpoints(self) -> None:
        status = self.client.get("/api/bonus?user_id=74001")
        self.assertEqual(status.status_code, 200, status.text)
        self.assertTrue(status.json()["bonus"]["available"])
        self.assertEqual(status.json()["coins"], START_COINS)

        claim = self.client.post("/api/bonus", json={"user_id": 74001})
        self.assertEqual(claim.status_code, 200, claim.text)
        self.assertEqual(claim.json()["amount"], DAILY_BONUS_BASE)
        self.assertEqual(claim.json()["coins"], START_COINS + DAILY_BONUS_BASE)
        self.assertFalse(claim.json()["bonus"]["available"])

        again = self.client.post("/api/bonus", json={"user_id": 74001})
        self.assertEqual(again.status_code, 400, again.text)
        self.assertIn("allaqachon", again.json()["detail"])

    def test_mission_endpoints(self) -> None:
        before = self.client.post(
            "/api/missions/first_game/claim", json={"user_id": 74002}
        )
        self.assertEqual(before.status_code, 400, before.text)

        self.economy.record_finished_game("BNKM7400", [74002], [74002])
        listing = self.client.get("/api/missions?user_id=74002")
        self.assertEqual(listing.status_code, 200, listing.text)
        missions = {item["key"]: item for item in listing.json()["missions"]}
        self.assertTrue(missions["first_game"]["claimable"])

        claim = self.client.post(
            "/api/missions/first_game/claim", json={"user_id": 74002}
        )
        self.assertEqual(claim.status_code, 200, claim.text)
        self.assertTrue(claim.json()["mission"]["claimed"])
        self.assertEqual(claim.json()["coins"], START_COINS + 50)

        again = self.client.post(
            "/api/missions/first_game/claim", json={"user_id": 74002}
        )
        self.assertEqual(again.status_code, 400, again.text)

    def test_promo_endpoint(self) -> None:
        self.economy.create_promo_code("APITEST", 250, 2)
        first = self.client.post(
            "/api/promo", json={"user_id": 74003, "code": "apitest"}
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["amount"], 250)
        self.assertEqual(first.json()["coins"], START_COINS + 250)

        second = self.client.post(
            "/api/promo", json={"user_id": 74003, "code": "APITEST"}
        )
        self.assertEqual(second.status_code, 400, second.text)
        self.assertIn("allaqachon", second.json()["detail"])

    def test_promo_endpoint_rejects_invalid_code(self) -> None:
        response = self.client.post(
            "/api/promo", json={"user_id": 74007, "code": "AB"}
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("Promo kod", response.json()["detail"])

    def test_top_endpoint_ranks_players(self) -> None:
        for user_id, winner in ((74004, True), (74005, True), (74006, False)):
            self.economy.record_finished_game(
                f"BNKM7{user_id}",
                [user_id],
                [user_id] if winner else [],
            )

        payload = self.client.get("/api/top?limit=2&user_id=74005").json()
        self.assertEqual(len(payload["top"]), 2)
        self.assertEqual(payload["top"][0]["rank"], 1)
        self.assertTrue(any(row["is_me"] for row in payload["top"]))
        self.assertTrue(payload["me"]["is_me"])
        self.assertGreaterEqual(payload["me"]["rank"], 1)

        outside = self.client.get("/api/top?limit=1&user_id=74006").json()
        self.assertEqual(outside["me"]["rank"], 3)
        self.assertFalse(outside["me"]["in_top"])


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append((chat_id, text))


class FakeMessage:
    def __init__(self, user_id: int = 75001, text: str = "") -> None:
        self.from_user = SimpleNamespace(
            id=user_id, username="ali", full_name="Ali Valiyev"
        )
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.text = text
        self.bot = FakeBot()
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)


class FakeState:
    def __init__(self) -> None:
        self.state = None
        self.cleared = False

    async def set_state(self, state) -> None:
        self.state = state

    async def clear(self) -> None:
        self.state = None
        self.cleared = True


class RewardsHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EconomyStore(url="", key="", client=None)
        self.store_patch = patch.object(
            rewards, "get_economy", return_value=self.store
        )
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)

    def test_bonus_button_claims_once(self) -> None:
        message = FakeMessage(user_id=75002)
        asyncio.run(rewards.claim_bonus(message))
        self.assertIn("Kunlik bonus olindi", message.answers[-1])
        self.assertEqual(
            self.store.get_user(75002).coins, START_COINS + DAILY_BONUS_BASE
        )

        again = FakeMessage(user_id=75002)
        asyncio.run(rewards.claim_bonus(again))
        self.assertIn("allaqachon", again.answers[-1])

    def test_bonus_message_shows_table_and_next_reward(self) -> None:
        claim = self.store.claim_daily_bonus(75005)
        text = rewards.bonus_text(claim)
        self.assertIn("1-kun", text)
        self.assertIn("+25", text)
        self.assertIn("7-kun", text)
        self.assertIn("Katta mukofot", text)
        self.assertIn("+35", text)
        self.assertIn("Ertaga kirsangiz", text)
        self.assertIn("2-kun", text)

        status = self.store.daily_bonus_status(75005)
        wait = rewards.bonus_wait_text("Kunlik bonus allaqachon olingan", status)
        self.assertIn("seriya", wait)
        self.assertIn("+25", wait)
        self.assertIn("Kunlik mukofotlar jadvali", wait)

    def test_promo_flow(self) -> None:
        self.store.create_promo_code("BOTPROMO", 120)
        state = FakeState()
        prompt = FakeMessage(user_id=75003)
        asyncio.run(rewards.ask_promo(prompt, state))
        self.assertIs(state.state, rewards.RewardStates.waiting_promo)
        self.assertIn("Promo kod", prompt.answers[-1])

        message = FakeMessage(user_id=75003, text="botpromo")
        asyncio.run(rewards.save_promo(message, state))
        self.assertTrue(state.cleared)
        self.assertIn("qabul qilindi", message.answers[-1])
        self.assertEqual(
            self.store.get_user(75003).coins, START_COINS + 120
        )

    def test_invalid_promo_keeps_state(self) -> None:
        state = FakeState()
        asyncio.run(rewards.ask_promo(FakeMessage(user_id=75004), state))
        message = FakeMessage(user_id=75004, text="YOQKOD")
        asyncio.run(rewards.save_promo(message, state))
        self.assertFalse(state.cleared)
        self.assertIn("topilmadi", message.answers[-1])


if __name__ == "__main__":
    unittest.main()
