"""Guruhda «Mafiya» xonasini ochish, qo'shilish va boshlash handlerlari.

Oqim «Bunker» bilan bir xil: guruhda ``/mafia`` xona ochadi, o'yinchilar
inline tugma orqali qo'shiladi, xona egasi o'yinni boshlaydi. Rollar har bir
o'yinchiga shaxsiy xabar bilan yuboriladi, tun va tong bildirishnomalari esa
guruhga chiqadi.

Mini App orqali o'yinchilar tungi harakatlarni yuboradi va kunduzgi ovoz
berishda qatnashadi. Tunni xona egasi guruhdagi
«⏭ Tunni yakunlash» tugmasi bilan yopadi.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from html import escape
from typing import Any, Callable

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import get_config
from core.i18n import resolve_language, t
from core import room_store
from core.economy import MAFIA_WIN_REWARD, get_economy
from games.mafia.boosters import KEVLAR
from games.mafia.engine import (
    GamePhase,
    MafiaError,
    MafiaPlayer,
    MafiaRoom,
    Winner,
    resolve_night,
    winning_player_ids,
)
from games.mafia.generator import MIN_PLAYERS
from games.mafia.images import (
    COVER_IMAGE,
    DAY_IMAGE,
    ELIMINATED_IMAGE,
    NIGHT_IMAGE,
    image_path,
    victory_image_path,
)
from games.mafia.roles import Faction, MafiaRole, get_role_profile

logger = logging.getLogger(__name__)

router = Router(name="mafia_group")

JOIN_PREFIX = "join_mafia_"
START_PREFIX = "start_mafia_"
END_NIGHT_PREFIX = "end_night_mafia_"

MAX_PLAYERS = 20

WINNER_LABELS: dict[Winner, str] = {
    Winner.TOWN: "ŞAHAR",
    Winner.MAFIA: "MAFIYA",
    Winner.MANIAC: "MANIAK",
    Winner.JESTER: "JESTER",
}

FACTION_LABELS: dict[Faction, str] = {
    Faction.TOWN: "Şahar aholisi",
    Faction.MAFIA: "Mafiya",
    Faction.NEUTRAL: "Yolğiz",
}

FACTION_KEYS: dict[Faction, str] = {
    Faction.TOWN: "mafia_faction_town",
    Faction.MAFIA: "mafia_faction_mafia",
    Faction.NEUTRAL: "mafia_faction_neutral",
}


class MafiaGameError(Exception):
    """Guruh o'yini bilan bog'liq xatolik."""


@dataclass
class MafiaGame:
    """Bitta guruhdagi Mafiya xonasi."""

    code: str
    chat_id: int
    host_id: int
    room: MafiaRoom
    usernames: dict[int, str] = field(default_factory=dict)
    lobby_message_id: int | None = None
    phase_deadline: float | None = None
    phase_duration: int = 60

    def start_phase_timer(self, seconds: int = 60) -> None:
        """Joriy bosqich uchun 60 soniyalik taymerni boshlaydi."""
        self.phase_duration = max(1, int(seconds))
        self.phase_deadline = time.time() + self.phase_duration

    def clear_phase_timer(self) -> None:
        """Taymerni to'xtatadi (o'yin tugaganda)."""
        self.phase_deadline = None

    def phase_seconds_left(self) -> int:
        """Taymer tugashiga qolgan soniyalar."""
        if self.phase_deadline is None:
            return 0
        return max(0, int(round(self.phase_deadline - time.time())))

    # ------------------------------------------------------------------
    # Saqlash / tiklash
    # ------------------------------------------------------------------
    def to_state(self) -> dict[str, Any]:
        """Xonani Supabase JSONB uchun dict'ga aylantiradi."""
        return {
            "code": self.code,
            "chat_id": self.chat_id,
            "host_id": self.host_id,
            "usernames": {
                str(user_id): username
                for user_id, username in self.usernames.items()
            },
            "lobby_message_id": self.lobby_message_id,
            "phase_deadline": self.phase_deadline,
            "phase_duration": self.phase_duration,
            "room": self.room.to_state(),
        }

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "MafiaGame":
        """``to_state`` natijasidan Mafiya xonasini tiklaydi."""
        raw_room = state.get("room") or {}
        room = MafiaRoom.from_state(raw_room)
        return cls(
            code=str(state.get("code") or ""),
            chat_id=int(state.get("chat_id") or 0),
            host_id=int(state.get("host_id") or 0),
            room=room,
            usernames={
                int(user_id): str(username)
                for user_id, username in (state.get("usernames") or {}).items()
            },
            lobby_message_id=(
                int(state["lobby_message_id"])
                if state.get("lobby_message_id") is not None
                else None
            ),
            phase_deadline=(
                float(state["phase_deadline"])
                if state.get("phase_deadline") is not None
                else None
            ),
            phase_duration=int(state.get("phase_duration") or 60),
        )


