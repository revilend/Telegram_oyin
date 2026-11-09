"""Uch tillilik (UZ/RU/EN) bot lug'ati testlari (webapp'ga tegilmagan)."""

from __future__ import annotations

import unittest

from bot.keyboards.main_menu import BUTTON_TEXTS, build_main_menu
from core.economy import EconomyStore
from core.i18n import (
    BUTTONS,
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    STRINGS,
    all_button_texts,
    default_label,
    normalize_language,
    t,
)


class NormalizeTest(unittest.TestCase):
    def test_telegram_codes(self) -> None:
        self.assertEqual(normalize_language("ru"), "ru")
        self.assertEqual(normalize_language("ru-RU"), "ru")
        self.assertEqual(normalize_language("en"), "en")
        self.assertEqual(normalize_language("en-US"), "en")
        self.assertEqual(normalize_language("uz"), "uz")
        self.assertEqual(normalize_language("uz-Latn"), "uz")

    def test_unknown_defaults_to_uz(self) -> None:
        self.assertEqual(normalize_language("de"), "uz")
        self.assertEqual(normalize_language(None), DEFAULT_LANGUAGE)
        self.assertEqual(DEFAULT_LANGUAGE, "uz")


class DictionaryTest(unittest.TestCase):
    def test_all_spec_keys_exist_in_three_languages(self) -> None:
        for key in (
            "language_prompt",
            "welcome",
            "profile_title",
            "profile_coins",
            "catalog_title",
            "catalog_bunker",
            "catalog_mafia",
            "catalog_spy",
            "catalog_alias",
            "catalog_bomb",
            "leaderboard_title",
            "invite_title",
            "login_title",
            "tournament_rules",
            "room_created",
            "room_started",
            "room_finished",
            "cancelled",
            "help_text",
        ):
            for lang in ("uz", "ru", "en"):
                self.assertIn(lang, STRINGS[key], f"{key}/{lang}")
                self.assertTrue(STRINGS[key][lang])

    def test_button_labels_three_languages(self) -> None:
        self.assertEqual(default_label("quick_game", "uz"), "🎮 Tezkor öyin")
        self.assertEqual(default_label("quick_game", "ru"), "🎮 Быстрая игра")
        self.assertEqual(default_label("quick_game", "en"), "🎮 Quick Game")
        self.assertEqual(default_label("profile", "en"), "👤 My Profile")

    def test_t_formats_params(self) -> None:
        text = t("ru", "registered_bonus", amount=100)
        self.assertIn("100", text)
        self.assertNotIn("{amount}", text)

    def test_language_prompt_trilingual(self) -> None:
        prompt = t("uz", "language_prompt")
        self.assertIn("Iltimos", prompt)
        self.assertIn("Пожалуйста", prompt)
        self.assertIn("Please", prompt)


class MenuTest(unittest.TestCase):
    def test_main_menu_labels_per_language(self) -> None:
        import os
        from unittest.mock import patch

        env = {
            "BOT_TOKEN": "123456:TEST",
            "MINI_APP_URL": "https://example.com",
            "ADMIN_ID": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            pass
        for lang in ("uz", "ru", "en"):
            with patch.dict(os.environ, env, clear=False):
                menu = build_main_menu(language=lang)
            texts = [
                button.text for row in menu.keyboard for button in row
            ]
            self.assertIn(BUTTONS["quick_game"][lang], texts)
            self.assertIn(BUTTONS["profile"][lang], texts)
            self.assertIn(BUTTONS["leaderboard"][lang], texts)
            self.assertIn(BUTTONS["tournaments"][lang], texts)
        return
        for lang in ("uz", "ru", "en"):
            menu = build_main_menu(language=lang)
            texts = [
                button.text for row in menu.keyboard for button in row
            ]
            self.assertIn(BUTTONS["quick_game"][lang], texts)
            self.assertIn(BUTTONS["profile"][lang], texts)
            self.assertIn(BUTTONS["leaderboard"][lang], texts)
            self.assertIn(BUTTONS["tournaments"][lang], texts)

    def test_button_texts_cover_all_languages(self) -> None:
        for lang in ("uz", "ru", "en"):
            self.assertIn(BUTTONS["shop"][lang], BUTTON_TEXTS)
            self.assertIn(BUTTONS["profile"][lang], BUTTON_TEXTS)
        self.assertEqual(all_button_texts("missions"), frozenset(
            {BUTTONS["missions"][lang] for lang in ("uz", "ru", "en")}
        ))


class EconomyLanguageTest(unittest.TestCase):
    def test_set_language_persists_and_reads(self) -> None:
        economy = EconomyStore(url="", key="", client=None)
        economy.ensure_user(778899, "test", "Test User")
        account = economy.set_language(778899, "ru")
        self.assertEqual(account.language_code, "ru")
        self.assertEqual(economy.find_user(778899).language_code, "ru")
        account = economy.set_language(778899, "en-US")
        self.assertEqual(account.language_code, "en")

    def test_language_defaults_to_uz(self) -> None:
        economy = EconomyStore(url="", key="", client=None)
        account = economy.ensure_user(778900, "test", "Test")
        self.assertEqual(normalize_language(account.language_code), "uz")


class ProfileLanguageTest(unittest.TestCase):
    def test_profile_text_three_languages(self) -> None:
        from bot.handlers.profile import profile_text

        economy = EconomyStore(url="", key="", client=None)
        account = economy.ensure_user(889900, "test", "Test User")
        uz = profile_text(account, "", "uz")
        ru = profile_text(account, "", "ru")
        en = profile_text(account, "", "en")
        self.assertIn("Mening profilim", uz)
        self.assertIn("Мой профиль", ru)
        self.assertIn("My profile", en)
        self.assertIn("Tangalar", uz)
        self.assertIn("Монеты", ru)
        self.assertIn("Coins", en)

    def test_language_keyboard_has_three_buttons(self) -> None:
        from bot.handlers.profile import language_keyboard, profile_keyboard

        keyboard = language_keyboard("uz")
        texts = [
            button.text
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertIn(LANGUAGE_NAMES["uz"], texts)
        self.assertIn(LANGUAGE_NAMES["ru"], texts)
        self.assertIn(LANGUAGE_NAMES["en"], texts)
        profile_kb = profile_keyboard("ru")
        self.assertIn("Сменить язык", profile_kb.inline_keyboard[0][0].text)


if __name__ == "__main__":
    unittest.main()
