"""Admin panel: statistika, karta sozlamalari, cheklar, tanga va broadcast.

Panel to'liq inline tugmalar bilan ishlaydi:

* 💳 Karta raqamini sozlash — karta ``system_settings`` jadvaliga saqlanadi;
* 📥 Kutilayotgan to'lovlar — tasdiqlanmagan cheklar navbat bilan chiqadi;
* ➕ Foydalanuvchiga tanga berish — qo'lda balans to'ldirish;
* 📢 Hammaga xabar — ro'yxatdan o'tgan o'yinchilarga e'lon.
"""

from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import get_config
from core.economy import EconomyError, format_price, get_economy
from core.settings import (
    SettingsError,
    format_card_number,
    get_settings_store,
    parse_card_line,
)
from engine.game_manager import get_default_manager

logger = logging.getLogger(__name__)

router = Router(name="admin")

CARD_CALLBACK = "admin_card"
PENDING_CALLBACK = "admin_pending"
GIVE_CALLBACK = "admin_give"
PROMO_CALLBACK = "admin_promo"
BROADCAST_CALLBACK = "admin_broadcast"
BACK_CALLBACK = "admin_back"

CARD_PROMPT = (
    "💳 <b>Karta raqamini sozlash</b>\n\n"
    "Karta raqami va egasining ismini yuboring "
    "(Masalan: <code>9860123456789012 Ali Valiyev</code>):"
)
GIVE_PROMPT = (
    "➕ <b>Foydalanuvchiga tanga berish</b>\n\n"
    "O'yinchi ID raqami va tanga miqdorini yuboring "
    "(Masalan: <code>123456789 500</code>):"
)
PROMO_PROMPT = (
    "🎟 <b>Promo kod yaratish</b>\n\n"
    "Format: <code>KOD TANGA [ISHLATISHLAR]</code>\n"
    "Masalan: <code>YANGIYIL 500 20</code> — 500 tanga, 20 marta ishlatiladi."
)
BROADCAST_PROMPT = (
    "📢 <b>Hammaga xabar</b>\n\n"
    "Yuboriladigan xabar matnini yozing:"
)


class AdminStates(StatesGroup):
    """Admin panel ichidagi kiritish holatlari."""

    waiting_card = State()
    waiting_give = State()
    waiting_promo = State()
    waiting_broadcast = State()


def is_admin(user_id: int) -> bool:
    """ADMIN_ID bilan mos kelsa yoki `users.role` ``admin`` bo'lsa ruxsat beradi."""
    config = get_config()
    if config.admin_id and int(user_id) == config.admin_id:
        return True
    try:
        return get_economy().is_admin_user(int(user_id))
    except Exception:
        logger.exception("`users` jadvalida rolni tekshirib bo'lmadi: %s", user_id)
        return False


async def _reply_denied(message: Message) -> None:
    await message.answer("⛔ Bu buyruq faqat administrator uchun.")


def panel_keyboard() -> InlineKeyboardMarkup:
    """Admin panelning inline tugmalari."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Karta raqamini sozlash",
                    callback_data=CARD_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📥 Kutilayotgan to'lovlar (Cheklar)",
                    callback_data=PENDING_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Foydalanuvchiga tanga berish",
                    callback_data=GIVE_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎟 Promo kod yaratish",
                    callback_data=PROMO_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Hammaga xabar (Broadcast)",
                    callback_data=BROADCAST_CALLBACK,
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
    return (
        "🛠 <b>Admin panel</b>\n\n"
        f"👥 Jami o'yinchilar: <b>{stats['users']}</b>\n"
        f"🪙 Umumiy xarid qilingan tangalar: <b>{format_price(stats['coins_purchased'])}</b>\n"
        f"💰 Balanslardagi tangalar: <b>{format_price(stats['coins_in_balance'])}</b>\n"
        f"🏠 Faol xonalar: <b>{stats['active_rooms']}</b>\n"
        f"🗂 Jami xonalar: <b>{stats['total_rooms']}</b>\n\n"
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
        await message.answer("⚠️ Statistikani yuklab bo'lmadi.")
        return
    await message.answer(text, reply_markup=panel_keyboard())


@router.callback_query(F.data == BACK_CALLBACK)
async def back_to_panel(callback: CallbackQuery, state: FSMContext) -> None:
    """«⬅️ Orqaga» — holatni tozalab, panelni qaytaradi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uchun.", show_alert=True)
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
        await callback.answer("⛔ Bu amal faqat admin uchun.", show_alert=True)
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
        logger.exception("Karta ma'lumotlarini saqlab bo'lmadi")
        await message.answer(
            "⚠️ Karta saqlanmadi. Birozdan keyin qayta urinib ko'ring.",
            reply_markup=back_keyboard(),
        )
        return

    await state.clear()
    await message.answer(
        "✅ <b>Karta saqlandi!</b>\n\n"
        f"💳 <code>{escape(format_card_number(stored_number))}</code>\n"
        f"👤 {escape(stored_holder)}\n\n"
        "Endi do'kon (/shop) xaridorlarga shu kartani ko'rsatadi.",
        reply_markup=panel_keyboard(),
    )


