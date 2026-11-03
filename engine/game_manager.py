"""«Bunker» o'yin xonalari va o'yin jarayoni menejeri.

Modul xona yaratish, o'yinchilarni qo'shish, kartalarni tarqatish, kartani
ochish va ovoz berish bosqichlarini boshqaradi. Holat Pydantic modellarida
saqlanadi, xonalar esa kod bo'yicha xotiradagi reyestrda turadi.

Odatiy foydalanish::

    room = create_room(1, "Ali", "ali")
    join_room(room.code, 2, "Vali", "vali")
    start_game(room.code)
    reveal_card(room.code, 1, "profession")
    cast_vote(room.code, 1, 2)
    tally_votes(room.code)
"""

from __future__ import annotations

import copy
import logging
import random
import threading
import uuid
from collections import Counter
from collections.abc import Callable

from engine.generator import CharacterGenerator
from models.game import CardType, GameRoom, Player, PlayerCard, RoomStatus

GAME_CODE_PREFIX = "BNK"
GAME_CODE_LENGTH = 6
GAME_CODE_ATTEMPTS = 1000
DEFAULT_MAX_PLAYERS = 12
MIN_PLAYERS_TO_START = 2

logger = logging.getLogger(__name__)

RoomChangeHandler = Callable[[GameRoom, dict[int, int]], None]
RoomSnapshot = GameRoom | tuple[GameRoom, dict[int, int]]
RoomLoader = Callable[[str], RoomSnapshot | None]


class GameError(Exception):
    """O'yin qoidalari yoki holati bilan bog'liq umumiy xatolik."""


class RoomNotFoundError(GameError):
    """Berilgan kodli xona topilmadi."""


class PlayerNotFoundError(GameError):
    """O'yinchi xonada topilmadi."""


class CardNotFoundError(GameError):
    """O'yinchida bunday karta yo'q."""


class InvalidGameStateError(GameError):
    """Amalni bajarish uchun xona holati mos emas."""


