"""Klaviatura tugmalarining uch tilda ishlashini tekshiruvchi regressiya testi.

Har bir pastki menyu tugmasi (`BUTTONS`) uchun `uz`, `ru`, `en` matnlari
handlerning filtrlaridan o'tishi shart. Ilgari «🎮 Быстрая игра» va
«🎮 Quick Game» faqat o'zbekcha filtrga tushib qolgan edi — bu test shu
kabi regressiyalarni ushlaydi.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("ADMIN_ID", "424242")
os.environ.setdefault("CARD_NUMBER", "9860 0000 0000 0000")
os.environ.setdefault("CARD_HOLDER", "Falonchi Pistonchiyev")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")

from core.i18n import BUTTONS, LANGUAGES, all_variants  # noqa: E402

#: Menyu tugmalarini qabul qiladigan handler modullari.
HANDLER_MODULES = (
    "menu",
    "common",
    "rewards",
    "profile",
    "leaderboard",
    "missions",
    "tournaments",
    "matchmaking",
    "shop",
    "admin",
    "games_catalog",
)

#: Har bir tugma qaysi modul handleriga tushishi kerak (kamida bittasi).
EXPECTED_HANDLERS: dict[str, set[str]] = {
    "games": {"menu"},
    "quick_game": {"matchmaking"},
    "games_list": {"menu"},
    "missions": {"menu", "missions"},
    "bonus": {"rewards"},
    "shop": {"menu"},
    "tournaments": {"menu", "tournaments"},
    "profile": {"profile"},
    "leaderboard": {"leaderboard"},
    "promo": {"rewards"},
    "invite": {"common"},
    "rules": {"common"},
    "admin": {"menu"},
    "change_language": {"profile"},
}


class FakeBot:
    """Filtrlar uchun minimal bot obyekti."""

    async def send_message(self, *args, **kwargs) -> None:  # pragma: no cover
        return None


def _message(text: str, chat_type: str = "private") -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        content_type="text",
        chat=SimpleNamespace(id=424242, type=chat_type),
        from_user=SimpleNamespace(id=424242, username="ali", full_name="Ali"),
        bot=FakeBot(),
    )


class ButtonRoutingTest(unittest.TestCase):
    """Tugma matni → handler filtri mosligi."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.routers: list[tuple[str, object]] = []
        for name in HANDLER_MODULES:
            module = importlib.import_module(f"bot.handlers.{name}")
            for attr in ("router", "cancel_router"):
                router = getattr(module, attr, None)
                if router is not None:
                    cls.routers.append((name, router))

    async def _handlers_for(self, text: str) -> set[str]:
        """Matnni qabul qiladigan handler modullari."""
        found: set[str] = set()
        message = _message(text)
        for name, router in self.routers:
            for handler in router.message.handlers:
                matched = True
                for filter_object in handler.filters:
                    try:
                        passed = await filter_object.call(message, bot=message.bot)
                    except Exception:  # Command kabi qo'shimcha kontekst talab qiladi
                        matched = False
                        break
                    if not passed:
                        matched = False
                        break
                if matched:
                    found.add(name)
        return found

    def test_every_button_in_every_language_is_routed(self) -> None:
        missing: list[str] = []
        wrong: list[str] = []

        async def run() -> None:
            for key, variants in BUTTONS.items():
                for lang in LANGUAGES:
                    text = variants[lang]
                    hits = await self._handlers_for(text)
                    if not hits:
                        missing.append(f"{key}/{lang}: {text}")
                        continue
                    expected = EXPECTED_HANDLERS.get(key, set())
                    if expected and not (hits & expected):
                        wrong.append(f"{key}/{lang}: {sorted(hits)}")

        asyncio.run(run())
        self.assertEqual(missing, [], f"Handlerga tushmaydigan tugmalar: {missing}")
        self.assertEqual(wrong, [], f"Noto'g'ri handlerga tushgan tugmalar: {wrong}")

    def test_all_variants_covers_three_languages(self) -> None:
        for key, variants in BUTTONS.items():
            texts = all_variants(key)
            self.assertEqual(len(texts), len(set(texts)))
            for lang in LANGUAGES:
                self.assertIn(variants[lang], texts, f"{key}/{lang}")

    def test_all_variants_rejects_unknown_key(self) -> None:
        with self.assertRaises(KeyError):
            all_variants("yoq_bunday_tugma")

    def test_plain_text_is_not_a_button(self) -> None:
        async def run() -> None:
            for text in ("Salom", "hello", "Привет", "/start"):
                hits = await self._handlers_for(text)
                self.assertEqual(hits, set(), f"{text!r} tugma deb tanildi: {hits}")

        asyncio.run(run())

    def test_cancel_is_recognised_in_three_languages(self) -> None:
        from bot.handlers.common import CANCEL_TEXTS
        from core.i18n import t

        for lang in LANGUAGES:
            self.assertIn(t(lang, "cancel_button"), CANCEL_TEXTS)
            self.assertIn(t(lang, "cancelled"), CANCEL_TEXTS)
        self.assertIn("/cancel", CANCEL_TEXTS)

    def test_no_single_language_text_filters_left(self) -> None:
        """``F.text == "..."`` ko'rinishidagi bir tilli filtr qolmasligi kerak."""
        offenders: list[str] = []
        for path in sorted(Path("bot/handlers").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
                    continue
                left = node.left
                if not (
                    isinstance(left, ast.Attribute)
                    and left.attr == "text"
                    and isinstance(left.value, ast.Name)
                    and left.value.id == "F"
                ):
                    continue
                comparable = node.comparators[0]
                if isinstance(comparable, ast.Constant) and isinstance(
                    comparable.value, str
                ):
                    offenders.append(f"{path}:{node.lineno}")
        self.assertEqual(
            offenders, [], f"Bir tilli F.text == filtrlari: {offenders}"
        )


class KeyboardCoverageTest(unittest.TestCase):
    """Klaviaturada chizilgan har bir tugma uchun handler bor."""

    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "BOT_TOKEN": "123456:TEST",
                "ADMIN_ID": "424242",
                "MINI_APP_URL": "https://revilend.games",
                "SUPABASE_URL": "",
                "SUPABASE_KEY": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_every_keyboard_button_has_all_translations(self) -> None:
        from bot.keyboards.main_menu import build_main_menu

        for lang in LANGUAGES:
            keyboard = build_main_menu(is_admin=True, language=lang)
            for row in keyboard.keyboard:
                for button in row:
                    self.assertTrue(button.text.strip(), (lang, button.text))
                    self.assertIn(
                        button.text,
                        all_button_texts_for_language(button.text),
                        f"{lang}: {button.text!r} lug'atda yo'q",
                    )


def all_button_texts_for_language(text: str) -> set[str]:
    """Barcha tillardagi tugma matnlari to'plami (yordamchi)."""
    return {variants[lang] for variants in BUTTONS.values() for lang in LANGUAGES}


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
