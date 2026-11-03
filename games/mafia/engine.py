"""«Revilend Mafia» o'yin dvigateli: tun, tonggi hisobot va ovoz berish.

O'yin bir necha bosqichdan o'tadi::

    LOBBY -> NIGHT -> DAY_REPORT -> VOTING -> NIGHT ... -> FINISHED

Tungi harakatlar :meth:`MafiaRoom.submit_night_action` orqali yig'iladi va
:func:`resolve_night` da qat'iy prioritet bo'yicha hal qilinadi:

1. bloklash (Bloklovchi nishonning harakatini bekor qiladi),
2. himoya (Doktor davolaydi, Tansoqchi o'zini qurbon qiladi),
3. hujum (mafiya jamoasi, Maniak va Snayper),
4. tekshiruv (Sherif; Advokat himoyasi natijani «Tinch aholi» qiladi),
5. tonggi hisobot (o'lganlar ro'yxati yoki «hech kim halok bo'lmadi»).

Keyingi bosqichlarda qo'shiladigan qobiliyatlar hozircha dvigatelda
qo'llanmaydi: Jodugar, Shantajchi va Amneziya uchun harakat yuborish
:class:`MafiaError` bilan rad etiladi.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from games.mafia.generator import MIN_PLAYERS, deal_mafia_roles
from games.mafia.roles import Faction, MafiaRole, get_role_profile

INVESTIGATION_TOWN = "Tinch aholi"
INVESTIGATION_MAFIA = "Mafiya"
INVESTIGATION_NEUTRAL = "Yolg'iz"


class MafiaError(Exception):
    """O'yin qoidasi buzilganda yoki harakat ruxsat etilmaganda ko'tariladi."""


class GamePhase(Enum):
    """O'yin bosqichlari."""

    LOBBY = "LOBBY"
    NIGHT = "NIGHT"
    DAY_REPORT = "DAY_REPORT"
    VOTING = "VOTING"
    FINISHED = "FINISHED"


class Winner(Enum):
    """O'yin g'olibi."""

    TOWN = "town"
    MAFIA = "mafia"
    MANIAC = "maniac"
    JESTER = "jester"


class NightActionType(Enum):
    """Tungi harakat turlari."""

    KILL = "kill"
    HEAL = "heal"
    PROTECT = "protect"
    BLOCK = "block"
    SNIPE = "snipe"
    INVESTIGATE = "investigate"
    FRAME = "frame"


# Rol o'z ixtiyori bilan yuboradigan harakat turi.
NIGHT_ACTION_BY_ROLE: dict[MafiaRole, NightActionType] = {
    MafiaRole.SHERIFF: NightActionType.INVESTIGATE,
    MafiaRole.DOCTOR: NightActionType.HEAL,
    MafiaRole.BODYGUARD: NightActionType.PROTECT,
    MafiaRole.BLOCKER: NightActionType.BLOCK,
    MafiaRole.SNIPER: NightActionType.SNIPE,
    MafiaRole.DON: NightActionType.KILL,
    MafiaRole.MAFIA: NightActionType.KILL,
    MafiaRole.LAWYER: NightActionType.FRAME,
    MafiaRole.MANIAC: NightActionType.KILL,
}

WIN_REASONS: dict[Winner, str] = {
    Winner.TOWN: "Barcha mafiyalar va maniak yo'q qilindi — shahar g'alaba qozondi.",
    Winner.MAFIA: "Tirik mafiyalar soni shahar aholisidan kam emas — mafiya g'alaba qozondi.",
    Winner.MANIAC: "Oxirgi tirik o'yinchi Maniak — u yakka o'zi g'alaba qozondi.",
    Winner.JESTER: "Hazilkash ovoz bilan haydaldi — u yakka o'zi g'alaba qozondi.",
}


@dataclass
class MafiaPlayer:
    """Mafiya o'yinchisi."""

    user_id: int
    name: str = ""
    role: MafiaRole | None = None
    is_alive: bool = True

    def __post_init__(self) -> None:
        self.name = (self.name or "").strip()
        if isinstance(self.role, str):
            try:
                self.role = MafiaRole(self.role.strip().lower())
            except ValueError as exc:
                raise MafiaError(f"Noma'lum rol: {self.role!r}") from exc
        if self.role is not None and not isinstance(self.role, MafiaRole):
            raise MafiaError("role MafiaRole yoki uning kaliti bo'lishi kerak")

    @property
    def faction(self) -> Faction | None:
        """Rolning jamoasi (rol hali berilmagan bo'lsa ``None``)."""
        if self.role is None:
            return None
        return get_role_profile(self.role).faction


