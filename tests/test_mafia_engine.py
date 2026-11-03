"""«Revilend Mafia» o'yin dvigateli testlari."""

from __future__ import annotations

import random
import unittest
from collections import Counter

from games.mafia.engine import (
    INVESTIGATION_MAFIA,
    INVESTIGATION_NEUTRAL,
    INVESTIGATION_TOWN,
    GamePhase,
    MafiaError,
    MafiaPlayer,
    MafiaRoom,
    NightAction,
    NightActionType,
    Winner,
    check_game_over,
    resolve_day_vote,
    resolve_night,
    start_game,
)
from games.mafia.generator import get_balanced_roles
from games.mafia.roles import MafiaRole


def build_room(
    roles: dict[int, MafiaRole],
    *,
    phase: GamePhase = GamePhase.NIGHT,
    round_number: int = 1,
) -> MafiaRoom:
    """Belgilangan rollar bilan test xonasini yasaydi."""
    players = [
        MafiaPlayer(user_id, f"P{user_id}", role=role)
        for user_id, role in sorted(roles.items())
    ]
    room = MafiaRoom(players)
    room.phase = phase
    room.round = round_number
    return room


class NightResolutionTest(unittest.TestCase):
    def test_doctor_heal_saves_target(self) -> None:
        room = build_room(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.DOCTOR,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
            }
        )
        room.submit_night_action(1, 4)
        room.submit_night_action(2, 4)

        report = resolve_night(room)

        self.assertEqual(report.deaths, ())
        self.assertTrue(report.peaceful)
        self.assertEqual(report.healed, (4,))
        self.assertTrue(room.get_player(4).is_alive)
        self.assertIs(room.phase, GamePhase.DAY_REPORT)

    def test_blocker_cancels_doctor(self) -> None:
        room = build_room(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.DOCTOR,
                3: MafiaRole.BLOCKER,
                4: MafiaRole.CITIZEN,
                5: MafiaRole.SHERIFF,
            }
        )
        room.submit_night_action(1, 4)
        room.submit_night_action(2, 4)
        room.submit_night_action(3, 2)

        report = resolve_night(room)

        self.assertEqual(report.deaths, (4,))
        self.assertEqual(report.blocked, (2,))
        self.assertEqual(report.healed, ())
        self.assertFalse(room.get_player(4).is_alive)

    def test_bodyguard_dies_instead_of_target(self) -> None:
        room = build_room(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.BODYGUARD,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
            }
        )
        room.submit_night_action(1, 4)
        room.submit_night_action(2, 4)

        report = resolve_night(room)

        self.assertEqual(report.deaths, (2,))
        self.assertEqual(report.protected, (4,))
        self.assertFalse(room.get_player(2).is_alive)
        self.assertTrue(room.get_player(4).is_alive)

    def test_mafia_team_fires_one_shot_and_don_chooses(self) -> None:
        room = build_room(
            {
                1: MafiaRole.DON,
                2: MafiaRole.MAFIA,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
                5: MafiaRole.CITIZEN,
            }
        )
        room.submit_night_action(1, 3)
        room.submit_night_action(2, 4)

        report = resolve_night(room)

        self.assertEqual(report.deaths, (3,))
        self.assertTrue(room.get_player(4).is_alive)

    def test_blocked_mafia_shot_kills_nobody(self) -> None:
        room = build_room(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.BLOCKER,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
            }
        )
        room.submit_night_action(1, 3)
        room.submit_night_action(2, 1)

        report = resolve_night(room)

        self.assertEqual(report.deaths, ())
        self.assertEqual(report.blocked, (1,))
        self.assertTrue(room.get_player(3).is_alive)

    def test_sniper_shooting_town_dies_too(self) -> None:
        room = build_room(
            {
                1: MafiaRole.SNIPER,
                2: MafiaRole.MAFIA,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
                5: MafiaRole.CITIZEN,
            }
        )
        room.submit_night_action(1, 4)

        report = resolve_night(room)

        self.assertEqual(report.deaths, (1, 4))
        self.assertFalse(room.get_player(1).is_alive)

    def test_sniper_shooting_mafia_survives(self) -> None:
        room = build_room(
            {
                1: MafiaRole.SNIPER,
                2: MafiaRole.MAFIA,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
                5: MafiaRole.CITIZEN,
            }
        )
        room.submit_night_action(1, 2)

        report = resolve_night(room)

        self.assertEqual(report.deaths, (2,))
        self.assertTrue(room.get_player(1).is_alive)

    def test_blocked_sniper_has_no_penalty(self) -> None:
        room = build_room(
            {
                1: MafiaRole.SNIPER,
                2: MafiaRole.BLOCKER,
                3: MafiaRole.MAFIA,
                4: MafiaRole.CITIZEN,
                5: MafiaRole.SHERIFF,
            }
        )
        room.submit_night_action(1, 4)
        room.submit_night_action(2, 1)

        report = resolve_night(room)

        self.assertEqual(report.deaths, ())
        self.assertEqual(report.blocked, (1,))
        self.assertTrue(room.get_player(1).is_alive)

    def test_kamikaze_takes_night_killer_with_him(self) -> None:
        room = build_room(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.KAMIKAZE,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
            }
        )
        room.submit_night_action(1, 2)

        report = resolve_night(room)

        self.assertEqual(report.deaths, (1, 2))
        self.assertFalse(room.get_player(2).is_alive)

    def test_empty_night_report(self) -> None:
        room = build_room(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.CITIZEN,
            }
        )

        report = resolve_night(room)

        self.assertTrue(report.peaceful)
        self.assertEqual(room.report_text(), "Tunda hech kim halok bo'lmadi.")

    def test_report_names_the_dead(self) -> None:
        room = build_room(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.CITIZEN,
            }
        )
        room.submit_night_action(1, 3)

        resolve_night(room)

        self.assertEqual(room.report_text(), "Tunda halok bo'ldilar: P3.")


