"""Admin panel: statistika, karta sozlamalari, cheklar, tanga va broadcast.

Panel to'liq inline tugmalar bilan ishlaydi:

* 💳 Karta raqamini sozlash — karta ``system_settings`` jadvaliga saqlanadi;
* 📥 Kutilayotgan to'lovlar — tasdiqlanmagan cheklar navbat bilan chiqadi;
* ➕ Foydalanuvchiga tanga berish — qo'lda balans to'ldirish;
* 📢 Hammaga xabar — ro'yxatdan o'tgan o'yinchilarga e'lon.
"""

from __future__ import annotations

import asyncio
import json
import logging
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import get_config
from core.backup import (
    BackupError,
    backup_caption,
    backup_filename,
    dumps_backup,
    get_backup_store,
    restore_caption,
)
from core.economy import (
    EconomyError,
    UserAccount,
    format_price,
    get_economy,
    player_rating,
)
from core.metrics import metrics
from core.settings import (
    SettingsError,
    format_card_number,
    get_settings_store,
    parse_card_line,
)
from core.tournaments import (
    ACTIVE,
    GAME_TITLES,
    Tournament,
    TournamentError,
    format_local,
    get_tournament_store,
)
from engine.game_manager import get_default_manager

logger = logging.getLogger(__name__)

router = Router(name="admin")

CARD_CALLBACK = "admin_card"
PENDING_CALLBACK = "admin_pending"
PLAYERS_CALLBACK = "admin_players"
PLAYERS_PAGE_PREFIX = "admin_players_page_"
PLAYERS_SEARCH_CALLBACK = "admin_players_find"
PLAYER_ADD_PREFIX = "admin_player_add_"
PLAYER_SUB_PREFIX = "admin_player_sub_"
GIVE_CALLBACK = "admin_give"
PROMO_CALLBACK = "admin_promo"
BROADCAST_CALLBACK = "admin_broadcast"
BACKUP_CALLBACK = "admin_backup"
RESTORE_CALLBACK = "admin_restore"
TOURNAMENT_CALLBACK = "admin_tournament"
TOUR_MAX_CALLBACK = "admin_tour_max"
TOUR_MAX_SET_PREFIX = "admin_tour_max_set_"
TOUR_MAX_CUSTOM_CALLBACK = "admin_tour_max_custom"
TOUR_TIME_CALLBACK = "admin_tour_time"
TOUR_PRIZE_CALLBACK = "admin_tour_prize"
TOUR_GAME_CALLBACK = "admin_tour_game"
TOUR_GAME_PREFIX = "admin_tour_game_"
TOUR_ROOM_CALLBACK = "admin_tour_room"
TOUR_ROOM_CLEAR_CALLBACK = "admin_tour_room_clear"
TOUR_START_CALLBACK = "admin_tour_start"
TOUR_REFRESH_CALLBACK = "admin_tour_yangila"
TOUR_BACK_CALLBACK = "admin_tour_back"
BACK_CALLBACK = "admin_back"

# Telegram bot orqali yuklab olinadigan faylning amaliy chegarasi.
MAX_BACKUP_BYTES = 20 * 1024 * 1024

CARD_PROMPT = (
    "💳 <b>Karta raqamini sozlaş</b>\n\n"
    "Karta raqami va egasining ismini yuboring "
    "(Masalan: <code>9860123456789012 Ali Valiyev</code>):"
)
GIVE_PROMPT = (
    "➕ <b>Foydalanuvçiga tanga beriş</b>\n\n"
    "Öyinçi ID raqami va tanga miqdorini yuboring "
    "(Masalan: <code>123456789 500</code>):"
)
PROMO_PROMPT = (
    "🎟 <b>Promo kod yaratiş</b>\n\n"
    "Format: <code>KOD TANGA [IŞLATIŞLAR]</code>\n"
    "Masalan: <code>YANGIYIL 500 20</code> — 500 tanga, 20 marta işlatiladi."
)
BROADCAST_PROMPT = (
    "📢 <b>Hammaga xabar</b>\n\n"
    "Yuboriladigan xabar matnini yozing:"
)
RESTORE_PROMPT = (
    "📤 <b>Bazani tiklaş</b>\n\n"
    "Zaxira JSON faylini hujjat sifatida yuboring.\n"
    "Mavjud qatorlar yangilanadi, yangilari qöşiladi — heç narsa "
    "öçirilmaydi."
)


class AdminStates(StatesGroup):
    """Admin panel ichidagi kiritish holatlari."""

    waiting_card = State()
    waiting_player_search = State()
    waiting_player_amount = State()
    waiting_give = State()
    waiting_promo = State()
    waiting_broadcast = State()
    waiting_restore = State()
    waiting_tournament_max = State()
    waiting_tournament_time = State()
    waiting_tournament_prize = State()
    waiting_tournament_room = State()


def is_admin(user_id: int) -> bool:
    """ADMIN_ID bilan mos kelsa yoki `users.role` ``admin`` bo'lsa ruxsat beradi."""
    config = get_config()
    if config.admin_id and int(user_id) == config.admin_id:
        return True
    try:
        return get_economy().is_admin_user(int(user_id))
    except Exception:
        logger.exception("`users` jadvalida rolni tekşirib bölmadi: %s", user_id)
        return False


def is_root_admin(user_id: int) -> bool:
    """Bazani tiklaş faqat ``ADMIN_ID`` egasiga ochiq."""
    config = get_config()
    return bool(config.admin_id) and int(user_id) == int(config.admin_id)


async def _reply_denied(message: Message) -> None:
    await message.answer("⛔ Bu buyruq faqat administrator uçun.")


def panel_keyboard() -> InlineKeyboardMarkup:
    """Admin panelning inline tugmalari."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Karta raqamini sozlaş",
                    callback_data=CARD_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📥 Kutilayotgan tölovlar (Çeklar)",
                    callback_data=PENDING_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Öyinçilar",
                    callback_data=PLAYERS_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Foydalanuvçiga tanga beriş",
                    callback_data=GIVE_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎟 Promo kod yaratiş",
                    callback_data=PROMO_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏆 Turnir sozlamalari",
                    callback_data=TOURNAMENT_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Hammaga xabar (Broadcast)",
                    callback_data=BROADCAST_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📥 Bazadan nusxa oliş (Backup)",
                    callback_data=BACKUP_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📤 Bazani tiklaş (Restore)",
                    callback_data=RESTORE_CALLBACK,
                )
            ],
        ]
    )


def back_keyboard() -> InlineKeyboardMarkup:
    """Kiritish holatidan panelga qaytish tugmasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=BACK_CALLBACK)]
        ]
    )


def card_status_text() -> str:
    """Panelda ko'rinadigan karta holati."""
    number, holder = get_settings_store().payment_card()
    if not number or not holder:
        return "💳 Karta: <i>hali sozlanmagan</i>"
    return (
        f"💳 Karta: <code>{escape(format_card_number(number))}</code> "
        f"({escape(holder)})"
    )


