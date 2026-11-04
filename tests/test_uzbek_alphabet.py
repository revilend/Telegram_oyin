"""Yangi o'zbek lotin alifbosi normallashtirgichi testlari."""
import unittest

from core.uzbek_alphabet import new_uzbek_latin


class UzbekAlphabetTests(unittest.TestCase):
    def test_requested_letter_pairs(self) -> None:
        self.assertEqual(
            new_uzbek_latin("O'yin o‘yin G'ALABA g‘alaba"),
            "Öyin öyin ĞALABA ğalaba",
        )

    def test_sh_and_ch_case(self) -> None:
        self.assertEqual(
            new_uzbek_latin("Shahar shifokor CHIQISH chiqish"),
            "Şahar şifokor ÇIQIŞ çiqiş",
        )

    def test_unrelated_text_is_preserved(self) -> None:
        self.assertEqual(new_uzbek_latin("Bunker 123 API"), "Bunker 123 API")


if __name__ == "__main__":
    unittest.main()
