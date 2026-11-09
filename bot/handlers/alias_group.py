"""Guruhda «Alias / Krokodil» o'yinini yuritish.

Oqim: ``/alias`` yoki ``/krokodil`` guruhda yangi xona ochadi, o'yinchilar
«➕ Qöşiliş» tugmasi bilan qo'shiladi, xona egasi «▶️ Boşlaş»ni bosadi.
Har raundda eng kam tushuntirgan o'yinchi tanlanadi va unga so'z hamda uchta
taqiqlangan so'z shaxsiy xabar orqali yuboriladi.  Guruhdagi barcha matnli
xabarlar tekshiriladi: kim birinchi bo'lib to'g'ri so'zni yozsa, +10 tanga
oladi, tushuntiruvchi esa +5 tanga bilan taqdirlanadi.

O'yin cheksiz aylanmaydi: har bir ishtirokchi 2 martadan tushuntiradi
(masalan, 3 kishi — jami 6 raund), so'ng g'olib e'lon qilinadi va +25 tanga
beriladi.  Ketma-ket 2 raundda hech kim so'zni topmasa, xona avtomatik
yopiladi.  Xona egasi yoki guruh administratori /stop, /stopalias yoki
/cancel bilan o'yinni darhol to'xtatadi.
"""

from __future__ import annotations

import asyncio
import base64
import json
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

from aiogram.types import WebAppInfo

from bot.config import get_config
from core.i18n import resolve_language, t
from bot.keyboards.main_menu import mini_app_url_for
from bot.handlers.admin import is_admin
from core.economy import get_economy
from games.alias.engine import (
    EXPLAINER_REWARD,
    GUESS_REWARD,
    INACTIVE_ROUNDS_LIMIT,
    MAX_PLAYERS,
    MIN_PLAYERS,
    ROUNDS_PER_PLAYER,
    ROUND_SECONDS,
    WINNER_REWARD,
    AliasError,
    AliasRoom,
    AliasRound,
    AliasStatus,
    get_default_manager,
)

logger = logging.getLogger(__name__)

router = Router(name="alias_group")

JOIN_PREFIX = "alias_join_"
START_PREFIX = "alias_start_"
END_PREFIX = "alias_end_"

# To'g'ri javobdan keyin keyingi raundgacha kutish (soniya).
NEXT_ROUND_DELAY = 2.0

INACTIVE_TEXT = "💤 Guruhda faollik bölmagani sababli Alias töxtatildi."

GROUP_TYPES = {"group", "supergroup"}

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
        f"{index}. {player.label()} — {player.score} oçko"
        for index, player in enumerate(room.players.values(), start=1)
    ) or "hali heç kim qöşilmadi"
    return (
        "🐊 <b>ALIAS / KROKODIL</b>\n\n"
        "Tuşuntiruvçi sözni aytmasdan, taqiqlangan sözlarsiz "
        "tuşuntiradi. Qolganlar birinçi bölib topişga harakat qiladi.\n\n"
        f"👥 <b>Öyinçilar ({len(room.players)}/{MAX_PLAYERS}):</b>\n{players}\n\n"
        f"🔑 Xona kodi: <code>{room.code}</code>\n"
        f"⏱ Har raund {ROUND_SECONDS} soniya · kamida {MIN_PLAYERS} kişi kerak.\n"
        f"💤 {ROUND_SECONDS} soniya faollik bölmasa navbat avtomatik keyingi öyinçiga ötadi.\n"
        "💬 Sözni çatda töğri yozgan öyinçi darhol topadi va oçko oladi.\n"
        f"🔁 Har bir iştirokçi {ROUNDS_PER_PLAYER} martadan tuşuntiradi "
        f"(jami {room.total_rounds} raund).\n"
        f"🏆 Topgan öyinçiga +{GUESS_REWARD}, tuşuntiruvçiga "
        f"+{EXPLAINER_REWARD} tanga, umumiy ğolibga +{WINNER_REWARD} tanga."
    )


