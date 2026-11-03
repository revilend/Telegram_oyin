"""«Revilend Mafia» rollar katalogi va generatori testlari."""

from __future__ import annotations

import random
import unittest
from collections import Counter

from games.mafia.generator import deal_mafia_roles, get_balanced_roles
from games.mafia.roles import (
    ROLE_PROFILES,
    Faction,
    MafiaRole,
    get_role_profile,
    roles_by_faction,
)

NIGHT_ACTION_ROLES = {
    MafiaRole.SHERIFF,
    MafiaRole.DOCTOR,
    MafiaRole.BODYGUARD,
    MafiaRole.BLOCKER,
    MafiaRole.SNIPER,
    MafiaRole.WITCH,
    MafiaRole.DON,
    MafiaRole.MAFIA,
    MafiaRole.LAWYER,
    MafiaRole.BLACKMAILER,
    MafiaRole.MANIAC,
    MafiaRole.AMNESIAC,
}


class RoleCatalogTest(unittest.TestCase):
    def test_every_role_has_a_profile(self) -> None:
        self.assertEqual(set(ROLE_PROFILES), set(MafiaRole))
        self.assertEqual(len(ROLE_PROFILES), 16)

        names: set[str] = set()
        for role, profile in ROLE_PROFILES.items():
            self.assertIs(profile.role, role)
            self.assertTrue(profile.name_uz.strip(), f"{role} nomi bo'sh")
            self.assertGreaterEqual(len(profile.description.strip()), 20)
            self.assertIsInstance(profile.faction, Faction)
            self.assertIsInstance(profile.has_night_action, bool)
            names.add(profile.name_uz)
        self.assertEqual(len(names), len(ROLE_PROFILES), "Rol nomlari takrorlanmasin")

    def test_faction_split(self) -> None:
        self.assertEqual(len(roles_by_faction(Faction.TOWN)), 9)
        self.assertEqual(len(roles_by_faction(Faction.MAFIA)), 4)
        self.assertEqual(len(roles_by_faction(Faction.NEUTRAL)), 3)

        self.assertEqual(
            set(roles_by_faction(Faction.MAFIA)),
            {MafiaRole.DON, MafiaRole.MAFIA, MafiaRole.LAWYER, MafiaRole.BLACKMAILER},
        )
        self.assertEqual(
            set(roles_by_faction(Faction.NEUTRAL)),
            {MafiaRole.MANIAC, MafiaRole.JESTER, MafiaRole.AMNESIAC},
        )

    def test_night_actions_match_role_kit(self) -> None:
        for role in MafiaRole:
            profile = ROLE_PROFILES[role]
            self.assertEqual(
                profile.has_night_action,
                role in NIGHT_ACTION_ROLES,
                f"{role} uchun tungi harakat noto'g'ri belgilangan",
            )
        for passive in (
            MafiaRole.CITIZEN,
            MafiaRole.KAMIKAZE,
            MafiaRole.MAYOR,
            MafiaRole.JESTER,
        ):
            self.assertFalse(ROLE_PROFILES[passive].has_night_action)

    def test_profile_lookup_accepts_key_or_enum(self) -> None:
        self.assertIs(get_role_profile(MafiaRole.SHERIFF), ROLE_PROFILES[MafiaRole.SHERIFF])
        self.assertIs(get_role_profile(" sheriff "), ROLE_PROFILES[MafiaRole.SHERIFF])
        with self.assertRaises(ValueError):
            get_role_profile("nomalum")
        with self.assertRaises(ValueError):
            get_role_profile("")