class MafiaLobbyManager:
    """Guruh Mafiya xonalari reyestri."""

    def __init__(self, *, seed: int | None = None) -> None:
        self._games: dict[str, MafiaGame] = {}
        self._times: dict[str, float] = {}
        self._rng = random.Random(seed)
        self._lock = threading.RLock()
        self._on_change: Callable[[MafiaGame], None] | None = None
        self._room_loader: Callable[[str], MafiaGame | None] | None = None

    # ------------------------------------------------------------------
    # Saqlash integratsiyasi
    # ------------------------------------------------------------------
    def set_change_handler(
        self, handler: Callable[[MafiaGame], None] | None
    ) -> None:
        """Har bir o'zgarishdan keyin chaqiriladigan saqlash funksiyasi."""
        self._on_change = handler

    def set_room_loader(
        self, loader: Callable[[str], MafiaGame | None] | None
    ) -> None:
        """Xona xotirada bo'lmasa chaqiriladigan yuklash funksiyasi."""
        self._room_loader = loader

    def save(self, game: MafiaGame) -> None:
        """Xonani darhol saqlashga yuboradi (API/bot amallari uchun)."""
        self._times[game.code] = time.time()
        self._persist(game)

    def _persist(self, game: MafiaGame) -> None:
        handler = self._on_change
        if handler is None:
            return
        try:
            handler(game)
        except Exception:
            logger.exception("Mafiya %s xonasi saqlanmadi", game.code)

    def _restore(self, code: str) -> MafiaGame | None:
        loader = self._room_loader
        if loader is None:
            return None
        try:
            return loader(code)
        except Exception:
            logger.exception("Mafiya %s xonasi yuklanmadi", code)
            return None

    def sync_from_store(self) -> int:
        """Bazadagi tugamagan Mafiya xonalarini xotiraga qaytaradi."""
        restored = 0
        for state in room_store.load_states(room_store.MAFIA_ROOMS_TABLE):
            try:
                game = MafiaGame.from_state(state)
            except Exception:
                logger.exception("Mafiya xonasi bazadan tiklanmadi")
                continue
            if game.room.phase in (GamePhase.FINISHED, GamePhase.EXPIRED):
                continue
            with self._lock:
                if game.code not in self._games:
                    self._games[game.code] = game
                    self._times[game.code] = time.time()
                    restored += 1
        if restored:
            logger.info("Mafiya: bazadan %s ta xona tiklandi", restored)
        return restored

    def create_game(
        self,
        chat_id: int,
        host_id: int,
        host_name: str,
        host_username: str = "",
    ) -> MafiaGame:
        """Yangi xona ochib, xona egasini unga qo'shadi."""
        with self._lock:
            code = self._generate_code()
            room = MafiaRoom(
                [MafiaPlayer(int(host_id), host_name)], room_id=code
            )
            game = MafiaGame(
                code=code,
                chat_id=int(chat_id),
                host_id=int(host_id),
                room=room,
            )
            game.usernames[int(host_id)] = host_username or ""
            self._games[code] = game
            self._times[code] = time.time()
            self._persist(game)
            return game

    def get_game(self, code: str) -> MafiaGame:
        """Kod bo'yicha xonani qaytaradi (kerak bo'lsa bazadan tiklaydi)."""
        normalized = (code or "").strip().upper()
        with self._lock:
            game = self._games.get(normalized)
            if game is None:
                game = self._restore(normalized)
                if game is not None:
                    self._games[normalized] = game
            if game is None:
                raise MafiaGameError(
                    f"'{normalized or code}' kodli Mafiya xonasi topilmadi"
                )
            self._times[normalized] = time.time()
            return game

    def prune_lobbies(self, max_age_seconds: int = 30 * 60) -> int:
        """Uzoq vaqt harakatsiz qolgan Mafiya lobby'larini yopadi."""
        now = time.time()
        removed = 0
        with self._lock:
            for code, game in list(self._games.items()):
                if game.room.phase is not GamePhase.LOBBY:
                    continue
                if now - self._times.get(code, now) > max_age_seconds:
                    game.room.phase = GamePhase.EXPIRED
                    self._persist(game)
                    self._games.pop(code, None)
                    self._times.pop(code, None)
                    removed += 1
        return removed

    def expire_stale(
        self,
        *,
        lobby_idle_seconds: float = 15 * 60,
        game_idle_seconds: float = 30 * 60,
    ) -> dict[str, int]:
        """Tashlab ketilgan Mafiya xonalarini yopadi va xotiradan olib tashlaydi."""
        now = time.time()
        expired = 0
        finished = 0
        with self._lock:
            for code, game in list(self._games.items()):
                idle = now - self._times.get(code, now)
                if game.room.phase is GamePhase.LOBBY and idle > lobby_idle_seconds:
                    game.room.phase = GamePhase.EXPIRED
                    game.clear_phase_timer()
                    self._persist(game)
                    self._games.pop(code, None)
                    self._times.pop(code, None)
                    expired += 1
                elif (
                    game.room.phase not in (GamePhase.FINISHED, GamePhase.EXPIRED)
                    and idle > game_idle_seconds
                ):
                    game.room.phase = GamePhase.FINISHED
                    game.clear_phase_timer()
                    self._persist(game)
                    self._games.pop(code, None)
                    self._times.pop(code, None)
                    finished += 1
        if expired or finished:
            logger.info(
                "Mafiya xonalari tozalandi: %s ta muddati ötgan, %s ta yopilgan",
                expired,
                finished,
            )
        return {"expired": expired, "finished": finished}

    def open_games(self, limit: int = 50) -> list[MafiaGame]:
        """Global qidiruv uchun ochiq Mafiya lobby'lari."""
        self.prune_lobbies()
        with self._lock:
            games = [
                game
                for game in self._games.values()
                if game.room.phase is GamePhase.LOBBY
            ]
            games.sort(
                key=lambda game: self._times.get(game.code, 0),
                reverse=True,
            )
            return games[: max(1, int(limit))]

    def join(
        self,
        code: str,
        user_id: int,
        full_name: str,
        username: str = "",
    ) -> MafiaPlayer:
        """O'yinchini xonaga qo'shadi."""
        with self._lock:
            game = self.get_game(code)
            if len(game.room.players) >= MAX_PLAYERS:
                raise MafiaGameError("Xona tölgan")
            try:
                player = game.room.add_player(
                    MafiaPlayer(int(user_id), full_name)
                )
            except MafiaError as exc:
                raise MafiaGameError(str(exc)) from exc
            game.usernames[int(user_id)] = username or ""
            self._persist(game)
            return player

    def start_game(self, code: str, host_id: int) -> MafiaGame:
        """Xona egasi uchun rollarni tarqatib, o'yinni boshlaydi."""
        with self._lock:
            game = self.get_game(code)
            if int(host_id) != game.host_id:
                raise MafiaGameError(
                    "Öyinni faqat xona egasi boşlaşi mumkin"
                )
            try:
                game.room.start(rng=self._rng)
            except MafiaError as exc:
                raise MafiaGameError(str(exc)) from exc
            game.start_phase_timer()
            self._persist(game)
            return game

    def _generate_code(self) -> str:
        for _ in range(1000):
            code = f"MAF{self._rng.randint(0, 999):03d}"
            if code not in self._games:
                return code
        raise MafiaGameError(
            "Böş xona kodi topilmadi, keyinroq qayta urinib köring"
        )


