"""🏆 Haftalik turnirlar: afisha, qatnashish va eslatmalar.

Bosh menyudagi «🏆 Turnirlar» tugmasi va ``/tournaments`` buyrug'i yaqin
kelayotgan turnirlar afishasini ko'rsatadi.  Qatnaşiş uchun 50 tanga
yoki ``tournament_ticket`` çiptasi sarflanadi.  Boshlanişga 15 daqiqa
qolganda yozilgan o'yinchilarga shaxsiy eslatma (va boshlanganda xona
havolasi) yuboriladi.  Ro'yxatdan o'tish faqat yozuvdir: xona ochilmaydi,
Mini App ``web_app`` ga yo'naltirilmaydi.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from bot.config import get_config
from bot.keyboards.main_menu import mini_app_url_for
from core.economy import format_price
from core.tournaments import (
    ENTRY_FEE,
    OPEN,
    REMINDER_MINUTES,
    AlreadyJoinedError,
    Tournament,
    TournamentError,
    TournamentStore,
    countdown_text,
    format_local,
    get_tournament_store,
    status_label,
)

logger = logging.getLogger(__name__)

router = Router(name="tournaments")

TOURNAMENTS_BUTTON = "🏆 Turnirlar"
OPEN_CALLBACK = "tournaments_open"
REFRESH_CALLBACK = "tour_update"
# Yangi tugmalar; eski ``tour_join_`` xabarlari ham ishlashda davom etadi.
JOIN_CALLBACK_PREFIX = "join_tournament_"
LEAVE_CALLBACK_PREFIX = "leave_tournament_"
JOIN_PREFIX = "tour_join_"
NOOP_CALLBACK = "tournament_noop"
BACK_CALLBACK = "catalog_back"

REMINDER_INTERVAL_SECONDS = 60


def _ticket_count(user_id: int | None, store: TournamentStore) -> int:
    if user_id is None:
        return 0
    try:
        return store.shop.entry(int(user_id), "tournament_ticket").quantity
    except Exception:
        logger.exception("Turnir çiptasini öqib bölmadi: %s", user_id)
        return 0


def poster_text(user_id: int | None = None, store: TournamentStore | None = None) -> str:
    """Turnirlar afishasi matni (Supabase holatidan)."""
    storehouse = store or get_tournament_store()
    tournaments = storehouse.visible()
    lines = ["🏆 <b>Revilend Haftalik Turnirlar</b>", ""]
    if not tournaments:
        lines.append(
            "Hozirça röyxatga oliş oçiq turnir yöq. Tez orada yangi "
            "çempionat e'lon qilinadi!"
        )
        return "\n".join(lines)

    lines.append(
        "Haftalik çempionatlarda kuçingizni sinang — sovrin fondi va "
        "şön-şöhrat sizni kutmoqda."
    )
    lines.append("")
    for tournament in tournaments:
        joined = (
            user_id is not None
            and storehouse.joined(tournament.id, int(user_id))
        )
        lines.append(f"🏆 <b>{escape(tournament.title, quote=False)}!</b>")
        lines.append(f"🎮 Öyin: <b>{escape(tournament.game_title, quote=False)}</b>")
        lines.append(
            f"💰 Sovrin fondi: <b>{format_price(tournament.prize_pool)} tanga</b>"
        )
        lines.append(
            f"👥 Örinlar: <b>{storehouse.participant_count(tournament.id)}"
            f" / {tournament.max_participants} kişi</b>"
        )
        lines.append(
            f"⏰ Boşlaniş vaqti: <b>{format_local(tournament.starts_at) or '—'}</b>"
            f" ({countdown_text(tournament.starts_at)})"
        )
        lines.append(
            f"📌 Holati: <b>{escape(status_label(tournament.status), quote=False)}</b>"
        )
        if joined:
            lines.append("✅ Siz bu turnirga röyxatdan ötgansiz.")
        lines.append("")

    tickets = _ticket_count(user_id, storehouse)
    lines.append(
        f"🎟 Qatnaşiş narxi: <b>{ENTRY_FEE} tanga</b> yoki turnir çiptasi."
    )
    if tickets:
        lines.append(f"🎟 Sizda <b>{tickets}</b> ta turnir çiptasi bor.")
    lines.append("")
    if any(item.status == OPEN for item in tournaments):
        lines.append("Örinlar çeklangan — hoziroq yoziling!")
    else:
        lines.append("Turnir boşlanişini kuting — barça öyinçilarga xabar beriladi.")
    return "\n".join(lines)


def _mini_app_url(user_id: int | None, username: str = "", full_name: str = "") -> str:
    """Mini App havolasini foydalanuvchi ma'lumotlari bilan qaytaradi."""
    try:
        config = get_config()
        return mini_app_url_for(
            config.mini_app_url or "",
            user_id=user_id,
            username=username,
            full_name=full_name,
        )
    except Exception:
        logger.debug("Mini App havolasini olib bölmadi", exc_info=True)
        return ""