@dataclass(frozen=True)
class NightAction:
    """Bitta o'yinchining tungi harakati."""

    actor_id: int
    kind: NightActionType
    target_id: int


@dataclass(frozen=True)
class NightReport:
    """Tun natijasi: o'lganlar, bloklanganlar va Sherif javoblari."""

    night: int
    deaths: tuple[int, ...] = ()
    blocked: tuple[int, ...] = ()
    protected: tuple[int, ...] = ()
    healed: tuple[int, ...] = ()
    sheriff_results: dict[int, str] = field(default_factory=dict)

    @property
    def peaceful(self) -> bool:
        """Tunda hech kim halok bo'lmaganini bildiradi."""
        return not self.deaths


class MafiaRoom:
    """Bitta mafiya partiyasining to'liq holati."""

    def __init__(
        self, players: Iterable[MafiaPlayer | int], room_id: str = ""
    ) -> None:
        normalized: dict[int, MafiaPlayer] = {}
        for item in players:
            player = MafiaPlayer(item) if isinstance(item, int) else item
            if not isinstance(player, MafiaPlayer):
                raise MafiaError("O'yinchilar MafiaPlayer yoki user_id bo'lishi kerak")
            if player.user_id in normalized:
                raise MafiaError(
                    f"O'yinchi {player.user_id} xonada takrorlangan"
                )
            normalized[player.user_id] = player
        if not normalized:
            raise MafiaError("Xona bo'sh bo'lishi mumkin emas")

        self.players = normalized
        self.room_id = room_id
        self.phase = GamePhase.LOBBY
        self.round = 0
        self.night_actions: dict[int, NightAction] = {}
        self.votes: dict[int, int] = {}
        self.eliminated: list[int] = []
        self.last_report: NightReport | None = None
        self.winner: Winner | None = None
        self.finish_reason = ""
        self.log: list[str] = []

    # ------------------------------------------------------------------ holat
    def get_player(self, user_id: int) -> MafiaPlayer:
        """O'yinchini id bo'yicha qaytaradi."""
        player = self.players.get(user_id)
        if player is None:
            raise MafiaError(f"O'yinchi {user_id} topilmadi")
        return player

    @property
    def alive_players(self) -> list[MafiaPlayer]:
        """Tirik o'yinchilar (id tartibida)."""
        return sorted(
            (player for player in self.players.values() if player.is_alive),
            key=lambda player: player.user_id,
        )

    @property
    def alive_ids(self) -> set[int]:
        """Tirik o'yinchilar id'lari."""
        return {player.user_id for player in self.alive_players}

    @staticmethod
    def display_name(player: MafiaPlayer) -> str:
        """O'yinchi uchun ko'rinadigan ism."""
        return player.name or f"ID {player.user_id}"

    def start(self, *, rng: random.Random | None = None) -> None:
        """Lobby'da rollarni tarqatib, birinchi tunni boshlaydi."""
        if self.phase is not GamePhase.LOBBY:
            raise MafiaError("O'yin allaqachon boshlangan")
        if len(self.players) < MIN_PLAYERS:
            raise MafiaError(
                f"Mafiya uchun kamida {MIN_PLAYERS} o'yinchi kerak, "
                f"{len(self.players)} berildi"
            )

        dealt = deal_mafia_roles(list(self.players), rng=rng)
        for user_id, role in dealt.items():
            self.players[user_id].role = role

        self.round = 0
        self.night_actions.clear()
        self.votes.clear()
        self.eliminated.clear()
        self.last_report = None
        self.winner = None
        self.finish_reason = ""
        self.log.clear()
        self.begin_night()

    def begin_night(self) -> None:
        """Keyingi tunni boshlaydi."""
        if self.phase is GamePhase.FINISHED:
            raise MafiaError("Tugagan o'yinda yangi tun boshlanmaydi")
        if self.phase is GamePhase.NIGHT:
            raise MafiaError("Tun allaqachon boshlangan")
        if any(player.role is None for player in self.players.values()):
            raise MafiaError("Avval rollarni tarqatib, o'yinni boshlang")

        self.round += 1
        self.night_actions.clear()
        self.votes.clear()
        self.phase = GamePhase.NIGHT

    def begin_voting(self) -> None:
        """Tonggi hisobotdan keyin kunduzgi ovoz berishni boshlaydi."""
        if self.phase is not GamePhase.DAY_REPORT:
            raise MafiaError("Ovoz berish faqat DAY_REPORT bosqichidan boshlanadi")
        self.votes.clear()
        self.phase = GamePhase.VOTING

    def finish(self, winner: Winner, reason: str = "") -> None:
        """O'yinni g'olib bilan yakunlaydi."""
        self.phase = GamePhase.FINISHED
        self.winner = winner
        self.finish_reason = reason or WIN_REASONS.get(winner, "")
        self.log.append(self.finish_reason)

    def eliminate(self, player_id: int) -> MafiaPlayer:
        """O'yinchini o'yindan chiqaradi."""
        player = self.get_player(player_id)
        if not player.is_alive:
            raise MafiaError(
                f"{self.display_name(player)} allaqachon o'yindan chiqqan"
            )
        player.is_alive = False
        if player.user_id not in self.eliminated:
            self.eliminated.append(player.user_id)
        return player

    # --------------------------------------------------------------- tungi fazalar
    def submit_night_action(self, actor_id: int, target_id: int) -> NightAction:
        """Faol rol uchun tungi harakatni yozib qo'yadi."""
        if self.phase is not GamePhase.NIGHT:
            raise MafiaError("Tungi harakat faqat NIGHT bosqichida yuboriladi")
        actor = self.get_player(actor_id)
        if not actor.is_alive:
            raise MafiaError("Halok bo'lgan o'yinchi harakat qila olmaydi")
        if actor.role is None:
            raise MafiaError("Rol hali berilmagan")

        kind = NIGHT_ACTION_BY_ROLE.get(actor.role)
        if kind is None:
            profile = get_role_profile(actor.role)
            raise MafiaError(
                f"{profile.name_uz} bu bosqichda tungi harakatga ega emas"
            )

        target = self.get_player(target_id)
        if not target.is_alive:
            raise MafiaError(
                f"{self.display_name(target)} allaqachon halok bo'lgan"
            )
        if kind is NightActionType.PROTECT and target_id == actor_id:
            raise MafiaError("Tansoqchi o'zini himoya qila olmaydi")

        action = NightAction(actor_id=actor_id, kind=kind, target_id=target_id)
        self.night_actions[actor_id] = action
        return action

    def report_text(self) -> str:
        """Oxirgi tungi hisobotning o'zbekcha matni."""
        report = self.last_report
        if report is None:
            return "Tunda hisobot yo'q."
        if not report.deaths:
            return "Tunda hech kim halok bo'lmadi."
        names = ", ".join(
            self.display_name(self.players[user_id])
            for user_id in report.deaths
            if user_id in self.players
        )
        return f"Tunda halok bo'ldilar: {names}."

    # --------------------------------------------------------------- kunduz
    def cast_vote(self, voter_id: int, target_id: int) -> None:
        """Kunduzgi ovozni yozadi (ovozni o'zgartirish mumkin)."""
        if self.phase is not GamePhase.VOTING:
            raise MafiaError("Ovoz berish faqat VOTING bosqichida mumkin")
        voter = self.get_player(voter_id)
        if not voter.is_alive:
            raise MafiaError("Halok bo'lgan o'yinchi ovoz bera olmaydi")
        if voter_id == target_id:
            raise MafiaError("O'ziga ovoz berish mumkin emas")
        target = self.get_player(target_id)
        if not target.is_alive:
            raise MafiaError(
                f"{self.display_name(target)} allaqachon halok bo'lgan"
            )
        self.votes[voter_id] = target_id


