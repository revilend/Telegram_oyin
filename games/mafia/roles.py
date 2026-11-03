"""«Revilend Mafia» rollar katalogi.

Har bir rol uchun o'zbekcha nom, qisqa tavsif, jamoa (:class:`Faction`) va
tunda harakat qilish-qilmasligi (:attr:`RoleProfile.has_night_action`)
saqlanadi. Tungi fazalar va ovoz berish logikasi shu katalogga tayanadi.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Faction(Enum):
    """Rol tegishli bo'lgan jamoa."""

    TOWN = "town"
    MAFIA = "mafia"
    NEUTRAL = "neutral"


class MafiaRole(Enum):
    """Barcha rollar. Qiymati — kod va API'da ishlatiladigan kalit."""

    # Tinch aholi
    CITIZEN = "citizen"
    SHERIFF = "sheriff"
    DOCTOR = "doctor"
    BODYGUARD = "bodyguard"
    BLOCKER = "blocker"
    KAMIKAZE = "kamikaze"
    SNIPER = "sniper"
    WITCH = "witch"
    MAYOR = "mayor"

    # Mafiya
    DON = "don"
    MAFIA = "mafia"
    LAWYER = "lawyer"
    BLACKMAILER = "blackmailer"

    # Yolg'izlar
    MANIAC = "maniac"
    JESTER = "jester"
    AMNESIAC = "amnesiac"


@dataclass(frozen=True)
class RoleProfile:
    """Bitta rolning o'yinchi ko'radigan ta'rifi."""

    role: MafiaRole
    name_uz: str
    description: str
    faction: Faction
    has_night_action: bool


