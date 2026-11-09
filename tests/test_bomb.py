"""«Revilend: Xavfli Bomba» kartalari, dastasi va dvigateli testlari."""

from __future__ import annotations

import random
import unittest

from games.bomb.cards import (
    ACTION_CARD_TYPES,
    CARD_INFO,
    CardType,
    card_info,
)
from games.bomb.engine import (
    BombError,
    BombRoom,
    BombStatus,
    check_winner,
    create_room,
    draw_card,
    play_action_card,
    reset_rooms,
)
from games.bomb.generator import build_bomb_deck


def make_room(
    player_count: int = 3,
    *,
    seed: int = 1,
    awards: list[tuple[int, int]] | None = None,
) -> BombRoom:
    """Test uchun tayyor o'yin xonasi yasaydi."""
    room = BombRoom(
        "BMB001",
        rng=random.Random(seed),
        coin_award=(
            (lambda uid, amount: awards.append((uid, amount)))
            if awards is not None
            else None
        ),
    )
    for user_id in range(1, player_count + 1):
        room.add_player(user_id, f"P{user_id}")
    room.start()
    return room


class CardMetadataTest(unittest.TestCase):
    def test_every_card_has_name_symbol_and_ability(self) -> None:
        for card in CardType:
            with self.subTest(card=card):
                info = card_info(card)
                self.assertEqual(info, CARD_INFO[card])
                self.assertTrue(info.name.strip())
                self.assertTrue(info.symbol.strip())
                self.assertTrue(info.ability.strip())

    def test_card_names_use_the_new_alphabet(self) -> None:
        self.assertEqual(card_info(CardType.BOMB).name, "Portlovçi Bomba")
        self.assertEqual(card_info(CardType.DEFUSE).name, "Zararsizlantiriş")
        self.assertEqual(card_info(CardType.ATTACK).name, "Hujum")
        self.assertEqual(card_info(CardType.SKIP).name, "Ötkäzib yuborish")
        self.assertEqual(card_info(CardType.FUTURE).name, "Kelajak")
        self.assertEqual(card_info(CardType.SHUFFLE).name, "Aralaştiriş")
        self.assertEqual(card_info(CardType.STEAL).name, "Öğirlaş")


class BombDeckTest(unittest.TestCase):
    def test_deck_matches_player_count(self) -> None:
        deal = build_bomb_deck(4, rng=random.Random(7))

        self.assertEqual(len(deal.hands), 4)
        for hand in deal.hands:
            self.assertEqual(len(hand), 5)
            self.assertEqual(hand.count(CardType.DEFUSE), 1)
            self.assertEqual(
                sum(1 for card in hand if card in ACTION_CARD_TYPES), 4
            )

        self.assertEqual(deal.count(CardType.BOMB), 3)
        self.assertEqual(deal.count(CardType.DEFUSE), 2)
        self.assertEqual(len(deal), 5)
        self.assertEqual(deal.total_cards, 20 + len(deal))

    def test_bomb_count_is_one_less_than_players(self) -> None:
        for player_count in (2, 3, 5, 8):
            with self.subTest(player_count=player_count):
                deal = build_bomb_deck(player_count, rng=random.Random(11))
                self.assertEqual(
                    deal.count(CardType.BOMB), player_count - 1
                )
                self.assertEqual(len(deal.hands), player_count)
                self.assertEqual(
                    sum(hand.count(CardType.DEFUSE) for hand in deal.hands),
                    player_count,
                )

    def test_invalid_player_count_rejected(self) -> None:
        for value in (0, 1, 9):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    build_bomb_deck(value)
        with self.assertRaises(TypeError):
            build_bomb_deck(True)  # type: ignore[arg-type]