def panel_text() -> str:
    """Statistika va karta holati bilan panel matni."""
    economy = get_economy()
    manager = get_default_manager()
    stats = economy.stats(
        active_rooms=manager.active_room_count,
        total_rooms=manager.total_room_count,
    )
    live = metrics.snapshot()
    return (
        "🛠 <b>Admin panel</b>\n\n"
        f"👥 Jami öyinçilar: <b>{stats['users']}</b>\n"
        f"🪙 Umumiy xarid qilingan tangalar: <b>{format_price(stats['coins_purchased'])}</b>\n"
        f"💰 Balanslardagi tangalar: <b>{format_price(stats['coins_in_balance'])}</b>\n"
        f"🏠 Faol xonalar: <b>{stats['active_rooms']}</b>\n"
        f"🗂 Jami xonalar: <b>{stats['total_rooms']}</b>\n"
        f"📈 Sörovlar: <b>{live.requests}</b> · xatolar: <b>{live.errors}</b>\n"
        f"🎮 Tugagan öyinlar: <b>{live.games_finished}</b> · "
        f"tanga: <b>{format_price(live.coins_awarded)}</b>\n\n"
        f"{card_status_text()}\n\n"
        "Quyidagi tugmalardan birini tanlang:"
    )


@router.message(Command("admin"))
async def admin_command(message: Message, state: FSMContext) -> None:
    """/admin — statistika va inline boshqaruv tugmalari."""
    await admin_panel(message, state)


async def admin_panel(message: Message, state: FSMContext | None = None) -> None:
    """/admin va «👑 Admin panel» — statistika va inline boshqaruv tugmalari."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await _reply_denied(message)
        return
    if state is not None:
        await state.clear()
    try:
        text = panel_text()
    except Exception:
        logger.exception("Admin statistikasida xatolik")
        await message.answer("⚠️ Statistikani yuklab bölmadi.")
        return
    await message.answer(text, reply_markup=panel_keyboard())


@router.callback_query(F.data == BACK_CALLBACK)
async def back_to_panel(callback: CallbackQuery, state: FSMContext) -> None:
    """«⬅️ Orqaga» — holatni tozalab, panelni qaytaradi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    await callback.bot.send_message(
        callback.from_user.id, panel_text(), reply_markup=panel_keyboard()
    )


# ----------------------------------------------------------------------
# 💳 Karta raqamini sozlash
# ----------------------------------------------------------------------
@router.callback_query(F.data == CARD_CALLBACK)
async def ask_card(callback: CallbackQuery, state: FSMContext) -> None:
    """Karta ma'lumotlarini so'raydi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_card)
    await callback.answer()
    await callback.bot.send_message(
        callback.from_user.id, CARD_PROMPT, reply_markup=back_keyboard()
    )


@router.message(AdminStates.waiting_card)
async def save_card(message: Message, state: FSMContext) -> None:
    """Karta raqami va egasini ``system_settings``ga saqlaydi."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await state.clear()
        await _reply_denied(message)
        return
    try:
        number, holder = parse_card_line(message.text or "")
        stored_number, stored_holder = get_settings_store().set_payment_card(
            number, holder
        )
    except SettingsError as exc:
        await message.answer(f"⚠️ {escape(str(exc))}", reply_markup=back_keyboard())
        return
    except Exception:
        logger.exception("Karta ma'lumotlarini saqlab bölmadi")
        await message.answer(
            "⚠️ Karta saqlanmadi. Birozdan keyin qayta urinib köring.",
            reply_markup=back_keyboard(),
        )
        return

    await state.clear()
    await message.answer(
        "✅ <b>Karta saqlandi!</b>\n\n"
        f"💳 <code>{escape(format_card_number(stored_number))}</code>\n"
        f"👤 {escape(stored_holder)}\n\n"
        "Endi dökon (/shop) xaridorlarga şu kartani körsatadi.",
        reply_markup=panel_keyboard(),
    )