class BalancedRolesTest(unittest.TestCase):
    def test_exact_compositions_for_small_games(self) -> None:
        self.assertEqual(
            get_balanced_roles(4),
            [MafiaRole.MAFIA, MafiaRole.SHERIFF, MafiaRole.CITIZEN, MafiaRole.CITIZEN],
        )
        self.assertEqual(
            get_balanced_roles(5),
            [
                MafiaRole.MAFIA,
                MafiaRole.SHERIFF,
                MafiaRole.DOCTOR,
                MafiaRole.CITIZEN,
                MafiaRole.CITIZEN,
            ],
        )

    def test_core_roles_at_six_and_seven_players(self) -> None:
        six = get_balanced_roles(6)
        self.assertEqual(len(six), 6)
        self.assertEqual(
            set(six),
            {
                MafiaRole.DON,
                MafiaRole.MAFIA,
                MafiaRole.SHERIFF,
                MafiaRole.DOCTOR,
                MafiaRole.BODYGUARD,
                MafiaRole.CITIZEN,
            },
        )

        seven = get_balanced_roles(7)
        self.assertEqual(len(seven), 7)
        self.assertEqual(seven.count(MafiaRole.CITIZEN), 2)

    def test_mid_game_roles_at_eight_and_nine_players(self) -> None:
        for count in (8, 9):
            roles = get_balanced_roles(count)
            self.assertEqual(len(roles), count)
            for role in (
                MafiaRole.BLOCKER,
                MafiaRole.MANIAC,
                MafiaRole.SNIPER,
            ):
                self.assertIn(role, roles)
            self.assertNotIn(MafiaRole.JESTER, roles)
        self.assertEqual(get_balanced_roles(8).count(MafiaRole.CITIZEN), 0)
        self.assertEqual(get_balanced_roles(9).count(MafiaRole.CITIZEN), 1)

    def test_late_game_roles_grow_until_twelve(self) -> None:
        ten = get_balanced_roles(10)
        self.assertEqual(len(ten), 10)
        self.assertIn(MafiaRole.JESTER, ten)
        self.assertIn(MafiaRole.WITCH, ten)
        self.assertNotIn(MafiaRole.MAYOR, ten)
        self.assertNotIn(MafiaRole.LAWYER, ten)

        eleven = get_balanced_roles(11)
        self.assertIn(MafiaRole.MAYOR, eleven)
        self.assertNotIn(MafiaRole.LAWYER, eleven)

        twelve = get_balanced_roles(12)
        self.assertIn(MafiaRole.LAWYER, twelve)
        self.assertEqual(twelve.count(MafiaRole.CITIZEN), 0)

    def test_full_roster_from_thirteen_players(self) -> None:
        thirteen = get_balanced_roles(13)
        self.assertEqual(len(thirteen), 13)
        self.assertIn(MafiaRole.BLACKMAILER, thirteen)

        fifteen = get_balanced_roles(15)
        self.assertEqual(len(fifteen), 15)
        self.assertEqual(len(set(fifteen)), 15)
        self.assertEqual(fifteen.count(MafiaRole.CITIZEN), 0)
        for role in MafiaRole:
            if role is MafiaRole.CITIZEN:
                continue
            self.assertIn(role, fifteen)

        sixteen = get_balanced_roles(16)
        self.assertEqual(len(sixteen), 16)
        self.assertEqual(sixteen.count(MafiaRole.CITIZEN), 1)

        twenty = get_balanced_roles(20)
        self.assertEqual(len(twenty), 20)
        self.assertEqual(twenty.count(MafiaRole.CITIZEN), 5)

    def test_every_table_is_playable(self) -> None:
        for count in range(4, 31):
            roles = get_balanced_roles(count)
            self.assertEqual(len(roles), count, f"{count} o'yinchi uchun uzunlik")
            self.assertGreaterEqual(
                sum(
                    1
                    for role in roles
                    if ROLE_PROFILES[role].faction is Faction.MAFIA
                ),
                1,
                f"{count} o'yinchi uchun mafiya yo'q",
            )
            self.assertGreaterEqual(
                sum(
                    1
                    for role in roles
                    if ROLE_PROFILES[role].faction is Faction.TOWN
                ),
                1,
                f"{count} o'yinchi uchun tinch aholi yo'q",
            )

    def test_invalid_player_counts(self) -> None:
        for count in (0, 1, 3, -5):
            with self.assertRaises(ValueError):
                get_balanced_roles(count)
        for value in ("6", None, 5.0, True):
            with self.assertRaises(TypeError):
                get_balanced_roles(value)  # type: ignore[arg-type]


class DealRolesTest(unittest.TestCase):
    def test_every_player_gets_exactly_one_role(self) -> None:
        players = [1001, 1002, 1003, 1004, 1005, 1006, 1007]
        dealt = deal_mafia_roles(players, rng=random.Random(7))

        self.assertEqual(set(dealt), set(players))
        self.assertEqual(len(dealt), len(players))
        self.assertEqual(
            Counter(dealt.values()), Counter(get_balanced_roles(len(players)))
        )

    def test_deal_shuffles_roles(self) -> None:
        players = [f"p{i}" for i in range(8)]
        first = deal_mafia_roles(players, rng=random.Random(1))
        second = deal_mafia_roles(players, rng=random.Random(2))
        self.assertEqual(
            Counter(first.values()), Counter(second.values())
        )
        self.assertTrue(
            any(first[player] != second[player] for player in players),
            "Turli seed bilan bir xil taqsimot chiqmasligi kerak",
        )

    def test_same_seed_is_reproducible(self) -> None:
        players = [1, 2, 3, 4, 5, 6]
        self.assertEqual(
            deal_mafia_roles(players, rng=random.Random(42)),
            deal_mafia_roles(players, rng=random.Random(42)),
        )

    def test_invalid_player_lists(self) -> None:
        with self.assertRaises(ValueError):
            deal_mafia_roles([1, 2, 3])
        with self.assertRaises(ValueError):
            deal_mafia_roles([1, 1, 2, 4, 5])
        with self.assertRaises(ValueError):
            deal_mafia_roles([])

    def test_real_tables_for_all_sizes(self) -> None:
        for count in (4, 5, 6, 9, 12, 13, 15, 18):
            players = list(range(9000, 9000 + count))
            dealt = deal_mafia_roles(players)
            self.assertEqual(len(dealt), count)
            self.assertIsInstance(next(iter(dealt.values())), MafiaRole)


if __name__ == "__main__":
    unittest.main()
