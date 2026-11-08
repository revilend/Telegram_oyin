"""«Revilend: Xavfli Bomba» o'yin dvigateli.

O'yin xona kodi bo'yicha global reyestrda saqlanadi. Har bir xona navbat,
qo'llar va tortish dastasini mustaqil boshqaradi; Telegram va tanga
qatlamlaridan ajratilgan. G'olib aniqlanganda standart holatda
:func:`core.economy.get_economy` orqali +30 tanga beriladi, testlarda esa
``coin_award`` callback bilan almashtirish mumkin.
"""

from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from games.bomb.cards import CardType, card_info
from games.bomb.generator import MAX_PLAYERS, MIN_PLAYERS, build_bomb_deck

logger = logging.getLogger(__name__)

WINNER_REWARD = 30
FUTURE_PEEK = 3

CoinAward = Callable[[int, int], None]


class BombError(Exception):
    """Xavfli Bomba qoidalari yoki xona holati bilan bog'liq xatolik."""


class BombStatus(str, Enum):
    """Xona holatlari."""

    LOBBY = "LOBBY"
    PLAYING = "PLAYING"
    FINISHED = "FINISHED"


@dataclass
class BombPlayer:
    """Xonadagi bitta o'yinchi."""

    user_id: int
    name: str = ""
    hand: list[CardType] = field(default_factory=list)
    is_alive: bool = True
    draws_left: int = 1

    def label(self) -> str:
        """Guruhda ko'rsatiladigan nom."""
        return self.name.strip() or f"ID {self.user_id}"

    @property
    def draw_turns_left(self) -> int:
        """Navbatda qolgan karta tortish soni."""
        return self.draws_left

    @draw_turns_left.setter
    def draw_turns_left(self, value: int) -> None:
        self.draws_left = max(0, int(value))

    def has(self, card: CardType) -> bool:
        """Karta qo'lda bormi."""
        return card in self.hand

    def take(self, card: CardType) -> bool:
        """Bitta kartani qo'ldan oladi; topilmasa ``False`` qaytaradi."""
        try:
            self.hand.remove(card)
        except ValueError:
            return False
        return True


@dataclass(frozen=True)
class DrawResult:
    """Bitta karta tortish natijasi."""

    player_id: int
    card: CardType | None
    exploded: bool = False
    defused: bool = False
    eliminated_id: int | None = None
    returned_index: int | None = None
    next_player_id: int | None = None
    winner_id: int | None = None
    deck_size: int = 0
    game_over: bool = False


@dataclass(frozen=True)
class ActionResult:
    """Harakat kartasini o'ynash natijasi."""

    player_id: int
    card: CardType
    target_id: int | None = None
    stolen_card: CardType | None = None
    future_cards: tuple[CardType, ...] = ()
    next_player_id: int | None = None
    winner_id: int | None = None
    game_over: bool = False


def _default_coin_award(user_id: int, amount: int) -> None:
    from core.economy import get_economy

    get_economy().add_coins(int(user_id), int(amount))


def _coerce_card_type(value: CardType | str) -> CardType:
    if isinstance(value, CardType):
        return value
    try:
        return CardType(str(value).strip().upper())
    except (TypeError, ValueError) as exc:
        raise BombError(f"Noto'g'ri karta turi: {value!r}") from exc


def _normalize_code(code: str) -> str:
    normalized = (code or "").strip().upper()
    if not normalized:
        raise BombError("Xona kodi bo'sh bo'lmasligi kerak")
    return normalized