# ----------------------------------------------------------------------
# 📥 Kutilayotgan to'lovlar
# ----------------------------------------------------------------------
@router.callback_query(F.data == PENDING_CALLBACK)
async def show_pending_payments(callback: CallbackQuery) -> None:
    """Barcha tasdiqlanmagan cheklarni navbat bilan ko'rsatadi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await callback.answer()

    # Lokal import: `shop` moduli `admin.is_admin`ni import qiladi.
    from bot.handlers import shop

    chat_id = callback.from_user.id
    try:
        payments = get_economy().list_pending_payments()
    except Exception:
        logger.exception("Kutilayotgan çeklarni yuklab bölmadi")
        await callback.bot.send_message(
            chat_id, "⚠️ Çeklarni yuklab bölmadi. Qayta urinib köring."
        )
        return

    if not payments:
        await callback.bot.send_message(
            chat_id, "📥 Hozirça kutilayotgan tölovlar yöq."
        )
        return

    await callback.bot.send_message(
        chat_id, f"📥 <b>Kutilayotgan tölovlar:</b> {len(payments)} ta"
    )
    for payment in payments:
        caption = shop.receipt_caption(payment, payment.username, payment.full_name)
        keyboard = shop.review_keyboard(payment.id)
        try:
            await callback.bot.send_photo(
                chat_id=chat_id,
                photo=payment.receipt_file_id,
                caption=caption,
                reply_markup=keyboard,
            )
        except TelegramAPIError:
            # Chek rasmi eskirgan/yo'q bo'lsa, oddiy matn bilan yuboramiz.
            await callback.bot.send_message(
                chat_id, caption, reply_markup=keyboard
            )


# ----------------------------------------------------------------------
# 👥 O'yinchilar ro'yxati va qidirish
# ----------------------------------------------------------------------
PLAYERS_PER_PAGE = 10


def player_level(account: UserAccount) -> int:
    """G'alabalar sonidan ko'rsatiladigan darajani hisoblaydi."""
    return 1 + max(0, int(account.wins)) // 5


def _player_label(account: UserAccount) -> str:
    """Ro'yxatda ko'rsatiladigan qisqa ism."""
    if account.username:
        return f"@{escape(account.username)}"
    return escape(account.full_name.strip() or "Noma'lum")


def players_page_text(page: int = 1) -> tuple[str, int, int]:
    """Oxirgi qo'shilgan o'yinchilar sahifasini tayyorlaydi."""
    economy = get_economy()
    total = economy.count_users()
    pages = max(1, (total + PLAYERS_PER_PAGE - 1) // PLAYERS_PER_PAGE)
    page = min(max(1, int(page)), pages)
    accounts = economy.recent_users(
        PLAYERS_PER_PAGE, (page - 1) * PLAYERS_PER_PAGE
    )
    lines = ["👥 <b>Oxirgi röyxatdan ötgan öyinçilar:</b>", ""]
    if accounts:
        for index, account in enumerate(
            accounts, start=(page - 1) * PLAYERS_PER_PAGE + 1
        ):
            lines.append(
                f"{index}. {_player_label(account)} "
                f"(ID: <code>{account.user_id}</code>) — "
                f"<b>{format_price(account.coins)}</b> 🪙 | "
                f"Level {player_level(account)}"
            )
    else:
        lines.append("<i>Hozirça öyinçilar yöq.</i>")
    lines.extend(
        [
            "",
            f"📄 Sahifa: <b>{page}/{pages}</b> · "
            f"Jami: <b>{format_price(total)}</b> kişi",
        ]
    )
    return "\n".join(lines), page, pages


def players_keyboard(page: int, pages: int) -> InlineKeyboardMarkup:
    """Sahifalash va qidirish tugmalari."""
    previous = max(1, page - 1)
    following = min(pages, page + 1)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Oldingi",
                    callback_data=f"{PLAYERS_PAGE_PREFIX}{previous}",
                ),
                InlineKeyboardButton(
                    text="Keyingi ➡️",
                    callback_data=f"{PLAYERS_PAGE_PREFIX}{following}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔍 ID böyiça qidiriş",
                    callback_data=PLAYERS_SEARCH_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Admin panel", callback_data=BACK_CALLBACK
                )
            ],
        ]
    )


def _inventory_lines(account: UserAccount) -> tuple[list[str], int]:
    """Profil uchun inventar qatorlari va buyum turlari soni."""
    try:
        from core.shop import get_shop_store

        entries = get_shop_store().inventory(account.user_id)
    except Exception:
        logger.exception("Inventarni öqib bölmadi: %s", account.user_id)
        return ["  • <i>inventar yuklanmadi</i>"], 0
    if not entries:
        return ["  • <i>boş</i>"], 0
    lines = []
    for entry in entries[:10]:
        item = entry.item
        title = item.title if item is not None else entry.item_slug
        emoji = item.emoji if item is not None else "🛍"
        equipped = " ✅" if entry.is_equipped else ""
        lines.append(
            f"  • {emoji} {escape(str(title))} ×{entry.quantity}{equipped}"
        )
    if len(entries) > 10:
        lines.append(f"  • … yana {len(entries) - 10} xil buyum")
    return lines, len(entries)


def player_profile_text(account: UserAccount) -> str:
    """Admin uchun to'liq o'yinchi profili."""
    name = escape(account.full_name.strip() or "Noma'lum")
    username = f"@{escape(account.username)}" if account.username else "—"
    total_wins = (
        int(account.bunker_wins)
        + int(account.mafia_wins)
        + int(account.spy_wins)
        + int(account.alias_wins)
        + int(account.bomb_wins)
    )
    inventory, inventory_count = _inventory_lines(account)
    return "\n".join(
        [
            "╭───────────────────────╮",
            "    👤 <b>Öyinçi profili</b>",
            "╰───────────────────────╯",
            "",
            f"👤 İsm: <b>{name}</b>",
            f"🔗 Username: {username}",
            f"🆔 ID: <code>{account.user_id}</code>",
            f"🪙 Balans: <b>{format_price(account.coins)}</b> tanga",
            f"🏅 Level: <b>{player_level(account)}</b> · "
            f"Reyting: <b>{format_price(player_rating(account))}</b>",
            f"🎮 Öyinlar: <b>{account.games_played}</b> | "
            f"🥇 Ğalabalar: <b>{account.wins}</b>",
            f"🛡 Bunker: <b>{account.bunker_wins}</b> | "
            f"🕵 Mafiya: <b>{account.mafia_wins}</b>",
            f"🕶 Josus: <b>{account.spy_wins}</b> | "
            f"🐊 Alias: <b>{account.alias_wins}</b>",
            f"💣 Bomba: <b>{account.bomb_wins}</b> | "
            f"🏅 Jami ğalaba: <b>{total_wins}</b>",
            f"👥 Taklif qilganlar: <b>{account.referral_count}</b>",
            "",
            f"🎒 <b>Inventar:</b> {inventory_count} xil",
            *inventory,
        ]
    )


def player_profile_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Profil ostidagi tanga amallari."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Tanga beriş",
                    callback_data=f"{PLAYER_ADD_PREFIX}{user_id}",
                ),
                InlineKeyboardButton(
                    text="➖ Tanga ayiriş",
                    callback_data=f"{PLAYER_SUB_PREFIX}{user_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Öyinçilar röyxati",
                    callback_data=PLAYERS_CALLBACK,
                )
            ],
        ]
    )


async def _edit_admin_message(
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup
) -> None:
    """Mavjud xabarni tahrirlaydi, imkoni bo'lmasa yangisini yuboradi."""
    message = callback.message
    if message is not None and hasattr(message, "edit_text"):
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            logger.debug("Admin xabarini tahrirlab bölmadi")
    await callback.bot.send_message(
        callback.from_user.id, text, reply_markup=keyboard
    )


@router.callback_query(F.data == PLAYERS_CALLBACK)
async def show_players(callback: CallbackQuery, state: FSMContext) -> None:
    """Oxirgi qo'shilgan o'yinchilar ro'yxatini ko'rsatadi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    try:
        text, page, pages = players_page_text(1)
    except Exception:
        logger.exception("Öyinçilar röyxatini yuklab bölmadi")
        await callback.bot.send_message(
            callback.from_user.id, "⚠️ Öyinçilar röyxatini yuklab bölmadi."
        )
        return
    await _edit_admin_message(callback, text, players_keyboard(page, pages))


@router.callback_query(F.data.startswith(PLAYERS_PAGE_PREFIX))
async def paginate_players(callback: CallbackQuery) -> None:
    """Ro'yxat sahifasini almashtiradi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    raw = (callback.data or "")[len(PLAYERS_PAGE_PREFIX) :]
    try:
        page = int(raw)
    except ValueError:
        await callback.answer("Sahifa notöğri", show_alert=True)
        return
    await callback.answer()
    try:
        text, current, pages = players_page_text(page)
    except Exception:
        logger.exception("Öyinçilar sahifasini yuklab bölmadi")
        await callback.bot.send_message(
            callback.from_user.id, "⚠️ Sahifani yuklab bölmadi."
        )
        return
    await _edit_admin_message(
        callback, text, players_keyboard(current, pages)
    )


