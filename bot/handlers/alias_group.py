"""Guruhda «Alias / Krokodil» o'yinini yuritish.

Oqim: ``/alias`` yoki ``/krokodil`` guruhda yangi xona ochadi, o'yinchilar
«➕ Qo'shilish» tugmasi bilan qo'shiladi, xona egasi «▶️ Boshlash»ni bosadi.
Har raundda tasodifiy tushuntiruvchi tanlanadi va unga so'z hamda uchta
taqiqlangan so'z shaxsiy xabar orqali yuboriladi.  Guruhdagi barcha matnli
xabarlar tekshiriladi: kim birinchi bo'lib to'g'ri so'zni yozsa, +10 tanga
oladi, tushuntiruvchi esa +5 tanga bilan taqdirlanadi.
"""

from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import get_config
from core.economy import get_economy
from games.alias.engine import (
    EXPLAINER_REWARD,
    GUESS_REWARD,
    MAX_PLAYERS,
    MIN_PLAYERS,
    ROUND_SECONDS,
    AliasError,
    AliasRoom,
    AliasRound,
    get_default_manager,
)

logger = logging.getLogger(__name__)

router = Router(name="alias_group")

JOIN_PREFIX = "alias_join_"
START_PREFIX = "alias_start_"
END_PREFIX = "alias_end_"

# To'g'ri javobdan keyin keyingi raundgacha kutish (soniya).
NEXT_ROUND_DELAY = 2.0

_tasks: set[asyncio.Task[None]] = set()


def _spawn(coro) -> asyncio.Task[None]:
    """Fon vazifasini yaratib, havolasini saqlaydi."""
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def _callback_code(data: str | None, prefix: str) -> str | None:
    """Callback ma'lumotidan xona kodini ajratadi."""
    if not data or not data.startswith(prefix):
        return None
    code = data[len(prefix) :].strip().upper()
    return code or None


def _callback_chat_id(callback: CallbackQuery) -> int:
    message = callback.message
    if message is None or getattr(message, "chat", None) is None:
        return 0
    return int(message.chat.id)


def _player_label(room: AliasRoom, user_id: int) -> str:
    player = room.players.get(int(user_id))
    if player is None:
        return f"ID {user_id}"
    return player.label()


def lobby_text(room: AliasRoom) -> str:
    """Lobby xabari matni."""
    players = "\n".join(
        f"{index}. {player.label()} — {player.score} ochko"
        for index, player in enumerate(room.players.values(), start=1)
    ) or "hali hech kim qo'shilmadi"
    return (
        "🐊 <b>ALIAS / KROKODIL</b>\n\n"
        "Tushuntiruvchi so'zni aytmasdan, taqiqlangan so'zlarsiz "
        "tushuntiradi. Qolganlar birinchi bo'lib topishga harakat qiladi.\n\n"
        f"👥 <b>O'yinchilar ({len(room.players)}/{MAX_PLAYERS}):</b>\n{players}\n\n"
        f"🔑 Xona kodi: <code>{room.code}</code>\n"
        f"⏱ Har raund {ROUND_SECONDS} soniya · kamida {MIN_PLAYERS} kishi kerak.\n"
        f"🏆 Topgan o'yinchiga +{GUESS_REWARD}, tushuntiruvchiga "
        f"+{EXPLAINER_REWARD} tanga."
    )