class BombRoom:
    """Bitta «Xavfli Bomba» xonasi."""

    def __init__(
        self,
        code: str,
        *,
        rng: random.Random | None = None,
        coin_award: CoinAward | None = None,
        winner_reward: int = WINNER_REWARD,
        chat_id: int = 0,
    ) -> None:
        self.code = _normalize_code(code)
        self.chat_id = int(chat_id or 0)
        self.host_id: int | None = None
        self.players: dict[int, BombPlayer] = {}
        self.order: list[int] = []
        self.deck: list[CardType] = []
        self.discard: list[CardType] = []
        self.status = BombStatus.LOBBY
        self.turn_index = 0
        self.winner_id: int | None = None
        self.last_eliminated_id: int | None = None
        self.last_future_owner: int | None = None
        self.last_future_cards: tuple[CardType, ...] = ()
        self.winner_reward = max(0, int(winner_reward))
        self._rng = rng or random.Random()
        self._coin_award = coin_award or _default_coin_award
        self._reward_paid = False
        self._result_recorded = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # O'yinchilar
    # ------------------------------------------------------------------
    def add_player(
        self, user_id: int, name: str = "", *, is_host: bool = False
    ) -> BombPlayer:
        """O'yinchini xonaga qo'shadi (faqat lobbida)."""
        with self._lock:
            if self.status is not BombStatus.LOBBY:
                raise BombError("O'yin boshlangan, qo'shilish mumkin emas")
            uid = int(user_id)
            if uid <= 0:
                raise BombError("Foydalanuvchi id musbat bo'lishi kerak")
            if self.host_id is None or is_host:
                self.host_id = uid
            existing = self.players.get(uid)
            if existing is not None:
                if name:
                    existing.name = name
                return existing
            if len(self.players) >= MAX_PLAYERS:
                raise BombError(f"Xona to'lgan (maksimal {MAX_PLAYERS} kishi)")
            player = BombPlayer(user_id=uid, name=(name or "").strip())
            self.players[uid] = player
            self.order.append(uid)
            return player

    def player(self, user_id: int) -> BombPlayer:
        """Id bo'yicha o'yinchini qaytaradi."""
        player = self.players.get(int(user_id))
        if player is None:
            raise BombError("Siz bu Xavfli Bomba xonasida emassiz")
        return player

    @property
    def alive_players(self) -> list[BombPlayer]:
        return [player for player in self.players.values() if player.is_alive]

    @property
    def current_player_id(self) -> int | None:
        if not self.order:
            return None
        uid = self.order[self.turn_index % len(self.order)]
        player = self.players.get(uid)
        if player is None or not player.is_alive:
            return None
        return uid

    @property
    def current_player(self) -> BombPlayer | None:
        uid = self.current_player_id
        return self.players.get(uid) if uid is not None else None

    @property
    def winner(self) -> BombPlayer | None:
        """G'olib o'yinchi (hali aniqlanmagan bo'lsa ``None``)."""
        if self.winner_id is None:
            return None
        return self.players.get(self.winner_id)

    def start(self) -> None:
        """Dastani yaratadi va boshlang'ich qo'llarni tarqatadi."""
        with self._lock:
            if self.status is not BombStatus.LOBBY:
                raise BombError("Bu xonada o'yin allaqachon boshlangan")
            if len(self.players) < MIN_PLAYERS:
                raise BombError(
                    f"O'yin uchun kamida {MIN_PLAYERS} kishi kerak "
                    f"(hozir {len(self.players)})"
                )
            deal = build_bomb_deck(len(self.order), rng=self._rng)
            for index, uid in enumerate(self.order):
                player = self.players[uid]
                player.hand = list(deal.hands[index])
                player.is_alive = True
                player.draws_left = 1
            self.deck = list(deal)
            self.discard = []
            self.status = BombStatus.PLAYING
            self.turn_index = 0
            self.winner_id = None
            self.last_eliminated_id = None
            self.last_future_owner = None
            self.last_future_cards = ()
            self._reward_paid = False

    # ------------------------------------------------------------------
    # Navbat
    # ------------------------------------------------------------------
    def _require_turn(self, user_id: int) -> BombPlayer:
        if self.status is not BombStatus.PLAYING:
            raise BombError("O'yin hozir faol emas")
        player = self.player(user_id)
        if not player.is_alive:
            raise BombError("Siz o'yindan chiqqansiz")
        if self.current_player_id != player.user_id:
            raise BombError("Hozir sizning navbatingiz emas")
        return player

    def _next_alive(self, after_id: int) -> BombPlayer | None:
        if not self.order:
            return None
        start = self.order.index(int(after_id))
        for offset in range(1, len(self.order) + 1):
            candidate = self.players[self.order[(start + offset) % len(self.order)]]
            if candidate.is_alive:
                return candidate
        return None

    def _advance_turn(self) -> None:
        if not self.order:
            return
        for offset in range(1, len(self.order) + 1):
            index = (self.turn_index + offset) % len(self.order)
            candidate = self.players[self.order[index]]
            if not candidate.is_alive:
                continue
            self.turn_index = index
            if candidate.draws_left <= 0:
                candidate.draws_left = 1
            return

    def _end_turn(self) -> None:
        uid = self.current_player_id
        if uid is not None:
            self.players[uid].draws_left = 0
        self._advance_turn()

    def _consume_draw(self, player: BombPlayer) -> None:
        """Bitta tortishni hisoblaydi; navbat tugasa keyingisiga o'tadi."""
        player.draws_left = max(0, player.draws_left - 1)
        if player.draws_left == 0:
            self._advance_turn()

    def _discard(self, card: CardType) -> None:
        self.discard.append(card)

    # ------------------------------------------------------------------
    # Karta tortish
    # ------------------------------------------------------------------
    def draw_card(self, user_id: int) -> DrawResult:
        """Joriy o'yinchi dastadan eng yuqori kartani tortadi."""
        with self._lock:
            player = self._require_turn(user_id)
            if not self.deck:
                self._finish_without_winner()
                return DrawResult(
                    player_id=player.user_id,
                    card=None,
                    next_player_id=None,
                    winner_id=None,
                    deck_size=0,
                    game_over=True,
                )

            card = self.deck.pop(0)
            exploded = defused = False
            eliminated_id: int | None = None
            returned_index: int | None = None
            self.last_eliminated_id = None

            if card is CardType.BOMB:
                if player.has(CardType.DEFUSE):
                    player.take(CardType.DEFUSE)
                    self._discard(CardType.DEFUSE)
                    returned_index = self._rng.randint(0, len(self.deck))
                    self.deck.insert(returned_index, card)
                    defused = True
                    self._consume_draw(player)
                else:
                    player.is_alive = False
                    player.hand.clear()
                    player.draws_left = 0
                    exploded = True
                    eliminated_id = player.user_id
                    self.last_eliminated_id = eliminated_id
                    self._discard(card)
                    self._advance_turn()
            else:
                player.hand.append(card)
                self._consume_draw(player)

            winner_id = self.check_winner()
            return DrawResult(
                player_id=player.user_id,
                card=card,
                exploded=exploded,
                defused=defused,
                eliminated_id=eliminated_id,
                returned_index=returned_index,
                next_player_id=self.current_player_id,
                winner_id=winner_id,
                deck_size=len(self.deck),
                game_over=self.status is BombStatus.FINISHED,
            )

    # ------------------------------------------------------------------
    # Harakat kartalari
    # ------------------------------------------------------------------
    def play_action_card(
        self,
        user_id: int,
        card_type: CardType | str,
        target_id: int | None = None,
    ) -> ActionResult:
        """Harakat kartasini o'ynaydi.

        ``BOMB`` va ``DEFUSE`` qo'ldan o'ynalmaydi: bomba avtomatik ishlaydi,
        defuse esa faqat bomba tortilganda sarflanadi.
        """
        with self._lock:
            card = _coerce_card_type(card_type)
            if card in (CardType.BOMB, CardType.DEFUSE):
                raise BombError(f"{card.value} kartasini qo'ldan o'ynab bo'lmaydi")

            player = self._require_turn(user_id)
            if not player.has(card):
                raise BombError(f"{card.value} kartasi qo'lingizda yo'q")

            # Nishonni kartani olib tashlashdan oldin tekshiramiz: xato
            # bo'lsa karta o'yinchining qo'lida qoladi.
            target: BombPlayer | None = None
            if card is CardType.ATTACK:
                target = self._next_alive(player.user_id)
                if target is None or target.user_id == player.user_id:
                    raise BombError("Hujum uchun keyingi tirik o'yinchi topilmadi")
            elif card is CardType.STEAL:
                target = self._steal_target(player, target_id)

            player.take(card)
            self._discard(card)
            stolen: CardType | None = None
            future_cards: tuple[CardType, ...] = ()

            if card is CardType.ATTACK:
                assert target is not None
                target.draw_turns_left = 2
                self._advance_turn()
            elif card is CardType.SKIP:
                self._end_turn()
            elif card is CardType.FUTURE:
                future_cards = tuple(self.deck[:FUTURE_PEEK])
                self.last_future_owner = player.user_id
                self.last_future_cards = future_cards
            elif card is CardType.SHUFFLE:
                self._rng.shuffle(self.deck)
            elif card is CardType.STEAL:
                assert target is not None
                stolen = target.hand.pop(self._rng.randrange(len(target.hand)))
                player.hand.append(stolen)

            winner_id = self.check_winner()
            return ActionResult(
                player_id=player.user_id,
                card=card,
                target_id=target.user_id if target is not None else None,
                stolen_card=stolen,
                future_cards=future_cards,
                next_player_id=self.current_player_id,
                winner_id=winner_id,
                game_over=self.status is BombStatus.FINISHED,
            )

    def _steal_target(
        self,
        player: BombPlayer,
        target_id: int | None,
    ) -> BombPlayer:
        if target_id is None:
            raise BombError("Öğirlaş uçun nishon tanlanişi kerak")
        try:
            target = self.players.get(int(target_id))
        except (TypeError, ValueError) as exc:
            raise BombError("Nishon id noto'g'ri") from exc
        if target is None:
            raise BombError("Nishon bu xonada topilmadi")
        if target.user_id == player.user_id:
            raise BombError("Özingizdan karta öğirlab bölmaysiz")
        if not target.is_alive:
            raise BombError("Nishon allaqachon öyindan çiqqan")
        if not target.hand:
            raise BombError("Nishonning qölida karta yo'q")
        return target

    # ------------------------------------------------------------------
    # G'olib
    # ------------------------------------------------------------------
    def check_winner(self) -> int | None:
        """Tirik o'yinchi bitta qolgan bo'lsa g'olibni qaytaradi."""
        with self._lock:
            if self.status is BombStatus.FINISHED:
                return self.winner_id
            if self.status is not BombStatus.PLAYING:
                return None

            alive = self.alive_players
            if len(alive) == 1:
                winner = alive[0]
                self.status = BombStatus.FINISHED
                self.winner_id = winner.user_id
                self._pay_reward(winner.user_id)
                self._record_result()
                return winner.user_id
            if not alive:
                self.status = BombStatus.FINISHED
                self.winner_id = None
                self._record_result()
            return None

    def _finish_without_winner(self) -> None:
        self.status = BombStatus.FINISHED
        self.winner_id = None
        self._record_result()

    def _record_result(self) -> None:
        """Natijani iqtisodiyotga bir marta yozadi (``bomb_wins``)."""
        if self._result_recorded:
            return
        self._result_recorded = True
        try:
            from core.economy import get_economy

            get_economy().record_finished_game(
                self.code,
                [player.user_id for player in self.players.values()],
                [self.winner_id] if self.winner_id is not None else [],
                game="bomb",
            )
        except Exception:
            logger.exception("Bomb natijasini yozib bo'lmadi: %s", self.code)

    def _pay_reward(self, user_id: int) -> None:
        if self._reward_paid or self.winner_reward <= 0:
            return
        self._reward_paid = True
        try:
            self._coin_award(int(user_id), int(self.winner_reward))
        except Exception:  # mukofot xatosi o'yin natijasini yo'qotmasin
            logger.exception("Xavfli Bomba g'olibiga tanga berilmadi")

    # ------------------------------------------------------------------
    # Saqlash / tiklash
    # ------------------------------------------------------------------
    def to_state(self) -> dict[str, Any]:
        """Xonani Supabase JSONB uchun dict'ga aylantiradi."""
        return {
            "code": self.code,
            "chat_id": self.chat_id,
            "host_id": self.host_id,
            "players": [
                {
                    "user_id": player.user_id,
                    "name": player.name,
                    "hand": [card.value for card in player.hand],
                    "is_alive": player.is_alive,
                    "draws_left": player.draws_left,
                }
                for player in self.players.values()
            ],
            "order": list(self.order),
            "deck": [card.value for card in self.deck],
            "discard": [card.value for card in self.discard],
            "status": self.status.value,
            "turn_index": self.turn_index,
            "winner_id": self.winner_id,
            "last_eliminated_id": self.last_eliminated_id,
            "last_future_owner": self.last_future_owner,
            "last_future_cards": [card.value for card in self.last_future_cards],
            "winner_reward": self.winner_reward,
            "reward_paid": self._reward_paid,
            "result_recorded": self._result_recorded,
        }

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "BombRoom":
        """``to_state`` natijasidan Bomb xonasini tiklaydi."""
        room = cls(
            str(state.get("code") or ""),
            chat_id=int(state.get("chat_id") or 0),
            winner_reward=int(state.get("winner_reward") or WINNER_REWARD),
        )
        room.host_id = (
            int(state["host_id"]) if state.get("host_id") is not None else None
        )
        for raw in state.get("players") or []:
            if not isinstance(raw, dict):
                continue
            player = BombPlayer(
                user_id=int(raw.get("user_id") or 0),
                name=str(raw.get("name") or ""),
                hand=[
                    _coerce_card_type(card)
                    for card in raw.get("hand") or []
                ],
                is_alive=bool(raw.get("is_alive", True)),
                draws_left=int(raw.get("draws_left") or 0),
            )
            room.players[player.user_id] = player
        room.order = [int(item) for item in state.get("order") or []]
        room.deck = [_coerce_card_type(card) for card in state.get("deck") or []]
        room.discard = [
            _coerce_card_type(card) for card in state.get("discard") or []
        ]
        room.status = BombStatus(str(state.get("status") or "LOBBY"))
        room.turn_index = int(state.get("turn_index") or 0)
        room.winner_id = (
            int(state["winner_id"]) if state.get("winner_id") is not None else None
        )
        room.last_eliminated_id = (
            int(state["last_eliminated_id"])
            if state.get("last_eliminated_id") is not None
            else None
        )
        room.last_future_owner = (
            int(state["last_future_owner"])
            if state.get("last_future_owner") is not None
            else None
        )
        room.last_future_cards = tuple(
            _coerce_card_type(card)
            for card in state.get("last_future_cards") or []
        )
        room._reward_paid = bool(state.get("reward_paid", False))
        room._result_recorded = bool(state.get("result_recorded", False))
        return room

    # ------------------------------------------------------------------
    # Ko'rinish
    # ------------------------------------------------------------------
    def public_state(self) -> dict[str, object]:
        """Hamma ko'radigan xona holati (qo'llar va future yashirin)."""
        current_id = self.current_player_id
        return {
            "code": self.code,
            "status": self.status.value,
            "host_id": self.host_id,
            "players": [
                {
                    "user_id": player.user_id,
                    "name": player.label(),
                    "is_alive": player.is_alive,
                    "hand_count": len(player.hand),
                    "draw_turns_left": player.draw_turns_left,
                    "is_host": player.user_id == self.host_id,
                    "is_current": player.user_id == current_id,
                }
                for player in self.players.values()
            ],
            "current_player_id": current_id,
            "deck_size": len(self.deck),
            "discard": [card.value for card in self.discard[-20:]],
            "winner_id": self.winner_id,
            "winner_reward": self.winner_reward,
            "last_eliminated_id": self.last_eliminated_id,
            "cards": {
                card.value: {
                    "name": card_info(card).name,
                    "symbol": card_info(card).symbol,
                    "ability": card_info(card).ability,
                }
                for card in CardType
            },
        }

    def player_view(self, user_id: int) -> dict[str, object] | None:
        """Bitta o'yinchiga ko'rinadigan shaxsiy qo'l va future."""
        player = self.players.get(int(user_id))
        if player is None:
            return None
        future: list[str] = []
        if self.last_future_owner == player.user_id:
            future = [card.value for card in self.last_future_cards]
        return {
            "user_id": player.user_id,
            "hand": [card.value for card in player.hand],
            "is_alive": player.is_alive,
            "draw_turns_left": player.draw_turns_left,
            "future_cards": future,
        }

    def snapshot(self) -> dict[str, object]:
        """Eski API bilan moslik uchun umumiy xona ko'rinishi."""
        state = self.public_state()
        state["players"] = [
            {
                **player,  # type: ignore[dict-item]
                "hand_size": player["hand_count"],  # type: ignore[index]
            }
            for player in state["players"]  # type: ignore[union-attr]
        ]
        return state


