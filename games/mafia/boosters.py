"""«Revilend Mafia» uchun pullik boosterlar.

Boosterlar guruh xonasi kodiga bog'lanadi va bir o'yinda bir marta
ishlatiladi. Tangalar :mod:`core.economy` orqali yechiladi, o'yin holati
esa :class:`games.mafia.engine.MafiaRoom`da yangilanadi.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from core.economy import EconomyStore, UserAccount
from games.mafia.engine import GamePhase, MafiaError, MafiaRoom
from games.mafia.roles import get_role_profile


class MafiaBoosterError(Exception):
    """Mafiya boosterini sotib olish yoki ishlatish mumkin bo'lmaganda."""


@dataclass(frozen=True)
class MafiaBooster:
    """Mafiya boosterining katalog yozuvi."""

    key: str
    name: str
    emoji: str
    price: int
    description: str


KEVLAR = MafiaBooster(
    key="kevlar",
    name="Kevlar Jilet",
    emoji="🦺",
    price=40,
    description=(
        "40 tanga evaziga Kevlar jilet kiyib, omon qolasizmi? Tunda "
        "mafiya yoki maniak nishoniga tushsangiz, bir marta o'limdan "
        "saqlaydi."
    ),
)
REROLL = MafiaBooster(
    key="reroll",
    name="Rolni almashtirish",
    emoji="🔄",
    price=30,
    description="Birinchi tunda rolingizni boshqa o'yinchi roli bilan almashtiradi.",
)
DOUBLE_VOTE = MafiaBooster(
    key="double_vote",
    name="2x Ovoz",
    emoji="✖️",
    price=15,
    description="Kunduzgi ovoz berishda ovozingiz 2 barobar hisoblanadi.",
)

BOOSTERS: dict[str, MafiaBooster] = {
    booster.key: booster for booster in (KEVLAR, REROLL, DOUBLE_VOTE)
}


@dataclass(frozen=True)
class BoosterOption:
    """Mini App'da ko'rsatiladigan booster holati."""

    booster: MafiaBooster
    used: bool
    active: bool
    available: bool
    reason: str = ""


@dataclass(frozen=True)
class BoosterPurchase:
    """Muvaffaqiyatli xarid natijasi."""

    booster: MafiaBooster
    account: UserAccount
    message: str


def get_booster(key: str) -> MafiaBooster:
    """Kalit bo'yicha boosterni qaytaradi."""
    try:
        return BOOSTERS[str(key or "").strip().lower()]
    except KeyError as exc:
        raise MafiaBoosterError(f"Noma'lum Mafiya boosteri: {key!r}") from exc


def boosters_payload() -> list[dict[str, object]]:
    """Bot va Mini App uchun barcha Mafiya boosterlari."""
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


def _availability(
    room: MafiaRoom, player_id: int, booster: MafiaBooster
) -> tuple[bool, str]:
    """Booster hozir sotib olinishi mumkinligini qaytaradi."""
    if room.phase is GamePhase.LOBBY:
        return False, "O'yin hali boshlanmagan"
    if room.phase is GamePhase.FINISHED:
        return False, "O'yin tugagan"
    try:
        player = room.get_player(player_id)
    except MafiaError:
        return False, "Siz bu xonada emassiz"
    if not player.is_alive:
        return False, "Halok bo'lgan o'yinchi booster olmaydi"

    if booster.key == KEVLAR.key:
        if player.kevlar_used:
            return False, "Kevlar jilet allaqachon ishlatilgan"
        if player.kevlar_active:
            return False, "Kevlar jilet bu tun uchun kiyilgan"
        return True, ""

    if booster.key == REROLL.key:
        if player.role_rerolled:
            return False, "Rol allaqachon almashtirilgan"
        if room.phase is not GamePhase.NIGHT or room.round != 1:
            return False, "Rolni faqat birinchi tunda almashtirish mumkin"
        return True, ""

    if booster.key == DOUBLE_VOTE.key:
        if player.double_vote:
            return False, "2x ovoz allaqachon faol"
        if room.phase not in (GamePhase.DAY_REPORT, GamePhase.VOTING):
            return False, "2x ovoz faqat kunduzgi ovoz berishda olinadi"
        return True, ""

    return False, "Bu booster hozir mavjud emas"


def booster_options(
    room: MafiaRoom,
    code: str,
    economy: EconomyStore,
    user_id: int,
) -> list[BoosterOption]:
    """Har bir boosterning xarid holatini qaytaradi."""
    options: list[BoosterOption] = []
    for booster in BOOSTERS.values():
        used = economy.has_booster(code, user_id, booster.key)
        active = False
        player = room.players.get(int(user_id))
        if player is not None:
            if booster.key == KEVLAR.key:
                active = player.kevlar_active
            elif booster.key == DOUBLE_VOTE.key:
                active = player.double_vote
            elif booster.key == REROLL.key:
                active = player.role_rerolled
        if used:
            available, reason = False, "Bu o'yinda allaqachon ishlatilgan"
        else:
            available, reason = _availability(room, int(user_id), booster)
        options.append(
            BoosterOption(
                booster=booster,
                used=used,
                active=active,
                available=available and not used,
                reason=reason,
            )
        )
    return options


def purchase_booster(
    economy: EconomyStore,
    room: MafiaRoom,
    code: str,
    user_id: int,
    key: str,
    *,
    rng: random.Random | None = None,
) -> BoosterPurchase:
    """Boosterni sotib oladi va uning ta'sirini o'yin holatiga qo'llaydi.

    Raises:
        MafiaBoosterError: booster mavjud bo'lmasa, qoidalar buzilsa yoki
            tanga yetmasa.
    """
    booster = get_booster(key)
    uid = int(user_id)
    try:
        player = room.get_player(uid)
    except MafiaError as exc:
        raise MafiaBoosterError(str(exc)) from exc

    if economy.has_booster(code, uid, booster.key):
        raise MafiaBoosterError("Bu boosterni o'yinda allaqachon ishlatgansiz")
    available, reason = _availability(room, uid, booster)
    if not available:
        raise MafiaBoosterError(reason)

    try:
        account = economy.spend_coins(uid, booster.price)
    except Exception as exc:
        # EconomyError va InsufficientCoinsError ikkalasi ham tushunarli xato.
        raise MafiaBoosterError(str(exc)) from exc

    if not economy.record_booster(code, uid, booster.key):
        economy.add_coins(uid, booster.price)
        raise MafiaBoosterError("Bu boosterni o'yinda allaqachon ishlatgansiz")

    message = ""
    try:
        if booster.key == KEVLAR.key:
            player.kevlar_active = True
            message = (
                "🦺 Kevlar jilet kiyildi. Bu kecha o'limdan "
                "himoyalanasiz."
            )
        elif booster.key == REROLL.key:
            new_role = room.reroll_role(uid, rng=rng)
            message = (
                "🔄 Rol almashtirildi. Yangi rolingiz: "
                f"{get_role_profile(new_role).name_uz}."
            )
        elif booster.key == DOUBLE_VOTE.key:
            player.double_vote = True
            message = "✖️ 2x ovoz faollashtirildi."
    except Exception as exc:
        economy.add_coins(uid, booster.price)
        raise MafiaBoosterError(str(exc)) from exc

    account = economy.get_user(uid)
    return BoosterPurchase(booster=booster, account=account, message=message)