def lobby_keyboard(room: AliasRoom) -> InlineKeyboardMarkup:
    """Lobby tugmalari."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Qöşiliş", callback_data=f"{JOIN_PREFIX}{room.code}"
                ),
                InlineKeyboardButton(
                    text="▶️ Boşlaş", callback_data=f"{START_PREFIX}{room.code}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🛑 Öyinni tugatiş",
                    callback_data=f"{END_PREFIX}{room.code}",
                )
            ],
        ]
    )


def round_announcement(room: AliasRoom, current: AliasRound) -> str:
    """Raund boshlanganda guruhga chiqadigan xabar (so'zsiz)."""
    explainer = _player_label(room, current.explainer_id)
    return (
        "🐊 <b>ALIAS ÖYINI BOŞLANDI!</b>\n"
        f"🎤 Hozir <b>{explainer}</b> söz tuşuntirmoqda! "
        f"({current.number}/{room.total_rounds}-raund)\n"
        f"⏳ Sizda {current.duration} soniya bor. Sözni birinçi bölib toping!"
    )


def explainer_message(room: AliasRoom, current: AliasRound) -> str:
    """Tushuntiruvchiga shaxsiy xabar."""
    forbidden = current.word.forbidden or ()
    lines = [
        "🎯 <b>Sizning sözingiz:</b>",
        f"<b>{current.word.word}</b>",
        "",
    ]
    if forbidden:
        lines.append("🚫 <b>Taqiqlangan sözlar:</b>")
        lines.extend(f"• {word}" for word in forbidden)
        lines.append("")
    lines.extend(
        [
            f"⏳ {current.duration} soniya. Sözni va taqiqlangan sözlarni "
            "aytmasdan tuşuntiring!",
            f"🔑 Xona: <code>{room.code}</code> · "
            f"{current.number}/{room.total_rounds}-raund",
        ]
    )
    return "\n".join(lines)



def _alias_result_payload(room: AliasRoom) -> dict:
    """Mini App natija kartasi uchun qisqa JSON payload."""
    leaders = room.leaderboard()[:8]
    return {
        "code": room.code,
        "reason": getattr(room, "stop_reason", "") or "completed",
        "rounds": int(getattr(room, "total_rounds", 0) or 0),
        "winners": [int(player.user_id) for player in room.winners()],
        "winner_names": [player.label() for player in room.winners()],
        "players": [
            {
                "id": int(player.user_id),
                "name": player.label(),
                "score": int(player.score),
            }
            for player in leaders
        ],
    }


def alias_result_token(room: AliasRoom) -> str:
    """Natijani URL-safe base64 tokeniga aylantiradi."""
    raw = json.dumps(
        _alias_result_payload(room), ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def results_keyboard(room: AliasRoom) -> InlineKeyboardMarkup | None:
    """Natija va MVPni Mini App'da ochiş tugmasi."""
    try:
        base = (get_config().mini_app_url or "").strip()
    except Exception:  # konfiguratsiya yo'q bo'lsa tugma körsatilmaydi
        return None
    if not base.startswith("https://"):
        return None
    url = mini_app_url_for(base)
    separator = "&" if "?" in url else "?"
    url = f"{url}{separator}alias_result={alias_result_token(room)}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Natija va MVPni köriş",
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )


def results_text(room: AliasRoom, *, reason: str = "completed") -> str:
    """O'yin yakunlanganda chiqadigan natijalar jadvali."""
    leaders = room.leaderboard()[:3]
    table = "\n".join(
        f"{index}. {player.label()} — {player.score} oçko"
        for index, player in enumerate(leaders, start=1)
    ) or "heç kim oçko töplamadi"
    if reason == "stopped":
        title = "🛑 <b>Alias töxtatildi!</b>"
    else:
        title = "🏁 <b>Alias öyini tugadi!</b>"
    winners = room.winners() if reason == "completed" else []
    if winners:
        names = ", ".join(player.label() for player in winners)
        headline = f"🏆 <b>Ğolib: {names}</b> — +{WINNER_REWARD} tanga!"
    elif reason == "completed":
        headline = "🏆 Bu öyinda ğolib aniqlanmadi."
    else:
        headline = "🏆 Öyin yakunlandi."
    mvp = leaders[0] if leaders else None
    analysis = []
    if mvp is not None:
        analysis.append(f"👑 <b>Öyin MVPsi: {mvp.label()}</b> — {mvp.score} oçko")
    analysis.append(f"🎯 Öynalgan raundlar: <b>{room.total_rounds}</b>")
    if room.players:
        analysis.append(f"👥 Qatnaşçilar: <b>{len(room.players)}</b>")
    analysis_text = "\n".join(analysis)
    return (
        f"{title}\n\n🏆 <b>Eng yaxşilar:</b>\n{table}\n\n"
        f"{headline}\n\n📊 <b>Tahlil:</b>\n{analysis_text}"
    )


def _award_coins(user_id: int, amount: int) -> None:
    """O'yinchiga tanga beradi (xato bo'lsa o'yin to'xtamaydi)."""
    try:
        get_economy().add_coins(int(user_id), int(amount))
    except Exception:  # iqtisod xatosi o'yinni buzmaydi
        logger.exception("Alias mukofotini berib bölmadi: %s", user_id)


async def _is_group_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Guruh administratori yoki bot adminimi?"""
    if is_admin(user_id):
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        logger.info("Guruh a'zosini tekşirib bölmadi: %s", user_id)
        return False
    status = getattr(member, "status", "")
    value = getattr(status, "value", status)
    return str(value).lower() in {"administrator", "creator"}


async def _stop_game(bot: Bot, room: AliasRoom, *, reason: str) -> None:
    """O'yinni yakunlaydi, natijani e'lon qiladi va xonani yopadi."""
    manager = get_default_manager()
    if room.status is AliasStatus.FINISHED:
        return
    room.finish(reason)
    manager.save(room)
    try:
        if reason == "inactive":
            await bot.send_message(room.chat_id, INACTIVE_TEXT)
            return
        if reason == "completed":
            winners = room.winners()
            for winner in winners:
                _award_coins(winner.user_id, WINNER_REWARD)
            try:
                get_economy().record_finished_game(
                    room.code,
                    [player.user_id for player in room.players.values()],
                    [winner.user_id for winner in winners],
                    game="alias",
                )
            except Exception:
                logger.exception("Alias natijasini yozib bölmadi: %s", room.code)
        keyboard = results_keyboard(room)
        if keyboard is None:
            await bot.send_message(room.chat_id, results_text(room, reason=reason))
        else:
            await bot.send_message(
                room.chat_id,
                results_text(room, reason=reason),
                reply_markup=keyboard,
            )
    finally:
        manager.drop(room.code)


def has_active_room(chat_id: int) -> bool:
    """Guruhda ochiq Alias xonasi (lobby yoki o'yin) bormi?"""
    return get_default_manager().room_by_chat(chat_id) is not None


async def stop_alias_for_chat(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Faol Alias o'yinini darhol to'xtatadi (ega yoki guruh admini).

    Returns:
        ``True`` — o'yin to'xtatildi, ``False`` — ruxsat yo'q yoki xona yo'q.
    """
    room = get_default_manager().room_by_chat(chat_id)
    if room is None:
        return False
    if int(room.host_id) != int(user_id) and not await _is_group_admin(
        bot, chat_id, user_id
    ):
        await bot.send_message(
            chat_id,
            "⛔ Öyinni faqat xona egasi yoki guruh administratori töxtatadi.\n"
            "Töxtatiş uçun /stop, /stopalias yoki /cancel yuboring.",
        )
        return False
    await _stop_game(bot, room, reason="stopped")
    return True


async def _send_private_word(bot: Bot, room: AliasRoom, current: AliasRound) -> bool:
    """Tushuntiruvchiga so'zni shaxsiy xabarda yuboradi."""
    try:
        await bot.send_message(current.explainer_id, explainer_message(room, current))
        return True
    except Exception:
        logger.info(
            "Alias sözini şaxsiy yuborib bölmadi: %s", current.explainer_id
        )
        return False


async def _announce_round(bot: Bot, room: AliasRoom, current: AliasRound) -> None:
    """Raundni guruhga e'lon qiladi va taymerni ishga tushiradi."""
    await bot.send_message(room.chat_id, round_announcement(room, current))
    delivered = await _send_private_word(bot, room, current)
    if not delivered:
        await bot.send_message(
            room.chat_id,
            f"⚠️ {_player_label(room, current.explainer_id)} botga şaxsiy "
            "yozmagan. Sözni oliş uçun botga /start yuborişi kerak. "
            "Raund bekor qilindi, keyingi tuşuntiruvçi tanlanadi.",
        )
        room.abort_round()
        get_default_manager().save(room)
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
    manager.save(room)
    explainer = _player_label(room, current.explainer_id)
    await bot.send_message(
        room.chat_id,
        "⏳ <b>Vaqt tugadi!</b>\n"
        f"Söz: <b>{escape(current.word.word)}</b>\n"
        f"🎤 {explainer} tuşuntira olmadi.",
    )
    _spawn(_delay_next_round(bot, code, round_number))


async def _delay_next_round(bot: Bot, code: str, round_number: int) -> None:
    """Tanaffusdan keyin keyingi raundni boshlaydi yoki o'yinni yakunlaydi."""
    await asyncio.sleep(NEXT_ROUND_DELAY)
    manager = get_default_manager()
    try:
        room = manager.get_room(code)
    except AliasError:
        return
    current = room.current_round
    if room.status is not AliasStatus.PLAYING:
        return
    if current is not None and current.number != round_number:
        return
    if room.should_stop_for_inactivity():
        await _stop_game(bot, room, reason="inactive")
        return
    if room.is_complete:
        await _stop_game(bot, room, reason="completed")
        return
    try:
        room = manager.next_round(code)
    except AliasError as exc:
        logger.info("Keyingi Alias raundi boşlanmadi: %s", exc)
        return
    if room.current_round is not None:
        await _announce_round(bot, room, room.current_round)


# ----------------------------------------------------------------------
# Handlerlar
# ----------------------------------------------------------------------
@router.message(
    F.chat.type.in_(GROUP_TYPES),
    Command("alias", "krokodil"),
)
async def create_alias_game(message: Message) -> None:
    """/alias yoki /krokodil — guruhda yangi xona ochadi."""
    try:
        user = message.from_user
        if user is None:
            raise ValueError("Buyruq yuborgan foydalanuvçi aniqlanmadi")
        manager = get_default_manager()
        existing = manager.room_by_chat(message.chat.id)
        if existing is not None:
            # Takroriy buyruq yangi xona ochmaydi: mavjud xona ko'rsatiladi.
            await message.answer(
                "⚠️ Bu guruhda Alias xonasi allaqaçon oçiq. "
                "Avval uni tugating yoki qöşiling.\n\n" + lobby_text(existing),
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
        manager.save(room)
    except Exception as exc:
        logger.exception("Guruhda /alias buyruğida xatolik: %s", exc)
        await message.reply(f"⚠️ Xatolik yuz berdi: {escape(str(exc))}")


@router.message(F.chat.type.in_(GROUP_TYPES), Command("stop", "stopalias"))
async def stop_alias_command(message: Message) -> None:
    """/stop yoki /stopalias — ega yoki guruh admini o'yinni to'xtatadi."""
    user = message.from_user
    if user is None:
        return
    if not has_active_room(message.chat.id):
        await message.answer(
            "🐊 Guruhda faol Alias öyini yöq. Boşlaş uçun /alias yuboring."
        )
        return
    await stop_alias_for_chat(message.bot, message.chat.id, user.id)


@router.message(F.chat.type == "private", Command("alias", "krokodil"))
async def create_alias_game_private(message: Message) -> None:
    """/alias — shaxsiy chatda guruhga yo'naltiradi."""
    config = get_config()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Guruhga qöşiş",
                    url=f"https://t.me/{config.bot_username}?startgroup=true",
                )
            ]
        ]
    )
    await message.answer(
        "🐊 <b>Alias / Krokodil</b> faqat guruhda öynaladi.\n\n"
        "1. Botni guruhingizga qöşing.\n"
        "2. Guruhda <code>/alias</code> yoki <code>/krokodil</code> yuboring.\n"
        "3. Döstlar «➕ Qöşiliş»ni bosadi.\n"
        f"4. Kamida {MIN_PLAYERS} kişi bölgaç xona egasi öyinni boşlaydi.",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith(JOIN_PREFIX))