_default_manager: MafiaLobbyManager | None = None
_default_manager_lock = threading.Lock()


def get_default_manager() -> MafiaLobbyManager:
    """Modul darajasidagi umumiy menejerni qaytaradi."""
    global _default_manager
    if _default_manager is None:
        with _default_manager_lock:
            if _default_manager is None:
                _default_manager = MafiaLobbyManager()
    return _default_manager


# ----------------------------------------------------------------------
# Matn va tugmalar
# ----------------------------------------------------------------------
def _startapp(code: str) -> str:
    return (
        f"https://t.me/{get_config().bot_username}"
        f"?startapp=mafia_{code}"
    )


def _player_label(game: MafiaGame, player: MafiaPlayer) -> str:
    name = escape(player.name or f"ID {player.user_id}")
    username = game.usernames.get(player.user_id, "")
    if username:
        return f"{name} (@{escape(username)})"
    return name


def players_list(game: MafiaGame) -> str:
    """Xona o'yinchilarining HTML ro'yxati."""
    labels = [
        _player_label(game, player)
        for player in game.room.players.values()
    ]
    return ", ".join(labels) or "—"


def _game_language(game: MafiaGame) -> str:
    """Xona egasining tili (e'lonlar shu tilda chiqadi)."""
    host_id = int(getattr(getattr(game, "room", None), "host_id", 0) or 0)
    return resolve_language(host_id) if host_id else "uz"