class GameManager:
    """Xonalar reyestri va o'yin jarayonini boshqaruvchi sinf.

    Bitta bot uchun bitta menejer yetarli; testlarda esa alohida nusxa
    yaratish mumkin.
    """

    def __init__(
        self,
        generator: CharacterGenerator | None = None,
        *,
        seed: int | None = None,
    ) -> None:
        self._generator = generator or CharacterGenerator()
        self._rng = random.Random(seed)
        self._rooms: dict[str, GameRoom] = {}
        self._votes: dict[str, dict[int, int]] = {}
        self._lock = threading.RLock()
        self._on_change: RoomChangeHandler | None = None
        self._room_loader: RoomLoader | None = None

    # ------------------------------------------------------------------
    # Xona yaratish va qo'shilish
    # ------------------------------------------------------------------
    def create_room(
        self,
        host_id: int,
        host_name: str,
        host_username: str,
        bunker_capacity: int = 5,
    ) -> GameRoom:
        """Yangi xona yaratadi va hostni unga qo'shadi.

        Kod 6 belgidan iborat (masalan ``BNK482``) va xonalar orasida
        takrorlanmaydi. Falokat katalogdan tasodifiy tanlanadi.
        """
        if not MIN_PLAYERS_TO_START <= bunker_capacity <= DEFAULT_MAX_PLAYERS:
            raise GameError(
                "Bunker sig'imi 2 dan 12 gacha bo'lishi kerak "
                f"(berildi: {bunker_capacity})"
            )

        with self._lock:
            code = self._generate_code()
            catastrophe = copy.deepcopy(
                self._rng.choice(self._generator.catalog["catastrophes"])
            )
            room = GameRoom(
                room_id=uuid.uuid4().hex,
                code=code,
                host_id=host_id,
                max_players=DEFAULT_MAX_PLAYERS,
                bunker_capacity=bunker_capacity,
                catastrophe=catastrophe,
            )
            room.add_player(
                Player(
                    user_id=host_id,
                    username=host_username,
                    full_name=host_name,
                    is_host=True,
                )
            )
            self._rooms[room.code] = room
            self._votes[room.code] = {}
            self._notify(room)
            return room

    def join_room(
        self,
        code: str,
        user_id: int,
        full_name: str,
        username: str,
    ) -> Player:
        """O'yinchini mavjud xonaga qo'shadi.

        O'yin boshlangan yoki tugagan bo'lsa, shuningdek xona to'lgan yoki
        o'yinchi allaqachon ichkarida bo'lsa, xatolik qaytaradi.
        """
        with self._lock:
            room = self.get_room(code)
            if room.status != RoomStatus.LOBBY:
                raise InvalidGameStateError("O'yin allaqachon boshlangan")
            if room.get_player(user_id) is not None:
                raise InvalidGameStateError("Siz allaqachon xonadasiz")

            player = Player(
                user_id=user_id,
                username=username,
                full_name=full_name,
            )
            try:
                room.add_player(player)
            except ValueError as exc:
                raise InvalidGameStateError(str(exc)) from exc
            self._notify(room)
            return player

    # ------------------------------------------------------------------
    # O'yinni boshlash
    # ------------------------------------------------------------------
    def start_game(self, code: str) -> GameRoom:
        """Xonani PLAYING holatiga o'tkazadi va kartalarni tarqatadi."""
        with self._lock:
            room = self.get_room(code)
            if room.status != RoomStatus.LOBBY:
                raise InvalidGameStateError("O'yin allaqachon boshlangan")
            if len(room.players) < MIN_PLAYERS_TO_START:
                raise InvalidGameStateError(
                    f"O'yinni boshlash uchun kamida {MIN_PLAYERS_TO_START} o'yinchi kerak"
                )

            for player in room.players.values():
                player.cards = self._generator.generate_character()
                player.is_alive = True
                player.votes_against = 0

            room.eliminated_players.clear()
            room.current_round = 1
            room.status = RoomStatus.PLAYING
            self._votes[room.code] = {}
            self._notify(room)
            return room

    # ------------------------------------------------------------------
    # Kartalar
    # ------------------------------------------------------------------
    def reveal_card(self, code: str, user_id: int, card_type: str) -> PlayerCard:
        """O'yinchi o'zining yopiq kartasini ochadi.

        Faqat o'z kartasini va faqat o'yin davomida ochish mumkin.
        """
        with self._lock:
            room = self.get_room(code)
            if room.status not in (RoomStatus.PLAYING, RoomStatus.VOTING):
                raise InvalidGameStateError("Kartalarni faqat o'yin davomida ochish mumkin")

            player = room.get_player(user_id)
            if player is None:
                raise PlayerNotFoundError(f"O'yinchi {user_id} xonada topilmadi")
            if not player.is_alive:
                raise InvalidGameStateError("Haydalgan o'yinchi kartasini ocha olmaydi")

            normalized = self._card_type(card_type)
            card = player.get_card(normalized)
            if card is None:
                raise CardNotFoundError(
                    f"'{normalized.value}' kartasi bu o'yinchida mavjud emas"
                )
            card.is_revealed = True
            self._notify(room)
            return card

    # ------------------------------------------------------------------
    # Ovoz berish
    # ------------------------------------------------------------------
    def cast_vote(self, code: str, voter_id: int, target_id: int) -> Player:
        """Ovoz beradi yoki oldingi ovozini yangilaydi.

        Ovoz berish PLAYING holatida boshlanadi va birinchi ovoz bilan xona
        VOTING holatiga o'tadi. O'lik o'yinchilarga, o'ziga va o'lik
        o'yinchidan ovoz berish mumkin emas.
        """
        with self._lock:
            room = self.get_room(code)
            if room.status not in (RoomStatus.PLAYING, RoomStatus.VOTING):
                raise InvalidGameStateError("Ovoz berish faqat o'yin davomida mumkin")

            voter = room.get_player(voter_id)
            if voter is None:
                raise PlayerNotFoundError(f"Ovoz beruvchi {voter_id} topilmadi")
            target = room.get_player(target_id)
            if target is None:
                raise PlayerNotFoundError(f"Nomzod {target_id} topilmadi")
            if not voter.is_alive:
                raise InvalidGameStateError("Haydalgan o'yinchi ovoz bera olmaydi")
            if not target.is_alive:
                raise InvalidGameStateError("Haydalgan o'yinchiga ovoz berish mumkin emas")
            if voter_id == target_id:
                raise InvalidGameStateError("O'ziga qarshi ovoz berish mumkin emas")

            room.status = RoomStatus.VOTING
            votes = self._votes.setdefault(room.code, {})
            votes[voter_id] = target_id
            self._sync_vote_counts(room)
            self._notify(room)
            return target

    def tally_votes(self, code: str) -> Player | None:
        """Ovozlarni sanaydi va eng ko'p ovoz olgan o'yinchini haydaydi.

        Ovozlar teng bo'lsa hech kim haydalmaydi va keyingi raund boshlanadi.
        Haydalgandan keyin tirik o'yinchilar soni bunker sig'imiga teng
        bo'lsa, o'yin FINISHED holatiga o'tadi.

        Returns:
            Haydalgan o'yinchi yoki durang bo'lsa ``None``.
        """
        with self._lock:
            room = self.get_room(code)
            if room.status not in (RoomStatus.PLAYING, RoomStatus.VOTING):
                raise InvalidGameStateError("Ovozlarni faqat o'yin davomida sanash mumkin")

            votes = self._votes.get(room.code, {})
            if not votes:
                raise InvalidGameStateError("Hali hech kim ovoz bermagan")

            counts = Counter(votes.values())
            max_votes = max(counts.values())
            leaders = [player_id for player_id, count in counts.items() if count == max_votes]

            eliminated: Player | None = None
            if len(leaders) == 1:
                eliminated = room.eliminate_player(leaders[0])

            self._votes[room.code] = {}
            self._sync_vote_counts(room)

            if len(room.alive_players) <= room.bunker_capacity:
                room.status = RoomStatus.FINISHED
            else:
                room.status = RoomStatus.PLAYING
                room.current_round += 1

            self._notify(room)
            return eliminated

    # ------------------------------------------------------------------
    # Yordamchi metodlar
    # ------------------------------------------------------------------
    def get_room(self, code: str) -> GameRoom:
        """Kod bo'yicha xonani qaytaradi.

        Xona xotirada bo'lmasa va loader o'rnatilgan bo'lsa (masalan Supabase),
        holat yuklanadi va menejerga ro'yxatga olinadi.
        """
        normalized = (code or "").strip().upper()
        room = self._rooms.get(normalized)
        if room is None and self._room_loader is not None:
            loaded = self._room_loader(normalized)
            if loaded is not None:
                if isinstance(loaded, tuple):
                    room, votes = loaded
                else:
                    room, votes = loaded, {}
                self._rooms[normalized] = room
                self._votes[normalized] = {
                    int(voter): int(target) for voter, target in votes.items()
                }
                self._sync_vote_counts(room)
        if room is None:
            raise RoomNotFoundError(f"'{normalized or code}' kodli xona topilmadi")
        return room

    # ------------------------------------------------------------------
    # Saqlash / yuklash integratsiyasi
    # ------------------------------------------------------------------
    def set_change_handler(self, handler: RoomChangeHandler | None) -> None:
        """Har bir o'zgarishdan keyin chaqiriladigan saqlash funksiyasini o'rnatadi."""
        self._on_change = handler

    def set_room_loader(self, loader: RoomLoader | None) -> None:
        """Xona xotirada topilmasa chaqiriladigan yuklash funksiyasini o'rnatadi."""
        self._room_loader = loader

    def _notify(self, room: GameRoom) -> None:
        """Holat o'zgarganini saqlash handleriga bildiradi."""
        handler = self._on_change
        if handler is None:
            return
        try:
            handler(room, dict(self._votes.get(room.code, {})))
        except Exception:  # saqlash xatosi o'yinni to'xtatmasligi kerak
            logger.exception("Xona holatini saqlashda xatolik: %s", room.code)

    def _generate_code(self) -> str:
        for _ in range(GAME_CODE_ATTEMPTS):
            digits = self._rng.randint(0, 10**3 - 1)
            code = f"{GAME_CODE_PREFIX}{digits:03d}"
            if len(code) == GAME_CODE_LENGTH and code not in self._rooms:
                return code
        raise GameError("Bo'sh xona kodi topilmadi, keyinroq qayta urinib ko'ring")

    @staticmethod
    def _card_type(card_type: str | CardType) -> CardType:
        if isinstance(card_type, CardType):
            return card_type
        value = str(card_type).strip()
        try:
            return CardType(value.lower())
        except ValueError:
            try:
                return CardType[value.upper()]
            except KeyError as exc:
                raise CardNotFoundError(f"Noma'lum karta turi: {card_type!r}") from exc

    def _sync_vote_counts(self, room: GameRoom) -> None:
        for player in room.players.values():
            player.votes_against = 0
        for target_id in self._votes.get(room.code, {}).values():
            room.players[target_id].votes_against += 1