ROLE_PROFILES: dict[MafiaRole, RoleProfile] = {
    MafiaRole.CITIZEN: RoleProfile(
        role=MafiaRole.CITIZEN,
        name_uz="Tinch fuqaro",
        description=(
            "Tunda maxsus harakati yo'q. Kunduzi muhokamada qatnashadi va "
            "mafiyani topishga yordam beradi."
        ),
        faction=Faction.TOWN,
        has_night_action=False,
    ),
    MafiaRole.SHERIFF: RoleProfile(
        role=MafiaRole.SHERIFF,
        name_uz="Sherif",
        description=(
            "Har tunda bitta o'yinchini tekshiradi va uning mafiya yoki "
            "tinch aholi ekanini bilib oladi."
        ),
        faction=Faction.TOWN,
        has_night_action=True,
    ),
    MafiaRole.DOCTOR: RoleProfile(
        role=MafiaRole.DOCTOR,
        name_uz="Doktor",
        description=(
            "Har tunda bitta o'yinchini davolaydi va uni o'ldirilishdan saqlaydi."
        ),
        faction=Faction.TOWN,
        has_night_action=True,
    ),
    MafiaRole.BODYGUARD: RoleProfile(
        role=MafiaRole.BODYGUARD,
        name_uz="Tansoqchi",
        description=(
            "Tunda bir o'yinchini qo'riqlaydi; unga qilingan hujumni o'ziga oladi."
        ),
        faction=Faction.TOWN,
        has_night_action=True,
    ),
    MafiaRole.BLOCKER: RoleProfile(
        role=MafiaRole.BLOCKER,
        name_uz="Bloklovchi",
        description=(
            "Tunda bitta o'yinchining harakatini bloklaydi, shu tunda u hech "
            "narsa qila olmaydi."
        ),
        faction=Faction.TOWN,
        has_night_action=True,
    ),
    MafiaRole.KAMIKAZE: RoleProfile(
        role=MafiaRole.KAMIKAZE,
        name_uz="Kamikadze",
        description=(
            "Tunda harakati yo'q, ammo o'ldirilsa qotilni ham o'zi bilan olib ketadi."
        ),
        faction=Faction.TOWN,
        has_night_action=False,
    ),
    MafiaRole.SNIPER: RoleProfile(
        role=MafiaRole.SNIPER,
        name_uz="Snayper",
        description=(
            "Tunda bitta o'yinchini otadi, lekin tinch aholini o'ldirsa o'zi halok bo'ladi."
        ),
        faction=Faction.TOWN,
        has_night_action=True,
    ),
    MafiaRole.WITCH: RoleProfile(
        role=MafiaRole.WITCH,
        name_uz="Jodugar",
        description=(
            "Tunda bitta o'yinchini o'ldirishi yoki tiriltirishi mumkin "
            "(cheklangan miqdorda)."
        ),
        faction=Faction.TOWN,
        has_night_action=True,
    ),
    MafiaRole.MAYOR: RoleProfile(
        role=MafiaRole.MAYOR,
        name_uz="Mer",
        description=(
            "Kunduzgi ovozini ikki barobar kuchli qilishi mumkin; tunda harakati yo'q."
        ),
        faction=Faction.TOWN,
        has_night_action=False,
    ),
    MafiaRole.DON: RoleProfile(
        role=MafiaRole.DON,
        name_uz="Don",
        description=(
            "Mafiya sardori: tunda qurbonni tanlaydi va sherif tekshiruvida "
            "begunoh ko'rinadi."
        ),
        faction=Faction.MAFIA,
        has_night_action=True,
    ),
    MafiaRole.MAFIA: RoleProfile(
        role=MafiaRole.MAFIA,
        name_uz="Mafiya",
        description=(
            "Tunda boshqa mafiya a'zolari bilan birga qurbon tanlaydi."
        ),
        faction=Faction.MAFIA,
        has_night_action=True,
    ),
    MafiaRole.LAWYER: RoleProfile(
        role=MafiaRole.LAWYER,
        name_uz="Advokat",
        description=(
            "Mafiya advokati: tunda bir o'yinchini himoya qilib, tekshiruv "
            "natijasini chalg'itadi."
        ),
        faction=Faction.MAFIA,
        has_night_action=True,
    ),
    MafiaRole.BLACKMAILER: RoleProfile(
        role=MafiaRole.BLACKMAILER,
        name_uz="Shantajchi",
        description=(
            "Tunda bir o'yinchini shantaj qiladi; u ertasi kuni ovoz bera olmaydi."
        ),
        faction=Faction.MAFIA,
        has_night_action=True,
    ),
    MafiaRole.MANIAC: RoleProfile(
        role=MafiaRole.MANIAC,
        name_uz="Maniak",
        description=(
            "Yolg'iz qotil: tunda o'ldiradi va faqat o'zi g'alaba qozonishni istaydi."
        ),
        faction=Faction.NEUTRAL,
        has_night_action=True,
    ),
    MafiaRole.JESTER: RoleProfile(
        role=MafiaRole.JESTER,
        name_uz="Hazilkash",
        description=(
            "Kunduzi ovoz bilan haydalsa o'yinda g'alaba qozonadi; tunda harakati yo'q."
        ),
        faction=Faction.NEUTRAL,
        has_night_action=False,
    ),
    MafiaRole.AMNESIAC: RoleProfile(
        role=MafiaRole.AMNESIAC,
        name_uz="Amneziya",
        description=(
            "Tunda halok bo'lgan o'yinchining rolini eslab qoladi va shu rolni egallaydi."
        ),
        faction=Faction.NEUTRAL,
        has_night_action=True,
    ),
}


def get_role_profile(role: MafiaRole | str) -> RoleProfile:
    """Rol profilini qaytaradi.

    ``role`` sifatida :class:`MafiaRole` yoki uning kaliti (masalan ``"sheriff"``)
    berilishi mumkin.

    Raises:
        ValueError: rol noma'lum bo'lsa.
    """
    if isinstance(role, MafiaRole):
        return ROLE_PROFILES[role]
    key = str(role or "").strip().lower()
    try:
        return ROLE_PROFILES[MafiaRole(key)]
    except ValueError as exc:
        raise ValueError(f"Noma'lum rol: {role!r}") from exc


def roles_by_faction(faction: Faction) -> list[MafiaRole]:
    """Berilgan jamoadagi barcha rollar ro'yxati (katalog tartibida)."""
    return [
        profile.role
        for profile in ROLE_PROFILES.values()
        if profile.faction is faction
    ]
