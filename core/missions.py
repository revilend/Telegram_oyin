"""Missiyalar katalogi: taraqqiyotni o'lchaydigan maqsadlar va mukofotlar.

Har bir missiya foydalanuvchi statistikasidagi bitta ko'rsatkichga bog'langan
(``games_played``, ``wins`` yoki ``referral_count``). Mukofot faqat bir marta
olinadi; olingan missiyalar ``core.economy.EconomyStore``da saqlanadi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.economy import EconomyError, EconomyStore, UserAccount

MISSION_GAMES = "games_played"
MISSION_WINS = "wins"
MISSION_REFERRALS = "referral_count"


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
        emoji="🎮",
        description="Bitta o'yinda qatnashing",
        metric=MISSION_GAMES,
        target=1,
        reward=50,
    ),
    Mission(
        key="games_5",
        title="Tajribali o'yinchi",
        emoji="🕹️",
        description="5 ta o'yinda qatnashing",
        metric=MISSION_GAMES,
        target=5,
        reward=150,
    ),
    Mission(
        key="games_20",
        title="Bunker faxriysi",
        emoji="🏅",
        description="20 ta o'yinda qatnashing",
        metric=MISSION_GAMES,
        target=20,
        reward=400,
    ),
    Mission(
        key="first_win",
        title="Birinchi g'alaba",
        emoji="🥇",
        description="Bitta o'yinda bunkerga tushing",
        metric=MISSION_WINS,
        target=1,
        reward=100,
    ),
    Mission(
        key="wins_5",
        title="G'oliblar safida",
        emoji="🏆",
        description="5 ta o'yinda g'olib bo'ling",
        metric=MISSION_WINS,
        target=5,
        reward=300,
    ),
    Mission(
        key="friend_1",
        title="Do'st olib kel",
        emoji="👥",
        description="1 do'stingizni taklif qiling",
        metric=MISSION_REFERRALS,
        target=1,
        reward=100,
    ),
    Mission(
        key="friends_5",
        title="Katta jamoa",
        emoji="🤝",
        description="5 do'stingizni taklif qiling",
        metric=MISSION_REFERRALS,
        target=5,
        reward=500,
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
