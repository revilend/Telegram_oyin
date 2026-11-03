"""«Revilend Mafia» uchun dinamik va balansli rol generatori.

Tarkib o'yinchilar soniga moslashadi: 4–5 kishilik tezkor partiyalar faqat
klassik rollar bilan o'tadi, 6 kishidan boshlab Don va Tansoqchi, 8 kishidan
boshlab Bloklovchi, Maniak va Snayper, 10 kishidan boshlab esa Hazilkash,
Jodugar, Mer va Advokat qo'shiladi. 13 va undan ko'p o'yinchi uchun boyitilgan
rollarning to'liq jamlanmasi ishlatiladi; sig'maganlar Tinch fuqaro bilan
to'ldiriladi. Rol soni har doim o'yinchilar soniga teng bo'ladi.
"""

from __future__ import annotations

import random
from typing import Hashable, Sequence, TypeVar

from games.mafia.roles import MafiaRole

MIN_PLAYERS = 4

PlayerT = TypeVar("PlayerT", bound=Hashable)

# 4 kishi: faqat tezkor klassika.
QUICK_PLAY_ROLES: tuple[MafiaRole, ...] = (
    MafiaRole.MAFIA,
    MafiaRole.SHERIFF,
    MafiaRole.CITIZEN,
    MafiaRole.CITIZEN,
)

# 5 kishi: klassik tarkib.
CLASSIC_ROLES: tuple[MafiaRole, ...] = (
    MafiaRole.MAFIA,
    MafiaRole.SHERIFF,
    MafiaRole.DOCTOR,
    MafiaRole.CITIZEN,
    MafiaRole.CITIZEN,
)

# 6–7 kishi: Don va Tansoqchi qo'shiladi.
CORE_ROLES: tuple[MafiaRole, ...] = (
    MafiaRole.DON,
    MafiaRole.MAFIA,
    MafiaRole.SHERIFF,
    MafiaRole.DOCTOR,
    MafiaRole.BODYGUARD,
)

# 8–9 kishi: faol maxsus rollar.
MID_GAME_ROLES: tuple[MafiaRole, ...] = (
    MafiaRole.BLOCKER,
    MafiaRole.MANIAC,
    MafiaRole.SNIPER,
)

# 10–12 kishi: kuchli va hiyla-nayrangli rollar.
LATE_GAME_ROLES: tuple[MafiaRole, ...] = (
    MafiaRole.JESTER,
    MafiaRole.WITCH,
    MafiaRole.MAYOR,
    MafiaRole.LAWYER,
)

# 13+ kishi: boyitilgan jamlanmaning qolgan rollari.
FULL_GAME_ROLES: tuple[MafiaRole, ...] = (
    MafiaRole.BLACKMAILER,
    MafiaRole.KAMIKAZE,
    MafiaRole.AMNESIAC,
)

ENRICHED_ROLES: tuple[MafiaRole, ...] = (
    CORE_ROLES + MID_GAME_ROLES + LATE_GAME_ROLES + FULL_GAME_ROLES
)


def get_balanced_roles(player_count: int) -> list[MafiaRole]:
    """O'yinchilar soniga mos, balansli rollar ro'yxatini qaytaradi.

    Ro'yxat uzunligi har doim ``player_count`` ga teng va tartibi o'yin
    boshlanishida aralashtiriladi (:func:`deal_mafia_roles`).

    Args:
        player_count: O'yinchilar soni (kamida 4).

    Raises:
        TypeError: ``player_count`` butun son bo'lmasa.
        ValueError: O'yinchi soni 4 dan kam bo'lsa.
    """
    if isinstance(player_count, bool) or not isinstance(player_count, int):
        raise TypeError("player_count butun son bo'lishi kerak")
    if player_count < MIN_PLAYERS:
        raise ValueError(
            f"Mafiya uchun kamida {MIN_PLAYERS} o'yinchi kerak, {player_count} berildi"
        )

    if player_count == 4:
        return list(QUICK_PLAY_ROLES)
    if player_count == 5:
        return list(CLASSIC_ROLES)

    roles = list(CORE_ROLES)

    if player_count <= 7:
        roles += [MafiaRole.CITIZEN] * (player_count - len(roles))
        return roles

    if player_count <= 9:
        roles += list(MID_GAME_ROLES)
        roles += [MafiaRole.CITIZEN] * (player_count - len(roles))
        return roles

    if player_count <= 12:
        roles += list(MID_GAME_ROLES) + list(LATE_GAME_ROLES)
        # 10 → BLOCKER, MANIAC, SNIPER, JESTER, WITCH
        # 11 → + MAYOR, 12 → + LAWYER
        return roles[:player_count]

    roles = list(ENRICHED_ROLES[:player_count])
    if player_count > len(ENRICHED_ROLES):
        roles += [MafiaRole.CITIZEN] * (player_count - len(ENRICHED_ROLES))
    return roles


def deal_mafia_roles(
    players: Sequence[PlayerT], *, rng: random.Random | None = None
) -> dict[PlayerT, MafiaRole]:
    """Rollarni aralashtirib, o'yinchilarga taqsimlaydi.

    Args:
        players: Hashable o'yinchi identifikatorlari (user_id, ism va h.k.).
        rng: Ixtiyoriy tasodif generatori (testlarda takrorlanuvchi natija uchun).

    Returns:
        Har bir o'yinchi uchun bitta rol.

    Raises:
        ValueError: O'yinchi soni 4 dan kam yoki identifikatorlar takrorlangan bo'lsa.
    """
    participants = list(players)
    if len(participants) != len(set(participants)):
        raise ValueError("O'yinchi identifikatorlari takrorlanmasligi kerak")

    roles = get_balanced_roles(len(participants))
    (rng if rng is not None else random).shuffle(roles)
    return dict(zip(participants, roles))