async def join_alias_game(callback: CallbackQuery) -> None:
    """«➕ Qo'shilish» tugmasi."""
    code = _callback_code(callback.data, JOIN_PREFIX)
    if code is None:
        await callback.answer("Notöğri tugma.", show_alert=True)
        return

    user = callback.from_user
    manager = get_default_manager()
    try:
        room = manager.join(code, user.id, user.full_name, user.username or "")
    except AliasError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    language = resolve_language(user.id, getattr(user, "language_code", None))
    await callback.answer(t(language, "room_joined", name=escape(user.full_name)))
    try:
        if callback.message is not None:
            await callback.message.edit_text(
                lobby_text(room), reply_markup=lobby_keyboard(room)
            )
    except Exception:
        logger.debug("Alias lobby xabarini tahrirlab bölmadi")


@router.callback_query(F.data.startswith(START_PREFIX))
async def start_alias_game(callback: CallbackQuery) -> None:
    """«▶️ Boshlash» — faqat xona egasi uchun."""
    code = _callback_code(callback.data, START_PREFIX)
    if code is None:
        await callback.answer("Notöğri tugma.", show_alert=True)
        return

    manager = get_default_manager()
    try:
        room = manager.start_game(code, callback.from_user.id)
    except AliasError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    current = room.current_round
    if current is None:  # pragma: no cover - start_game har doim raund ochadi
        await callback.answer("Raund boşlanmadi.", show_alert=True)
        return

    language = resolve_language(
        callback.from_user.id, getattr(callback.from_user, "language_code", None)
    )
    await callback.answer(t(language, "room_started", game="Alias"))
    try:
        if callback.message is not None:
            await callback.message.edit_text(
                "🐊 <b>ALIAS ÖYINI BOŞLANDI!</b>\n"
                f"👥 Öyinçilar: {len(room.players)} kişi\n"
                f"🔁 Jami raundlar: {room.total_rounds} ta\n"
                f"🔑 Xona kodi: <code>{room.code}</code>\n"
                "🎤 Söz tuşuntiruvçiga şaxsiy xabar bilan yuborildi.",
                reply_markup=None,
            )
    except Exception:
        logger.debug("Alias lobby xabarini tahrirlab bölmadi")

    await _announce_round(callback.bot, room, current)


