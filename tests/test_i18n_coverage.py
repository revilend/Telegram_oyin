"""Uch tillilik qamrovi: UZ / RU / EN hamma joyda to'liqmi.

Bu testlar ``scripts/i18n_audit.py`` natijalarini qo'riqlaydi, shuning uchun
yangi matn qo'shilib tarjimasi unutilib qolsa CI darhol yiqiladi.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.i18n_audit import GAME_SLUGS, LANGS, audit, problems  # noqa: E402


class I18nCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = audit()

    def test_bot_dictionaries_have_three_languages(self) -> None:
        self.assertEqual(self.result["missing"], [])
        self.assertEqual(self.result["empty"], [])
        self.assertGreaterEqual(self.result["strings"]["total"], 100)
        self.assertGreaterEqual(self.result["buttons"]["total"], 10)

    def test_webapp_keys_are_equal_in_all_languages(self) -> None:
        counts = self.result["webapp"]["counts"]
        self.assertEqual(counts["uz"], counts["ru"])
        self.assertEqual(counts["uz"], counts["en"])
        for lang in LANGS:
            self.assertEqual(self.result["webapp"]["missing"][lang], [])
        self.assertEqual(self.result["webapp"]["empty"], [])

    def test_phrase_table_has_three_columns(self) -> None:
        self.assertGreaterEqual(self.result["phrases"]["rows"], 500)
        self.assertEqual(self.result["phrases"]["bad"], [])

    def test_tr_keys_exist_in_dictionary(self) -> None:
        self.assertEqual(self.result["tr_keys"]["missing"], [])

    def test_game_cards_are_translated(self) -> None:
        for slug in GAME_SLUGS:
            for suffix in ("name", "desc"):
                self.assertNotIn(f"game_{slug}_{suffix}", self.result["game_cards"]["missing"])

    def test_audit_reports_no_structural_problems(self) -> None:
        self.assertEqual(problems(self.result), [])


if __name__ == "__main__":
    unittest.main()