def lobby_text(game: MafiaGame, language: str = "uz") -> str:
    """Guruhdagi xona e'loni."""
    return t(language, "mafia_lobby", players=players_list(game), total=len(game.room.players))


def lobby_keyboard(game: MafiaGame, language: str = "uz") -> InlineKeyboardMarkup:
    """Mini App havolasi, qo'shilish va boshlash tugmalari."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_enter_mafia"),
                    url=_startapp(game.code),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_join"),
                    callback_data=f"{JOIN_PREFIX}{game.code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_start"),
                    callback_data=f"{START_PREFIX}{game.code}",
                )
            ],
        ]
    )


def night_text(game: MafiaGame, language: str = "uz") -> str:
    """Tun boshlanganidagi guruh xabari."""
    return t(language, "mafia_night")


def night_keyboard(game: MafiaGame, language: str = "uz") -> InlineKeyboardMarkup:
    """Tungi harakat va (egasi uchun) tunni yakunlash tugmalari."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "mafia_night_action_btn"),
                    url=_startapp(game.code),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "mafia_end_night_btn"),
                    callback_data=f"{END_NIGHT_PREFIX}{game.code}",
                )
            ],
        ]
    )


def day_text(game: MafiaGame, language: str = "uz") -> str:
    """Tonggi hisobot matni."""
    report = game.room.last_report
    if report is None or not report.deaths:
        result = t(language, "mafia_day_none")
    else:
        names = ", ".join(
            _player_label(game, game.room.players[user_id])
            for user_id in report.deaths
            if user_id in game.room.players
        )
        result = t(language, "mafia_day_deaths", names=names)
    return (
        t(language, "mafia_day_head")
        + "\n"
        + result
        + "\n\n"
        + t(language, "mafia_day_tail")
    )


def day_keyboard(game: MafiaGame, language: str = "uz") -> InlineKeyboardMarkup:
    """Mini App'dagi ovoz berish havolasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_vote"),
                    url=_startapp(game.code),
                )
            ]
        ]
    )


def execution_text(game: MafiaGame, player: MafiaPlayer, language: str = "uz") -> str:
    """Kunduzgi qatl e'loni."""
    username = game.usernames.get(player.user_id, "")
    if username:
        who = f"@{escape(username)}"
    else:
        who = escape(player.name or f"ID {player.user_id}")
    role_name = (
        t(language, f"role_name_{player.role.value}")
        if player.role is not None
        else t(language, "mafia_role_unknown")
    )
    return t(language, "mafia_execution", who=who, role=role_name)


def finish_text(winner: Winner, language: str = "uz") -> str:
    """G'alaba e'loni."""
    label = WINNER_LABELS.get(winner, winner.value.upper())
    return t(language, "mafia_end", winner=label)


def role_text(game: MafiaGame, player: MafiaPlayer, language: str = "uz") -> str:
    """O'yinchiga shaxsiy xabar bilan yuboriladigan rol kartasi."""
    if player.role is None:
        raise MafiaGameError("Rol hali berilmagan")
    profile = get_role_profile(player.role)
    slug = player.role.value
    action = t(
        language,
        "mafia_night_action" if profile.has_night_action else "mafia_night_none",
    )
    return t(
        language,
        "mafia_role",
        name=t(language, f"role_name_{slug}"),
        description=t(language, f"role_desc_{slug}"),
        faction=t(
            language,
            FACTION_KEYS.get(profile.faction, "mafia_faction_town"),
        ),
        action=action,
        code=game.code,
    )