# ----------------------------------------------------------------------
# 📥 Kutilayotgan to'lovlar
# ----------------------------------------------------------------------
@router.callback_query(F.data == PENDING_CALLBACK)
async def show_pending_payments(callback: CallbackQuery) -> None:
    """Barcha tasdiqlanmagan cheklarni navbat bilan ko'rsatadi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uchun.", show_alert=True)
        return
    await callback.answer()

    # Lokal import: `shop` moduli `admin.is_admin`ni import qiladi.
    from bot.handlers import shop

    chat_id = callback.from_user.id
    try:
        payments = get_economy().list_pending_payments()
    except Exception:
        logger.exception("Kutilayotgan cheklarni yuklab bo'lmadi")
        await callback.bot.send_message(
            chat_id, "⚠️ Cheklarni yuklab bo'lmadi. Qayta urinib ko'ring."
        )
        return

    if not payments:
        await callback.bot.send_message(
            chat_id, "📥 Hozircha kutilayotgan to'lovlar yo'q."
        )
        return

    await callback.bot.send_message(
        chat_id, f"📥 <b>Kutilayotgan to'lovlar:</b> {len(payments)} ta"
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
# ➕ Foydalanuvchiga tanga berish
# ----------------------------------------------------------------------
@router.callback_query(F.data == GIVE_CALLBACK)
async def ask_give_coins(callback: CallbackQuery, state: FSMContext) -> None:
    """Tanga berish uchun ID va miqdorni so'raydi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uchun.", show_alert=True)
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
            "user_id va miqdor musbat butun son bo'lishi kerak.",
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
        logger.exception("Tanga qo'shib bo'lmadi: %s", user_id)
        return "⚠️ Tanga qo'shilmadi. Qayta urinib ko'ring."
    return (
        f"✅ <code>{user_id}</code>ga <b>+{format_price(amount)}</b> tanga qo'shildi.\n"
        f"Yangi balans: <b>{format_price(account.coins)}</b> tanga."
    )


# ----------------------------------------------------------------------
# 🎟 Promo kod yaratish
# ----------------------------------------------------------------------
@router.callback_query(F.data == PROMO_CALLBACK)
async def ask_promo(callback: CallbackQuery, state: FSMContext) -> None:
    """Promo kod parametrlarini so'raydi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uchun.", show_alert=True)
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
            "(ixtiyoriy) ishlatishlar soni.",
            reply_markup=back_keyboard(),
        )
        return
    try:
        coins = int(tokens[1].replace(" ", ""))
        max_uses = int(tokens[2]) if len(tokens) == 3 else 1
    except ValueError:
        await message.answer(
            "Tanga miqdori va ishlatishlar soni butun son bo'lishi kerak.",
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
        logger.exception("Promo kod yaratib bo'lmadi")
        await message.answer(
            "⚠️ Promo kod yaratilmadi. Qayta urinib ko'ring.",
            reply_markup=back_keyboard(),
        )
        return

    await state.clear()
    await message.answer(
        "✅ <b>Promo kod yaratildi!</b>\n\n"
        f"🎟 <code>{escape(promo.code)}</code>\n"
        f"🪙 {format_price(promo.coins)} tanga\n"
        f"🔁 {promo.max_uses} marta ishlatiladi\n\n"
        "O'yinchilar kodni botdagi «🎟 Promo kod» tugmasi yoki Mini App'dagi "
        "do'kon orqali kiritadi.",
        reply_markup=panel_keyboard(),
    )


# ----------------------------------------------------------------------
# 📢 Hammaga xabar
# ----------------------------------------------------------------------
@router.callback_query(F.data == BROADCAST_CALLBACK)
async def ask_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    """Broadcast matnini so'raydi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uchun.", show_alert=True)
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
        logger.exception("Foydalanuvchilar ro'yxatini olib bo'lmadi")
        return "⚠️ Foydalanuvchilar ro'yxatini olib bo'lmadi."
    if not user_ids:
        return "ℹ️ Hali ro'yxatdan o'tgan o'yinchilar yo'q."

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
            logger.exception("Broadcast yuborishda xatolik: %s", user_id)
        await asyncio.sleep(0.04)

    return (
        f"📣 Broadcast tugadi: <b>{sent}</b> ta yuborildi, "
        f"<b>{failed}</b> ta yetkazilmadi."
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
        await message.answer("user_id va miqdor musbat butun son bo'lishi kerak.")
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
        "👤 <b>O'yinchi</b>\n"
        f"Ism: {escape(name)}\n"
        f"Username: {'@' + escape(account.username) if account.username else '—'}\n"
        f"🆔 <code>{account.user_id}</code>\n"
        f"🪙 Balans: <b>{format_price(account.coins)}</b> tanga\n"
        f"🛒 Xarid qilingan: <b>{format_price(account.total_purchased)}</b> tanga\n"
        f"🎮 O'ynagan o'yinlari: <b>{account.games_played}</b>\n"
        f"🏆 G'alabalari: <b>{account.wins}</b>"
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
