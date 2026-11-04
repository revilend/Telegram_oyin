"""Missiyalar katalogi: taraqqiyotni o'lchaydigan maqsadlar va mukofotlar.

Har bir missiya foydalanuvchi statistikasidagi bitta ko'rsatkichga bog'langan
(``games_played``, ``wins``, ``referral_count`` yoki ``bonus_streak``). Mukofot faqat bir marta
olinadi; olingan missiyalar ``core.economy.EconomyStore``da saqlanadi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.economy import EconomyError, EconomyStore, UserAccount

MISSION_GAMES = "games_played"
MISSION_WINS = "wins"
MISSION_REFERRALS = "referral_count"
MISSION_BONUS_STREAK = "bonus_streak"


@dataclass(frozen=True)
class Mission:
    """Bitta missiya ta'rifi."""

    key: str
    title: str
    emoji: str
    description: str
    metric: str
    target: int
    reward: int


MISSIONS: tuple[Mission, ...] = (
    Mission(
        key="first_game",
        title="Birinchi qadam",
        emoji="🎲",
        description="1 ta istalgan o'yinda qatnashing",
        metric=MISSION_GAMES,
        target=1,
        reward=50,
    ),
    Mission(
        key="first_win",
        title="G'olib",
        emoji="🏆",
        description="Bunker yoki Mafiyada 1 marta g'alaba qozoning",
        metric=MISSION_WINS,
        target=1,
        reward=100,
    ),
    Mission(
        key="friend_1",
        title="Do'stlar davrasi",
        emoji="👥",
        description="1 ta do'stni referal orqali taklif qiling",
        metric=MISSION_REFERRALS,
        target=1,
        reward=75,
    ),
    Mission(
        key="bonus_3",
        title="Faol o'yinchi",
        emoji="🔥",
        description="3 kun ketma-ket kunlik bonus oling",
        metric=MISSION_BONUS_STREAK,
        target=3,
        reward=120,
    ),
    Mission(
        key="games_5",
        title="Tajribali",
        emoji="🛡",
        description="Jami 5 ta o'yinda qatnashing",
        metric=MISSION_GAMES,
        target=5,
        reward=200,
    ),
)

MISSIONS_BY_KEY: dict[str, Mission] = {mission.key: mission for mission in MISSIONS}


@dataclass(frozen=True)
class MissionStatus:
    """Missiyaning o'yinchi uchun holati."""

    mission: Mission
    progress: int
    claimed: bool

    @property
    def completed(self) -> bool:
        return self.progress >= self.mission.target

    @property
    def claimable(self) -> bool:
        return self.completed and not self.claimed

    @property
    def percent(self) -> int:
        target = max(1, self.mission.target)
        return min(100, int(round(self.progress / target * 100)))


def mission_progress(account: UserAccount, mission: Mission) -> int:
    """Hisob statistikasidan missiya taraqqiyotini o'qiydi (chegaralangan)."""
    value = int(getattr(account, mission.metric, 0) or 0)
    return max(0, min(value, mission.target))


def mission_statuses(store: EconomyStore, user_id: int) -> list[MissionStatus]:
    """Foydalanuvchining barcha missiyalari holati."""
    uid = int(user_id)
    account = store.ensure_user(uid)
    claimed = store.claimed_missions(uid)
    return [
        MissionStatus(
            mission=mission,
            progress=mission_progress(account, mission),
            claimed=mission.key in claimed,
        )
        for mission in MISSIONS
    ]


def claim_mission(
    store: EconomyStore, user_id: int, key: str
) -> tuple[MissionStatus, UserAccount]:
    """Bajarilgan missiya mukofotini oladi.

    Raises:
        EconomyError: missiya noma'lum, bajarilmagan yoki mukofot olingan.
    """
    normalized = str(key or "").strip().lower()
    mission = MISSIONS_BY_KEY.get(normalized)
    if mission is None:
        raise EconomyError("Noma'lum missiya")
    statuses = mission_statuses(store, user_id)
    status = next(
        item for item in statuses if item.mission.key == mission.key
    )
    if status.claimed:
        raise EconomyError("Bu missiya mukofoti allaqachon olingan")
    if not status.completed:
        raise EconomyError(
            f"Missiya hali bajarilmagan: {status.progress}/{mission.target}"
        )
    account = store.claim_mission_reward(int(user_id), mission.key, mission.reward)
    return MissionStatus(mission=mission, progress=status.progress, claimed=True), account


def missions_payload(statuses: list[MissionStatus]) -> list[dict[str, Any]]:
    """Mini App va bot uchun JSON'ga tayyor ro'yxat."""
    return [
        {
            "key": status.mission.key,
            "title": status.mission.title,
            "emoji": status.mission.emoji,
            "description": status.mission.description,
            "target": status.mission.target,
            "progress": status.progress,
            "percent": status.percent,
            "reward": status.mission.reward,
            "completed": status.completed,
            "claimed": status.claimed,
            "claimable": status.claimable,
        }
        for status in statuses
    ]
