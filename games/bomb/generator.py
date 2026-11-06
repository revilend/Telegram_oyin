"""«Xavfli Bomba» dastasini yaratish.

O'yin qoidasi: har bir o'yinchi bitta Zararsizlantirish va to'rtta tasodifiy
harakat kartasi bilan boshlaydi. Umumiy dastada o'yinchilar sonidan bitta kam
Portlovchi Bomba va qolgan Zararsizlantirish kartalari bo'ladi; harakat
kartalari faqat boshlang'ich qo'llarga tarqatiladi.
"""

from __future__ import annotations

import random

from games.bomb.cards import ACTION_CARD_TYPES, CardType

MIN_PLAYERS = 2
MAX_PLAYERS = 8

DEFUSES_PER_PLAYER = 1
ACTION_CARDS_PER_PLAYER = 4

# Kamida oltita defuse bo'ladi; katta guruhlarda har bir o'yinchiga bittadan
# tarqatilgach, dastaga ham kamida bitta defuse qoladi.
TOTAL_DEFUSES = 6


class BombDeck(list):
    """Tortish dastasi va o'yinchilarning boshlang'ich qo'llari.

    ``BombDeck`` oddiy ro'yxat bo'lgani uchun ``len(deck)``, ``deck.count``
    va iteratsiya tortish dastasi ustida ishlaydi. Boshlang'ich qo'llar
    ``hands`` atributida, o'yinchilar tartibida saqlanadi.
    """

    def __init__(
        self,
        cards: list[CardType],
        hands: list[list[CardType]],
    ) -> None:
        super().__init__(cards)
        self.hands = [list(hand) for hand in hands]

    @property
    def draw_pile(self) -> list[CardType]:
        """Tortish dastasining nusxasi."""
        return list(self)

    @property
    def total_cards(self) -> int:
        """Qo'llar va dastadagi barcha kartalar soni."""
        return len(self) + sum(len(hand) for hand in self.hands)


def _validate_player_count(player_count: int) -> int:
    if isinstance(player_count, bool) or not isinstance(player_count, int):
        raise TypeError("player_count butun son bo'lishi kerak")
    if player_count < MIN_PLAYERS:
        raise ValueError(
            f"Xavfli Bomba uchun kamida {MIN_PLAYERS} o'yinchi kerak, "
            f"{player_count} berildi"
        )
    if player_count > MAX_PLAYERS:
        raise ValueError(
            f"Xavfli Bomba uchun ko'pi bilan {MAX_PLAYERS} o'yinchi mumkin, "
            f"{player_count} berildi"
        )
    return player_count


def _random_actions(rng: random.Random, count: int) -> list[CardType]:
    return [rng.choice(ACTION_CARD_TYPES) for _ in range(count)]


def build_bomb_deck(
    player_count: int,
    rng: random.Random | None = None,
) -> BombDeck:
    """O'yinchilar soniga mos dasta va boshlang'ich qo'llarni yaratadi.

    Har bir qo'lda aynan bitta ``DEFUSE`` va to'rtta harakat kartasi bo'ladi.
    Tortish dastasida ``player_count - 1`` ta ``BOMB``, qolgan defuselar va
    qo'shimcha harakat kartalari aralashtirilgan holda qaytadi.
    """
    count = _validate_player_count(player_count)
    randomizer = rng or random.Random()

    hands: list[list[CardType]] = []
    for _ in range(count):
        hand = [CardType.DEFUSE] * DEFUSES_PER_PLAYER
        hand.extend(_random_actions(randomizer, ACTION_CARDS_PER_PLAYER))
        randomizer.shuffle(hand)
        hands.append(hand)

    total_defuses = max(TOTAL_DEFUSES, count + 1)
    remaining_defuses = total_defuses - count
    deck = (
        [CardType.BOMB] * (count - 1)
        + [CardType.DEFUSE] * remaining_defuses
    )
    randomizer.shuffle(deck)
    return BombDeck(deck, hands)
