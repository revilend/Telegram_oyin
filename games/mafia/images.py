"""«Revilend Mafia» rasmlari: rol, sahna va g'alaba kartalari.

Barcha rasmlar ``webapp/assets/images/mafia/`` papkasida saqlanadi. Bot
guruh xabarlarida ularni ``FSInputFile`` orqali yuboradi, Mini App esa
:func:`role_image_url` qaytargan manzil orqali ko'rsatadi.

``mafia`` roli uchun alohida fayl yo'q, shuning uchun ``mobster.png``
ishlatiladi; ``amnesiac`` uchun esa neytral ``citizen.png`` olinadi.
"""

from __future__ import annotations

from pathlib import Path

from games.mafia.engine import Winner
from games.mafia.roles import MafiaRole

IMAGE_DIR = (
    Path(__file__).resolve().parents[2]
    / "webapp"
    / "assets"
    / "images"
    / "mafia"
)
ASSET_URL_PREFIX = "/assets/images/mafia"

COVER_IMAGE = "cover.png"
NIGHT_IMAGE = "night.png"
DAY_IMAGE = "day.png"
ELIMINATED_IMAGE = "eliminated.jpg"

ROLE_IMAGE_FILES: dict[MafiaRole, str] = {
    MafiaRole.CITIZEN: "citizen.png",
    MafiaRole.SHERIFF: "sheriff.png",
    MafiaRole.DOCTOR: "doctor.png",
    MafiaRole.BODYGUARD: "bodyguard.png",
    MafiaRole.BLOCKER: "blocker.png",
    MafiaRole.KAMIKAZE: "kamikaze.png",
    MafiaRole.SNIPER: "sniper.png",
    MafiaRole.WITCH: "witch.png",
    MafiaRole.MAYOR: "mayor.png",
    MafiaRole.DON: "don.png",
    MafiaRole.MAFIA: "mobster.png",
    MafiaRole.LAWYER: "lawyer.png",
    MafiaRole.BLACKMAILER: "blackmailer.png",
    MafiaRole.MANIAC: "maniac.png",
    MafiaRole.JESTER: "jester.png",
    MafiaRole.AMNESIAC: "citizen.png",
}

VICTORY_IMAGE_FILES: dict[Winner, str] = {
    Winner.TOWN: "town_victory.png",
    Winner.MAFIA: "mafia_victory.png",
    Winner.MANIAC: "maniac_victory.png",
    Winner.JESTER: "jester_victory.png",
}


def image_path(filename: str) -> Path:
    """Rasm papkasidagi faylning to'liq yo'li."""
    return IMAGE_DIR / filename


def role_image_file(role: MafiaRole | str) -> str:
    """Rol uchun rasm fayli nomi."""
    if not isinstance(role, MafiaRole):
        role = MafiaRole(str(role).strip().lower())
    try:
        return ROLE_IMAGE_FILES[role]
    except KeyError as exc:  # pragma: no cover - barcha rollar qamrab olingan
        raise ValueError(f"Rol uchun rasm topilmadi: {role}") from exc


def role_image_path(role: MafiaRole | str) -> Path:
    """Rol kartasi rasmining to'liq yo'li."""
    return image_path(role_image_file(role))


def role_image_url(role: MafiaRole | str) -> str:
    """Mini App uchun rol rasmining URL manzili."""
    return f"{ASSET_URL_PREFIX}/{role_image_file(role)}"


def victory_image_file(winner: Winner) -> str:
    """G'olib jamoa uchun rasm fayli nomi."""
    try:
        return VICTORY_IMAGE_FILES[winner]
    except KeyError as exc:
        raise ValueError(f"G'olib uchun rasm topilmadi: {winner}") from exc


def victory_image_path(winner: Winner) -> Path:
    """G'olib jamoa rasmining to'liq yo'li."""
    return image_path(victory_image_file(winner))
