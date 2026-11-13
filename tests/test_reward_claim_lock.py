"""Mukofot yechish endpointlarida rate limit va per-user lock testlari.

Talab: missiya, kunlik topshiriq va haftalik sandiq mukofotlarini bir
vaqtda 5 ta parallel so'rov bilan so'rasa ham faqat **bittasi** bajariladi
(mukofot ikki marta berilmaydi), qolganlari 400 yoki 429 oladi.
"""

from __future__ import annotations

import os
import unittest
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")

from fastapi.testclient import TestClient  # noqa: E402

from api.server import app  # noqa: E402
from core import daily_quests  # noqa: E402
from core.daily_quests import (  # noqa: E402
    CHEST_REWARD,
    CHEST_TARGET,
    EVENT_METRICS,
    daily_quests_payload,
)
from core.economy import START_COINS, EconomyStore  # noqa: E402
from core.rate_limit import reset_rate_limits, reset_user_locks  # noqa: E402

try:  # unittest discover -s tests
    from api_patches import patch_economy
except ImportError:  # pytest / paket sifatida
    from tests.api_patches import patch_economy

#: Bir vaqtda yuboriladigan so'rovlar soni.
PARALLEL = 5


class RewardClaimLockTest(unittest.TestCase):
    """Uchala mukofot endpointi ham parallel so'rovda bitta mukofot beradi."""

    def setUp(self) -> None:
        import unittest.mock as mock

        self.env = mock.patch.dict(
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

        daily_quests.reset_memory()
        reset_rate_limits()
        reset_user_locks()
        self.addCleanup(reset_user_locks)

        self.economy = EconomyStore(url="", key="", client=None)
        self.economy_patch = patch_economy(self.economy)
        self.addCleanup(self.economy_patch.close)

        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    # -- yordamchilar -------------------------------------------------
    def _coins(self, user_id: int) -> int:
        response = self.client.get(f"/api/quests?user_id={user_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return int(response.json()["coins"])

    def _claim_many(self, path: str, user_id: int, times: int = PARALLEL):
        """``times`` ta so'rovni bir vaqtda yuboradi."""

        def post():
            return self.client.post(path, json={"user_id": user_id})

        with ThreadPoolExecutor(max_workers=times) as pool:
            return list(pool.map(lambda _: post(), range(times)))

    def _assert_single_claim(self, responses, reward: int, user_id: int) -> None:
        codes = sorted(response.status_code for response in responses)
        succeeded = [response for response in responses if response.status_code == 200]
        self.assertEqual(
            len(succeeded), 1, f"faqat bitta so'rov o'tishi kerak: {codes}"
        )
        for code in codes:
            self.assertIn(code, {200, 400, 429}, f"kutilmagan status: {codes}")
        self.assertIn(429, codes, f"rate limit ishlamadi: {codes}")
        self.assertEqual(
            self._coins(user_id),
            START_COINS + reward,
            "mukofot faqat bir marta berilishi kerak",
        )

    # -- testlar ------------------------------------------------------
    def test_mission_claim_is_locked(self) -> None:
        user_id = 950_101
        self.economy.record_finished_game("BNKM950101", [user_id], [user_id])
        responses = self._claim_many(f"/api/missions/first_game/claim", user_id)
        self._assert_single_claim(responses, 50, user_id)

    def test_daily_quest_claim_is_locked(self) -> None:
        user_id = 950_102
        daily = daily_quests_payload(self.economy, user_id)["quests"]
        quest = next(
            item
            for item in daily
            if item["claimable"] is False and item["claimed"] is False
        )
        metric = next(
            candidate.metric
            for candidate in daily_quests.QUESTS
            if candidate.key == quest["key"]
        )
        target = int(quest["target"])
        if metric in EVENT_METRICS:
            daily_quests.record_daily_event(self.economy, user_id, metric, target)
        elif metric == "games_played":
            for index in range(target):
                self.economy.record_finished_game(
                    f"BNKM95{user_id}{index}", [user_id], []
                )
        else:  # wins / referral_count
            for index in range(target):
                self.economy.record_finished_game(
                    f"BNKM9W{user_id}{index}", [user_id], [user_id]
                )

        responses = self._claim_many(
            f"/api/quests/{quest['key']}/claim", user_id
        )
        self._assert_single_claim(responses, int(quest["reward"]), user_id)

    def test_weekly_chest_claim_is_locked(self) -> None:
        user_id = 950_103
        # Sandiq sharti: haftada 5 ta topshiriq mukofoti olingan bo'lishi.
        daily_quests._MEMORY_PROFILES[user_id] = {
            "week": daily_quests._week_key(),
            "claims": CHEST_TARGET,
            "chest_claimed": False,
        }
        responses = self._claim_many("/api/quests/chest", user_id)
        self._assert_single_claim(responses, CHEST_REWARD, user_id)

    def test_sequential_second_claim_is_rejected(self) -> None:
        """Lockdan tashqari: ketma-ket takroriy so'rov ham 400 oladi."""
        user_id = 950_104
        self.economy.record_finished_game("BNKM950104", [user_id], [user_id])
        first = self.client.post(
            "/api/missions/first_game/claim", json={"user_id": user_id}
        )
        self.assertEqual(first.status_code, 200, first.text)
        reset_rate_limits()
        again = self.client.post(
            "/api/missions/first_game/claim", json={"user_id": user_id}
        )
        self.assertEqual(again.status_code, 400, again.text)
        self.assertEqual(self._coins(user_id), START_COINS + 50)


if __name__ == "__main__":
    unittest.main()
