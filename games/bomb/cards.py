"""«Revilend: Xavfli Bomba» kartalari va ularning qobiliyatlari.

Kartalar oddiy :class:`CardType` qiymatlari bilan ifodalanadi. Har bir tur
uchun o'zbekcha nom, belgi va qisqa qobiliyat matni :data:`CARD_INFO` da
saqlanadi; bu matnlarni bot va Mini App bir xil manbadan oladi.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CardType(str, Enum):
    """Dastadagi barcha karta turlari."""

    BOMB = "BOMB"
    DEFUSE = "DEFUSE"
    ATTACK = "ATTACK"
    SKIP = "SKIP"
    FUTURE = "FUTURE"
    SHUFFLE = "SHUFFLE"
    STEAL = "STEAL"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class CardInfo:
    """Bitta karta turining foydalanuvchiga ko'rinadigan tavsifi."""

    name: str
    symbol: str
    ability: str


CARD_INFO: dict[CardType, CardInfo] = {
    CardType.BOMB: CardInfo(
        name="Portlovchi Bomba",
        symbol="💥",
        ability=(
            "Tortilganda portlaydi. Qölingizda Zararsizlantirish bölsa, "
            "uni sarflab qutqarasiz; bölsa — öyindan çiqasiz."
        ),
    ),
    CardType.DEFUSE: CardInfo(
        name="Zararsizlantirish",
        symbol="🛡️",
        ability=(
            "Portlovchi Bombani zararsizlantirib, uni dastaga tasodifiy "
            "joyga qaytaradi."
        ),
    ),
    CardType.ATTACK: CardInfo(
        name="Hujum",
        symbol="⚔️",
        ability=(
            "Navbatni keyingi öyinçiga ötkazadi va unga 2 marta tortiş "
            "huquqini beradi."
        ),
    ),
    CardType.SKIP: CardInfo(
        name="Ötkäzib yuborish",
        symbol="⏭️",
        ability="Karta tortmasdan navbatni keyingisiga ötkazadi.",
    ),
    CardType.FUTURE: CardInfo(
        name="Kelajak",
        symbol="🔮",
        ability="Dastadagi eng yuqori 3 kartani faqat sizga körsätadi.",
    ),
    CardType.SHUFFLE: CardInfo(
        name="Aralashtirish",
        symbol="🔀",
        ability="Tortiş dastasini tasodifiy tartibda aralashtiradi.",
    ),
    CardType.STEAL: CardInfo(
        name="Öğirlash",
        symbol="🖐️",
        ability=(
            "Raqib qölidan 1 ta tasodifiy kartani öz qölingizga oladi."
        ),
    ),
}

# Boshlang'ich qo'llarga va dastaga tarqatiladigan harakat kartalari.
ACTION_CARD_TYPES: tuple[CardType, ...] = (
    CardType.ATTACK,
    CardType.SKIP,
    CardType.FUTURE,
    CardType.SHUFFLE,
    CardType.STEAL,
)


def card_info(card: CardType) -> CardInfo:
    """Karta turining tavsifini qaytaradi."""
    return CARD_INFO[CardType(card)]


def card_name(card: CardType) -> str:
    """Kartaning o'zbekcha nomini qaytaradi."""
    return card_info(card).name


def card_symbol(card: CardType) -> str:
    """Kartaning belgisini qaytaradi."""
    return card_info(card).symbol


def card_ability(card: CardType) -> str:
    """Kartaning qobiliyat matnini qaytaradi."""
    return card_info(card).ability
