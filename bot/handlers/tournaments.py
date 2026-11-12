"""🏆 Haftalik turnirlar: afisha, qatnashish va eslatmalar.

Bosh menyudagi «🏆 Turnirlar» tugmasi va ``/tournaments`` buyrug'i yaqin
kelayotgan turnirlar afishasini ko'rsatadi.  Qatnaşiş uchun 50 tanga
yoki ``tournament_ticket`` çiptasi sarflanadi.  Boshlanişga 15 daqiqa
qolganda yozilgan o'yinchilarga shaxsiy eslatma (va boshlanganda xona
havolasi) yuboriladi.  Ro'yxatdan o'tish faqat yozuvdir: xona ochilmaydi,
Mini App ``web_app`` ga yo'naltirilmaydi.

Barcha matnlar ``core/i18n_texts.py`` dagi ``tourn_*`` kalitlaridan UZ/RU/EN
da olinadi; til foydalanuvchining ``language_code`` si bo'yicha aniqlanadi.
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
from core.i18n import all_variants, resolve_language, t
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


def poster_text(
    user_id: int | None = None,
    store: TournamentStore | None = None,
    *,
    language: str = "uz",
) -> str:
    """Turnirlar afishasi matni (Supabase holatidan, tilga mos)."""
    storehouse = store or get_tournament_store()
    tournaments = storehouse.visible()
    lines = [t(language, "tourn_poster_title"), ""]
    if not tournaments:
        lines.append(t(language, "tourn_poster_empty"))
        return "\n".join(lines)

    lines.append(t(language, "tourn_poster_lede"))
    lines.append("")
    for tournament in tournaments:
        joined = (
            user_id is not None
            and storehouse.joined(tournament.id, int(user_id))
        )
        lines.append(
            t(
                language,
                "tourn_poster_line_title",
                title=escape(tournament.title, quote=False),
            )
        )
        lines.append(
            t(
                language,
                "tourn_poster_line_game",
                game=escape(tournament.game_title, quote=False),
            )
        )
        lines.append(
            t(
                language,
                "tourn_poster_line_prize",
                prize=format_price(tournament.prize_pool),
            )
        )
        lines.append(
            t(
                language,
                "tourn_poster_line_slots",
                joined=storehouse.participant_count(tournament.id),
                total=tournament.max_participants,
            )
        )
        lines.append(
            t(
                language,
                "tourn_poster_line_start",
                when=format_local(tournament.starts_at) or "—",
                countdown=countdown_text(tournament.starts_at),
            )
        )
        lines.append(
            t(
                language,
                "tourn_poster_line_status",
                status=escape(status_label(tournament.status), quote=False),
            )
        )
        if joined:
            lines.append(t(language, "tourn_poster_joined"))
        lines.append("")

    tickets = _ticket_count(user_id, storehouse)
    lines.append(t(language, "tourn_poster_fee", fee=ENTRY_FEE))
    if tickets:
        lines.append(t(language, "tourn_poster_tickets", count=tickets))
    lines.append("")
    if any(item.status == OPEN for item in tournaments):
        lines.append(t(language, "tourn_poster_hurry"))
    else:
        lines.append(t(language, "tourn_poster_wait"))
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
    language: str = "uz",
) -> InlineKeyboardMarkup:
    """Har bir turnir uchun holatga mos tugmalar (tilga mos)."""
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
                        text=t(language, "tourn_btn_started"),
                        callback_data=NOOP_CALLBACK,
                    )
                ]
            )
        elif joined:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t(language, "tourn_btn_joined"),
                        callback_data=NOOP_CALLBACK,
                    )
                ]
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t(language, "tourn_btn_leave"),
                        callback_data=f"{LEAVE_CALLBACK_PREFIX}{tournament.id}",
                    )
                ]
            )
        elif storehouse.participant_count(tournament.id) >= tournament.max_players:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t(language, "tourn_btn_full"),
                        callback_data=NOOP_CALLBACK,
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t(language, "tourn_btn_join"),
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
                        text=t(language, "tourn_btn_mini_app"),
                        web_app=WebAppInfo(url=url),
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t(language, "tourn_btn_mini_app"), url=url
                    )
                ]
            )
    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "tourn_btn_reload"), callback_data=REFRESH_CALLBACK
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "tourn_btn_back"), callback_data=BACK_CALLBACK
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_tournaments(message: Message) -> None:
    """Turnirlar afishasini yuboradi."""
    user = message.from_user
    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    await message.answer(
        poster_text(user.id if user is not None else None, language=language),
        reply_markup=poster_keyboard(
            user.id if user is not None else None,
            username=(user.username or "") if user is not None else "",
            full_name=(user.full_name or "") if user is not None else "",
            language=language,
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


def _callback_language(callback: CallbackQuery) -> str:
    """Callback egasining tilini aniqlaydi."""
    user = callback.from_user
    return resolve_language(user.id, getattr(user, "language_code", None))


async def _refresh(callback: CallbackQuery) -> None:
    user = callback.from_user
    language = _callback_language(callback)
    await _show(
        callback,
        poster_text(user.id, language=language),
        poster_keyboard(
            user.id,
            username=user.username or "",
            full_name=user.full_name or "",
            language=language,
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
    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    if user is None or not is_admin(user.id):
        await message.answer(t(language, "tourn_admin_only"))
        return
    parts = (command.args or "").split()
    if len(parts) != 4:
        await message.answer(t(language, "tourn_new_format"))
        return
    game, fee_raw, prize_raw, start_raw = parts
    try:
        fee = int(fee_raw)
        prize = int(prize_raw)
        starts_at = parse_start(start_raw)
    except (ValueError, TypeError):
        await message.answer(t(language, "tourn_new_bad_input"))
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
        await message.answer(t(language, "tourn_new_error", error=exc))
        return
    await message.answer(
        t(
            language,
            "tourn_new_created",
            title=escape(tournament.title, quote=False),
            game=escape(tournament.game_title, quote=False),
            prize=format_price(tournament.prize_pool),
            fee=format_price(tournament.entry_fee),
            start=format_local(tournament.starts_at),
        )
    )


@router.message(Command("tournaments"))
@router.message(Command("turnir"))
@router.message(F.text.in_(all_variants("tournaments")))
async def tournaments_command(message: Message) -> None:
    """/tournaments — haftalik turnirlar afishasi."""
    await show_tournaments(message)


@router.callback_query(F.data == OPEN_CALLBACK)
async def tournaments_open(callback: CallbackQuery) -> None:
    """O'yinlar vitrinasidan turnirlarga o'tish."""
    await callback.answer()
    await _refresh(callback)


@router.callback_query(F.data == REFRESH_CALLBACK)
async def tournaments_refresh(callback: CallbackQuery) -> None:
    """Afishani yangilaydi."""
    language = _callback_language(callback)
    await callback.answer(t(language, "tourn_reloaded"))
    await _refresh(callback)


def _join_tournament_id(data: str) -> str:
    """Yangi va eski qatnashish callback'idan turnir id'sini oladi."""
    for prefix in (JOIN_CALLBACK_PREFIX, JOIN_PREFIX):
        if data.startswith(prefix):
            return data[len(prefix) :]
    return ""


def join_success_text(
    tournament: Tournament,
    user_id: int | None = None,
    *,
    language: str = "uz",
) -> str:
    """Ro'yxatdan o'tish tasdiq matni: boshlanish vaqti va 15 daqiqa izohi.

    Bu xabar ``tournament_participants`` ga yozilganidan keyin ko'rsatiladi;
    o'yin xonasi hali yaratilmagan bo'ladi.
    """
    starts = escape(format_local(tournament.starts_at) or "—", quote=False)
    return t(
        language,
        "tourn_join_success",
        title=escape(tournament.title, quote=False),
        start=starts,
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
    language = _callback_language(callback)
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
            await callback.answer(
                t(language, "tourn_not_found"), show_alert=True
            )
            return
        await callback.answer(t(language, "tourn_already_joined"))
        await _show(
            callback,
            join_success_text(tournament, language=language)
            + "\n\n"
            + poster_text(callback.from_user.id, store, language=language),
            poster_keyboard(
                callback.from_user.id,
                store,
                username=callback.from_user.username or "",
                full_name=callback.from_user.full_name or "",
                language=language,
            ),
        )
        return
    except TournamentError as exc:
        await callback.answer(
            t(language, "tourn_new_error", error=exc), show_alert=True
        )
        return
    await callback.answer(t(language, "tourn_joined_ok"))
    await _show(
        callback,
        join_success_text(result.tournament, language=language)
        + "\n\n"
        + poster_text(callback.from_user.id, store, language=language),
        poster_keyboard(
            callback.from_user.id,
            store,
            username=callback.from_user.username or "",
            full_name=callback.from_user.full_name or "",
            language=language,
        ),
    )


@router.callback_query(F.data.startswith(LEAVE_CALLBACK_PREFIX))
async def tournaments_leave(callback: CallbackQuery) -> None:
    """Foydalanuvchini turnir ro'yxatidan chiqaradi."""
    language = _callback_language(callback)
    tournament_id = (callback.data or "")[len(LEAVE_CALLBACK_PREFIX) :]
    try:
        get_tournament_store().leave(callback.from_user.id, tournament_id)
    except TournamentError as exc:
        await callback.answer(
            t(language, "tourn_leave_error", error=exc), show_alert=True
        )
        return
    await callback.answer(t(language, "tourn_left"), show_alert=True)
    await _refresh(callback)