# Hujjatlar va tashqi kod uchun qulay taxallus.
GameState = MafiaRoom


def _effective_blocks(
    actions: dict[int, NightAction],
) -> tuple[dict[int, int], set[int]]:
    """Bloklashlarni zanjir bo'yicha hal qiladi.

    Bloklangan Bloklovchining o'z bloki bekor bo'ladi; o'zaro bloklashda ikkala
    blok ham kuchga kirmaydi.
    """
    active = {
        actor_id: action.target_id
        for actor_id, action in actions.items()
        if action.kind is NightActionType.BLOCK
    }
    for _ in range(len(active) + 1):
        blocked = set(active.values())
        stale = [actor_id for actor_id in active if actor_id in blocked]
        if not stale:
            break
        for actor_id in stale:
            del active[actor_id]
    return active, set(active.values())


def _mafia_shot(
    room: MafiaRoom, actions: dict[int, NightAction]
) -> NightAction | None:
    """Mafiya jamoasining bitta o'qini tanlaydi (Don ustuvor)."""
    shots = [
        action
        for action in actions.values()
        if action.kind is NightActionType.KILL
        and room.players[action.actor_id].faction is Faction.MAFIA
    ]
    if not shots:
        return None
    shots.sort(
        key=lambda action: (
            room.players[action.actor_id].role is not MafiaRole.DON,
            action.actor_id,
        )
    )
    return shots[0]


