"""Rate limiting va per-user lock (double-spend) testlari.

Talab: bir foydalanuvchidan sekundiga 2 tadan ko'p so'rov ``429`` oladi va
bir vaqtda yuborilgan 5 ta parallel spin/buy so'rovidan faqat bittasi
bajariladi.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")

from fastapi.testclient import TestClient  # noqa: E402

from api.server import app  # noqa: E402
from core.economy import START_COINS, EconomyStore  # noqa: E402
from core.rate_limit import (  # noqa: E402
    RateLimiter,
    reset_rate_limits,
    reset_user_locks,
    user_lock,
)
from core.shop import (  # noqa: E402
    CATALOG_BY_SLUG,
    SPIN_COST,
    ShopStore,
    WheelSegment,
    get_shop_store,
    set_shop_store,
)

try:  # unittest discover -s tests
    from api_patches import patch_economy
except ImportError:  # pytest / paket sifatida
    from tests.api_patches import patch_economy

#: Bir vaqtda yuboriladigan so'rovlar soni.
PARALLEL = 5

#: Tekshiruv uchun arzon buyum.
ITEM = CATALOG_BY_SLUG["booster_double_vote"]

#: Tanga bermaydigan sektor — balans o'zgarmaydi, spin deterministik bo'ladi.
NO_COIN_SEGMENT = WheelSegment(
    "frame_gold", "Oltin ramka", 1, item_slug="frame_gold", emoji="🖼"
)


class RateLimiterUnitTest(unittest.TestCase):
    """Limiter oynasi va kalit izolyatsiyasi."""

    def test_two_requests_per_second_per_key(self) -> None:
        limiter = RateLimiter(limit=2, window=1.0)
        self.assertTrue(limiter.allow("buy:1"))
        self.assertTrue(limiter.allow("buy:1"))
        self.assertFalse(limiter.allow("buy:1"))
        # Boshqa foydalanuvchi cheklanmaydi.
        self.assertTrue(limiter.allow("buy:2"))
        # Boshqa amal ham alohida hisoblanadi.
        self.assertTrue(limiter.allow("spin:1"))

    def test_window_expiry_and_reset(self) -> None:
        limiter = RateLimiter(limit=1, window=0.05)
        self.assertTrue(limiter.allow("promo:9"))
        self.assertFalse(limiter.allow("promo:9"))
        self.assertGreaterEqual(limiter.retry_after("promo:9"), 0.0)
        limiter.reset()
        self.assertTrue(limiter.allow("promo:9"))


class UserLockUnitTest(unittest.TestCase):
    """Per-user ``asyncio.Lock`` bir vaqtda ikki jarayonni o'tkazmaydi."""

    def test_same_user_tasks_are_serialized(self) -> None:
        async def scenario() -> list[tuple[str, int]]:
            events: list[tuple[str, int]] = []

            async def worker(index: int) -> None:
                async with user_lock(991, "wallet"):
                    events.append(("start", index))
                    await asyncio.sleep(0.01)
                    events.append(("end", index))

            await asyncio.gather(*(worker(index) for index in range(PARALLEL)))
            return events

        events = asyncio.run(scenario())
        self.assertEqual(len(events), PARALLEL * 2)
        for index in range(0, len(events), 2):
            self.assertEqual(events[index][0], "start")
            self.assertEqual(events[index + 1][0], "end")
            self.assertEqual(events[index][1], events[index + 1][1])

    def test_different_users_do_not_share_lock(self) -> None:
        async def scenario() -> bool:
            return user_lock(1) is user_lock(2)

        self.assertFalse(asyncio.run(scenario()))


