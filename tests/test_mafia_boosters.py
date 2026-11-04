"""Mafiya boosterlari, Kevlar, 2x ovoz, mukofotlar va profil testlari."""

from __future__ import annotations

import random
import unittest

from bot.handlers.profile import profile_text
from core.economy import (
    MAFIA_WIN_REWARD,
    START_COINS,
    EconomyStore,
    UserAccount,
)
from games.mafia.boosters import (
    KEVLAR,
    MafiaBoosterError,
    booster_options,
    boosters_payload,
    purchase_booster,
)
from games.mafia.engine import (
    GamePhase,
    MafiaError,
    MafiaPlayer,
    MafiaRoom,
    resolve_night,
)
from games.mafia.roles import MafiaRole


def room_with(
    roles: dict[int, MafiaRole],
    *,
    phase: GamePhase = GamePhase.NIGHT,
    round_number: int = 1,
) -> MafiaRoom:
    """Belgilangan rollar bilan xona yasaydi."""
    room = MafiaRoom(
        [
            MafiaPlayer(user_id, f"P{user_id}", role=role)
            for user_id, role in sorted(roles.items())
        ],
        room_id="MAF500",
    )
    room.phase = phase
    room.round = round_number
    return room


class BoosterCatalogTest(unittest.TestCase):
    def test_catalog_prices_and_keys(self) -> None:
        payload = {item["key"]: item for item in boosters_payload()}
        self.assertEqual(set(payload), {"kevlar", "reroll", "double_vote"})
        self.assertEqual(payload["kevlar"]["price"], 40)
        self.assertEqual(payload["reroll"]["price"], 30)
        self.assertEqual(payload["double_vote"]["price"], 15)
        self.assertIn("omon qolasizmi", payload["kevlar"]["description"])


class KevlarEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.roles = {
            1: MafiaRole.DON,
            2: MafiaRole.MAFIA,
            3: MafiaRole.SHERIFF,
            4: MafiaRole.CITIZEN,
            5: MafiaRole.CITIZEN,
        }

    def test_kevlar_saves_target_once(self) -> None:
        room = room_with(self.roles)
        victim = room.get_player(4)
        victim.kevlar_active = True
        room.submit_night_action(1, 4)

        report = resolve_night(room)

        self.assertNotIn(4, report.deaths)
        self.assertEqual(report.shielded, (4,))
        self.assertTrue(victim.is_alive)
        self.assertTrue(victim.kevlar_used)
        self.assertFalse(victim.kevlar_active)

        # Keyingi tun jilet qayta ishlamaydi.
        room.begin_night()
        room.submit_night_action(1, 4)
        report = resolve_night(room)
        self.assertIn(4, report.deaths)
        self.assertFalse(victim.is_alive)

    def test_kevlar_is_consumed_even_without_attack(self) -> None:
        room = room_with(self.roles)
        player = room.get_player(4)
        player.kevlar_active = True
        room.submit_night_action(1, 3)

        resolve_night(room)

        self.assertTrue(player.kevlar_used)
        self.assertFalse(player.kevlar_active)


class RerollTest(unittest.TestCase):
    def test_reroll_swaps_roles_and_preserves_composition(self) -> None:
        room = room_with(
            {
                1: MafiaRole.SHERIFF,
                2: MafiaRole.MAFIA,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.DOCTOR,
            }
        )
        before = {player.role for player in room.players.values()}
        player = room.get_player(1)
        old_role = player.role

        new_role = room.reroll_role(1, rng=random.Random(3))

        self.assertNotEqual(new_role, old_role)
        self.assertTrue(player.role_rerolled)
        self.assertEqual({item.role for item in room.players.values()}, before)

        with self.assertRaises(MafiaError):
            room.reroll_role(1, rng=random.Random(4))

    def test_reroll_only_in_first_night(self) -> None:
        room = room_with(
            {
                1: MafiaRole.SHERIFF,
                2: MafiaRole.MAFIA,
                3: MafiaRole.CITIZEN,
                4: MafiaRole.DOCTOR,
            },
            round_number=2,
        )
        with self.assertRaises(MafiaError):
            room.reroll_role(1)


class DoubleVoteTest(unittest.TestCase):
    def test_double_vote_changes_tally(self) -> None:
        room = room_with(
            {
                1: MafiaRole.CITIZEN,
                2: MafiaRole.SHERIFF,
                3: MafiaRole.MAFIA,
                4: MafiaRole.CITIZEN,
            },
            phase=GamePhase.VOTING,
        )
        room.cast_vote(1, 2)
        room.cast_vote(2, 3)
        self.assertEqual(room.vote_counts(), {2: 1, 3: 1})
        self.assertIsNone(room.tally_votes())

        room.get_player(1).double_vote = True
        self.assertEqual(room.vote_counts(), {2: 2, 3: 1})
        self.assertEqual(room.tally_votes(), 2)


class BoosterPurchaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.economy = EconomyStore(url="", key="", client=None)
        self.economy.ensure_user(1)
        self.roles = {
            1: MafiaRole.SHERIFF,
            2: MafiaRole.MAFIA,
            3: MafiaRole.CITIZEN,
            4: MafiaRole.DOCTOR,
        }

    def test_kevlar_purchase_activates_and_deducts_coins(self) -> None:
        room = room_with(self.roles)
        purchase = purchase_booster(
            self.economy, room, "MAF500", 1, "kevlar"
        )

        self.assertEqual(purchase.account.coins, START_COINS - KEVLAR.price)
        self.assertTrue(room.get_player(1).kevlar_active)
        options = {
            option.booster.key: option
            for option in booster_options(room, "MAF500", self.economy, 1)
        }
        self.assertTrue(options["kevlar"].used)
        self.assertFalse(options["kevlar"].available)

        with self.assertRaises(MafiaBoosterError):
            purchase_booster(self.economy, room, "MAF500", 1, "kevlar")

    def test_reroll_purchase_and_double_vote(self) -> None:
        room = room_with(self.roles)
        old_role = room.get_player(1).role
        purchase = purchase_booster(
            self.economy, room, "MAF501", 1, "reroll", rng=random.Random(2)
        )
        self.assertIn("Yangi rolingiz", purchase.message)
        self.assertNotEqual(room.get_player(1).role, old_role)
        self.assertEqual(purchase.account.coins, START_COINS - 30)

        voting = room_with(self.roles, phase=GamePhase.VOTING)
        doubled = purchase_booster(
            self.economy, voting, "MAF502", 3, "double_vote"
        )
        self.assertTrue(voting.get_player(3).double_vote)
        self.assertEqual(doubled.account.coins, START_COINS - 15)

    def test_insufficient_coins_and_rules(self) -> None:
        room = room_with(self.roles)
        self.economy.spend_coins(1, START_COINS)
        with self.assertRaises(MafiaBoosterError):
            purchase_booster(self.economy, room, "MAF503", 1, "kevlar")

        rich = EconomyStore(url="", key="", client=None)
        with self.assertRaises(MafiaBoosterError):
            purchase_booster(rich, room, "MAF504", 1, "nope")

        lobby = room_with(self.roles, phase=GamePhase.LOBBY, round_number=0)
        with self.assertRaises(MafiaBoosterError):
            purchase_booster(rich, lobby, "MAF505", 1, "kevlar")

        with self.assertRaises(MafiaBoosterError):
            purchase_booster(rich, room, "MAF506", 999, "kevlar")


class MafiaRewardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EconomyStore(url="", key="", client=None)

    def test_winners_get_coins_and_mafia_wins_once(self) -> None:
        self.assertTrue(
            self.store.record_mafia_game("MAF700", [1, 2, 3], [1, 2])
        )
        self.assertFalse(
            self.store.record_mafia_game("MAF700", [1, 2, 3], [1, 2])
        )

        first = self.store.get_user(1)
        second = self.store.get_user(2)
        loser = self.store.get_user(3)
        self.assertEqual(first.coins, START_COINS + MAFIA_WIN_REWARD)
        self.assertEqual(second.coins, START_COINS + MAFIA_WIN_REWARD)
        self.assertEqual(first.mafia_wins, 1)
        self.assertEqual(first.wins, 1)
        self.assertEqual(first.bunker_wins, 0)
        self.assertEqual(loser.coins, START_COINS)
        self.assertEqual(loser.mafia_wins, 0)
        self.assertEqual(loser.games_played, 1)

    def test_bunker_wins_are_counted_separately(self) -> None:
        self.store.record_finished_game("BNK700", [1], [1])
        self.store.record_mafia_game("MAF701", [1], [1])
        account = self.store.get_user(1)
        self.assertEqual(account.bunker_wins, 1)
        self.assertEqual(account.mafia_wins, 1)
        self.assertEqual(account.wins, 2)


class ProfileSplitTest(unittest.TestCase):
    def test_profile_shows_both_game_wins(self) -> None:
        account = UserAccount(
            user_id=42,
            full_name="Ali",
            coins=100,
            wins=3,
            bunker_wins=2,
            mafia_wins=1,
        )
        text = profile_text(account)
        self.assertIn("🛡️ Bunker: <b>2</b> g'alaba", text)
        self.assertIn("🕵️ Mafiya: <b>1</b> g'alaba", text)


class PhaseTimerTest(unittest.TestCase):
    def test_manager_starts_60_second_timer(self) -> None:
        from bot.handlers.mafia_group import MafiaLobbyManager

        manager = MafiaLobbyManager(seed=11)
        game = manager.create_game(-100, 1, "Ali", "ali")
        for user_id in (2, 3, 4):
            manager.join(game.code, user_id, f"P{user_id}")
        started = manager.start_game(game.code, 1)

        self.assertEqual(started.phase_duration, 60)
        self.assertIsNotNone(started.phase_deadline)
        self.assertGreater(started.phase_seconds_left(), 50)

        started.clear_phase_timer()
        self.assertIsNone(started.phase_deadline)


if __name__ == "__main__":
    unittest.main()