# ----------------------------------------------------------------------
# Guruhga bildirishnomalar
# ----------------------------------------------------------------------
async def announce_night(bot: Bot, game: MafiaGame) -> None:
    """«Shaharga tun cho'kdi» xabarini tun rasmi bilan yuboradi."""
    await bot.send_photo(
        game.chat_id,
        FSInputFile(image_path(NIGHT_IMAGE)),
        caption=night_text(game, _game_language(game)),
        reply_markup=night_keyboard(game, _game_language(game)),
    )
    await send_kevlar_offers(bot, game)


async def send_kevlar_offers(bot: Bot, game: MafiaGame) -> None:
    """Tirik o'yinchilarga Kevlar jilet taklifini shaxsiy yuboradi."""
    economy = get_economy()
    def _offer_keyboard(language: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t(
                            language, "mafia_kevlar_btn", price=KEVLAR.price
                        ),
                        url=_startapp(game.code),
                    )
                ]
            ]
        )
    for player in game.room.players.values():
        if not player.is_alive or player.kevlar_used or player.kevlar_active:
            continue
        if economy.has_booster(game.code, player.user_id, KEVLAR.key):
            continue
        try:
            language = resolve_language(player.user_id)
            await bot.send_message(
                player.user_id,
                t(language, "mafia_kevlar_offer", price=KEVLAR.price),
                reply_markup=_offer_keyboard(language),
            )
        except Exception:
            logger.info(
                "Kevlar taklifini yuborib bölmadi: %s", player.user_id
            )


async def notify_kevlar_saved(bot: Bot, game: MafiaGame) -> None:
    """Kevlar jilet saqlab qolgan o'yinchilarga xabar yuboradi."""
    report = game.room.last_report
    if report is None:
        return
    for user_id in report.shielded:
        try:
            await bot.send_message(
                user_id,
                t(resolve_language(user_id), "mafia_kevlar_saved"),
            )
        except Exception:
            logger.info("Kevlar natijasini yuborib bölmadi: %s", user_id)


async def announce_day(bot: Bot, game: MafiaGame) -> None:
    """Tonggi hisobotni yuboradi; o'yin tugagan bo'lsa g'olibni ham e'lon qiladi."""
    await bot.send_photo(
        game.chat_id,
        FSInputFile(image_path(DAY_IMAGE)),
        caption=day_text(game, _game_language(game)),
        reply_markup=day_keyboard(game, _game_language(game)),
    )
    if game.room.winner is not None:
        await announce_finish(bot, game)


async def announce_execution(
    bot: Bot, game: MafiaGame, player: MafiaPlayer
) -> None:
    """Kunduzgi qatl haqidagi xabarni qatl rasmi bilan yuboradi."""
    await bot.send_photo(
        game.chat_id,
        FSInputFile(image_path(ELIMINATED_IMAGE)),
        caption=execution_text(game, player, _game_language(game)),
    )


async def announce_finish(bot: Bot, game: MafiaGame) -> None:
    """G'olib jamoa haqidagi xabarni mos g'alaba rasmi bilan yuboradi."""
    if game.room.winner is None:
        return
    game.clear_phase_timer()
    caption = finish_text(game.room.winner, _game_language(game))
    try:
        rewarded = get_economy().record_mafia_game(
            game.code,
            game.room.players.keys(),
            winning_player_ids(game.room),
        )
        if rewarded:
            caption += t(
                _game_language(game), "mafia_win_reward", reward=MAFIA_WIN_REWARD
            )
    except Exception:
        logger.exception("Mafiya mukofotini yozib bölmadi: %s", game.code)
    await bot.send_photo(
        game.chat_id,
        FSInputFile(victory_image_path(game.room.winner)),
        caption=caption,
    )


async def send_role_cards(bot: Bot, game: MafiaGame) -> list[int]:
    """Rollarni shaxsiy xabarda yuboradi va muvaffaqiyatsiz ID'larni qaytaradi."""
    failed: list[int] = []
    for player in game.room.players.values():
        try:
            await bot.send_message(player.user_id, role_text(game, player, resolve_language(player.user_id)))
        except Exception:
            logger.exception(
                "Rol xabarini yuborib bölmadi: %s", player.user_id
            )
            failed.append(player.user_id)
    return failed


# ----------------------------------------------------------------------
# Yordamchi funksiyalar
# ----------------------------------------------------------------------
def _callback_code(data: str | None, prefix: str) -> str | None:
    if not data or not data.startswith(prefix):
        return None
    code = data[len(prefix) :].strip().upper()
    return code or None