class BombTurnTest(unittest.TestCase):
    def test_defuse_saves_player_and_returns_bomb_to_deck(self) -> None:
        room = make_room(2)
        room.deck = [CardType.BOMB]
        room.players[1].hand = [CardType.DEFUSE]

        result = room.draw_card(1)

        self.assertTrue(result.awaiting_defuse)
        self.assertFalse(result.defused)
        self.assertIs(result.card, CardType.BOMB)
        self.assertTrue(room.players[1].is_alive)
        self.assertEqual(room.pending_defuse, 1)
        self.assertEqual(room.deck, [])
        self.assertEqual(room.current_player_id, 1)

        resolved = room.defuse_bomb(1, "middle")
        self.assertTrue(resolved.defused)
        self.assertFalse(resolved.awaiting_defuse)
        self.assertNotIn(CardType.DEFUSE, room.players[1].hand)
        self.assertEqual(room.deck, [CardType.BOMB])
        self.assertEqual(room.current_player_id, 2)

    def test_bomb_without_defuse_eliminates_player_and_awards_winner(self) -> None:
        awards: list[tuple[int, int]] = []
        room = make_room(2, awards=awards)
        room.deck = [CardType.BOMB]
        room.players[1].hand = []

        result = room.draw_card(1)

        self.assertTrue(result.exploded)
        self.assertEqual(result.eliminated_id, 1)
        self.assertFalse(room.players[1].is_alive)
        self.assertEqual(result.winner_id, 2)
        self.assertIs(room.status, BombStatus.FINISHED)
        self.assertEqual(awards, [(2, 30)])
        self.assertEqual(room.players[1].hand, [])

    def test_normal_draw_goes_to_hand_and_advances_turn(self) -> None:
        room = make_room(2)
        room.deck = [CardType.ATTACK]

        result = room.draw_card(1)

        self.assertFalse(result.exploded)
        self.assertIn(CardType.ATTACK, room.players[1].hand)
        self.assertEqual(room.current_player_id, 2)
        self.assertEqual(result.deck_size, 0)

    def test_attack_chain_forces_four_draws(self) -> None:
        room = make_room(3)
        room.players[1].hand = [CardType.ATTACK]
        room.players[2].hand = [CardType.ATTACK]
        room.deck = [CardType.SKIP, CardType.SKIP, CardType.SKIP, CardType.SKIP]

        room.play_action_card(1, CardType.ATTACK)
        self.assertEqual(room.players[2].draw_turns_left, 2)
        room.play_action_card(2, CardType.ATTACK)

        self.assertEqual(room.players[3].draw_turns_left, 4)
        self.assertEqual(room.current_player_id, 3)

    def test_attack_gives_next_player_two_draws(self) -> None:
        room = make_room(3)
        room.players[1].hand = [CardType.ATTACK]
        room.deck = [CardType.SKIP, CardType.SKIP]

        result = room.play_action_card(1, CardType.ATTACK)

        self.assertIs(result.card, CardType.ATTACK)
        self.assertEqual(result.target_id, 2)
        self.assertEqual(room.players[2].draw_turns_left, 2)
        self.assertEqual(room.current_player_id, 2)
        self.assertNotIn(CardType.ATTACK, room.players[1].hand)

    def test_attacked_player_draws_twice(self) -> None:
        room = make_room(3)
        room.players[1].hand = [CardType.ATTACK]
        room.deck = [CardType.SKIP, CardType.SKIP]
        room.play_action_card(1, CardType.ATTACK)

        first = room.draw_card(2)
        second = room.draw_card(2)

        self.assertEqual(first.player_id, 2)
        self.assertEqual(second.player_id, 2)
        self.assertEqual(room.current_player_id, 3)

    def test_skip_advances_without_drawing(self) -> None:
        room = make_room(2)
        room.players[1].hand = [CardType.SKIP]
        room.deck = [CardType.ATTACK]

        result = room.play_action_card(1, CardType.SKIP)

        self.assertIs(result.card, CardType.SKIP)
        self.assertEqual(len(room.deck), 1)
        self.assertEqual(room.current_player_id, 2)

    def test_future_peeks_three_cards_without_removing_them(self) -> None:
        room = make_room(2)
        room.players[1].hand = [CardType.FUTURE]
        room.deck = [
            CardType.DEFUSE,
            CardType.ATTACK,
            CardType.SKIP,
            CardType.BOMB,
        ]

        result = room.play_action_card(1, CardType.FUTURE)

        self.assertEqual(
            result.future_cards,
            (CardType.DEFUSE, CardType.ATTACK, CardType.SKIP),
        )
        self.assertEqual(len(room.deck), 4)
        self.assertEqual(room.current_player_id, 1)
        self.assertEqual(room.last_future_owner, 1)
        self.assertEqual(room.last_future_cards, result.future_cards)

    def test_shuffle_reorders_deck(self) -> None:
        class ReverseShuffle(random.Random):
            def shuffle(self, items: list[CardType]) -> None:
                items.reverse()

        room = make_room(2)
        room._rng = ReverseShuffle(1)
        room.players[1].hand = [CardType.SHUFFLE]
        room.deck = [CardType.BOMB, CardType.DEFUSE, CardType.ATTACK]

        room.play_action_card(1, CardType.SHUFFLE)

        self.assertEqual(
            room.deck,
            [CardType.ATTACK, CardType.DEFUSE, CardType.BOMB],
        )

    def test_steal_takes_random_card_from_target(self) -> None:
        room = make_room(2)
        room.players[1].hand = [CardType.STEAL]
        room.players[2].hand = [CardType.ATTACK, CardType.SKIP]

        result = room.play_action_card(1, CardType.STEAL, target_id=2)

        self.assertIn(result.stolen_card, (CardType.ATTACK, CardType.SKIP))
        self.assertEqual(len(room.players[2].hand), 1)
        self.assertEqual(room.players[1].hand, [result.stolen_card])

    def test_steal_rejects_invalid_target_without_losing_card(self) -> None:
        room = make_room(2)
        room.players[1].hand = [CardType.STEAL]

        with self.assertRaises(BombError):
            room.play_action_card(1, CardType.STEAL, target_id=1)
        self.assertIn(CardType.STEAL, room.players[1].hand)

    def test_cannot_play_bomb_or_defuse(self) -> None:
        room = make_room(2)
        room.players[1].hand = [CardType.BOMB, CardType.DEFUSE]

        for card in (CardType.BOMB, CardType.DEFUSE):
            with self.subTest(card=card):
                with self.assertRaises(BombError):
                    room.play_action_card(1, card)

    def test_only_current_player_can_draw(self) -> None:
        room = make_room(2)
        room.deck = [CardType.SKIP, CardType.SKIP]

        with self.assertRaises(BombError):
            room.draw_card(2)

    def test_winner_reward_is_paid_once(self) -> None:
        awards: list[tuple[int, int]] = []
        room = make_room(3, awards=awards)
        room.players[2].is_alive = False
        room.players[3].is_alive = False

        self.assertEqual(room.check_winner(), 1)
        self.assertEqual(room.check_winner(), 1)
        self.assertEqual(room.winner_id, 1)
        self.assertEqual(awards, [(1, 30)])