@router.callback_query(F.data.startswith(END_PREFIX))
async def end_alias_game(callback: CallbackQuery) -> None:
    """«🛑 O'yinni tugatish» — ega yoki guruh admini o'yinni yakunlaydi."""
    code = _callback_code(callback.data, END_PREFIX)
    if code is None:
        await callback.answer("Notöğri tugma.", show_alert=True)
        return

    manager = get_default_manager()
    try:
        room = manager.get_room(code)
    except AliasError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    chat_id = _callback_chat_id(callback) or room.chat_id
    user_id = callback.from_user.id
    if user_id != room.host_id and not await _is_group_admin(
        callback.bot, chat_id, user_id
    ):
        await callback.answer(
            "Öyinni faqat xona egasi yoki guruh administratori tugatadi.",
            show_alert=True,
        )
        return

    await callback.answer("Öyin töxtatildi.")
    await _stop_game(callback.bot, room, reason="stopped")


@router.message(
    F.chat.type.in_(GROUP_TYPES),
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

    tail = (
        "Keyingi raund boşlanadi..."
        if room.rounds_left > 0
        else "Barça raundlar öynaldi, natijalar e'lon qilinadi..."
    )
    await message.answer(
        "🎉 <b>Töğri javob!</b>\n"
        f"{winner_label} sözni topdi: <b>{escape(result.word)}</b> "
        f"(+{GUESS_REWARD} tanga)!\n"
        f"🎤 {explainer_label}ga +{EXPLAINER_REWARD} tanga.\n\n"
        f"{tail}"
    )
    current = room.current_round
    if current is not None:
        _spawn(_delay_next_round(message.bot, room.code, current.number))


__all__ = [
    "router",
    "create_alias_game",
    "create_alias_game_private",
    "stop_alias_command",
    "join_alias_game",
    "start_alias_game",
    "end_alias_game",
    "alias_guess_watcher",
    "has_active_room",
    "stop_alias_for_chat",
    "lobby_text",
    "lobby_keyboard",
    "round_announcement",
    "explainer_message",
    "results_text",
]
