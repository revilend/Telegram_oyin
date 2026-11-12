"""API testlari uchun umumiy patch yordamchilari.

``get_economy`` har bir API moduliga nom sifatida import qilinadi (yulduzchali
import yo'q), shuning uchun patch ham har bir modulda alohida qo'llanadi.
Modullar ro'yxati ``api.routers.__all__`` dan olinadi — yangi router qo'shilsa
yordamchi uni o'zi qamrab oladi.
"""

from __future__ import annotations

import importlib
from contextlib import ExitStack
from types import ModuleType
from typing import Any
from unittest.mock import patch


def _api_modules() -> list[ModuleType]:
    """``get_economy`` bog'langan API modullari: deps, server va routerlar."""
    from api import deps, routers, server

    modules = [deps, server]
    modules.extend(
        importlib.import_module(f"api.routers.{name}") for name in routers.__all__
    )
    return [module for module in modules if hasattr(module, "get_economy")]


def patch_economy(economy: Any) -> ExitStack:
    """``get_economy`` ni API ning barcha modullarida ``economy`` ga almashtiradi.

    Qaytgan ``ExitStack`` ni testda ``self.addCleanup(stack.close)`` bilan
    yopish kifoya.
    """
    stack = ExitStack()
    for module in _api_modules():
        stack.enter_context(
            patch.object(module, "get_economy", return_value=economy)
        )
    return stack