# ----------------------------------------------------------------------
# Global xona reyestri va qulay funksiyalar
# ----------------------------------------------------------------------
_ROOMS: dict[str, BombRoom] = {}
_ROOMS_LOCK = threading.RLock()


def create_room(
    code: str,
    *,
    rng: random.Random | None = None,
    coin_award: CoinAward | None = None,
    winner_reward: int = WINNER_REWARD,
) -> BombRoom:
    """Yangi xonani reyestrga qo'shadi."""
    room = BombRoom(
        code,
        rng=rng,
        coin_award=coin_award,
        winner_reward=winner_reward,
    )
    with _ROOMS_LOCK:
        if room.code in _ROOMS:
            raise BombError(f"'{room.code}' kodli xona allaqachon mavjud")
        _ROOMS[room.code] = room
    return room


def get_room(code: str) -> BombRoom:
    """Kod bo'yicha xonani qaytaradi."""
    normalized = (code or "").strip().upper()
    with _ROOMS_LOCK:
        room = _ROOMS.get(normalized)
    if room is None:
        raise BombError(f"'{normalized or code}' kodli xona topilmadi")
    return room


def drop_room(code: str) -> None:
    """Xonani reyestrdan olib tashlaydi."""
    normalized = (code or "").strip().upper()
    with _ROOMS_LOCK:
        _ROOMS.pop(normalized, None)


