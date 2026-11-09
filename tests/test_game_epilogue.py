"""Bunker 10 yillik epilog simulyatsiyasi testlari."""

from __future__ import annotations

import unittest

from engine.game_manager import GameManager
from models.game import CardType, PlayerCard, RoomStatus


class EpilogueTest(unittest.TestCase):
    def _room(self) -> tuple[GameManager, object]:
        manager = GameManager(seed=77)
        room = manager.create_room(
            host_id=1,
            host_name="Ali",
            host_username="ali",
            bunker_capacity=5,
        )
        for index in range(2, 6):
            manager.join_room(room.code, index, f"P{index}", f"p{index}")
        manager.start_game(room.code)
        return manager, room

    @staticmethod
    def _set_profession(room, user_id: int, title: str) -> None:
        room.players[user_id].cards[CardType.PROFESSION.value] = PlayerCard(
            type=CardType.PROFESSION,
            title=title,
            description=title,
        )

    @staticmethod
    def _set_biology(room, user_id: int, title: str, description: str) -> None:
        room.players[user_id].cards[CardType.BIOLOGY.value] = PlayerCard(
            type=CardType.BIOLOGY,
            title=title,
            description=description,
        )

    def test_all_years_survive_and_civilization_returns(self) -> None:
        manager, room = self._room()
        self._set_profession(room, 1, "Muhandis")
        self._set_profession(room, 2, "Agronom")
        self._set_profession(room, 3, "Shifokor")
        self._set_profession(room, 4, "Psixolog")
        self._set_profession(room, 5, "Oshpaz")
        self._set_biology(
            room,
            1,
            "Erkak, 30 yosh",
            "Jinsi: Erkak · Bola ko'rish qobiliyati: bor.",
        )
        self._set_biology(
            room,
            2,
            "Ayol, 28 yosh",
            "Jinsi: Ayol · Bola ko'rish qobiliyati: bor.",
        )

        manager._build_epilogue(room)

        self.assertEqual([event["year"] for event in room.epilogue], [1, 3, 5, 10])
        self.assertTrue(room.epilogue_survived)
        self.assertIn("qayta tiklandi", room.epilogue_outcome)
        self.assertTrue(all(event["tone"] == "ok" for event in room.epilogue))

    def test_missing_doctor_and_psychologist_dooms_the_group(self) -> None:
        manager, room = self._room()
        self._set_profession(room, 1, "Muhandis")
        self._set_profession(room, 2, "Agronom")
        self._set_profession(room, 3, "Oshpaz")
        self._set_profession(room, 4, "Dasturchi")
        self._set_profession(room, 5, "Balıqchi")
        self._set_biology(
            room,
            1,
            "Erkak, 30 yosh",
            "Jinsi: Erkak · Bola ko'rish qobiliyati: bor.",
        )
        self._set_biology(
            room,
            2,
            "Ayol, 28 yosh",
            "Jinsi: Ayol · Bola ko'rish qobiliyati: bor.",
        )

        manager._build_epilogue(room)

        self.assertFalse(room.epilogue_survived)
        self.assertIn("omon qolmadi", room.epilogue_outcome)
        tones = {event["year"]: event["tone"] for event in room.epilogue}
        self.assertEqual(tones[3], "risk")
        self.assertEqual(tones[5], "risk")

    def test_finished_room_exposes_epilogue(self) -> None:
        manager, room = self._room()
        room.status = RoomStatus.FINISHED
        manager._build_epilogue(room)
        self.assertEqual(len(room.epilogue), 4)
        self.assertTrue(room.epilogue_outcome)


if __name__ == "__main__":
    unittest.main()