@router.callback_query(F.data == PLAYERS_SEARCH_CALLBACK)
async def ask_player_search(callback: CallbackQuery, state: FSMContext) -> None:
    """ID bo'yicha qidirish uchun ID so'raydi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_player_search)
    await callback.answer()
    await callback.bot.send_message(
        callback.from_user.id,
        "🔍 <b>Öyinçini ID böyiça qidiriş</b>\n\n"
        "Öyinçining Telegram ID raqamini yuboring:",
        reply_markup=back_keyboard(),
    )


@router.message(AdminStates.waiting_player_search)
async def search_player(message: Message, state: FSMContext) -> None:
    """Kiritilgan ID bo'yicha to'liq profilni ko'rsatadi."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await state.clear()
        await _reply_denied(message)
        return
    raw = (message.text or "").strip().lstrip("@")
    if not raw.isdigit():
        await message.answer(
            "⚠️ ID faqat raqamlardan iborat bölişi kerak.",
            reply_markup=back_keyboard(),
        )
        return
    try:
        account = get_economy().find_user(int(raw))
    except Exception:
        logger.exception("Öyinçini qidirib bölmadi: %s", raw)
        await message.answer(
            "⚠️ Qidiruvda xatolik yuz berdi.", reply_markup=back_keyboard()
        )
        return
    if account is None:
        await message.answer(
            f"❌ <code>{raw}</code> ID bilan öyinçi topilmadi.",
            reply_markup=back_keyboard(),
        )
        return
    await state.clear()
    await message.answer(
        player_profile_text(account),
        reply_markup=player_profile_keyboard(account.user_id),
    )


async def _ask_player_amount(
    callback: CallbackQuery, state: FSMContext, action: str
) -> None:
    """Profil tugmasidan tanga miqdorini so'raydi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    prefix = PLAYER_ADD_PREFIX if action == "add" else PLAYER_SUB_PREFIX
    raw = (callback.data or "")[len(prefix) :]
    try:
        user_id = int(raw)
    except ValueError:
        await callback.answer("Öyinçi ID notöğri", show_alert=True)
        return
    try:
        account = get_economy().find_user(user_id)
    except Exception:
        logger.exception("Öyinçini yuklab bölmadi: %s", user_id)
        await callback.answer("Öyinçi yuklanmadi", show_alert=True)
        return
    if account is None:
        await callback.answer("Öyinçi topilmadi", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_player_amount)
    await state.update_data(player_id=user_id, player_action=action)
    await callback.answer()
    verb = "qöşiş" if action == "add" else "ayiriş"
    await callback.bot.send_message(
        callback.from_user.id,
        f"{'➕' if action == 'add' else '➖'} <b>Tanga {verb}</b>\n\n"
        f"👤 {_player_label(account)} "
        f"(ID: <code>{user_id}</code>)\n"
        f"🪙 Joriy balans: <b>{format_price(account.coins)}</b> tanga\n\n"
        "Miqdorni butun son sifatida yuboring:",
        reply_markup=back_keyboard(),
    )


@router.callback_query(F.data.startswith(PLAYER_ADD_PREFIX))
async def ask_add_player_coins(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await _ask_player_amount(callback, state, "add")


@router.callback_query(F.data.startswith(PLAYER_SUB_PREFIX))
async def ask_subtract_player_coins(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await _ask_player_amount(callback, state, "sub")


@router.message(AdminStates.waiting_player_amount)
async def apply_player_coins(message: Message, state: FSMContext) -> None:
    """Profil orqali tanlangan öyinçining balansini özgartiradi."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await state.clear()
        await _reply_denied(message)
        return
    raw = (message.text or "").strip().replace(" ", "")
    try:
        amount = int(raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "⚠️ Miqdor musbat butun son bölişi kerak.",
            reply_markup=back_keyboard(),
        )
        return
    data = await state.get_data()
    try:
        user_id = int(data.get("player_id"))
    except (TypeError, ValueError):
        await state.clear()
        await message.answer(
            "⚠️ Öyinçi aniqlanmadi. Qaytadan qidiring.",
            reply_markup=panel_keyboard(),
        )
        return
    action = str(data.get("player_action") or "add")
    economy = get_economy()
    try:
        account = (
            economy.add_coins(user_id, amount)
            if action == "add"
            else economy.spend_coins(user_id, amount)
        )
    except EconomyError as exc:
        await message.answer(
            f"⚠️ {escape(str(exc))}", reply_markup=back_keyboard()
        )
        return
    except Exception:
        logger.exception("Balansni özgärtirib bölmadi: %s", user_id)
        await message.answer(
            "⚠️ Balans özgärtirilmadi. Qayta urinib köring.",
            reply_markup=back_keyboard(),
        )
        return
    await state.clear()
    sign = "+" if action == "add" else "−"
    await message.answer(
        f"✅ <code>{user_id}</code> balansi <b>{sign}{format_price(amount)}</b> "
        "tanga özgärtirildi.\n\n" + player_profile_text(account),
        reply_markup=player_profile_keyboard(user_id),
    )


# ----------------------------------------------------------------------
# ➕ Foydalanuvchiga tanga berish
# ----------------------------------------------------------------------
@router.callback_query(F.data == GIVE_CALLBACK)
async def ask_give_coins(callback: CallbackQuery, state: FSMContext) -> None:
    """Tanga berish uchun ID va miqdorni so'raydi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_give)
    await callback.answer()
    await callback.bot.send_message(
        callback.from_user.id, GIVE_PROMPT, reply_markup=back_keyboard()
    )


@router.message(AdminStates.waiting_give)
async def give_coins_from_panel(message: Message, state: FSMContext) -> None:
    """Panel orqali qo'lda tanga berish."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await state.clear()
        await _reply_denied(message)
        return
    raw = (message.text or "").split()
    if len(raw) != 2:
        await message.answer(
            "Format: <code>123456789 500</code>", reply_markup=back_keyboard()
        )
        return
    try:
        user_id = int(raw[0])
        amount = int(raw[1].replace(" ", ""))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "user_id va miqdor musbat butun son bölişi kerak.",
            reply_markup=back_keyboard(),
        )
        return

    await state.clear()
    await message.answer(
        await _credit_coins(user_id, amount), reply_markup=panel_keyboard()
    )


async def _credit_coins(user_id: int, amount: int) -> str:
    """Tangani qo'shib, natija matnini qaytaradi."""
    try:
        account = get_economy().add_coins(user_id, amount)
    except EconomyError as exc:
        return f"⚠️ {escape(str(exc))}"
    except Exception:
        logger.exception("Tanga qöşib bölmadi: %s", user_id)
        return "⚠️ Tanga qöşilmadi. Qayta urinib köring."
    return (
        f"✅ <code>{user_id}</code>ga <b>+{format_price(amount)}</b> tanga qöşildi.\n"
        f"Yangi balans: <b>{format_price(account.coins)}</b> tanga."
    )