def lobby_keyboard(room: AliasRoom) -> InlineKeyboardMarkup:
    """Lobby tugmalari."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Qo'shilish", callback_data=f"{JOIN_PREFIX}{room.code}"
                ),
                InlineKeyboardButton(
                    text="▶️ Boshlash", callback_data=f"{START_PREFIX}{room.code}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🛑 O'yinni tugatish",
                    callback_data=f"{END_PREFIX}{room.code}",
                )
            ],
        ]
    )


def round_announcement(room: AliasRoom, current: AliasRound) -> str:
    """Raund boshlanganda guruhga chiqadigan xabar (so'zsiz)."""
    explainer = _player_label(room, current.explainer_id)
    return (
        "🐊 <b>ALIAS O'YINI BOSHLANDI!</b>\n"
        f"🎤 Hozir <b>{explainer}</b> so'z tushuntirmoqda!\n"
        f"⏳ Sizda {current.duration} soniya bor. So'zni birinchi bo'lib toping!"
    )


def explainer_message(room: AliasRoom, current: AliasRound) -> str:
    """Tushuntiruvchiga shaxsiy xabar."""
    forbidden = current.word.forbidden or ()
    lines = [
        "🎯 <b>Sizning so'zingiz:</b>",
        f"<b>{current.word.word}</b>",
        "",
    ]
    if forbidden:
        lines.append("🚫 <b>Taqiqlangan so'zlar:</b>")
        lines.extend(f"• {word}" for word in forbidden)
        lines.append("")
    lines.extend(
        [
            f"⏳ {current.duration} soniya. So'zni va taqiqlangan so'zlarni "
            "aytmasdan tushuntiring!",
            f"🔑 Xona: <code>{room.code}</code> · {current.number}-raund",
        ]
    )
    return "\n".join(lines)


def _award_coins(user_id: int, amount: int) -> None:
    """O'yinchiga tanga beradi (xato bo'lsa o'yin to'xtamaydi)."""
    try:
        get_economy().add_coins(int(user_id), int(amount))
    except Exception:  # iqtisod xatosi o'yinni buzmaydi
        logger.exception("Alias mukofotini berib bo'lmadi: %s", user_id)


async def _send_private_word(bot: Bot, room: AliasRoom, current: AliasRound) -> bool:
    """Tushuntiruvchiga so'zni shaxsiy xabarda yuboradi."""
    try:
        await bot.send_message(current.explainer_id, explainer_message(room, current))
        return True
    except Exception:
        logger.info(
            "Alias so'zini shaxsiy yuborib bo'lmadi: %s", current.explainer_id
        )
        return False


async def _announce_round(bot: Bot, room: AliasRoom, current: AliasRound) -> None:
    """Raundni guruhga e'lon qiladi va taymerni ishga tushiradi."""
    await bot.send_message(room.chat_id, round_announcement(room, current))
    delivered = await _send_private_word(bot, room, current)
    if not delivered:
        await bot.send_message(
            room.chat_id,
            f"⚠️ {_player_label(room, current.explainer_id)} botga shaxsiy "
            "yozmagan. So'zni olish uchun botga /start yuborishi kerak. "
            "Raund bekor qilindi, keyingi tushuntiruvchi tanlanadi.",
        )
        room.abort_round()
        _spawn(_delay_next_round(bot, room.code, current.number))
        return
    _spawn(_round_timeout(bot, room.code, current.number, current.duration))


async def _round_timeout(
    bot: Bot, code: str, round_number: int, delay: float
) -> None:
    """Taymer tugagach raundni yopadi va keyingisini boshlaydi."""
    try:
        await asyncio.sleep(max(1.0, float(delay)))
    except asyncio.CancelledError:
        return
    manager = get_default_manager()
    try:
        room = manager.get_room(code)
    except AliasError:
        return
    current = room.current_round
    if current is None or current.number != round_number or current.finished:
        return
    if not room.expire_round():
        return
    explainer = _player_label(room, current.explainer_id)
    await bot.send_message(
        room.chat_id,
        "⏳ <b>Vaqt tugadi!</b>\n"
        f"So'z: <b>{escape(current.word.word)}</b>\n"
        f"🎤 {explainer} tushuntira olmadi. Keyingi raund boshlanadi...",
    )
    _spawn(_delay_next_round(bot, code, round_number))


async def _delay_next_round(bot: Bot, code: str, round_number: int) -> None:
    """Qisqa tanaffusdan keyin keyingi raundni boshlaydi."""
    await asyncio.sleep(NEXT_ROUND_DELAY)
    manager = get_default_manager()
    try:
        room = manager.get_room(code)
    except AliasError:
        return
    current = room.current_round
    if room.status.value != "PLAYING":
        return
    if current is not None and current.number != round_number:
        return
    try:
        room = manager.next_round(code)
    except AliasError as exc:
        logger.info("Keyingi Alias raundi boshlanmadi: %s", exc)
        return
    if room.current_round is not None:
        await _announce_round(bot, room, room.current_round)


# ----------------------------------------------------------------------
# Handlerlar
# ----------------------------------------------------------------------
@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    Command("alias", "krokodil"),
)
async def create_alias_game(message: Message) -> None:
    """/alias yoki /krokodil — guruhda yangi xona ochadi."""
    try:
        user = message.from_user
        if user is None:
            raise ValueError("Buyruq yuborgan foydalanuvchi aniqlanmadi")
        manager = get_default_manager()
        existing = manager.room_by_chat(message.chat.id)
        if existing is not None:
            # Takroriy buyruq yangi xona ochmaydi: mavjud xona ko'rsatiladi.
            await message.answer(
                "⚠️ Bu guruhda Alias xonasi allaqachon ochiq. "
                "Avval uni tugating yoki qo'shiling.\n\n" + lobby_text(existing),
                reply_markup=lobby_keyboard(existing),
            )
            return
        room = manager.create_room(
            chat_id=message.chat.id,
            host_id=user.id,
            host_name=user.full_name,
            host_username=user.username or "",
        )
        sent = await message.answer(
            lobby_text(room),
            reply_markup=lobby_keyboard(room),
        )
        room.lobby_message_id = getattr(sent, "message_id", None)
    except Exception as exc:
        logger.exception("Guruhda /alias buyrug'ida xatolik: %s", exc)
        await message.reply(f"⚠️ Xatolik yuz berdi: {escape(str(exc))}")


@router.message(F.chat.type == "private", Command("alias", "krokodil"))
async def create_alias_game_private(message: Message) -> None:
    """/alias — shaxsiy chatda guruhga yo'naltiradi."""
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
        "🐊 <b>Alias / Krokodil</b> faqat guruhda o'ynaladi.\n\n"
        "1. Botni guruhingizga qo'shing.\n"
        "2. Guruhda <code>/alias</code> yoki <code>/krokodil</code> yuboring.\n"
        "3. Do'stlar «➕ Qo'shilish»ni bosadi.\n"
        f"4. Kamida {MIN_PLAYERS} kishi bo'lgach xona egasi o'yinni boshlaydi.",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith(JOIN_PREFIX))