@router.callback_query(F.data == NOOP_CALLBACK)
async def tournaments_noop(callback: CallbackQuery) -> None:
    """Holat tugmalari uchun ma'lumot beradi."""
    await callback.answer(t(_callback_language(callback), "tourn_noop_info"))


def room_link_text(tournament: Tournament, *, language: str = "uz") -> str:
    """Turnir boşlanganda qatnaşçilarga yuboriladigan xona havolasi."""
    return t(
        language,
        "tourn_room_started",
        title=escape(tournament.title, quote=False),
        game=escape(tournament.game_title, quote=False),
        start=format_local(tournament.starts_at),
        prize=format_price(tournament.prize_pool),
        link=escape(tournament.room_link, quote=False),
    )


def room_link_keyboard(
    tournament: Tournament, *, language: str = "uz"
) -> InlineKeyboardMarkup:
    """Xona havolasiga o'tish tugmasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "tourn_btn_room"), url=tournament.room_link
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
    Har bir qatnashchi o'z tilida xabar oladi.
    """
    storehouse = store or get_tournament_store()
    targets = [tournament] if tournament is not None else storehouse.due_room_links()
    delivered = 0
    for item in targets:
        if item is None or not item.room_link:
            continue
        for participant in storehouse.participants(item.id):
            language = resolve_language(participant.user_id)
            try:
                await bot.send_message(
                    participant.user_id,
                    room_link_text(item, language=language),
                    reply_markup=room_link_keyboard(item, language=language),
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


def reminder_text(tournament: Tournament, *, language: str = "uz") -> str:
    """Turnir boşlanişidan öldin yuboriladigan eslatma (tilga mos)."""
    return t(
        language,
        "tourn_reminder",
        title=escape(tournament.title, quote=False),
        game=escape(tournament.game_title, quote=False),
        start=format_local(tournament.starts_at),
        prize=format_price(tournament.prize_pool),
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
                    language = resolve_language(participant.user_id)
                    try:
                        await bot.send_message(
                            participant.user_id,
                            reminder_text(tournament, language=language),
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