# ----------------------------------------------------------------------
# 🎟 Promo kod yaratish
# ----------------------------------------------------------------------
@router.callback_query(F.data == PROMO_CALLBACK)
async def ask_promo(callback: CallbackQuery, state: FSMContext) -> None:
    """Promo kod parametrlarini so'raydi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_promo)
    await callback.answer()
    await callback.bot.send_message(
        callback.from_user.id, PROMO_PROMPT, reply_markup=back_keyboard()
    )


@router.message(AdminStates.waiting_promo)
async def save_promo(message: Message, state: FSMContext) -> None:
    """Panel orqali promo kod yaratadi."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await state.clear()
        await _reply_denied(message)
        return
    tokens = (message.text or "").split()
    if len(tokens) not in (2, 3):
        await message.answer(
            "Format: <code>KOD 500 10</code> — kod, tanga miqdori va "
            "(ixtiyoriy) işlatişlar soni.",
            reply_markup=back_keyboard(),
        )
        return
    try:
        coins = int(tokens[1].replace(" ", ""))
        max_uses = int(tokens[2]) if len(tokens) == 3 else 1
    except ValueError:
        await message.answer(
            "Tanga miqdori va işlatişlar soni butun son bölişi kerak.",
            reply_markup=back_keyboard(),
        )
        return

    try:
        promo = get_economy().create_promo_code(
            tokens[0], coins, max_uses, created_by=message.from_user.id
        )
    except EconomyError as exc:
        await message.answer(f"⚠️ {escape(str(exc))}", reply_markup=back_keyboard())
        return
    except Exception:
        # Baza xatosi promokod yaratishni to'xtatmasligi kerak: economy kodi
        # avval xotirada saqlaydi. Bu yerga faqat kutilmagan holat tushadi.
        logger.exception("Promo kod yaratişda kutilmagan xatolik")
        await message.answer(
            "⚠️ Promo kodni saqlaşda vaqtinça xatolik. Qayta urinib köring.",
            reply_markup=back_keyboard(),
        )
        return

    await state.clear()
    await message.answer(
        "✅ <b>Promo kod yaratildi!</b>\n\n"
        f"🎟 Kod: <code>{escape(promo.code)}</code>\n"
        f"🪙 Mukofot: {format_price(promo.coins)} tanga\n"
        f"👥 Limit: {promo.max_uses} marta\n\n"
        "Öyinçilar kodni botdagi «🎟 Promo kod» tugmasi orqali kiritadi.",
        reply_markup=panel_keyboard(),
    )


# ----------------------------------------------------------------------
# 📢 Hammaga xabar
# ----------------------------------------------------------------------
@router.callback_query(F.data == BROADCAST_CALLBACK)
async def ask_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    """Broadcast matnini so'raydi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_broadcast)
    await callback.answer()
    await callback.bot.send_message(
        callback.from_user.id, BROADCAST_PROMPT, reply_markup=back_keyboard()
    )


@router.message(AdminStates.waiting_broadcast)
async def broadcast_from_panel(message: Message, state: FSMContext) -> None:
    """Panel orqali hammaga xabar yuborish."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await state.clear()
        await _reply_denied(message)
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "Iltimos, xabar matnini yozing.", reply_markup=back_keyboard()
        )
        return
    await state.clear()
    await message.answer(
        await _broadcast_text(message, text), reply_markup=panel_keyboard()
    )


async def _broadcast_text(message: Message, text: str) -> str:
    """Matnni barcha o'yinchilarga yuborib, hisobot qaytaradi."""
    try:
        user_ids = get_economy().list_user_ids()
    except Exception:
        logger.exception("Foydalanuvçilar röyxatini olib bölmadi")
        return "⚠️ Foydalanuvçilar röyxatini olib bölmadi."
    if not user_ids:
        return "ℹ️ Hali röyxatdan ötgan öyinçilar yöq."

    sent = 0
    failed = 0
    for user_id in user_ids:
        try:
            await message.bot.send_message(user_id, text)
            sent += 1
        except TelegramAPIError:
            failed += 1
        except Exception:
            failed += 1
            logger.exception("Broadcast yuborişda xatolik: %s", user_id)
        await asyncio.sleep(0.04)

    return (
        f"📣 Broadcast tugadi: <b>{sent}</b> ta yuborildi, "
        f"<b>{failed}</b> ta yetkazilmadi."
    )


# ----------------------------------------------------------------------
# 📥 Bazadan nusxa oliş va 📤 tiklaş
# ----------------------------------------------------------------------
@router.callback_query(F.data == BACKUP_CALLBACK)
async def send_backup(callback: CallbackQuery) -> None:
    """Barcha jadvallardan JSON zaxira olib, adminga hujjat sifatida yuboradi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await callback.answer("Zaxira tayyorlanmoqda...")
    chat_id = callback.from_user.id

    try:
        payload = await asyncio.to_thread(get_backup_store().create_backup)
        filename = backup_filename()
        document = BufferedInputFile(dumps_backup(payload), filename=filename)
    except BackupError as exc:
        await callback.bot.send_message(
            chat_id, f"⚠️ {escape(str(exc))}", reply_markup=panel_keyboard()
        )
        return
    except Exception:
        logger.exception("Bazadan nusxa olişda xatolik")
        await callback.bot.send_message(
            chat_id,
            "⚠️ Zaxira yaratilmadi. Qayta urinib köring.",
            reply_markup=panel_keyboard(),
        )
        return

    try:
        await callback.bot.send_document(
            chat_id, document, caption=backup_caption(payload, filename=filename)
        )
    except TelegramAPIError:
        logger.exception("Zaxira faylini yuborib bölmadi")
        await callback.bot.send_message(
            chat_id,
            "⚠️ Zaxira tayyor, lekin faylni yuborib bölmadi. Qayta urinib köring.",
            reply_markup=panel_keyboard(),
        )


@router.callback_query(F.data == RESTORE_CALLBACK)
async def ask_restore(callback: CallbackQuery, state: FSMContext) -> None:
    """Bosh admindan zaxira faylini so'raydi."""
    if not is_root_admin(callback.from_user.id):
        await callback.answer(
            "⛔ Bazani tiklaş faqat boş admin uçun.", show_alert=True
        )
        return
    await state.set_state(AdminStates.waiting_restore)
    await callback.answer()
    await callback.bot.send_message(
        callback.from_user.id, RESTORE_PROMPT, reply_markup=back_keyboard()
    )


@router.message(AdminStates.waiting_restore, F.document)
async def restore_from_file(message: Message, state: FSMContext) -> None:
    """Yuborilgan JSON faylni öqib, jadvallarni ``upsert`` qiladi."""
    if message.from_user is None or not is_root_admin(message.from_user.id):
        await state.clear()
        await _reply_denied(message)
        return
    document = message.document
    if document is None:
        await message.answer(
            "📤 Iltimos, zaxira JSON faylini hujjat sifatida yuboring.",
            reply_markup=back_keyboard(),
        )
        return
    name = document.file_name or ""
    if not name.lower().endswith(".json"):
        await message.answer(
            "⚠️ Faqat <code>.json</code> zaxira faylini yuboring.",
            reply_markup=back_keyboard(),
        )
        return
    if int(document.file_size or 0) > MAX_BACKUP_BYTES:
        await message.answer(
            "⚠️ Fayl juda katta (maksimal 20 MB).", reply_markup=back_keyboard()
        )
        return

    try:
        buffer = await message.bot.download(document)
        payload = json.loads(buffer.read().decode("utf-8"))
    except Exception:
        logger.exception("Zaxira faylini öqib bölmadi")
        await message.answer(
            "⚠️ Faylni öqib bölmadi: yaroqli JSON fayl kerak.",
            reply_markup=back_keyboard(),
        )
        return

    try:
        result = await asyncio.to_thread(get_backup_store().restore, payload)
    except BackupError as exc:
        await message.answer(f"⚠️ {escape(str(exc))}", reply_markup=back_keyboard())
        return
    except Exception:
        logger.exception("Bazani tiklaşda xatolik")
        await message.answer(
            "⚠️ Tiklaşda xatolik yuz berdi. Ma'lumotlar qisman tiklangen "
            "bölişi mumkin — zaxira faylini tekşirib qayta urinib köring.",
            reply_markup=back_keyboard(),
        )
        return

    await state.clear()
    await message.answer(restore_caption(result), reply_markup=panel_keyboard())


