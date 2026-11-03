"""«Bunker» o'yinidagi pullik boosterlar katalogi."""

from __future__ import annotations

from dataclasses import dataclass


class BoosterError(Exception):
    """Booster ishlatish qoidalari buzilganda ko'tariladi."""


class InsufficientCoinsError(BoosterError):
    """O'yinchi balansida booster uchun tanga yetarli emas."""


@dataclass(frozen=True)
class Booster:
    """Bitta boosterning nomi, narxi va tavsifi."""

    key: str
    name: str
    emoji: str
    price: int
    description: str


SHIELD = Booster(
    key="shield",
    name="Bunker Qalqoni",
    emoji="🛡️",
    price=50,
    description="Haydalishdan bir marta saqlanib qoladi.",
)
DOUBLE_VOTE = Booster(
    key="double_vote",
    name="2 karra ovoz",
    emoji="✖️",
    price=15,
    description="Joriy raunddagi ovozingiz 2 ta hisoblanadi.",
)
REROLL = Booster(
    key="reroll",
    name="Kartani almashtirish",
    emoji="🔄",
    price=20,
    description="Yopiq kartani boshqa tasodifiy karta bilan almashtiradi.",
)

BOOSTERS: dict[str, Booster] = {
    booster.key: booster for booster in (SHIELD, DOUBLE_VOTE, REROLL)
}


def get_booster(key: str) -> Booster:
    """Kalit bo'yicha boosterni qaytaradi yoki tushunarli xato beradi."""
    try:
        return BOOSTERS[str(key).strip().lower()]
    except KeyError as exc:
        raise BoosterError(f"Noma'lum booster: {key!r}") from exc


def boosters_payload() -> list[dict[str, object]]:
    """Mini App va bot uchun boosterlar ro'yxati."""
    return [
        {
            "key": booster.key,
            "name": booster.name,
            "emoji": booster.emoji,
            "price": booster.price,
            "description": booster.description,
        }
        for booster in BOOSTERS.values()
    ]