class SheriffTest(unittest.TestCase):
    def _investigate(self, target_role: MafiaRole) -> str:
        room = build_room(
            {
                1: MafiaRole.SHERIFF,
                2: target_role,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.JESTER,
            }
        )
        room.submit_night_action(1, 2)
        return resolve_night(room).sheriff_results[1]

    def test_reads_mafia(self) -> None:
        self.assertEqual(self._investigate(MafiaRole.MAFIA), INVESTIGATION_MAFIA)

    def test_reads_town(self) -> None:
        self.assertEqual(self._investigate(MafiaRole.CITIZEN), INVESTIGATION_TOWN)

    def test_reads_neutral(self) -> None:
        self.assertEqual(self._investigate(MafiaRole.MANIAC), INVESTIGATION_NEUTRAL)

    def test_lawyer_frame_returns_town(self) -> None:
        room = build_room(
            {
                1: MafiaRole.SHERIFF,
                2: MafiaRole.MAFIA,
                3: MafiaRole.LAWYER,
                4: MafiaRole.CITIZEN,
                5: MafiaRole.CITIZEN,
            }
        )
        room.submit_night_action(1, 2)
        room.submit_night_action(3, 2)

        report = resolve_night(room)

        self.assertEqual(report.sheriff_results[1], INVESTIGATION_TOWN)

    def test_blocked_lawyer_cannot_frame(self) -> None:
        room = build_room(
            {
                1: MafiaRole.SHERIFF,
                2: MafiaRole.MAFIA,
                3: MafiaRole.LAWYER,
                4: MafiaRole.BLOCKER,
                5: MafiaRole.CITIZEN,
                6: MafiaRole.CITIZEN,
            }
        )
        room.submit_night_action(1, 2)
        room.submit_night_action(3, 2)
        room.submit_night_action(4, 3)

        report = resolve_night(room)

        self.assertEqual(report.sheriff_results[1], INVESTIGATION_MAFIA)


class ActionValidationTest(unittest.TestCase):
    def test_actions_require_night_phase(self) -> None:
        room = build_room(
            {1: MafiaRole.MAFIA, 2: MafiaRole.SHERIFF, 3: MafiaRole.CITIZEN},
            phase=GamePhase.LOBBY,
        )
        with self.assertRaises(MafiaError):
            room.submit_night_action(1, 3)
        with self.assertRaises(MafiaError):
            resolve_night(room)

    def test_dead_actor_and_unknown_target(self) -> None:
        room = build_room(
            {1: MafiaRole.MAFIA, 2: MafiaRole.SHERIFF, 3: MafiaRole.CITIZEN}
        )
        room.get_player(2).is_alive = False
        with self.assertRaises(MafiaError):
            room.submit_night_action(2, 3)
        with self.assertRaises(MafiaError):
            room.submit_night_action(1, 99)

    def test_passive_role_has_no_night_action(self) -> None:
        room = build_room(
            {1: MafiaRole.CITIZEN, 2: MafiaRole.MAFIA, 3: MafiaRole.SHERIFF}
        )
        with self.assertRaises(MafiaError):
            room.submit_night_action(1, 2)

    def test_dead_target_is_rejected(self) -> None:
        room = build_room(
            {1: MafiaRole.MAFIA, 2: MafiaRole.SHERIFF, 3: MafiaRole.CITIZEN}
        )
        room.get_player(3).is_alive = False
        with self.assertRaises(MafiaError):
            room.submit_night_action(1, 3)

    def test_bodyguard_cannot_protect_self(self) -> None:
        room = build_room(
            {1: MafiaRole.BODYGUARD, 2: MafiaRole.MAFIA, 3: MafiaRole.CITIZEN}
        )
        with self.assertRaises(MafiaError):
            room.submit_night_action(1, 1)

    def test_unsupported_night_role_is_rejected(self) -> None:
        room = build_room(
            {1: MafiaRole.WITCH, 2: MafiaRole.MAFIA, 3: MafiaRole.CITIZEN}
        )
        with self.assertRaises(MafiaError):
            room.submit_night_action(1, 2)


