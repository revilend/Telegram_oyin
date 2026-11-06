"""🏆 Haftalik turnirlar: afisha, qatnashish va eslatmalar.

Bosh menyudagi «🏆 Turnirlar» tugmasi va ``/tournaments`` buyrug'i yaqin
kelayotgan turnirlar afishasini ko'rsatadi.  Qatnashish uchun 50 tanga
yoki ``tournament_ticket`` çiptasi sarflanadi.  Boshlanişga 30 daqiqa
qolganda yozilgan öyinçilarga şaxsiy eslatma yuboriladi.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from core.economy import format_price
from core.tournaments import (
    ENTRY_FEE,
    REMINDER_MINUTES,
    Tournament,
    TournamentError,
    TournamentStore,
    countdown_text,
    format_local,
    get_tournament_store,
)

logger = logging.getLogger(__name__)

router = Router(name="tournaments")

TOURNAMENTS_BUTTON = "🏆 Turnirlar"
OPEN_CALLBACK = "tournaments_open"
REFRESH_CALLBACK = "tour_update"
JOIN_PREFIX = "tour_join_"
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
    """Turnirlar afishasi matni."""
    storehouse = store or get_tournament_store()
    tournaments = storehouse.active()
    lines = ["🏆 <b>Revilend Haftalik Turnirlar</b>", ""]
    if not tournaments:
        lines.append(
            "Hozirça röyxatga oliş oçiq turnir yöq. Tez orada yangi "
            "çempionat e'lon qilinadi!"
        )
        return "\n".join(lines)

    lines.append(
        "Haftalik çempionatlarda qudratingizni sınang — sovrin fondi va "
        "şöhrat sizni kutmoqda."
    )
    lines.append("")
    for tournament in tournaments:
        joined = (
            user_id is not None
            and storehouse.joined(tournament.id, int(user_id))
        )
        lines.append(f"🔥 <b>{tournament.title}</b>")
        lines.append(f"🎮 Öyin: <b>{tournament.game_title}</b>")
        lines.append(f"💰 Sovrin fondi: <b>{format_price(tournament.prize_pool)} tanga</b>")
        lines.append(
            f"🕒 Boşlaniş: <b>{format_local(tournament.starts_at)}</b> "
            f"({countdown_text(tournament.starts_at)} qoldi)"
        )
        lines.append(
            f"👥 Qatnaşçilar: <b>{storehouse.participant_count(tournament.id)}</b>"
            f"/{tournament.max_players}"
        )
        if joined:
            lines.append("✅ Siz bu turnirga yozilgansiz.")
        lines.append("")
    tickets = _ticket_count(user_id, storehouse)
    lines.append(
        f"🎟 Qatnaşiş narxi: <b>{ENTRY_FEE} tanga</b> yoki turnir çiptasi."
    )
    if tickets:
        lines.append(f"🎟 Sizda <b>{tickets}</b> ta turnir çiptasi bor.")
    lines.append("")
    lines.append("Örinlar çeklangan — hoziroq yoziling!")
    return "\n".join(lines)


def poster_keyboard(
    user_id: int | None = None, store: TournamentStore | None = None
) -> InlineKeyboardMarkup:
    """Har bir turnir uchun qatnashish tugmasi."""
    storehouse = store or get_tournament_store()
    rows: list[list[InlineKeyboardButton]] = []
    for tournament in storehouse.active():
        joined = (
            user_id is not None
            and storehouse.joined(tournament.id, int(user_id))
        )
        if joined:
            label = f"✅ Yozilgansiz — {tournament.game_title}"
        else:
            label = f"🎟 Qatnaşiş ({ENTRY_FEE} 🪙) — {tournament.game_title}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"{JOIN_PREFIX}{tournament.id}",
                )
            ]
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
        reply_markup=poster_keyboard(user.id if user is not None else None),
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
    await _show(
        callback,
        poster_text(callback.from_user.id),
        poster_keyboard(callback.from_user.id),
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


@router.callback_query(F.data.startswith(JOIN_PREFIX))
async def tournaments_join(callback: CallbackQuery) -> None:
    """Turnirga yoziladi: çipta yoki 50 tanga sarflanadi."""
    tournament_id = (callback.data or "")[len(JOIN_PREFIX) :]
    try:
        result = get_tournament_store().join(
            callback.from_user.id,
            tournament_id,
            callback.from_user.username or "",
            callback.from_user.full_name or "",
        )
    except TournamentError as exc:
        await callback.answer(f"⚠️ {exc}", show_alert=True)
        return
    if result.ticket_used:
        paid = "turnir çiptasi sarflandi"
    else:
        paid = f"{format_price(result.expense)} tanga yeçildi"
    await callback.answer(
        f"✅ {result.tournament.title}ga yozildingiz!\n"
        f"{paid}. Balans: {format_price(result.account.coins)} tanga.",
        show_alert=True,
    )
    await _refresh(callback)


def reminder_text(tournament: Tournament) -> str:
    """Turnir boşlanişidan öldin yuboriladigan eslatma."""
    return (
        "🏆 <b>Turnir boşlanişiga 30 daqiqa qoldi!</b>\n\n"
        f"🔥 <b>{tournament.title}</b>\n"
        f"🎮 Öyin: <b>{tournament.game_title}</b>\n"
        f"🕒 Boşlaniş: <b>{format_local(tournament.starts_at)}</b>\n"
        f"💰 Sovrin fondi: <b>{format_price(tournament.prize_pool)} tanga</b>\n\n"
        "Guruhda öyin boşlanişini kuting va tayyor turing. Omad! 🍀"
    )


async def reminder_loop(bot: Bot, interval: int = REMINDER_INTERVAL_SECONDS) -> None:
    """Har daqiqada 30 daqiqa qolgan turnirlar uchun eslatma yuboradi."""
    while True:
        try:
            store = get_tournament_store()
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