def poster_keyboard(
    user_id: int | None = None,
    store: TournamentStore | None = None,
    *,
    username: str = "",
    full_name: str = "",
) -> InlineKeyboardMarkup:
    """Har bir turnir uchun holatga mos tugmalar."""
    storehouse = store or get_tournament_store()
    rows: list[list[InlineKeyboardButton]] = []
    for tournament in storehouse.visible():
        joined = (
            user_id is not None
            and storehouse.joined(tournament.id, int(user_id))
        )
        if tournament.status != OPEN:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="▶️ Turnir boşlangan",
                        callback_data=NOOP_CALLBACK,
                    )
                ]
            )
        elif joined:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="✅ Siz röyxatdan ötgansiz",
                        callback_data=NOOP_CALLBACK,
                    )
                ]
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        text="❌ Röyxatdan çiqiş",
                        callback_data=f"{LEAVE_CALLBACK_PREFIX}{tournament.id}",
                    )
                ]
            )
        elif storehouse.participant_count(tournament.id) >= tournament.max_players:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="⛔ Joylar töldi",
                        callback_data=NOOP_CALLBACK,
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="✍️ Turnirga röyxatdan ötiş",
                        callback_data=f"{JOIN_CALLBACK_PREFIX}{tournament.id}",
                    )
                ]
            )

    url = _mini_app_url(user_id, username, full_name)
    if url:
        if url.startswith("https://"):
            rows.append(
                [
                    InlineKeyboardButton(
                        text="🌐 Mini App'da köriş",
                        web_app=WebAppInfo(url=url),
                    )
                ]
            )
        else:
            rows.append(
                [InlineKeyboardButton(text="🌐 Mini App'da köriş", url=url)]
            )
    rows.append(
        [InlineKeyboardButton(text="🔄 Yangilaş", callback_data=REFRESH_CALLBACK)]
    )
    rows.append(
        [InlineKeyboardButton(text="⬅️ Öyinlar röyxati", callback_data=BACK_CALLBACK)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_tournaments(message: Message) -> None:
    """Turnirlar afishasini yuboradi."""
    user = message.from_user
    await message.answer(
        poster_text(user.id if user is not None else None),
        reply_markup=poster_keyboard(
            user.id if user is not None else None,
            username=(user.username or "") if user is not None else "",
            full_name=(user.full_name or "") if user is not None else "",
        ),
    )


async def _show(
    callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup
) -> None:
    """Callback xabarini yangilaydi (imkoni bo'lmasa yangisini yuboradi)."""
    message = callback.message
    if isinstance(message, Message):
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except TelegramAPIError:
            pass
    await callback.bot.send_message(
        callback.from_user.id, text, reply_markup=markup
    )


async def _refresh(callback: CallbackQuery) -> None:
    user = callback.from_user
    await _show(
        callback,
        poster_text(user.id),
        poster_keyboard(
            user.id,
            username=user.username or "",
            full_name=user.full_name or "",
        ),
    )



def parse_start(value: str) -> datetime:
    """Boşlaniş vaqtini ``2h``, ``3d`` yoki ISO formatidan o'qiydi."""
    text = (value or "").strip().lower()
    now = datetime.now(timezone.utc)
    if text.endswith("h") and text[:-1].isdigit():
        return now + timedelta(hours=int(text[:-1]))
    if text.endswith("d") and text[:-1].isdigit():
        return now + timedelta(days=int(text[:-1]))
    raw = (value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


@router.message(Command("new_tournament"))
async def new_tournament_command(message: Message, command: CommandObject) -> None:
    """``/new_tournament <oyin> <narx> <sovrin> <vaqt>`` — yangi turnir oçadi."""
    from bot.handlers.admin import is_admin

    user = message.from_user
    if user is None or not is_admin(user.id):
        await message.answer("⛔ Bu buyruq faqat administrator uçun.")
        return
    parts = (command.args or "").split()
    if len(parts) != 4:
        await message.answer(
            "Format: <code>/new_tournament bunker 50 1000 2d</code>\n"
            "Öyin: bunker, mafiya, josus, alias, mixed. Vaqt: <code>2h</code>, "
            "<code>3d</code> yoki ISO sana."
        )
        return
    game, fee_raw, prize_raw, start_raw = parts
    try:
        fee = int(fee_raw)
        prize = int(prize_raw)
        starts_at = parse_start(start_raw)
    except (ValueError, TypeError):
        await message.answer("⚠️ Narx, sovrin yoki vaqt notöğri kiritildi.")
        return
    try:
        tournament = get_tournament_store().create(
            game,
            starts_at,
            entry_fee=fee,
            prize_pool=prize,
            created_by=user.id,
        )
    except TournamentError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    await message.answer(
        "✅ <b>Yangi turnir yaratildi!</b>\n\n"
        f"🔥 {tournament.title}\n"
        f"🎮 Öyin: {tournament.game_title}\n"
        f"💰 Sovrin: {format_price(tournament.prize_pool)} tanga\n"
        f"🎟 Qatnaşiş: {format_price(tournament.entry_fee)} tanga\n"
        f"🕒 Boşlaniş: {format_local(tournament.starts_at)}"
    )


@router.message(Command("tournaments"))
@router.message(Command("turnir"))
@router.message(F.text == TOURNAMENTS_BUTTON)
async def tournaments_command(message: Message) -> None:
    """/tournaments — haftalik turnirlar afishasi."""
    await show_tournaments(message)


@router.callback_query(F.data == OPEN_CALLBACK)
async def tournaments_open(callback: CallbackQuery) -> None:
    """Öyinlar vitrinasidan turnirlarga ötiş."""
    await callback.answer()
    await _refresh(callback)


@router.callback_query(F.data == REFRESH_CALLBACK)
async def tournaments_refresh(callback: CallbackQuery) -> None:
    """Afishani yangilaydi."""
    await callback.answer("Yangilandi")
    await _refresh(callback)


def _join_tournament_id(data: str) -> str:
    """Yangi va eski qatnashish callback'idan turnir id'sini oladi."""
    for prefix in (JOIN_CALLBACK_PREFIX, JOIN_PREFIX):
        if data.startswith(prefix):
            return data[len(prefix) :]
    return ""


def join_success_text(tournament: Tournament, user_id: int | None = None) -> str:
    """Ro'yxatdan o'tish tasdiq matni: boshlanish vaqti va 15 daqiqa izohi.

    Bu xabar ``tournament_participants`` ga yozilganidan keyin ko'rsatiladi;
    o'yin xonasi hali yaratilmagan bo'ladi.
    """
    starts = escape(format_local(tournament.starts_at) or "—", quote=False)
    return (
        "✅ <b>Muvaffaqiyatli röyxatdan ötdingiz!</b>\n\n"
        f"🏆 Turnir: <b>{escape(tournament.title, quote=False)}</b>\n"
        f"🕒 Boşlaniş: <b>{starts}</b>\n\n"
        "Boşlanişidan 15 daqiqa oldin bot sizga xona havolasini yuboradi."
    )


@router.callback_query(F.data.startswith(JOIN_CALLBACK_PREFIX))
@router.callback_query(F.data.startswith(JOIN_PREFIX))
async def tournaments_join(callback: CallbackQuery) -> None:
    """Faqat ro'yxatdan o'tish: o'yin xonasi ochilmaydi, Mini App ochilmaydi.

    Oddiy Telegram callback orqali 50 tanga (yoki turnir chiptasi) yechiladi
    va ``tournament_participants`` ga ``REGISTERED`` yozuvi qo'shiladi.
    O'yin xonasi faqat turnir boshlanganda (yoki admin start bosganda)
    yaratilib, havolasi qatnashchilarga shaxsan yuboriladi.
    """
    tournament_id = _join_tournament_id(callback.data or "")
    store = get_tournament_store()
    try:
        result = store.join(
            callback.from_user.id,
            tournament_id,
            callback.from_user.username or "",
            callback.from_user.full_name or "",
        )
    except AlreadyJoinedError:
        # Qayta bosish pulni qayta yechmaydi: holat allaqachon yozilgan.
        tournament = store.get(tournament_id)
        if tournament is None:
            await callback.answer("Turnir topilmadi.", show_alert=True)
            return
        await callback.answer("✅ Siz allaqaçon röyxatdan ötgansiz!")
        await _show(
            callback,
            join_success_text(tournament) + "\n\n" + poster_text(callback.from_user.id, store),
            poster_keyboard(
                callback.from_user.id,
                store,
                username=callback.from_user.username or "",
                full_name=callback.from_user.full_name or "",
            ),
        )
        return
    except TournamentError as exc:
        await callback.answer(f"⚠️ {exc}", show_alert=True)
        return
    await callback.answer("✅ Röyxatdan ötdingiz!")
    await _show(
        callback,
        join_success_text(result.tournament) + "\n\n" + poster_text(callback.from_user.id, store),
        poster_keyboard(
            callback.from_user.id,
            store,
            username=callback.from_user.username or "",
            full_name=callback.from_user.full_name or "",
        ),
    )


@router.callback_query(F.data.startswith(LEAVE_CALLBACK_PREFIX))
async def tournaments_leave(callback: CallbackQuery) -> None:
    """Foydalanuvchini turnir röyxatidan chiqaradi."""
    tournament_id = (callback.data or "")[len(LEAVE_CALLBACK_PREFIX) :]
    try:
        get_tournament_store().leave(callback.from_user.id, tournament_id)
    except TournamentError as exc:
        await callback.answer(f"⚠️ {exc}", show_alert=True)
        return
    await callback.answer(
        "❌ Siz turnir röyxatidan çiqdingiz.", show_alert=True
    )
    await _refresh(callback)


@router.callback_query(F.data == NOOP_CALLBACK)
async def tournaments_noop(callback: CallbackQuery) -> None:
    """Holat tugmalari uchun ma'lumot beradi."""
    await callback.answer("Ma'lumot yangilandi")


def room_link_text(tournament: Tournament) -> str:
    """Turnir boşlanganda qatnaşçilarga yuboriladigan xona havolasi."""
    link = escape(tournament.room_link, quote=False)
    return (
        "🏆 <b>Turnir boşlandi!</b>\n\n"
        f"🔥 <b>{escape(tournament.title, quote=False)}</b>\n"
        f"🎮 Öyin: <b>{escape(tournament.game_title, quote=False)}</b>\n"
        f"🕒 Boşlaniş: <b>{format_local(tournament.starts_at)}</b>\n"
        f"💰 Sovrin fondi: <b>{format_price(tournament.prize_pool)} tanga</b>\n\n"
        f"🔗 <b>Xona havolasi:</b> {link}\n\n"
        "Xonaga kirib, öyinni başlang. Omad! 🍀"
    )


def room_link_keyboard(tournament: Tournament) -> InlineKeyboardMarkup:
    """Xona havolasiga ötiş tugmasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚪 Xonaga kiriş", url=tournament.room_link
                )
            ]
        ]
    )


async def send_room_links(
    bot: Bot,
    store: TournamentStore | None = None,
    tournament: Tournament | None = None,
) -> int:
    """Faol turnirning barcha qatnaşçilariga xona havolasini yuboradi.

    ``tournament`` berilmasa, vaqti kelgan va havolasi hali yuborilmagan
    turnirlar tanlanadi.  Yuborilgani ``room_sent_at`` bilan belgilanadi,
    shuning uchun sikl qayta işga tushsa ham takroriy xabar ketmaydi.
    """
    storehouse = store or get_tournament_store()
    targets = [tournament] if tournament is not None else storehouse.due_room_links()
    delivered = 0
    for item in targets:
        if item is None or not item.room_link:
            continue
        keyboard = room_link_keyboard(item)
        for participant in storehouse.participants(item.id):
            try:
                await bot.send_message(
                    participant.user_id,
                    room_link_text(item),
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
                delivered += 1
            except TelegramAPIError:
                logger.info(
                    "Turnir xona havolasini yuborib bölmadi: %s",
                    participant.user_id,
                )
            except Exception:
                logger.exception(
                    "Turnir xona havolasida kutilmagan xatolik: %s",
                    participant.user_id,
                )
        storehouse.mark_room_sent(item.id)
    return delivered


def reminder_text(tournament: Tournament) -> str:
    """Turnir boşlanişidan öldin yuboriladigan eslatma."""
    return (
        "🏆 <b>Turnir boşlanişiga 15 daqiqa qoldi!</b>\n\n"
        f"🔥 <b>{tournament.title}</b>\n"
        f"🎮 Öyin: <b>{tournament.game_title}</b>\n"
        f"🕒 Boşlaniş: <b>{format_local(tournament.starts_at)}</b>\n"
        f"💰 Sovrin fondi: <b>{format_price(tournament.prize_pool)} tanga</b>\n\n"
        "Guruhda öyin boşlanişini kuting va tayyor turing. Omad! 🍀"
    )


async def reminder_loop(bot: Bot, interval: int = REMINDER_INTERVAL_SECONDS) -> None:
    """Har daqiqada eslatma va turnir xonasi havolalarini yuboradi."""
    while True:
        try:
            store = get_tournament_store()
            await send_room_links(bot, store)
            for tournament in store.due_reminders():
                store.mark_reminded(tournament.id)
                for participant in store.participants(tournament.id):
                    try:
                        await bot.send_message(
                            participant.user_id, reminder_text(tournament)
                        )
                    except TelegramAPIError:
                        logger.info(
                            "Turnir eslatmasini yuborib bölmadi: %s",
                            participant.user_id,
                        )
                    except Exception:
                        logger.exception(
                            "Turnir eslatmasida kutilmagan xatolik: %s",
                            participant.user_id,
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Turnir eslatmalari siklida xatolik")
        await asyncio.sleep(max(10, int(interval)))


def start_reminder_loop(bot: Bot, interval: int = REMINDER_INTERVAL_SECONDS) -> asyncio.Task:
    """Eslatma siklini fonda işga tushiradi."""
    task = asyncio.get_running_loop().create_task(reminder_loop(bot, interval))
    task.add_done_callback(
        lambda finished: None if finished.cancelled() else finished.exception()
    )
    return task