def _callback_chat_id(callback: CallbackQuery) -> int:
    if callback.message is not None:
        return callback.message.chat.id
    return callback.from_user.id


async def _edit_lobby(
    callback: CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup | None,
) -> None:
    """Xona e'lonini tahrirlaydi; imkoni bo'lmasa yangi xabar yuboradi."""
    message = callback.message
    if message is not None:
        # E'lon rasm bilan yuborilgan bo'lsa, matn emas, izoh (caption)
        # tahrirlanadi; aks holda Telegram xato qaytaradi.
        if getattr(message, "photo", None) is not None and hasattr(
            message, "edit_caption"
        ):
            try:
                await message.edit_caption(
                    caption=text, reply_markup=keyboard
                )
                return
            except TelegramBadRequest:
                pass
        if hasattr(message, "edit_text"):
            try:
                await message.edit_text(text, reply_markup=keyboard)
                return
            except TelegramBadRequest:
                pass
    await callback.bot.send_message(
        _callback_chat_id(callback), text, reply_markup=keyboard
    )


# ----------------------------------------------------------------------
# Handlerlar
# ----------------------------------------------------------------------
@router.message(F.chat.type.in_({"group", "supergroup"}), Command("mafia"))
async def create_mafia_game(message: Message) -> None:
    """/mafia — guruhda yangi Mafiya xonasi ochadi."""
    try:
        user = message.from_user
        if user is None:
            raise ValueError("Buyruq yuborgan foydalanuvçi aniqlanmadi")
        logger.info(
            "Guruhda yangi Mafiya xonasi: çat=%s user=%s",
            message.chat.id,
            user.id,
        )
        game = get_default_manager().create_game(
            chat_id=message.chat.id,
            host_id=user.id,
            host_name=user.full_name,
            host_username=user.username or "",
        )
        sent = await message.answer_photo(
            FSInputFile(image_path(COVER_IMAGE)),
            caption=lobby_text(game, _game_language(game)),
            reply_markup=lobby_keyboard(game),
        )
        game.lobby_message_id = getattr(sent, "message_id", None)
        get_default_manager().save(game)
    except Exception as exc:
        logger.exception("Guruhda /mafia buyruğida xatolik: %s", exc)
        await message.reply(f"⚠️ Xatolik yuz berdi: {escape(str(exc))}")


@router.message(F.chat.type == "private", Command("mafia"))
async def create_mafia_game_private(message: Message) -> None:
    """/mafia — shaxsiy chatda guruhga yo'naltiradi."""
    user = message.from_user
    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    config = get_config()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "mafia_join_group_btn"),
                    url=f"https://t.me/{config.bot_username}?startgroup=true",
                )
            ]
        ]
    )
    await message.answer(
        t(language, "mafia_private_hint", min_players=MIN_PLAYERS),
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith(JOIN_PREFIX))
async def join_mafia_game(callback: CallbackQuery) -> None:
    """«➕ Qo'shilish» tugmasi."""
    code = _callback_code(callback.data, JOIN_PREFIX)
    language = resolve_language(
        getattr(callback.from_user, "id", None),
        getattr(callback.from_user, "language_code", None),
    )
    if code is None:
        await callback.answer(t(language, "booster_wrong_button"), show_alert=True)
        return

    user = callback.from_user
    manager = get_default_manager()
    try:
        manager.join(
            code,
            user.id,
            user.full_name,
            user.username or "",
        )
        game = manager.get_game(code)
    except MafiaGameError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    language = resolve_language(user.id, getattr(user, "language_code", None))
    await callback.answer(t(language, "room_joined", name=escape(user.full_name)))
    await _edit_lobby(callback, lobby_text(game, _game_language(game)), lobby_keyboard(game, _game_language(game)))


