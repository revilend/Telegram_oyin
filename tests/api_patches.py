"""API testlari uchun umumiy patch yordamchilari.

Routerlar ``api/deps.py`` dan import qilingan yordamchilarni o'z modulida
ko'radi, shuning uchun ``get_economy`` ni barcha API modullarida birga
almashtirish kerak.
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch
from typing import Any


def patch_economy(economy: Any) -> ExitStack:
    """``get_economy`` ni API ning barcha modullarida ``economy`` ga almashtiradi.

    Qaytgan ``ExitStack`` ni testda ``self.addCleanup(stack.close)`` bilan
    yopish kifoya.
    """
    from api import deps, server
    from api.routers import games, misc, profile, shop, tournaments

    stack = ExitStack()
    for module in (deps, server, games, misc, profile, shop, tournaments):
        stack.enter_context(
            patch.object(module, "get_economy", return_value=economy)
        )
    return stack