_default_manager: GameManager | None = None
_default_manager_lock = threading.Lock()


def get_default_manager() -> GameManager:
    """Modul darajasidagi umumiy menejerni qaytaradi (kerak bo'lsa yaratadi)."""
    global _default_manager
    if _default_manager is None:
        with _default_manager_lock:
            if _default_manager is None:
                _default_manager = GameManager()
    return _default_manager


def create_room(
    host_id: int,
    host_name: str,
    host_username: str,
    bunker_capacity: int = 5,
) -> GameRoom:
    """Yangi o'yin xonasi yaratadi (modul darajasidagi menejer orqali)."""
    return get_default_manager().create_room(
        host_id, host_name, host_username, bunker_capacity
    )


def join_room(
    code: str,
    user_id: int,
    full_name: str,
    username: str,
) -> Player:
    """O'yinchini xonaga qo'shadi."""
    return get_default_manager().join_room(code, user_id, full_name, username)


def start_game(code: str) -> GameRoom:
    """O'yinni boshlaydi va kartalarni tarqatadi."""
    return get_default_manager().start_game(code)


def reveal_card(code: str, user_id: int, card_type: str) -> PlayerCard:
    """O'yinchining yopiq kartasini ochadi."""
    return get_default_manager().reveal_card(code, user_id, card_type)


def cast_vote(code: str, voter_id: int, target_id: int) -> Player:
    """Ovoz beradi yoki ovozni yangilaydi."""
    return get_default_manager().cast_vote(code, voter_id, target_id)


def tally_votes(code: str) -> Player | None:
    """Ovozlarni sanaydi va kerak bo'lsa o'yinchini haydaydi."""
    return get_default_manager().tally_votes(code)
