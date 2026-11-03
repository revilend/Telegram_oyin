"""Guruhda «Mafiya» xonasini ochish, qo'shilish va boshlash handlerlari.

Oqim «Bunker» bilan bir xil: guruhda ``/mafia`` xona ochadi, o'yinchilar
inline tugma orqali qo'shiladi, xona egasi o'yinni boshlaydi. Rollar har bir
o'yinchiga shaxsiy xabar bilan yuboriladi, tun va tong bildirishnomalari esa
guruhga chiqadi.

Mini App hali Mafiya harakatlarini bajarmagani uchun tunni xona egasi
«⏭ Tunni yakunlash» tugmasi bilan yopadi; vot natijalari keyingi bosqichda
Mini App'dan keladi.
"""

from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass, field
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import get_config
from games.mafia.engine import (
    GamePhase,
    MafiaError,
    MafiaPlayer,
    MafiaRoom,
    Winner,
    resolve_night,
)
from games.mafia.generator import MIN_PLAYERS
from games.mafia.roles import Faction, MafiaRole, get_role_profile

logger = logging.getLogger(__name__)

router = Router(name="mafia_group")

JOIN_PREFIX = "join_mafia_"
START_PREFIX = "start_mafia_"
END_NIGHT_PREFIX = "end_night_mafia_"

MAX_PLAYERS = 20

WINNER_LABELS: dict[Winner, str] = {
    Winner.TOWN: "SHAHAR",
    Winner.MAFIA: "MAFIYA",
    Winner.MANIAC: "MANIAK",
    Winner.JESTER: "JESTER",
}

FACTION_LABELS: dict[Faction, str] = {
    Faction.TOWN: "Shahar aholisi",
    Faction.MAFIA: "Mafiya",
    Faction.NEUTRAL: "Yolg'iz",
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


class MafiaLobbyManager:
    """Guruh Mafiya xonalari reyestri."""

    def __init__(self, *, seed: int | None = None) -> None:
        self._games: dict[str, MafiaGame] = {}
        self._rng = random.Random(seed)
        self._lock = threading.RLock()

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
            return game

    def get_game(self, code: str) -> MafiaGame:
        """Kod bo'yicha xonani qaytaradi."""
        normalized = (code or "").strip().upper()
        game = self._games.get(normalized)
        if game is None:
            raise MafiaGameError(
                f"'{normalized or code}' kodli Mafiya xonasi topilmadi"
            )
        return game

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
                raise MafiaGameError("Xona to'lgan")
            try:
                player = game.room.add_player(
                    MafiaPlayer(int(user_id), full_name)
                )
            except MafiaError as exc:
                raise MafiaGameError(str(exc)) from exc
            game.usernames[int(user_id)] = username or ""
            return player

    def start_game(self, code: str, host_id: int) -> MafiaGame:
        """Xona egasi uchun rollarni tarqatib, o'yinni boshlaydi."""
        with self._lock:
            game = self.get_game(code)
            if int(host_id) != game.host_id:
                raise MafiaGameError(
                    "O'yinni faqat xona egasi boshlashi mumkin"
                )
            try:
                game.room.start(rng=self._rng)
            except MafiaError as exc:
                raise MafiaGameError(str(exc)) from exc
            return game

    def _generate_code(self) -> str:
        for _ in range(1000):
            code = f"MAF{self._rng.randint(0, 999):03d}"
            if code not in self._games:
                return code
        raise MafiaGameError(
            "Bo'sh xona kodi topilmadi, keyinroq qayta urinib ko'ring"
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


def lobby_text(game: MafiaGame) -> str:
    """Guruhdagi xona e'loni."""
    return (
        "🕵️‍♂️ <b>MAFIYA O'YINI BOSHLANMOQDA!</b>\n"
        "Shahar mafiyalar changalida qoldi. Kim omon qoladi?\n\n"
        f"👥 Qatnashuvchilar: {players_list(game)} "
        f"(jami {len(game.room.players)} kishi)"
    )


def lobby_keyboard(game: MafiaGame) -> InlineKeyboardMarkup:
    """Mini App havolasi, qo'shilish va boshlash tugmalari."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚪 Mafiyaga kirish",
                    url=_startapp(game.code),
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Qo'shilish",
                    callback_data=f"{JOIN_PREFIX}{game.code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="▶️ O'yinni boshlash",
                    callback_data=f"{START_PREFIX}{game.code}",
                )
            ],
        ]
    )


def night_text(game: MafiaGame) -> str:
    """Tun boshlanganidagi guruh xabari."""
    return (
        "🌃 <b>SHAHARGA TUN CHO'KDI!</b>\n"
        "Hamma uxladi. O'z vazifangizni bajarish uchun pastdagi "
        "tugmani bosing:"
    )


def night_keyboard(game: MafiaGame) -> InlineKeyboardMarkup:
    """Tungi harakat va (egasi uchun) tunni yakunlash tugmalari."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚪 Tungi harakatni tanlash",
                    url=_startapp(game.code),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏭ Tunni yakunlash (egasi)",
                    callback_data=f"{END_NIGHT_PREFIX}{game.code}",
                )
            ],
        ]
    )