def reset_rooms() -> None:
    """Barcha xonalarni tozalaydi (testlar va qayta ishga tushirish uchun)."""
    with _ROOMS_LOCK:
        _ROOMS.clear()


def _resolve_room(room_code: str | BombRoom) -> BombRoom:
    return room_code if isinstance(room_code, BombRoom) else get_room(room_code)


def draw_card(room_code: str | BombRoom, user_id: int) -> DrawResult:
    """Modul darajasidagi qulaylik: xona bo'yicha karta tortish."""
    return _resolve_room(room_code).draw_card(user_id)


def play_action_card(
    room_code: str | BombRoom,
    user_id: int,
    card_type: CardType | str,
    target_id: int | None = None,
) -> ActionResult:
    """Modul darajasidagi qulaylik: xona bo'yicha harakat kartasi."""
    return _resolve_room(room_code).play_action_card(
        user_id,
        card_type,
        target_id,
    )


def check_winner(room: str | BombRoom | None = None) -> int | None:
    """G'olibni tekshiradi.

    ``room`` berilmasa va reyestrda aynan bitta xona bo'lsa, o'sha xona
    tekshiriladi. Bu qisqa testlar va bitta faol xona uchun qulay.
    """
    if isinstance(room, BombRoom):
        return room.check_winner()
    if room is None:
        with _ROOMS_LOCK:
            rooms = list(_ROOMS.values())
        if len(rooms) != 1:
            raise BombError("check_winner uchun room_code yoki bitta xona kerak")
        return rooms[0].check_winner()
    return get_room(str(room)).check_winner()


__all__ = [
    "ActionResult",
    "BombError",
    "BombPlayer",
    "BombRoom",
    "BombStatus",
    "CoinAward",
    "DrawResult",
    "FUTURE_PEEK",
    "WINNER_REWARD",
    "check_winner",
    "create_room",
    "draw_card",
    "drop_room",
    "get_room",
    "play_action_card",
    "reset_rooms",
]