class RoomLifecycleTest(unittest.TestCase):
    def test_start_deals_roles_and_opens_first_night(self) -> None:
        players = [MafiaPlayer(user_id, f"P{user_id}") for user_id in range(1, 8)]
        room = MafiaRoom(players)

        room.start(rng=random.Random(11))

        self.assertIs(room.phase, GamePhase.NIGHT)
        self.assertEqual(room.round, 1)
        self.assertEqual(
            Counter(player.role for player in room.players.values()),
            Counter(get_balanced_roles(7)),
        )
        with self.assertRaises(MafiaError):
            room.start()

    def test_start_requires_four_players(self) -> None:
        with self.assertRaises(MafiaError):
            start_game([1, 2, 3])

    def test_duplicate_and_empty_rooms_are_rejected(self) -> None:
        with self.assertRaises(MafiaError):
            MafiaRoom([MafiaPlayer(1), MafiaPlayer(1)])
        with self.assertRaises(MafiaError):
            MafiaRoom([])

    def test_start_game_factory(self) -> None:
        room = start_game([1, 2, 3, 4], rng=random.Random(3))
        self.assertEqual(len(room.players), 4)
        self.assertIs(room.phase, GamePhase.NIGHT)
        self.assertTrue(all(player.role is not None for player in room.players.values()))

    def test_next_night_increments_round_and_clears_state(self) -> None:
        room = build_room(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.CITIZEN,
            },
            phase=GamePhase.VOTING,
        )
        room.votes[2] = 1
        room.night_actions[2] = NightAction(2, NightActionType.INVESTIGATE, 1)

        resolve_day_vote(room, None)

        self.assertIs(room.phase, GamePhase.NIGHT)
        self.assertEqual(room.round, 2)
        self.assertEqual(room.votes, {})
        self.assertEqual(room.night_actions, {})


class VotingTest(unittest.TestCase):
    def test_votes_can_be_changed_and_are_validated(self) -> None:
        room = build_room(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.CITIZEN,
            },
            phase=GamePhase.VOTING,
        )
        room.cast_vote(2, 3)
        self.assertEqual(room.votes, {2: 3})
        room.cast_vote(2, 4)
        self.assertEqual(room.votes, {2: 4})

        with self.assertRaises(MafiaError):
            room.cast_vote(2, 2)
        with self.assertRaises(MafiaError):
            room.cast_vote(1, 1)

        room.get_player(3).is_alive = False
        with self.assertRaises(MafiaError):
            room.cast_vote(3, 4)
        with self.assertRaises(MafiaError):
            room.cast_vote(2, 3)

    def test_vote_requires_voting_phase(self) -> None:
        room = build_room(
            {1: MafiaRole.MAFIA, 2: MafiaRole.SHERIFF, 3: MafiaRole.CITIZEN}
        )
        with self.assertRaises(MafiaError):
            room.cast_vote(2, 1)

    def test_regular_elimination_moves_to_next_night(self) -> None:
        room = build_room(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.CITIZEN,
                5: MafiaRole.CITIZEN,
            },
            phase=GamePhase.VOTING,
        )

        winner = resolve_day_vote(room, 3)

        self.assertIsNone(winner)
        self.assertFalse(room.get_player(3).is_alive)
        self.assertIn(3, room.eliminated)
        self.assertIs(room.phase, GamePhase.NIGHT)
        self.assertEqual(room.round, 2)
        self.assertEqual(room.votes, {})
        self.assertEqual(room.night_actions, {})

    def test_jester_wins_immediately_when_voted_out(self) -> None:
        room = build_room(
            {
                1: MafiaRole.JESTER,
                2: MafiaRole.MAFIA,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
                5: MafiaRole.CITIZEN,
            },
            phase=GamePhase.VOTING,
        )

        winner = resolve_day_vote(room, 1)

        self.assertIs(winner, Winner.JESTER)
        self.assertIs(room.phase, GamePhase.FINISHED)
        self.assertIs(room.winner, Winner.JESTER)
        self.assertIn("Hazilkash", room.finish_reason)
        self.assertFalse(room.get_player(1).is_alive)

    def test_kamikaze_takes_chosen_player_with_him(self) -> None:
        room = build_room(
            {
                1: MafiaRole.KAMIKAZE,
                2: MafiaRole.MAFIA,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
                5: MafiaRole.CITIZEN,
            },
            phase=GamePhase.VOTING,
        )

        winner = resolve_day_vote(room, 1, kamikaze_target_id=4)

        self.assertIsNone(winner)
        self.assertFalse(room.get_player(1).is_alive)
        self.assertFalse(room.get_player(4).is_alive)
        self.assertIs(room.phase, GamePhase.NIGHT)
        self.assertEqual(room.round, 2)

    def test_kamikaze_must_choose_a_valid_target(self) -> None:
        room = build_room(
            {
                1: MafiaRole.KAMIKAZE,
                2: MafiaRole.MAFIA,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
                5: MafiaRole.CITIZEN,
            },
            phase=GamePhase.VOTING,
        )

        with self.assertRaises(MafiaError):
            resolve_day_vote(room, 1)
        with self.assertRaises(MafiaError):
            resolve_day_vote(room, 1, kamikaze_target_id=1)
        self.assertTrue(room.get_player(1).is_alive)
        self.assertIs(room.phase, GamePhase.VOTING)

    def test_vote_result_requires_voting_phase(self) -> None:
        room = build_room(
            {1: MafiaRole.MAFIA, 2: MafiaRole.SHERIFF, 3: MafiaRole.CITIZEN}
        )
        with self.assertRaises(MafiaError):
            resolve_day_vote(room, 2)

    def test_voting_requires_day_report(self) -> None:
        room = build_room(
            {1: MafiaRole.MAFIA, 2: MafiaRole.SHERIFF, 3: MafiaRole.CITIZEN}
        )
        with self.assertRaises(MafiaError):
            room.begin_voting()

    def test_parity_after_vote_finishes_game(self) -> None:
        room = build_room(
            {1: MafiaRole.MAFIA, 2: MafiaRole.CITIZEN, 3: MafiaRole.CITIZEN},
            phase=GamePhase.VOTING,
        )

        winner = resolve_day_vote(room, 2)

        self.assertIs(winner, Winner.MAFIA)
        self.assertIs(room.phase, GamePhase.FINISHED)