@router.message(AdminStates.waiting_restore)
async def restore_needs_file(message: Message) -> None:
    """Fayl o'rniga matn kelganda yo'riqnoma beradi."""
    if message.from_user is None or not is_root_admin(message.from_user.id):
        await _reply_denied(message)
        return
    await message.answer(
        "📤 Iltimos, zaxira JSON faylini hujjat sifatida yuboring.",
        reply_markup=back_keyboard(),
    )


# ----------------------------------------------------------------------
# Buyruqlar (eski interfeys ham ishlab turadi)
# ----------------------------------------------------------------------
@router.message(Command("give"))
async def give_coins(message: Message, command: CommandObject) -> None:
    """/give <user_id> <miqdor> — qo'lda tanga berish."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await _reply_denied(message)
        return
    args = (command.args or "").split()
    if len(args) != 2:
        await message.answer("Format: <code>/give 123456789 500</code>")
        return
    try:
        user_id = int(args[0])
        amount = int(args[1].replace(" ", ""))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("user_id va miqdor musbat butun son bölişi kerak.")
        return
    await message.answer(await _credit_coins(user_id, amount))


@router.message(Command("user"))
async def user_info(message: Message, command: CommandObject) -> None:
    """/user <user_id> — balans, o'yinlar va g'alabalar."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await _reply_denied(message)
        return
    raw = (command.args or "").strip().split()[0] if (command.args or "").strip() else ""
    try:
        user_id = int(raw)
    except ValueError:
        await message.answer("Format: <code>/user 123456789</code>")
        return
    try:
        account = get_economy().ensure_user(user_id)
    except EconomyError as exc:
        await message.answer(f"⚠️ {escape(str(exc))}")
        return
    name = account.full_name or account.username or "Ismsiz"
    await message.answer(
        "👤 <b>Öyinçi</b>\n"
        f"Ism: {escape(name)}\n"
        f"Username: {'@' + escape(account.username) if account.username else '—'}\n"
        f"🆔 <code>{account.user_id}</code>\n"
        f"🪙 Balans: <b>{format_price(account.coins)}</b> tanga\n"
        f"🛒 Xarid qilingan: <b>{format_price(account.total_purchased)}</b> tanga\n"
        f"🎮 Öynagan öyinlari: <b>{account.games_played}</b>\n"
        f"🏆 Ğalabalari: <b>{account.wins}</b>"
    )


@router.message(Command("broadcast"))
async def broadcast(message: Message, command: CommandObject) -> None:
    """/broadcast <matn> — barcha ro'yxatdan o'tgan o'yinchilarga xabar."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await _reply_denied(message)
        return
    text = (command.args or "").strip()
    if not text:
        await message.answer("Format: <code>/broadcast E'lon matni</code>")
        return
    await message.answer(await _broadcast_text(message, text))


# ----------------------------------------------------------------------
# 🏆 Turnir sozlamalari
# ----------------------------------------------------------------------
TOUR_MAX_OPTIONS = (8, 16, 32, 64)
TOUR_GAME_OPTIONS = (
    ("bunker", "Bunker"),
    ("mafia", "Mafiya"),
    ("spyfall", "Josus"),
    ("alias", "Alias"),
    ("bomb", "Bomba"),
)
TOUR_MAX_PROMPT = (
    "👥 <b>Qatnaşçilar soni</b>\n\n"
    "Yangi limitni butun son sifatida yuboring (kamida 2):"
)
TOUR_TIME_PROMPT = (
    "⏰ <b>Boşlaniş vaqtini sozlaş</b>\n\n"
    "Vaqtni quyidagi formatlardan birida yuboring:\n"
    "<code>2026-11-12 20:00</code>\n"
    "<code>ertaga 21:00</code>\n"
    "<code>+3 kun</code> yoki <code>+3 kun 21:00</code>"
)
TOUR_PRIZE_PROMPT = (
    "💰 <b>Sovrin miqdorini sozlaş</b>\n\n"
    "Yangi sovrin miqdorini tangada yuboring:"
)
TOUR_ROOM_PROMPT = (
    "🔗 <b>Xona havolasini sozlaş</b>\n\n"
    "Turnir boşlanganda barça qatnaşçilarga avtomatik yuboriladigan "
    "havolani kiriting. Masalan: <code>https://t.me/+AbCdEf</code> "
    "yoki <code>https://t.me/revilend_games</code>.\n\n"
    "Havolani öçiriş uçun <code>-</code> yuboring."
)


def _current_tournament() -> Tournament | None:
    """Admin panelidagi joriy turnir; baza xatosi bo'lsa None."""
    try:
        store = get_tournament_store()
        store.ensure_weekly()
        return store.current()
    except Exception:
        logger.exception("Faol turnirni öqib bölmadi")
        return None


def tournament_status_text(tournament: Tournament | None = None) -> str:
    """Faol turnirning admin panelidagi holati."""
    item = tournament or _current_tournament()
    if item is None:
        return (
            "🏆 <b>Faol Turnir Holati:</b>\n\n"
            "Hozirça faol turnir topilmadi. Turnir yaratilgaç şu yerda körinadi."
        )
    store = get_tournament_store()
    try:
        joined = store.participant_count(item.id)
    except Exception:
        joined = 0
    lines = [
        "🏆 <b>Faol Turnir Holati:</b>",
        f"🎮 Öyin: <b>{escape(item.game_title)}</b>",
        f"💰 Sovrin: <b>{format_price(item.prize_pool)} tanga</b>",
        f"👥 Qatnaşçilar: <b>{joined} / {item.max_participants} kişi</b>",
        f"⏰ Boşlaniş vaqti: <b>{escape(format_local(item.starts_at) or '—')}</b>",
        f"📌 Holati: <b>{escape(item.status)}</b>",
    ]
    lines.append(
        f"🔗 Xona havolasi: {escape(item.room_link)}"
        if item.room_link
        else "🔗 Xona havolasi: <i>belgilanmagan</i>"
    )
    return "\n".join(lines)


