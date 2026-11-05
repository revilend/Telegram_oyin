"""`system_settings` sozlamalari va karta matni testlari."""

import unittest
from unittest.mock import patch

from bot.handlers import shop
from core.settings import (
    CARD_HOLDER_KEY,
    CARD_NUMBER_KEY,
    SettingsError,
    SettingsStore,
    format_card_number,
    normalize_card_number,
    parse_card_line,
)


class CardParsingTest(unittest.TestCase):
    def test_parse_valid_line(self) -> None:
        self.assertEqual(
            parse_card_line("9860123456789012 Ali Valiyev"),
            ("9860123456789012", "Ali Valiyev"),
        )

    def test_parse_line_with_spaces_in_number(self) -> None:
        self.assertEqual(
            parse_card_line("9860 1234 5678 9012  Ali   Valiyev"),
            ("9860123456789012", "Ali Valiyev"),
        )

    def test_short_number_is_rejected(self) -> None:
        with self.assertRaises(SettingsError):
            normalize_card_number("12345")

    def test_missing_holder_is_rejected(self) -> None:
        with self.assertRaises(SettingsError):
            parse_card_line("9860123456789012")

    def test_empty_text_is_rejected(self) -> None:
        with self.assertRaises(SettingsError):
            parse_card_line("   ")

    def test_format_card_number(self) -> None:
        self.assertEqual(
            format_card_number("9860123456789012"), "9860 1234 5678 9012"
        )


class SettingsStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SettingsStore(url="", key="", client=None)

    def test_values_round_trip(self) -> None:
        self.assertEqual(self.store.get(CARD_NUMBER_KEY), "")
        self.store.set(CARD_NUMBER_KEY, "9860123456789012")
        self.assertEqual(self.store.get(CARD_NUMBER_KEY), "9860123456789012")
        self.assertEqual(self.store.get_all()[CARD_NUMBER_KEY], "9860123456789012")

    def test_payment_card_is_normalized(self) -> None:
        number, holder = self.store.set_payment_card(
            "9860 1234 5678 9012", "  Ali   Valiyev "
        )
        self.assertEqual(number, "9860123456789012")
        self.assertEqual(holder, "Ali Valiyev")
        self.assertEqual(
            self.store.payment_card(), ("9860123456789012", "Ali Valiyev")
        )
        self.assertEqual(self.store.get(CARD_HOLDER_KEY), "Ali Valiyev")

    def test_payment_text_uses_saved_card(self) -> None:
        self.store.set_payment_card("9860123456789012", "Ali Valiyev")
        # `shop` kartani `get_settings_store()` orqali o'qiydi.
        with patch.object(shop, "get_settings_store", return_value=self.store):
            text = shop.payment_text(500, 10_000)
        self.assertIn("9860 1234 5678 9012", text)
        self.assertIn("Ali Valiyev", text)
        self.assertIn("10 000 söm", text)


if __name__ == "__main__":
    unittest.main()