class WinConditionTest(unittest.TestCase):
    def test_town_wins_when_mafia_and_maniac_are_gone(self) -> None:
        room = build_room(
            {
                1: MafiaRole.CITIZEN,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.MAFIA,
                4: MafiaRole.MANIAC,
            }
        )
        room.eliminate(3)
        room.eliminate(4)
        self.assertIs(check_game_over(room), Winner.TOWN)

    def test_mafia_wins_at_parity(self) -> None:
        room = build_room({1: MafiaRole.MAFIA, 2: MafiaRole.CITIZEN})
        self.assertIs(check_game_over(room), Winner.MAFIA)

    def test_maniac_wins_as_sole_survivor(self) -> None:
        room = build_room(
            {
                1: MafiaRole.MANIAC,
                2: MafiaRole.CITIZEN,
                3: MafiaRole.MAFIA,
            }
        )
        room.eliminate(2)
        room.eliminate(3)
        self.assertIs(check_game_over(room), Winner.MANIAC)

    def test_game_continues_while_town_outnumbers_mafia(self) -> None:
        room = build_room(
            {
                1: MafiaRole.MAFIA,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.CITIZEN,
            }
        )
        self.assertIsNone(check_game_over(room))

    def test_maniac_alone_with_town_does_not_end_game(self) -> None:
        room = build_room({1: MafiaRole.MANIAC, 2: MafiaRole.CITIZEN})
        self.assertIsNone(check_game_over(room))

    def test_night_parity_finishes_game(self) -> None:
        room = build_room(
            {
                1: MafiaRole.DON,
                2: MafiaRole.MAFIA,
                3: MafiaRole.SHERIFF,
                4: MafiaRole.CITIZEN,
            }
        )
        room.submit_night_action(1, 4)

        resolve_night(room)

        self.assertIs(room.phase, GamePhase.FINISHED)
        self.assertIs(room.winner, Winner.MAFIA)


class FullRoundTest(unittest.TestCase):
    def test_four_player_game_from_night_to_town_win(self) -> None:
        room = start_game([11, 12, 13, 14], rng=random.Random(5))
        mafia = next(
            player
            for player in room.players.values()
            if player.role is MafiaRole.MAFIA
        )
        victim = next(
            player
            for player in room.players.values()
            if player.role is MafiaRole.CITIZEN
        )

        room.submit_night_action(mafia.user_id, victim.user_id)
        report = resolve_night(room)

        self.assertIn(victim.user_id, report.deaths)
        self.assertIs(room.phase, GamePhase.DAY_REPORT)

        room.begin_voting()
        self.assertIs(room.phase, GamePhase.VOTING)
        winner = resolve_day_vote(room, mafia.user_id)

        self.assertIs(winner, Winner.TOWN)
        self.assertIs(room.phase, GamePhase.FINISHED)
        self.assertIn("shahar", room.finish_reason)


if __name__ == "__main__":
    unittest.main()