@router.callback_query(F.data.startswith(START_PREFIX))
async def start_mafia_game(callback: CallbackQuery) -> None:
    """«▶️ O'yinni boshlash» — faqat xona egasi uchun."""
    code = _callback_code(callback.data, START_PREFIX)
    language = resolve_language(
        getattr(callback.from_user, "id", None),
        getattr(callback.from_user, "language_code", None),
    )
    if code is None:
        await callback.answer(t(language, "booster_wrong_button"), show_alert=True)
        return

    manager = get_default_manager()
    try:
        game = manager.start_game(code, callback.from_user.id)
    except MafiaGameError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    language = resolve_language(
        callback.from_user.id, getattr(callback.from_user, "language_code", None)
    )
    await callback.answer(t(language, "room_started", game="Mafiya"))
    await _edit_lobby(
        callback,
        t(
            language,
            "mafia_started",
            players=len(game.room.players),
            code=game.code,
        ),
        None,
    )

    failed = await send_role_cards(callback.bot, game)
    await announce_night(callback.bot, game)
    if failed:
        names = ", ".join(
            _player_label(game, game.room.players[user_id])
            for user_id in failed
            if user_id in game.room.players
        )
        await callback.bot.send_message(
            game.chat_id,
            t(language, "mafia_roles_failed", names=names),
        )


@router.callback_query(F.data.startswith(END_NIGHT_PREFIX))
async def end_mafia_night(callback: CallbackQuery) -> None:
    """«⏭ Tunni yakunlash» — xona egasi tungi harakatlarni hal qiladi."""
    code = _callback_code(callback.data, END_NIGHT_PREFIX)
    language = resolve_language(
        getattr(callback.from_user, "id", None),
        getattr(callback.from_user, "language_code", None),
    )
    if code is None:
        await callback.answer(t(language, "booster_wrong_button"), show_alert=True)
        return

    manager = get_default_manager()
    try:
        game = manager.get_game(code)
        if callback.from_user.id != game.host_id:
            await callback.answer(
                t(language, "mafia_night_host_only"), show_alert=True
            )
            return
        resolve_night(game.room)
        if game.room.phase is not GamePhase.FINISHED:
            game.start_phase_timer()
        save = getattr(manager, "save", None)
        if callable(save):
            save(game)
    except (MafiaGameError, MafiaError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer("Tun yakunlandi.")
    await notify_kevlar_saved(callback.bot, game)
    await announce_day(callback.bot, game)

# ==========================================
# ARVOH REJIMI VA GURUH NAZORATI (MODERATION)
# ==========================================
# Faqat shu bosqichlarda guruh suhbati nazorat qilinadi: lobby'da hammani
# yozishga ruxsat beriladi, o'yin tugagach esa nazorat to'xtaydi.
MODERATED_PHASES = (
    GamePhase.NIGHT,
    GamePhase.DAY_REPORT,
    GamePhase.VOTING,
)

_last_words_spoken: set[tuple[str, int]] = set()


def _active_game_for_chat(chat_id: int) -> MafiaGame | None:
    """Guruh ID bo'yicha faol Mafiya xonasini topadi."""
    manager = get_default_manager()
    for game in manager._games.values():
        if game.chat_id == int(chat_id) and game.room.phase is not GamePhase.FINISHED:
            return game
    return None


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text,
    ~F.text.startswith("/"),
)
async def mafia_chat_moderator(message: Message) -> None:
    """O'yin paytida qatnashmagan va halok bo'lgan o'yinchilarni nazorat qiladi.

    Filtrda buyruqlar chiqarib tashlanadi: aks holda bu catch-all handler
    keyingi routerlardagi /bunker va /spy buyruqlarini yutib yuboradi.
    """
    if message.text and message.text.startswith("/"):
        return
    if message.from_user is None:
        return

    game = _active_game_for_chat(message.chat.id)
    if game is None or game.room.phase not in MODERATED_PHASES:
        return

    user_id = message.from_user.id
    player = game.room.players.get(user_id)

    # O'yinda qatnashmayotganlar faol o'yin guruhida yozolmaydi.
    if player is None:
        try:
            await message.delete()
        except Exception:
            logger.debug("Öyinçi bölmagan xabarni öçirib bölmadi")
        return

    # Halok bo'lgan o'yinchiga har bir o'yinda bir marta so'nggi so'z beriladi.
    if not player.is_alive:
        marker = (game.code, user_id)
        if marker not in _last_words_spoken:
            _last_words_spoken.add(marker)
            try:
                await message.reply(
                    t(resolve_language(user_id), "mafia_last_words")
                )
            except Exception:
                logger.debug("Sönggi söz xabarini yuborib bölmadi")
            return

        try:
            await message.delete()
        except Exception:
            logger.debug("Arvoh xabarini öçirib bölmadi")
