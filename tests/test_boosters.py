"""Qalqon, 2 karra ovoz va reroll oqimlari testlari."""

import unittest

from core.billing import buy_booster, decline_shield
from core.economy import EconomyStore, InsufficientCoinsError
from engine.boosters import BoosterError
from engine.game_manager import GameManager, InvalidGameStateError
from models.game import RoomStatus


class BoosterFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = GameManager(seed=77)
        self.economy = EconomyStore(url="", key="", client=None)

    def _drain(self, user_id: int) -> None:
        """Yangi o'yinchi sovg'asini hisobga olib, balansni nolga tushiradi."""
        balance = self.economy.get_user(user_id).coins
        if balance:
            self.economy.spend_coins(user_id, balance)

    def _room(self, capacity: int = 2, players: int = 4):
        room = self.manager.create_room(1, "Ali", "ali", bunker_capacity=capacity)
        for user_id in range(2, players + 1):
            self.manager.join_room(room.code, user_id, f"Player {user_id}", f"p{user_id}")
        self.manager.start_game(room.code)
        return room

    def _prepare_shield_offer(self, room):
        self._drain(2)
        self.economy.add_coins(2, 100)
        self.manager.set_coin_balance_reader(
            lambda uid: self.economy.get_user(uid).coins
        )
        self.manager.cast_vote(room.code, 1, 2)
        self.manager.cast_vote(room.code, 3, 2)
        self.manager.cast_vote(room.code, 4, 3)
        self.assertIsNone(self.manager.tally_votes(room.code))
        self.assertEqual(room.status, RoomStatus.SHIELD_OFFER)
        self.assertEqual(room.pending_shield.user_id, 2)

    def test_shield_saves_player_and_eliminates_next_candidate(self) -> None:
        room = self._room()
        self._prepare_shield_offer(room)

        result = buy_booster(self.manager, self.economy, room.code, 2, "shield")
        self.assertEqual(result.eliminated.user_id, 3)
        self.assertTrue(room.players[2].shield_used)
        self.assertEqual(self.economy.get_user(2).coins, 50)
        self.assertTrue(self.economy.has_booster(room.code, 2, "shield"))
        self.assertEqual(room.status, RoomStatus.PLAYING)
        self.assertEqual(room.current_round, 2)

        # Keyingi raundda qalqon qayta taklif qilinmaydi.
        self.manager.cast_vote(room.code, 1, 2)
        self.manager.cast_vote(room.code, 4, 2)
        self.manager.tally_votes(room.code)
        self.assertFalse(room.players[2].is_alive)
        self.assertEqual(room.status, RoomStatus.FINISHED)

    def test_shield_decline_eliminates_candidate(self) -> None:
        room = self._room()
        self._prepare_shield_offer(room)
        updated, player = decline_shield(self.manager, room.code, 2)
        self.assertEqual(player.user_id, 2)
        self.assertFalse(player.is_alive)
        self.assertEqual(updated.status, RoomStatus.PLAYING)
        self.assertEqual(updated.current_round, 2)

    def test_double_vote_counts_as_two(self) -> None:
        room = self._room()
        self._drain(1)
        self.economy.add_coins(1, 15)
        result = buy_booster(self.manager, self.economy, room.code, 1, "double_vote")
        self.assertEqual(result.account_coins, 0)
        self.manager.cast_vote(room.code, 1, 2)
        self.assertEqual(room.players[2].votes_against, 2)
        self.manager.cast_vote(room.code, 3, 2)
        self.assertEqual(room.players[2].votes_against, 3)
        self.assertEqual(self.manager.tally_votes(room.code).user_id, 2)

    def test_reroll_replaces_unrevealed_card(self) -> None:
        room = self._room()
        self._drain(1)
        self.economy.add_coins(1, 20)
        result = buy_booster(
            self.manager, self.economy, room.code, 1, "reroll", "profession"
        )
        self.assertEqual(result.card.type.value, "profession")
        self.assertEqual(result.card.type.value, room.players[1].cards["profession"].type.value)
        self.assertFalse(result.card.is_revealed)

    def test_insufficient_coins_does_not_change_game(self) -> None:
        room = self._room()
        self._drain(1)
        with self.assertRaises(InsufficientCoinsError):
            buy_booster(self.manager, self.economy, room.code, 1, "double_vote")
        self.assertFalse(room.players[1].double_vote)
        self.assertEqual(self.economy.get_user(1).coins, 0)

    def test_shield_requires_active_offer(self) -> None:
        room = self._room()
        self._drain(2)
        self.economy.add_coins(2, 100)
        with self.assertRaises(InvalidGameStateError):
            buy_booster(self.manager, self.economy, room.code, 2, "shield")
        self.assertEqual(self.economy.get_user(2).coins, 100)

    def test_unknown_booster_is_rejected(self) -> None:
        room = self._room()
        with self.assertRaises(BoosterError):
            buy_booster(self.manager, self.economy, room.code, 1, "nomalum")


if __name__ == "__main__":
    unittest.main()
