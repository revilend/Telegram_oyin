"""«Bunker» xona menejeri uchun to'liq o'yin ssenariysi testlari."""

import re
import unittest

import engine.game_manager as game_manager
from engine.game_manager import (
    CardNotFoundError,
    GameError,
    GameManager,
    InvalidGameStateError,
    PlayerNotFoundError,
    RoomNotFoundError,
)
from models.game import CardType, RoomStatus


class FullGameScenarioTest(unittest.TestCase):
    """6 o'yinchili o'yinni FINISHED holatigacha o'tkazadi."""

    def setUp(self) -> None:
        self.manager = GameManager(seed=2026)
        self.room = self.manager.create_room(
            host_id=101,
            host_name="Ali Valiyev",
            host_username="ali",
            bunker_capacity=3,
        )
        self.code = self.room.code

    def _join_rest(self) -> None:
        for user_id, name in (
            (102, "Vali Karimov"),
            (103, "Hasan Toshmatov"),
            (104, "Zilola Yusupova"),
            (105, "Dilnoza Rahimova"),
            (106, "Bekzod Olimov"),
        ):
            self.manager.join_room(self.code, user_id, name, f"user{user_id}")

    def test_room_creation(self) -> None:
        self.assertRegex(self.room.code, r"^BNK\d{3}$")
        self.assertEqual(len(self.room.code), 6)
        self.assertEqual(self.room.status, RoomStatus.LOBBY)
        self.assertEqual(self.room.current_round, 0)
        self.assertEqual(self.room.bunker_capacity, 3)
        self.assertEqual(self.room.players[101].full_name, "Ali Valiyev")
        self.assertTrue(self.room.players[101].is_host)
        self.assertEqual(self.room.catastrophe["name"], self.room.catastrophe["name"].strip())
        for field in ("id", "name", "description", "bunker_supplies", "survival_requirements"):
            self.assertIn(field, self.room.catastrophe)

    def test_full_game_until_finished(self) -> None:
        self._join_rest()
        self.assertEqual(len(self.room.players), 6)
        self.assertEqual(len(self.room.alive_players), 6)

        # Takroriy qo'shilish va noma'lum xona.
        with self.assertRaises(InvalidGameStateError):
            self.manager.join_room(self.code, 102, "Vali Karimov", "user102")
        with self.assertRaises(RoomNotFoundError):
            self.manager.join_room("BNK000", 999, "Yo'q", "yoq")

        # O'yinni boshlash va kartalarni tarqatish.
        self.manager.start_game(self.code)
        self.assertEqual(self.room.status, RoomStatus.PLAYING)
        self.assertEqual(self.room.current_round, 1)
        expected_categories = {
            CardType.PROFESSION.value,
            CardType.BIOLOGY.value,
            CardType.HEALTH.value,
            CardType.HOBBY.value,
            CardType.LUGGAGE.value,
            CardType.FACT.value,
        }
        for player in self.room.players.values():
            self.assertTrue(expected_categories.issubset(player.cards))
            self.assertFalse(any(card.is_revealed for card in player.cards.values()))
        professions = {player.cards["profession"].title for player in self.room.players.values()}
        self.assertEqual(len(professions), 6, "Bir xil kasb ikki o'yinchiga tushmasligi kerak")

        with self.assertRaises(InvalidGameStateError):
            self.manager.join_room(self.code, 107, "Yangi", "yangi")
        with self.assertRaises(InvalidGameStateError):
            self.manager.start_game(self.code)

        # Kartani ochish faqat o'z kartasi uchun.
        card = self.manager.reveal_card(self.code, 101, "profession")
        self.assertTrue(card.is_revealed)
        self.assertEqual(card.type, CardType.PROFESSION)
        with self.assertRaises(CardNotFoundError):
            self.manager.reveal_card(self.code, 101, "catastrophe")
        with self.assertRaises(CardNotFoundError):
            self.manager.reveal_card(self.code, 101, "noma'lum")
        with self.assertRaises(PlayerNotFoundError):
            self.manager.reveal_card(self.code, 999, "health")

        # 1-raund: 103 haydaladi.
        for voter in (101, 102, 104, 105):
            self.manager.cast_vote(self.code, voter, 103)
        self.manager.cast_vote(self.code, 106, 102)
        self.manager.cast_vote(self.code, 103, 102)
        self.assertEqual(self.room.players[103].votes_against, 4)
        self.assertEqual(self.room.players[102].votes_against, 2)
        self.assertEqual(self.room.status, RoomStatus.VOTING)

        eliminated = self.manager.tally_votes(self.code)
        self.assertIsNotNone(eliminated)
        self.assertEqual(eliminated.user_id, 103)
        self.assertFalse(self.room.players[103].is_alive)
        self.assertEqual(self.room.eliminated_players, [103])
        self.assertEqual(self.room.status, RoomStatus.PLAYING)
        self.assertEqual(self.room.current_round, 2)
        self.assertTrue(all(p.votes_against == 0 for p in self.room.players.values()))

        # Haydalgan o'yinchi bilan ishlash taqiqlanadi.
        with self.assertRaises(InvalidGameStateError):
            self.manager.cast_vote(self.code, 103, 101)
        with self.assertRaises(InvalidGameStateError):
            self.manager.cast_vote(self.code, 101, 103)
        with self.assertRaises(InvalidGameStateError):
            self.manager.reveal_card(self.code, 103, "profession")

        # 2-raund: 104 haydaladi.
        for voter in (101, 102, 105):
            self.manager.cast_vote(self.code, voter, 104)
        self.manager.cast_vote(self.code, 106, 102)
        self.manager.cast_vote(self.code, 104, 102)
        eliminated = self.manager.tally_votes(self.code)
        self.assertIsNotNone(eliminated)
        self.assertEqual(eliminated.user_id, 104)
        self.assertEqual(len(self.room.alive_players), 4)
        self.assertEqual(self.room.current_round, 3)

        # 3-raund: 105 haydalgach tiriklar soni sig'imga tenglashadi.
        for voter in (101, 102, 106):
            self.manager.cast_vote(self.code, voter, 105)
        self.manager.cast_vote(self.code, 105, 102)
        eliminated = self.manager.tally_votes(self.code)
        self.assertIsNotNone(eliminated)
        self.assertEqual(eliminated.user_id, 105)
        self.assertEqual(len(self.room.alive_players), 3)
        self.assertEqual(self.room.status, RoomStatus.FINISHED)
        self.assertEqual(self.room.eliminated_players, [103, 104, 105])
        self.assertEqual(self.room.current_round, 3)
        self.assertEqual(
            sorted(player.user_id for player in self.room.alive_players),
            [101, 102, 106],
        )

        # Tugagan o'yinda keyingi amallar rad etiladi.
        with self.assertRaises(InvalidGameStateError):
            self.manager.cast_vote(self.code, 101, 102)
        with self.assertRaises(InvalidGameStateError):
            self.manager.tally_votes(self.code)
        with self.assertRaises(InvalidGameStateError):
            self.manager.start_game(self.code)
        with self.assertRaises(InvalidGameStateError):
            self.manager.join_room(self.code, 108, "Kech", "kech")

    def test_state_errors(self) -> None:
        self._join_rest()
        with self.assertRaises(InvalidGameStateError):
            self.manager.reveal_card(self.code, 101, "profession")
        with self.assertRaises(InvalidGameStateError):
            self.manager.tally_votes(self.code)

        self.manager.start_game(self.code)
        with self.assertRaises(InvalidGameStateError):
            self.manager.cast_vote(self.code, 101, 101)
        with self.assertRaises(PlayerNotFoundError):
            self.manager.cast_vote(self.code, 999, 101)

    def test_single_player_cannot_start(self) -> None:
        room = self.manager.create_room(201, "Yolg'iz", "yolgiz")
        with self.assertRaises(InvalidGameStateError):
            self.manager.start_game(room.code)
        self.assertEqual(room.status, RoomStatus.LOBBY)

    def test_invalid_capacity(self) -> None:
        with self.assertRaises(GameError):
            self.manager.create_room(301, "A", "a", bunker_capacity=1)
        with self.assertRaises(GameError):
            self.manager.create_room(302, "B", "b", bunker_capacity=17)


class VoteRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = GameManager(seed=99)
        self.room = self.manager.create_room(1, "Host", "host", bunker_capacity=2)
        for user_id in (2, 3, 4):
            self.manager.join_room(self.room.code, user_id, f"P{user_id}", f"p{user_id}")
        self.manager.start_game(self.room.code)

    def test_vote_can_be_changed(self) -> None:
        self.manager.cast_vote(self.room.code, 1, 2)
        self.assertEqual(self.room.players[2].votes_against, 1)
        self.manager.cast_vote(self.room.code, 1, 3)
        self.assertEqual(self.room.players[2].votes_against, 0)
        self.assertEqual(self.room.players[3].votes_against, 1)

    def test_tie_eliminates_nobody(self) -> None:
        self.manager.cast_vote(self.room.code, 1, 2)
        self.manager.cast_vote(self.room.code, 2, 1)
        self.manager.cast_vote(self.room.code, 3, 2)
        self.manager.cast_vote(self.room.code, 4, 1)
        eliminated = self.manager.tally_votes(self.room.code)
        self.assertIsNone(eliminated)
        self.assertEqual(self.room.eliminated_players, [])
        self.assertEqual(len(self.room.alive_players), 4)
        self.assertEqual(self.room.status, RoomStatus.PLAYING)
        self.assertEqual(self.room.current_round, 2)

    def test_reveal_is_idempotent(self) -> None:
        first = self.manager.reveal_card(self.room.code, 1, "health")
        second = self.manager.reveal_card(self.room.code, 1, "health")
        self.assertIs(first, second)
        self.assertTrue(second.is_revealed)


class ModuleLevelApiTest(unittest.TestCase):
    def test_module_functions(self) -> None:
        room = game_manager.create_room(901, "Modul", "modul", bunker_capacity=2)
        game_manager.join_room(room.code, 902, "Ikkinchi", "ikkinchi")
        game_manager.join_room(room.code, 903, "Uchinchi", "uchinchi")
        game_manager.join_room(room.code, 904, "To'rtinchi", "tortinchi")
        game_manager.start_game(room.code)
        card = game_manager.reveal_card(room.code, 901, "hobby")
        self.assertTrue(card.is_revealed)
        game_manager.cast_vote(room.code, 901, 902)
        eliminated = game_manager.tally_votes(room.code)
        self.assertEqual(eliminated.user_id, 902)
        self.assertGreaterEqual(len(room.code), 6)
        self.assertTrue(re.fullmatch(r"BNK\d{3}", room.code))


if __name__ == "__main__":
    unittest.main()