def _sheriff_result(
    room: MafiaRoom, target_id: int, framed: set[int]
) -> str:
    """Sherif tekshiruvi natijasi (Advokat himoyasi hisobga olinadi)."""
    if target_id in framed:
        return INVESTIGATION_TOWN
    target = room.players[target_id]
    if target.faction is Faction.MAFIA:
        return INVESTIGATION_MAFIA
    if target.faction is Faction.NEUTRAL:
        return INVESTIGATION_NEUTRAL
    return INVESTIGATION_TOWN


def resolve_night(room: MafiaRoom) -> NightReport:
    """Tungi harakatlarni prioritet bo'yicha hal qiladi.

    Harakatlar bir vaqtda bajariladi: tunda o'lgan o'yinchining harakati
    bekor bo'lmaydi, lekin bloklangan harakat umuman kuchga kirmaydi.

    Returns:
        Shakllangan :class:`NightReport`; u ``room.last_report`` ga ham yoziladi.

    Raises:
        MafiaError: bosqich ``NIGHT`` bo'lmasa yoki tun boshlanmagan bo'lsa.
    """
    if room.phase is not GamePhase.NIGHT:
        raise MafiaError("Tungi harakatlar faqat NIGHT bosqichida hal qilinadi")
    if room.round < 1:
        raise MafiaError("Tun hali boshlanmagan")

    actions = {
        actor_id: action
        for actor_id, action in room.night_actions.items()
        if (actor := room.players.get(actor_id)) is not None
        and actor.is_alive
        and actor.role is not None
    }

    _, blocked = _effective_blocks(actions)
    effective = {
        actor_id: action
        for actor_id, action in actions.items()
        if actor_id not in blocked
    }

    heals = {
        action.target_id
        for action in effective.values()
        if action.kind is NightActionType.HEAL
    }
    protections = {
        action.target_id: action.actor_id
        for action in effective.values()
        if action.kind is NightActionType.PROTECT
    }
    frames = {
        action.target_id
        for action in effective.values()
        if action.kind is NightActionType.FRAME
    }

    # 3-qadam: hujumlar. Mafiya bitta qurbon tanlaydi, Maniak va Snayper alohida.
    attacks: list[tuple[int, int, bool]] = []
    mafia_shot = _mafia_shot(room, effective)
    if mafia_shot is not None:
        attacks.append((mafia_shot.actor_id, mafia_shot.target_id, False))
    for action in effective.values():
        if (
            action.kind is NightActionType.KILL
            and room.players[action.actor_id].role is MafiaRole.MANIAC
        ):
            attacks.append((action.actor_id, action.target_id, False))
        elif action.kind is NightActionType.SNIPE:
            attacks.append((action.actor_id, action.target_id, True))

    deaths: set[int] = set()
    retaliations: list[tuple[int, int]] = []
    for attacker_id, target_id, is_sniper in attacks:
        if target_id in heals:
            continue
        if target_id in protections:
            guard_id = protections[target_id]
            deaths.add(guard_id)
            retaliations.append((guard_id, attacker_id))
        else:
            deaths.add(target_id)
            retaliations.append((target_id, attacker_id))

        # Snayper tinch aholini otgan bo'lsa, o'zi ham halok bo'ladi.
        if is_sniper and room.players[target_id].faction is Faction.TOWN:
            deaths.add(attacker_id)

    # Kamikadze tunda o'ldirilsa, qotilni o'zi bilan olib ketadi.
    for victim_id, attacker_id in retaliations:
        if victim_id == attacker_id:
            continue
        if room.players[victim_id].role is MafiaRole.KAMIKAZE:
            deaths.add(attacker_id)

    for user_id in sorted(deaths):
        player = room.players.get(user_id)
        if player is not None and player.is_alive:
            player.is_alive = False
            room.eliminated.append(user_id)

    # 4-qadam: Sherif tekshiruvi.
    sheriff_results = {
        action.actor_id: _sheriff_result(room, action.target_id, frames)
        for action in effective.values()
        if action.kind is NightActionType.INVESTIGATE
    }

    # 5-qadam: tonggi hisobot.
    report = NightReport(
        night=room.round,
        deaths=tuple(sorted(deaths)),
        blocked=tuple(sorted(blocked)),
        protected=tuple(sorted(protections)),
        healed=tuple(sorted(heals)),
        sheriff_results=sheriff_results,
    )
    room.last_report = report
    room.phase = GamePhase.DAY_REPORT
    room.log.append(room.report_text())

    winner = check_game_over(room)
    if winner is not None:
        room.finish(winner, WIN_REASONS[winner])
    return report