def tournament_back_keyboard() -> InlineKeyboardMarkup:
    """Turnir sozlamalariga qaytish."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Turnir sozlamalari", callback_data=TOUR_BACK_CALLBACK)]
        ]
    )


def tournament_max_keyboard() -> InlineKeyboardMarkup:
    """Tezkor qatnashchilar limitlari."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{value} kişi", callback_data=f"{TOUR_MAX_SET_PREFIX}{value}"
            )
            for value in TOUR_MAX_OPTIONS[index : index + 2]
        ]
        for index in range(0, len(TOUR_MAX_OPTIONS), 2)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="✍️ Başqa son", callback_data=TOUR_MAX_CUSTOM_CALLBACK
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=TOUR_BACK_CALLBACK)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tournament_game_keyboard() -> InlineKeyboardMarkup:
    """Turnir o'yin turini tanlash."""
    rows = [
        [
            InlineKeyboardButton(
                text=label, callback_data=f"{TOUR_GAME_PREFIX}{key}"
            )
        ]
        for key, label in TOUR_GAME_OPTIONS
    ]
    rows.append(
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=TOUR_BACK_CALLBACK)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tournament_keyboard(tournament: Tournament | None = None) -> InlineKeyboardMarkup:
    """Turnirni başqarish tugmalari."""
    item = tournament or _current_tournament()
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="👥 Qatnaşçilar soni", callback_data=TOUR_MAX_CALLBACK
            ),
            InlineKeyboardButton(
                text="⏰ Vaqtni sozlaş", callback_data=TOUR_TIME_CALLBACK
            ),
        ],
        [
            InlineKeyboardButton(
                text="💰 Sovrin miqdori", callback_data=TOUR_PRIZE_CALLBACK
            ),
            InlineKeyboardButton(
                text="🎮 Öyin turi", callback_data=TOUR_GAME_CALLBACK
            ),
        ],
        [
            InlineKeyboardButton(
                text="🔗 Xona havolasi", callback_data=TOUR_ROOM_CALLBACK
            )
        ],
        *(
            [
                [
                    InlineKeyboardButton(
                        text="🗑 Xona havolasini öçiriş",
                        callback_data=TOUR_ROOM_CLEAR_CALLBACK,
                    )
                ]
            ]
            if item is not None and item.room_link
            else []
        ),
        [
            InlineKeyboardButton(
                text=(
                    "▶️ Turnirga start beriş"
                    if item is None or item.status != ACTIVE
                    else "✅ Turnir boşlangan"
                ),
                callback_data=TOUR_START_CALLBACK,
            )
        ],
        [
            InlineKeyboardButton(
                text="🔄 Yangilaş", callback_data=TOUR_REFRESH_CALLBACK
            ),
            InlineKeyboardButton(
                text="⬅️ Admin panel", callback_data=BACK_CALLBACK
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_tournament_status(
    callback: CallbackQuery,
    *,
    prefix: str = "",
    tournament: Tournament | None = None,
) -> None:
    """Turnir holatini yangi xabar sifatida yuboradi."""
    item = tournament or _current_tournament()
    text = (prefix + "\n\n" if prefix else "") + tournament_status_text(item)
    await callback.bot.send_message(
        callback.from_user.id,
        text,
        reply_markup=tournament_keyboard(item),
    )


def _check_tournament_admin(callback: CallbackQuery) -> bool:
    if not is_admin(callback.from_user.id):
        return False
    return True


@router.callback_query(F.data == TOURNAMENT_CALLBACK)
async def show_tournament_settings(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Admin panelidan turnir sozlamalarini ochadi."""
    if not _check_tournament_admin(callback):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    await _send_tournament_status(callback)


@router.callback_query(F.data == TOUR_BACK_CALLBACK)
async def tournament_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Turnir sozlamalariga qaytadi."""
    if not _check_tournament_admin(callback):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    await _send_tournament_status(callback)


@router.callback_query(F.data == TOUR_REFRESH_CALLBACK)
async def yangila_tournament_settings(callback: CallbackQuery) -> None:
    """Turnir holatini bazadan qayta o'qiydi."""
    if not _check_tournament_admin(callback):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await callback.answer("Yangilandi")
    await _send_tournament_status(callback)


@router.callback_query(F.data == TOUR_MAX_CALLBACK)
async def ask_tournament_max(callback: CallbackQuery) -> None:
    """Qatnaşçilar limitini tanlashni taklif qiladi."""
    if not _check_tournament_admin(callback):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await callback.answer()
    await callback.bot.send_message(
        callback.from_user.id,
        "👥 <b>Qatnaşçilar soni</b>\n\nTezkor tanlang yoki başqa son kiriting:",
        reply_markup=tournament_max_keyboard(),
    )


@router.callback_query(F.data == TOUR_MAX_CUSTOM_CALLBACK)
async def ask_tournament_max_custom(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Istalgan qatnashchilar sonini kiritish uchun holat."""
    if not _check_tournament_admin(callback):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_tournament_max)
    await callback.answer()
    await callback.bot.send_message(
        callback.from_user.id, TOUR_MAX_PROMPT, reply_markup=tournament_back_keyboard()
    )


@router.callback_query(F.data.startswith(TOUR_MAX_SET_PREFIX))
async def set_tournament_max(callback: CallbackQuery) -> None:
    """Tezkor tanlangan qatnashchilar sonini saqlaydi."""
    if not _check_tournament_admin(callback):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    raw = (callback.data or "")[len(TOUR_MAX_SET_PREFIX) :]
    item = _current_tournament()
    if item is None:
        await callback.answer("Faol turnir topilmadi", show_alert=True)
        return
    try:
        updated = get_tournament_store().set_max_participants(item.id, int(raw))
    except (TournamentError, ValueError) as exc:
        await callback.answer(f"⚠️ {exc}", show_alert=True)
        return
    await callback.answer("Saqlandi")
    await _send_tournament_status(
        callback, prefix="✅ Qatnaşçilar limiti yangilandi.", tournament=updated
    )


@router.callback_query(F.data == TOUR_TIME_CALLBACK)
async def ask_tournament_time(callback: CallbackQuery, state: FSMContext) -> None:
    """Boşlaniş vaqtini so'raydi."""
    if not _check_tournament_admin(callback):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_tournament_time)
    await callback.answer()
    await callback.bot.send_message(
        callback.from_user.id, TOUR_TIME_PROMPT, reply_markup=tournament_back_keyboard()
    )


@router.callback_query(F.data == TOUR_PRIZE_CALLBACK)
async def ask_tournament_prize(callback: CallbackQuery, state: FSMContext) -> None:
    """Sovrin miqdorini so'raydi."""
    if not _check_tournament_admin(callback):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_tournament_prize)
    await callback.answer()
    await callback.bot.send_message(
        callback.from_user.id, TOUR_PRIZE_PROMPT, reply_markup=tournament_back_keyboard()
    )


@router.callback_query(F.data == TOUR_GAME_CALLBACK)
async def ask_tournament_game(callback: CallbackQuery) -> None:
    """O'yin turini tanlashni taklif qiladi."""
    if not _check_tournament_admin(callback):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await callback.answer()
    await callback.bot.send_message(
        callback.from_user.id,
        "🎮 <b>Öyin turini tanlang</b>",
        reply_markup=tournament_game_keyboard(),
    )


@router.callback_query(F.data.startswith(TOUR_GAME_PREFIX))
async def set_tournament_game(callback: CallbackQuery) -> None:
    """Tanlangan o'yin turini saqlaydi."""
    if not _check_tournament_admin(callback):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    game = (callback.data or "")[len(TOUR_GAME_PREFIX) :]
    item = _current_tournament()
    if item is None:
        await callback.answer("Faol turnir topilmadi", show_alert=True)
        return
    try:
        updated = get_tournament_store().set_game(item.id, game)
    except TournamentError as exc:
        await callback.answer(f"⚠️ {exc}", show_alert=True)
        return
    await callback.answer("Saqlandi")
    await _send_tournament_status(
        callback, prefix="✅ Öyin turi yangilandi.", tournament=updated
    )


@router.callback_query(F.data == TOUR_ROOM_CALLBACK)
async def ask_tournament_room(callback: CallbackQuery, state: FSMContext) -> None:
    """Xona havolasini kiritishni söraydi."""
    if not _check_tournament_admin(callback):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    item = _current_tournament()
    if item is None:
        await callback.answer("Faol turnir topilmadi", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_tournament_room)
    await callback.answer()
    await callback.bot.send_message(
        callback.from_user.id, TOUR_ROOM_PROMPT, reply_markup=tournament_back_keyboard()
    )


@router.callback_query(F.data == TOUR_ROOM_CLEAR_CALLBACK)
async def clear_tournament_room(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Xona havolasini öçiradi."""
    if not _check_tournament_admin(callback):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    await state.clear()
    item = _current_tournament()
    if item is None:
        await callback.answer("Faol turnir topilmadi", show_alert=True)
        return
    try:
        updated = get_tournament_store().set_room_link(item.id, "")
    except TournamentError as exc:
        await callback.answer(f"⚠️ {exc}", show_alert=True)
        return
    await callback.answer("Havola öçirildi")
    await _send_tournament_status(
        callback, prefix="✅ Xona havolasi öçirildi.", tournament=updated
    )


@router.callback_query(F.data == TOUR_START_CALLBACK)
async def start_tournament(callback: CallbackQuery) -> None:
    """Qatnaşçilardan bracket yasab, turnirni boshlaydi."""
    if not _check_tournament_admin(callback):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
        return
    item = _current_tournament()
    if item is None:
        await callback.answer("Faol turnir topilmadi", show_alert=True)
        return
    try:
        updated = get_tournament_store().start(item.id)
    except TournamentError as exc:
        await callback.answer(f"⚠️ {exc}", show_alert=True)
        return

    sent = 0
    if updated.room_link:
        from bot.handlers.tournaments import send_room_links

        sent = await send_room_links(
            callback.bot, get_tournament_store(), updated
        )
    await callback.answer("Turnir boşlandi")
    prefix = "✅ <b>Turnir boşlandi!</b> Bracket bazaga saqlandi."
    if updated.room_link:
        prefix += f"\n📨 Xona havolasi {sent} qatnaşçiga yuborildi."
    else:
        prefix += (
            "\n⚠️ Xona havolasi belgilanmagan — qatnaşçilarga yuborilmadi."
            " «🔗 Xona havolasi» orqali kiriting."
        )
    await _send_tournament_status(
        callback,
        prefix=prefix,
        tournament=updated,
    )


@router.message(AdminStates.waiting_tournament_max)
async def save_tournament_max(message: Message, state: FSMContext) -> None:
    """Admin kiritgan istalgan qatnashchilar sonini saqlaydi."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await state.clear()
        await _reply_denied(message)
        return
    item = _current_tournament()
    if item is None:
        await state.clear()
        await message.answer("⚠️ Faol turnir topilmadi.", reply_markup=panel_keyboard())
        return
    try:
        value = int((message.text or "").strip().replace(" ", ""))
        updated = get_tournament_store().set_max_participants(item.id, value)
    except (ValueError, TournamentError) as exc:
        await message.answer(
            f"⚠️ {escape(str(exc))}", reply_markup=tournament_back_keyboard()
        )
        return
    await state.clear()
    await message.answer(
        tournament_status_text(updated), reply_markup=tournament_keyboard(updated)
    )


@router.message(AdminStates.waiting_tournament_time)
async def save_tournament_time(message: Message, state: FSMContext) -> None:
    """Admin kiritgan boshlanish vaqtini saqlaydi."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await state.clear()
        await _reply_denied(message)
        return
    item = _current_tournament()
    if item is None:
        await state.clear()
        await message.answer("⚠️ Faol turnir topilmadi.", reply_markup=panel_keyboard())
        return
    try:
        updated = get_tournament_store().set_start_time(
            item.id, (message.text or "").strip()
        )
    except TournamentError as exc:
        await message.answer(
            f"⚠️ {escape(str(exc))}", reply_markup=tournament_back_keyboard()
        )
        return
    await state.clear()
    await message.answer(
        tournament_status_text(updated), reply_markup=tournament_keyboard(updated)
    )


@router.message(AdminStates.waiting_tournament_room)
async def save_tournament_room(message: Message, state: FSMContext) -> None:
    """Admin kiritgan xona havolasini saqlaydi."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await state.clear()
        await _reply_denied(message)
        return
    item = _current_tournament()
    if item is None:
        await state.clear()
        await message.answer("⚠️ Faol turnir topilmadi.", reply_markup=panel_keyboard())
        return
    try:
        updated = get_tournament_store().set_room_link(
            item.id, (message.text or "").strip()
        )
    except TournamentError as exc:
        await message.answer(
            f"⚠️ {escape(str(exc))}", reply_markup=tournament_back_keyboard()
        )
        return
    await state.clear()
    await message.answer(
        tournament_status_text(updated), reply_markup=tournament_keyboard(updated)
    )


@router.message(AdminStates.waiting_tournament_prize)
async def save_tournament_prize(message: Message, state: FSMContext) -> None:
    """Admin kiritgan sovrin miqdorini saqlaydi."""
    if message.from_user is None or not is_admin(message.from_user.id):
        await state.clear()
        await _reply_denied(message)
        return
    item = _current_tournament()
    if item is None:
        await state.clear()
        await message.answer("⚠️ Faol turnir topilmadi.", reply_markup=panel_keyboard())
        return
    try:
        updated = get_tournament_store().set_prize_pool(
            item.id, int((message.text or "").strip().replace(" ", ""))
        )
    except (ValueError, TournamentError) as exc:
        await message.answer(
            f"⚠️ {escape(str(exc))}", reply_markup=tournament_back_keyboard()
        )
        return
    await state.clear()
    await message.answer(
        tournament_status_text(updated), reply_markup=tournament_keyboard(updated)
    )