def day_text(game: MafiaGame) -> str:
    """Tonggi hisobot matni."""
    report = game.room.last_report
    if report is None or not report.deaths:
        result = "Tunda hech kim halok bo'lmadi."
    else:
        names = ", ".join(
            _player_label(game, game.room.players[user_id])
            for user_id in report.deaths
            if user_id in game.room.players
        )
        result = f"Tunda halok bo'ldilar: {names}."
    return (
        "🌅 <b>TONG OTDI!</b>\n"
        "Shahar uyg'ondi. Tungi natijalar:\n"
        f"{result}\n\n"
        "⚖️ Guruhda muhokama boshlandi!"
    )


def day_keyboard(game: MafiaGame) -> InlineKeyboardMarkup:
    """Mini App'dagi ovoz berish havolasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗳 Ovoz berish",
                    url=_startapp(game.code),
                )
            ]
        ]
    )


def execution_text(game: MafiaGame, player: MafiaPlayer) -> str:
    """Kunduzgi qatl e'loni."""
    username = game.usernames.get(player.user_id, "")
    if username:
        who = f"@{escape(username)}"
    else:
        who = escape(player.name or f"ID {player.user_id}")
    role_name = (
        get_role_profile(player.role).name_uz
        if player.role is not None
        else "Noma'lum"
    )
    return (
        "⚰️ Shahar aholisi qaroriga ko'ra "
        f"{who} qatl qilindi! Uning roli: <b>{role_name}</b> edi!"
    )


def finish_text(winner: Winner) -> str:
    """G'alaba e'loni."""
    return (
        "🏆 <b>O'YIN YAKUNLANDI!</b>\n"
        f"{WINNER_LABELS.get(winner, winner.value.upper())} g'alaba qozondi!"
    )


def role_text(game: MafiaGame, player: MafiaPlayer) -> str:
    """O'yinchiga shaxsiy xabar bilan yuboriladigan rol kartasi."""
    if player.role is None:
        raise MafiaGameError("Rol hali berilmagan")
    profile = get_role_profile(player.role)
    action = (
        "Tunda harakat qilasiz."
        if profile.has_night_action
        else "Tunda maxsus harakatingiz yo'q."
    )
    return (
        f"🕵️ <b>Sizning rolingiz: {profile.name_uz}</b>\n\n"
        f"{profile.description}\n\n"
        f"🎯 Jamoa: <b>{FACTION_LABELS[profile.faction]}</b>\n"
        f"🌙 {action}\n"
        f"🔑 Xona kodi: <code>{game.code}</code>"
    )


# ----------------------------------------------------------------------
# Guruhga bildirishnomalar
# ----------------------------------------------------------------------
async def announce_night(bot: Bot, game: MafiaGame) -> None:
    """«Shaharga tun cho'kdi» xabarini guruhga yuboradi."""
    await bot.send_message(
        game.chat_id, night_text(game), reply_markup=night_keyboard(game)
    )


async def announce_day(bot: Bot, game: MafiaGame) -> None:
    """Tonggi hisobotni yuboradi; o'yin tugagan bo'lsa g'olibni ham e'lon qiladi."""
    await bot.send_message(
        game.chat_id, day_text(game), reply_markup=day_keyboard(game)
    )
    if game.room.winner is not None:
        await announce_finish(bot, game)


async def announce_execution(
    bot: Bot, game: MafiaGame, player: MafiaPlayer
) -> None:
    """Kunduzgi qatl haqidagi xabarni yuboradi."""
    await bot.send_message(game.chat_id, execution_text(game, player))


async def announce_finish(bot: Bot, game: MafiaGame) -> None:
    """G'olib jamoa haqidagi xabarni yuboradi."""
    if game.room.winner is None:
        return
    await bot.send_message(game.chat_id, finish_text(game.room.winner))