class ParallelPurchaseTest(unittest.TestCase):
    """5 ta parallel so'rovdan faqat bittasi muvaffaqiyatli bo'ladi."""

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
        self.addCleanup(patch_economy(self.economy).close)
        set_shop_store(ShopStore(economy=self.economy))
        self.addCleanup(set_shop_store, None)
        reset_rate_limits()
        reset_user_locks()
        self.addCleanup(reset_rate_limits)
        self.addCleanup(reset_user_locks)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    # ------------------------------------------------------------ helpers
    def _set_coins(self, user_id: int, target: int) -> None:
        self.economy.ensure_user(user_id, "tester", "Tester")
        current = self.economy.get_user(user_id).coins
        delta = int(target) - int(current)
        if delta > 0:
            self.economy.add_coins(user_id, delta)
        elif delta < 0:
            self.economy.spend_coins(user_id, -delta)

    def _buy_many(self, user_id: int, slug: str) -> list:
        def call(_: int):
            return self.client.post(
                "/api/shop/buy",
                json={"user_id": user_id, "item_slug": slug},
            )

        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            return list(pool.map(call, range(PARALLEL)))

    def _spin_many(self, user_id: int) -> list:
        def call(_: int):
            return self.client.post("/api/spin/wheel", json={"user_id": user_id})

        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            return list(pool.map(call, range(PARALLEL)))

    def _claim_bonus_many(self, user_id: int) -> list:
        def call(_: int):
            return self.client.post("/api/bonus", json={"user_id": user_id})

        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            return list(pool.map(call, range(PARALLEL)))

    # -------------------------------------------------------------- tests
    def test_parallel_buys_spend_coins_once(self) -> None:
        user_id = 960_101
        balance = ITEM.price + 5  # faqat bitta xaridga yetadi
        self._set_coins(user_id, balance)

        responses = self._buy_many(user_id, ITEM.slug)
        statuses = sorted(response.status_code for response in responses)

        self.assertEqual(statuses.count(200), 1, statuses)
        for status in statuses:
            # 200 — o'tdi; 400/402/409 — biznes qoidasi; 429 — rate limit.
            self.assertIn(status, {200, 400, 402, 409, 429}, statuses)

        self.assertEqual(self.economy.get_user(user_id).coins, 5)
        entries = {
            entry.item_slug: entry.quantity
            for entry in get_shop_store().inventory(user_id)
        }
        self.assertEqual(entries.get(ITEM.slug), 1)
        self.assertEqual(len(get_shop_store().transactions()), 1)

    def test_parallel_spins_use_free_spin_once(self) -> None:
        user_id = 960_102
        self._set_coins(user_id, 0)  # bepul aylantirişdan keyin tanga yo'q

        # Sovrin tanga bo'lmasin: aks holda ikkinchi aylantiriş to'lanadi.
        with patch("core.shop.pick_segment", return_value=NO_COIN_SEGMENT):
            responses = self._spin_many(user_id)
        statuses = sorted(response.status_code for response in responses)

        self.assertEqual(statuses.count(200), 1, statuses)
        for status in statuses:
            # 200 — o'tdi; 400/402/409 — biznes qoidasi; 429 — rate limit.
            self.assertIn(status, {200, 400, 402, 409, 429}, statuses)

        # Bepul aylantiriş işlatilgan: keyingi spin endi bepul emas.
        self.assertFalse(get_shop_store().spin_status(user_id)["free"])

    def test_parallel_bonus_claims_pay_once(self) -> None:
        user_id = 960_103
        self._set_coins(user_id, 0)

        responses = self._claim_bonus_many(user_id)
        statuses = sorted(response.status_code for response in responses)

        self.assertEqual(statuses.count(200), 1, statuses)
        for status in statuses:
            # 200 — o'tdi; 400/402/409 — biznes qoidasi; 429 — rate limit.
            self.assertIn(status, {200, 400, 402, 409, 429}, statuses)
        self.assertGreater(self.economy.get_user(user_id).coins, 0)

    def test_burst_requests_get_429_with_retry_after(self) -> None:
        user_id = 960_104
        self._set_coins(user_id, ITEM.price * 10)

        self.assertEqual(
            self.client.post(
                "/api/shop/buy", json={"user_id": user_id, "item_slug": ITEM.slug}
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/shop/buy", json={"user_id": user_id, "item_slug": ITEM.slug}
            ).status_code,
            200,
        )
        blocked = self.client.post(
            "/api/shop/buy", json={"user_id": user_id, "item_slug": ITEM.slug}
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)
        self.assertEqual(
            self.economy.get_user(user_id).coins,
            ITEM.price * 10 - ITEM.price * 2,
        )

    def test_spin_cost_is_not_charged_twice(self) -> None:
        user_id = 960_105
        # Balans aynan ikkita to'langan spin uchun yetadi.
        self._set_coins(user_id, SPIN_COST * 2)

        # 1) Bepul aylantiriş: tanga sarflanmaydi (sovrin ham tanga emas).
        with patch("core.shop.pick_segment", return_value=NO_COIN_SEGMENT):
            free = self.client.post("/api/spin/wheel", json={"user_id": user_id})
        self.assertEqual(free.status_code, 200, free.text)
        self.assertTrue(free.json()["free"])
        self.assertEqual(free.json()["expense"], 0)
        coins_after_free = self.economy.get_user(user_id).coins
        self.assertEqual(coins_after_free, SPIN_COST * 2)
        reset_rate_limits()

        # 2) 5 ta parallel to'langan spin: pul faqat ikkitasiga yetadi.
        with patch("core.shop.pick_segment", return_value=NO_COIN_SEGMENT):
            responses = self._spin_many(user_id)

        paid = [r for r in responses if r.status_code == 200]
        self.assertEqual(
            len(paid), 2, [r.status_code for r in responses]
        )
        for status in (r.status_code for r in responses if r.status_code != 200):
            # 402 — balans yetmadi, 429 — rate limit; 5xx bo'lmasligi kerak.
            self.assertIn(status, {402, 429})

        # Har bir to'langan spin aynan bir marta yechilgan.
        for response in paid:
            payload = response.json()
            self.assertFalse(payload["free"])
            self.assertFalse(payload["ticket_used"])
            self.assertEqual(payload["expense"], SPIN_COST)

        spent = coins_after_free - self.economy.get_user(user_id).coins
        self.assertEqual(spent, SPIN_COST * len(paid))
        self.assertEqual(self.economy.get_user(user_id).coins, 0)

        # Chipta ishlatilmagan va ortiqcha yechim yo'q.
        inventory = {
            entry.item_slug: entry.quantity
            for entry in get_shop_store().inventory(user_id)
        }
        self.assertFalse(inventory.get("spin_extra"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
