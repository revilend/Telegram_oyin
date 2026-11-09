"""Bloklangan foydalanuvchi middleware testlari."""

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot import middlewares
from bot.config import get_config
from core.economy import EconomyStore


class FakeEvent:
    def __init__(self, user_id: int) -> None:
        self.from_user = SimpleNamespace(id=user_id)


class BlockedMiddlewareTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "BOT_TOKEN": "123456:TEST",
                "ADMIN_ID": "424242",
                "SUPABASE_URL": "",
                "SUPABASE_KEY": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        get_config.cache_clear()
        self.addCleanup(get_config.cache_clear)
        self.store = EconomyStore(url="", key="", client=None)

    def _run(self, user_id: int):
        handler = AsyncMock(return_value="ok")
        middleware = middlewares.BlockedUserMiddleware()
        with patch.object(middlewares, "get_economy", return_value=self.store):
            result = asyncio.run(
                middleware(handler, FakeEvent(user_id), {})
            )
        return result, handler

    def test_blocked_user_does_not_reach_handler(self) -> None:
        self.store.ensure_user(777, "blocked", "Blocked")
        self.store.set_blocked(777, True)
        result, handler = self._run(777)
        self.assertIsNone(result)
        handler.assert_not_awaited()

    def test_unblocked_user_reaches_handler(self) -> None:
        self.store.ensure_user(778, "ok", "OK")
        result, handler = self._run(778)
        self.assertEqual(result, "ok")
        handler.assert_awaited_once()

    def test_root_admin_is_never_blocked(self) -> None:
        self.store.ensure_user(424242, "root", "Root")
        self.store.set_blocked(424242, True)
        result, handler = self._run(424242)
        self.assertEqual(result, "ok")
        handler.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