class BombDefusePlacementTest(unittest.TestCase):
    def test_defuse_can_hide_bomb_at_top_middle_or_bottom(self) -> None:
        for position, expected in (
            ("top", 0),
            ("bottom", 2),
            ("middle", 1),
        ):
            with self.subTest(position=position):
                room = make_room(2)
                room.deck = [CardType.BOMB, CardType.SKIP, CardType.ATTACK]
                room.players[1].hand = [CardType.DEFUSE]
                room.draw_card(1)
                result = room.defuse_bomb(1, position)
                self.assertEqual(result.returned_index, expected)
                self.assertIs(room.deck[expected], CardType.BOMB)


class BombRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_rooms()
        self.addCleanup(reset_rooms)

    def test_module_level_flow(self) -> None:
        awards: list[tuple[int, int]] = []
        room = create_room(
            "bmb777", coin_award=lambda uid, amount: awards.append((uid, amount))
        )
        room.add_player(1, "Ali")
        room.add_player(2, "Vali")
        room.start()
        room.deck = [CardType.BOMB]
        room.players[1].hand = []

        result = draw_card("BMB777", 1)

        self.assertTrue(result.exploded)
        self.assertEqual(result.winner_id, 2)
        self.assertEqual(check_winner("BMB777"), 2)
        self.assertEqual(check_winner(), 2)
        self.assertEqual(awards, [(2, 30)])

    def test_play_action_through_module_registry(self) -> None:
        room = create_room("BMB778")
        room.add_player(1, "Ali")
        room.add_player(2, "Vali")
        room.start()
        room.players[1].hand = [CardType.SKIP]

        result = play_action_card("BMB778", 1, "skip")

        self.assertIs(result.card, CardType.SKIP)
        self.assertEqual(room.current_player_id, 2)


if __name__ == "__main__":
    unittest.main()