async def join_alias_game(callback: CallbackQuery) -> None:
    """«➕ Qo'shilish» tugmasi."""
    code = _callback_code(callback.data, JOIN_PREFIX)
    if code is None:
        await callback.answer("Noto'g'ri tugma.", show_alert=True)
        return

    user = callback.from_user
    manager = get_default_manager()
    try:
        room = manager.join(code, user.id, user.full_name, user.username or "")
    except AliasError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer("Aliasga qo'shildingiz!")
    try:
        if callback.message is not None:
            await callback.message.edit_text(
                lobby_text(room), reply_markup=lobby_keyboard(room)
            )
    except Exception:
        logger.debug("Alias lobby xabarini tahrirlab bo'lmadi")


@router.callback_query(F.data.startswith(START_PREFIX))
async def start_alias_game(callback: CallbackQuery) -> None:
    """«▶️ Boshlash» — faqat xona egasi uchun."""
    code = _callback_code(callback.data, START_PREFIX)
    if code is None:
        await callback.answer("Noto'g'ri tugma.", show_alert=True)
        return

    manager = get_default_manager()
    try:
        room = manager.start_game(code, callback.from_user.id)
    except AliasError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    current = room.current_round
    if current is None:  # pragma: no cover - start_game har doim raund ochadi
        await callback.answer("Raund boshlanmadi.", show_alert=True)
        return

    await callback.answer("O'yin boshlandi!")
    try:
        if callback.message is not None:
            await callback.message.edit_text(
                "🐊 <b>ALIAS O'YINI BOSHLANDI!</b>\n"
                f"👥 O'yinchilar: {len(room.players)} kishi\n"
                f"🔑 Xona kodi: <code>{room.code}</code>\n"
                "🎤 So'z tushuntiruvchiga shaxsiy xabar bilan yuborildi.",
                reply_markup=None,
            )
    except Exception:
        logger.debug("Alias lobby xabarini tahrirlab bo'lmadi")

    await _announce_round(callback.bot, room, current)


@router.callback_query(F.data.startswith(END_PREFIX))
async def end_alias_game(callback: CallbackQuery) -> None:
    """«🛑 O'yinni tugatish» — xona egasi o'yinni yakunlaydi."""
    code = _callback_code(callback.data, END_PREFIX)
    if code is None:
        await callback.answer("Noto'g'ri tugma.", show_alert=True)
        return

    manager = get_default_manager()
    try:
        room = manager.get_room(code)
    except AliasError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if callback.from_user.id != room.host_id:
        await callback.answer(
            "O'yinni faqat xona egasi tugatadi.", show_alert=True
        )
        return

    room.finish()
    await callback.answer("O'yin tugatildi.")
    leaders = room.leaderboard()[:3]
    table = "\n".join(
        f"{index}. {player.label()} — {player.score} ochko"
        for index, player in enumerate(leaders, start=1)
    ) or "hech kim ochko to'plamadi"
    await callback.bot.send_message(
        room.chat_id,
        "🏁 <b>Alias o'yini tugadi!</b>\n\n"
        f"🏆 <b>Eng yaxshilar:</b>\n{table}",
    )
    manager.drop(code)


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text,
    ~F.text.startswith("/"),
)
async def alias_guess_watcher(message: Message) -> None:
    """Guruhdagi javoblarni tekshiradi va birinchi to'g'ri javobni e'lon qiladi.

    Filtr buyruqlarni chiqarib tashlaydi, shuning uchun ``/bunker``, ``/spy``
    kabi buyruqlar keyingi routerlar tomonidan ushlanadi.
    """
    if message.from_user is None or not message.text:
        return
    manager = get_default_manager()
    outcome = manager.submit_guess(
        message.chat.id, message.from_user.id, message.text
    )
    if outcome is None:
        return
    room, result = outcome
    if not result.correct or result.winner_id is None:
        return

    winner_label = _player_label(room, result.winner_id)
    explainer_label = _player_label(room, result.explainer_id or 0)
    _award_coins(result.winner_id, GUESS_REWARD)
    if result.explainer_id:
        _award_coins(result.explainer_id, EXPLAINER_REWARD)

    await message.answer(
        "🎉 <b>To'g'ri javob!</b>\n"
        f"{winner_label} so'zni topdi: <b>{escape(result.word)}</b> "
        f"(+{GUESS_REWARD} tanga)!\n"
        f"🎤 {explainer_label}ga +{EXPLAINER_REWARD} tanga.\n\n"
        "Keyingi raund boshlanadi..."
    )
    current = room.current_round
    if current is not None:
        _spawn(_delay_next_round(message.bot, room.code, current.number))


__all__ = [
    "router",
    "create_alias_game",
    "create_alias_game_private",
    "join_alias_game",
    "start_alias_game",
    "end_alias_game",
    "alias_guess_watcher",
    "lobby_text",
    "lobby_keyboard",
    "round_announcement",
    "explainer_message",
]