async def send_role_cards(bot: Bot, game: MafiaGame) -> list[int]:
    """Rollarni shaxsiy xabarda yuboradi va muvaffaqiyatsiz ID'larni qaytaradi."""
    failed: list[int] = []
    for player in game.room.players.values():
        try:
            await bot.send_message(player.user_id, role_text(game, player))
        except Exception:
            logger.exception(
                "Rol xabarini yuborib bo'lmadi: %s", player.user_id
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
    if message is not None and hasattr(message, "edit_text"):
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
            raise ValueError("Buyruq yuborgan foydalanuvchi aniqlanmadi")
        logger.info(
            "Guruhda yangi Mafiya xonasi: chat=%s user=%s",
            message.chat.id,
            user.id,
        )
        game = get_default_manager().create_game(
            chat_id=message.chat.id,
            host_id=user.id,
            host_name=user.full_name,
            host_username=user.username or "",
        )
        sent = await message.answer(
            lobby_text(game), reply_markup=lobby_keyboard(game)
        )
        game.lobby_message_id = getattr(sent, "message_id", None)
    except Exception as exc:
        logger.exception("Guruhda /mafia buyrug'ida xatolik: %s", exc)
        await message.reply(f"⚠️ Xatolik yuz berdi: {escape(str(exc))}")


@router.message(F.chat.type == "private", Command("mafia"))
async def create_mafia_game_private(message: Message) -> None:
    """/mafia — shaxsiy chatda guruhga yo'naltiradi."""
    config = get_config()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Guruhga qo'shish",
                    url=f"https://t.me/{config.bot_username}?startgroup=true",
                )
            ]
        ]
    )
    await message.answer(
        "🕵️ <b>Mafiya</b> faqat guruhda o'ynaladi.\n\n"
        "1. Botni guruhingizga qo'shing.\n"
        "2. Guruhda <code>/mafia</code> buyrug'ini yuboring.\n"
        "3. Do'stlar «Mafiyaga kirish» yoki «Qo'shilish»ni bosadi.\n"
        f"4. Kamida {MIN_PLAYERS} kishi bo'lgach xona egasi o'yinni boshlaydi.",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith(JOIN_PREFIX))
async def join_mafia_game(callback: CallbackQuery) -> None:
    """«➕ Qo'shilish» tugmasi."""
    code = _callback_code(callback.data, JOIN_PREFIX)
    if code is None:
        await callback.answer("Noto'g'ri tugma.", show_alert=True)
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

    await callback.answer("Mafiyaga qo'shildingiz!")
    await _edit_lobby(callback, lobby_text(game), lobby_keyboard(game))


@router.callback_query(F.data.startswith(START_PREFIX))
async def start_mafia_game(callback: CallbackQuery) -> None:
    """«▶️ O'yinni boshlash» — faqat xona egasi uchun."""
    code = _callback_code(callback.data, START_PREFIX)
    if code is None:
        await callback.answer("Noto'g'ri tugma.", show_alert=True)
        return

    manager = get_default_manager()
    try:
        game = manager.start_game(code, callback.from_user.id)
    except MafiaGameError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer("O'yin boshlandi!")
    await _edit_lobby(
        callback,
        "🕵️‍♂️ <b>MAFIYA O'YINI BOSHLANDI!</b>\n\n"
        f"👥 O'yinchilar: {len(game.room.players)} kishi\n"
        f"🔑 Xona kodi: <code>{game.code}</code>\n"
        "🎭 Rollaringiz shaxsiy xabar orqali yuborildi.",
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
            f"⚠️ {names} botga shaxsiy yozmagan, shuning uchun rol "
            "kartasini olmadi. Ular botga /start yuborishi kerak.",
        )


@router.callback_query(F.data.startswith(END_NIGHT_PREFIX))
async def end_mafia_night(callback: CallbackQuery) -> None:
    """«⏭ Tunni yakunlash» — xona egasi tungi harakatlarni hal qiladi."""
    code = _callback_code(callback.data, END_NIGHT_PREFIX)
    if code is None:
        await callback.answer("Noto'g'ri tugma.", show_alert=True)
        return

    manager = get_default_manager()
    try:
        game = manager.get_game(code)
        if callback.from_user.id != game.host_id:
            await callback.answer(
                "Tunni faqat xona egasi yakunlashi mumkin.",
                show_alert=True,
            )
            return
        resolve_night(game.room)
    except (MafiaGameError, MafiaError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer("Tun yakunlandi.")
    await announce_day(callback.bot, game)
