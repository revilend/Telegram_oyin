"""Bot matnlari yangi alifboda qolishini qo'riqlaydigan testlar."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent / "bot"

# Texnik satrlar: buyruq nomlari, callback ma'lumotlari, kalitlar va brendlar.
MACHINE_WORDS = {
    "bot",
    "callback",
    "catch",
    "ch",
    "chat",
    "check",
    "children",
    "choices",
    "finished",
    "hash",
    "match",
    "matchmaking",
    "purchased",
    "sh",
    "share",
    "sheriff",
    "shield",
    "shop",
    "shopsection",
    "shopsec",
    "shopbuy",
    "show",
    "spyfall",
    "watcher",
}

OLD_LETTER = re.compile(r"[oOgG]['‘’ʻ]")
OLD_DIGRAPH = re.compile(r"sh|ch", re.IGNORECASE)
WORD = re.compile(r"[^\W\d_]+(?:['‘’ʻ][^\W\d_]+)*", re.UNICODE)


def _docstring_ids(tree: ast.AST) -> set[int]:
    """Modul, sinf va funksiya docstringlarining id'larini yig'adi."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def iter_bot_texts():
    """bot/ ichidagi foydalanuvchiga ko'rinadigan satr qiymatlarini beradi."""
    for path in sorted(BOT_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = _docstring_ids(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                yield path, node.lineno, node.value


def old_words(text: str) -> set[str]:
    """Satrdagi eski alifbo so'zlarini qaytaradi."""
    found = {
        word
        for word in WORD.findall(text)
        if OLD_LETTER.search(word) or OLD_DIGRAPH.search(word)
    }
    return {word for word in found if word.lower() not in MACHINE_WORDS}


class BotOrthographyTest(unittest.TestCase):
    def test_no_bot_text_uses_the_old_alphabet(self) -> None:
        offenders = [
            f"{path.relative_to(BOT_DIR.parent)}:{line} -> {sorted(old_words(text))}"
            for path, line, text in iter_bot_texts()
            if old_words(text)
        ]
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_start_and_help_use_the_new_alphabet(self) -> None:
        from bot.handlers import common

        texts = {
            "WELCOME_TEXT": common.WELCOME_TEXT,
            "WELCOME_ONLY_TEXT": common.WELCOME_ONLY_TEXT,
            "HELP_TEXT": common.HELP_TEXT,
            "BUNKER_HELP_TEXT": common.BUNKER_HELP_TEXT,
            "MAFIA_HELP_TEXT": common.MAFIA_HELP_TEXT,
            "SPY_HELP_TEXT": common.SPY_HELP_TEXT,
            "ALIAS_HELP_TEXT": common.ALIAS_HELP_TEXT,
            "ECONOMY_HELP_TEXT": common.ECONOMY_HELP_TEXT,
        }
        for name, text in texts.items():
            with self.subTest(text=name):
                self.assertEqual(old_words(text), set())

    def test_games_catalog_uses_the_new_alphabet(self) -> None:
        from bot.handlers import games_catalog

        for name in (
            "CATALOG_TEXT",
            "BUNKER_TEXT",
            "MAFIA_TEXT",
            "SPY_TEXT",
            "ALIAS_TEXT",
        ):
            with self.subTest(text=name):
                self.assertEqual(old_words(getattr(games_catalog, name)), set())

    def test_menu_buttons_use_the_new_alphabet(self) -> None:
        from bot.keyboards import __all__ as exported
        from bot.keyboards import main_menu

        for name in exported:
            value = getattr(main_menu, name, None)
            if isinstance(value, str):
                with self.subTest(button=name):
                    self.assertEqual(old_words(value), set())


if __name__ == "__main__":
    unittest.main()