def check_game_over(room: MafiaRoom) -> Winner | None:
    """G'alaba shartlarini tekshiradi (holatni o'zgartirmaydi).

    * Maniak oxirgi tirik o'yinchi bo'lsa — Maniak g'alabasi.
    * Barcha mafiyalar va maniak yo'q bo'lsa — shahar g'alabasi.
    * Tirik mafiyalar soni tirik shahar aholisidan kam bo'lmasa — mafiya g'alabasi.
    """
    alive = room.alive_players
    if len(alive) == 1 and alive[0].role is MafiaRole.MANIAC:
        return Winner.MANIAC

    mafia = [player for player in alive if player.faction is Faction.MAFIA]
    town = [player for player in alive if player.faction is Faction.TOWN]
    maniacs = [
        player for player in alive if player.role is MafiaRole.MANIAC
    ]

    if not mafia and not maniacs:
        return Winner.TOWN
    if mafia and len(mafia) >= len(town):
        return Winner.MAFIA
    return None


def resolve_day_vote(
    room: MafiaRoom,
    eliminated_id: int | None,
    *,
    kamikaze_target_id: int | None = None,
) -> Winner | None:
    """Kunduzgi ovoz natijasini qo'llaydi.

    * Hazilkash haydalsa — o'yin darhol tugaydi va u yakka o'zi g'olib bo'ladi.
    * Kamikadze haydalsa — ``kamikaze_target_id`` bilan ko'rsatilgan o'yinchini
      o'zi bilan olib ketadi (qurbon tanlash majburiy).
    * Aks holda oddiy haydash, g'alaba tekshiruvi va keyingi tun boshlanadi.

    Args:
        room: O'yin holati (``VOTING`` bosqichida).
        eliminated_id: Haydaladigan o'yinchi yoki ``None`` (hech kim).
        kamikaze_target_id: Kamikadze qurboni (faqat Kamikadze haydalganda).

    Returns:
        G'olib bo'lsa :class:`Winner`, aks holda ``None``.

    Raises:
        MafiaError: Bosqich noto'g'ri yoki Kamikadze qurboni tanlanmagan bo'lsa.
    """
    if room.phase is not GamePhase.VOTING:
        raise MafiaError("Ovoz natijasi faqat VOTING bosqichida qo'llanadi")

    if eliminated_id is None:
        room.begin_night()
        return None

    player = room.get_player(eliminated_id)
    if not player.is_alive:
        raise MafiaError(
            f"{room.display_name(player)} allaqachon o'yindan chiqqan"
        )

    if player.role is MafiaRole.JESTER:
        room.eliminate(player.user_id)
        room.finish(
            Winner.JESTER,
            f"{room.display_name(player)} (Hazilkash) ovoz bilan haydaldi va "
            "yakka o'zi g'olib bo'ldi.",
        )
        return Winner.JESTER

    kamikaze_target: MafiaPlayer | None = None
    if player.role is MafiaRole.KAMIKAZE:
        if kamikaze_target_id is None:
            raise MafiaError(
                "Kamikadze o'zi bilan olib ketadigan o'yinchini tanlashi kerak"
            )
        if kamikaze_target_id == player.user_id:
            raise MafiaError("Kamikadze o'zini qurbon qilib olmaydi")
        kamikaze_target = room.get_player(kamikaze_target_id)
        if not kamikaze_target.is_alive:
            raise MafiaError(
                f"{room.display_name(kamikaze_target)} allaqachon halok bo'lgan"
            )

    room.eliminate(player.user_id)
    if kamikaze_target is not None:
        room.eliminate(kamikaze_target.user_id)

    winner = check_game_over(room)
    if winner is not None:
        room.finish(winner, WIN_REASONS[winner])
        return winner

    room.begin_night()
    return None


def start_game(
    players: Iterable[MafiaPlayer | int], *, rng: random.Random | None = None
) -> MafiaRoom:
    """Yangi xona yaratib, rollarni tarqatadi va birinchi tunni boshlaydi."""
    room = MafiaRoom(players)
    room.start(rng=rng)
    return room
