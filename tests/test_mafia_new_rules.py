"""Yangi Mafiya qoidalari: Komissar otishi, Don qidiruvi va Doktor cheklovi."""

from __future__ import annotations

import unittest

from games.mafia.engine import (
    GamePhase,
    MafiaError,
    MafiaPlayer,
    MafiaRoom,
    NightActionType,
    resolve_night,
)
from games.mafia.roles import MafiaRole


def build_room(roles: dict[int, MafiaRole]) -> MafiaRoom:
    players = [
        MafiaPlayer(user_id, f"P{user_id}", role=role)
        for user_id, role in sorted(roles.items())
    ]
    room = MafiaRoom(players)
    room.phase = GamePhase.NIGHT
    room.round = 1
    return room


class NewNightRulesTest(unittest.TestCase):
    def test_sheriff_can_shoot_instead_of_investigating(self) -> None:
        room = build_room(
            {
                1: MafiaRole.SHERIFF,
                2: MafiaRole.CITIZEN,
                3: MafiaRole.MAFIA,
                4: MafiaRole.CITIZEN,
            }
        )

        room.submit_night_action(1, 2, kind=NightActionType.SHOOT)
        report = resolve_night(room)

        self.assertIn(2, report.deaths)
        self.assertTrue(room.get_player(1).is_alive)
        self.assertEqual(report.sheriff_results, {})

    def test_don_can_search_for_sheriff(self) -> None:
        room = build_room(
            {
                1: MafiaRole.DON,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.CITIZEN,
            }
        )

        room.submit_night_action(1, 2, kind=NightActionType.DON_SEARCH)
        report = resolve_night(room)

        self.assertIn("topildi", report.don_results[1].lower())
        self.assertTrue(room.get_player(2).is_alive)

    def test_don_search_does_not_fire_mafia_kill(self) -> None:
        room = build_room(
            {
                1: MafiaRole.DON,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.CITIZEN,
            }
        )

        room.submit_night_action(1, 3, kind=NightActionType.DON_SEARCH)
        report = resolve_night(room)

        self.assertEqual(report.deaths, ())

    def test_doctor_cannot_heal_same_target_on_consecutive_nights(self) -> None:
        room = build_room(
            {
                1: MafiaRole.DOCTOR,
                2: MafiaRole.CITIZEN,
                3: MafiaRole.MAFIA,
                4: MafiaRole.CITIZEN,
            }
        )
        room.submit_night_action(1, 2, kind=NightActionType.HEAL)

        room.phase = GamePhase.NIGHT
        room.night_actions.clear()
        room.round = 2
        with self.assertRaises(MafiaError):
            room.submit_night_action(1, 2, kind=NightActionType.HEAL)

        # Boshqa nishon yoki o'zini davolash mumkin.
        room.submit_night_action(1, 1, kind=NightActionType.HEAL)
        self.assertEqual(room.night_actions[1].target_id, 1)


if __name__ == "__main__":
    unittest.main()
