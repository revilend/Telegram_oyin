"""Tangalar do'koni, chek qabul qilish va admin tasdiqlash handlerlari."""

from __future__ import annotations

import logging
import re
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import get_config
from core.economy import (
    COIN_PACKAGES,
    EconomyError,
    format_price,
    get_economy,
    package_price,
)

logger = logging.getLogger(__name__)

router = Router(name="shop")

PACK_PREFIX = "shop_pack_"
CANCEL_CALLBACK = "shop_cancel"
PAY_OK_PREFIX = "pay_ok_"
PAY_NO_PREFIX = "pay_no_"

SHOP_START_PATTERN = re.compile(r"^/start(?:@\w+)?\s+shop(?:_(\d+))?\s*$")


class ShopStates(StatesGroup):
    """Chek rasmini kutish holati."""

    waiting_receipt = State()


def packages_keyboard() -> InlineKeyboardMarkup:
    """Tanga paketlari tugmalari."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{format_price(coins)} tanga — {format_price(price)} so'm",
                callback_data=f"{PACK_PREFIX}{coins}",
            )
        ]
        for coins, price in COIN_PACKAGES.items()
    ]
    rows.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data=CANCEL_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shop_text() -> str:
    """Do'konning birinchi xabari."""
    return (
        "🪙 <b>Tangalar do'koni</b>\n\n"
        "Tangalar Mini App'da boosterlar uchun ishlatiladi.\n"
        "Kerakli paketni tanlang:\n\n"
        + "\n".join(
            f"• <b>{format_price(coins)} tanga</b> — {format_price(price)} so'm"
            for coins, price in COIN_PACKAGES.items()
        )
    )


def payment_text(coins: int, price: int) -> str:
    """Karta ma'lumotlari va chek yuborish ko'rsatmasi."""
    config = get_config()
    return (
        "💳 <b>To'lov uchun karta</b>\n"
        f"<code>{escape(config.card_number or 'Karta kiritilmagan')}</code>"
        f" ({escape(config.card_holder or 'Karta egasi kiritilmagan')})\n"
        f"Summa: <b>{format_price(price)} so'm</b>\n\n"
        "To'lovni amalga oshirgach, chek (skrinshot) rasmini shu yerga yuboring!"
    )


def receipt_caption(payment, username: str, full_name: str) -> str:
    """Admin ko'radigan chek izohi."""
    return (
        "🧾 <b>Yangi to'lov cheki</b>\n\n"
        f"👤 {escape(full_name or 'Ismsiz')}"
        f" (@{escape(username) if username else 'username yo‘q'})\n"
        f"🆔 <code>{payment.user_id}</code>\n"
        f"🪙 {format_price(payment.package_coins)} tanga\n"
        f"💵 {format_price(payment.price_uzs)} so'm\n"
        f"🔖 Chek: <code>{payment.id}</code>"
    )


def review_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash", callback_data=f"{PAY_OK_PREFIX}{request_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish", callback_data=f"{PAY_NO_PREFIX}{request_id}"
                ),
            ]
        ]
    )


def _shop_ready() -> bool:
    config = get_config()
    return bool(config.card_number and config.card_holder and config.admin_id)


async def _begin_payment(event: Message | CallbackQuery, state: FSMContext, coins: int) -> None:
    """Paketni tanlab, FSM holatini va karta xabarini ko'rsatadi."""
    try:
        price = package_price(coins)
    except EconomyError as exc:
        text = f"⚠️ {escape(str(exc))}"
        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
        else:
            await event.answer(text)
        return

    if not _shop_ready():
        text = (
            "⚠️ To'lov hozircha sozlanmagan. Administrator CARD_NUMBER, "
            "CARD_HOLDER va ADMIN_ID qiymatlarini kiritishi kerak."
        )
        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
        else:
            await event.answer(text)
        return

    await state.set_state(ShopStates.waiting_receipt)
    await state.update_data(package_coins=coins, price_uzs=price)
    text = payment_text(coins, price)

    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
        if isinstance(message, Message):
            try:
                await message.edit_text(text)
                return
            except TelegramAPIError:
                pass
        await event.bot.send_message(event.from_user.id, text)
    else:
        await event.answer(text)


@router.message(F.chat.type == "private", Command("shop"))
async def shop_command(message: Message, state: FSMContext) -> None:
    """/shop — shaxsiy chatda tanga paketlari."""
    await state.clear()
    await message.answer(shop_text(), reply_markup=packages_keyboard())


@router.message(Command("shop"))
async def shop_group(message: Message) -> None:
    """Guruhda /shop — shaxsiy chatga yo'naltirish."""
    await message.answer(
        "🪙 Tangalar do'koni shaxsiy chatda ishlaydi. Botga o'tib /shop yuboring."
    )


@router.message(F.chat.type == "private", F.text.regexp(SHOP_START_PATTERN))
async def shop_deep_link(message: Message, state: FSMContext) -> None:
    """Mini App'dan `/start shop_500` havolasi orqali kelgan paket."""
    match = SHOP_START_PATTERN.match(message.text or "")
    coins = int(match.group(1)) if match and match.group(1) else None
    if coins is None:
        await message.answer(shop_text(), reply_markup=packages_keyboard())
        return
    await _begin_payment(message, state, coins)


@router.callback_query(F.data.startswith(PACK_PREFIX))
async def select_package(callback: CallbackQuery, state: FSMContext) -> None:
    """Paket tugmasi bosilganda karta ma'lumotlarini ko'rsatadi."""
    raw = (callback.data or "")[len(PACK_PREFIX) :]
    try:
        coins = int(raw)
    except ValueError:
        await callback.answer("Noto'g'ri paket.", show_alert=True)
        return
    await _begin_payment(callback, state, coins)


@router.callback_query(F.data == CANCEL_CALLBACK)
async def cancel_payment(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Bekor qilindi")
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text("❌ To'lov bekor qilindi.")
        except TelegramAPIError:
            pass


@router.message(ShopStates.waiting_receipt, F.photo)
async def receipt_photo(message: Message, state: FSMContext) -> None:
    """Chek rasmini qabul qilib, adminga yuboradi."""
    data = await state.get_data()
    coins = data.get("package_coins")
    if not coins or not message.photo:
        await message.answer("⚠️ Paket aniqlanmadi. /shop orqali qaytadan boshlang.")
        await state.clear()
        return

    config = get_config()
    if not config.admin_id:
        await message.answer("⚠️ ADMIN_ID sozlanmagan, chekni yuborib bo'lmaydi.")
        return

    user = message.from_user
    economy = get_economy()
    try:
        payment = economy.create_payment(
            user_id=user.id,
            username=user.username or "",
            full_name=user.full_name,
            package_coins=int(coins),
            receipt_file_id=message.photo[-1].file_id,
        )
    except EconomyError as exc:
        logger.exception("Chekni saqlab bo'lmadi")
        await message.answer(f"⚠️ Chekni qabul qilib bo'lmadi: {escape(str(exc))}")
        return

    await state.clear()
    await message.answer(
        "✅ Chek qabul qilindi! Administrator tekshirib, tasdiqlagach tangalar "
        "balansingizga qo'shiladi."
    )

    caption = receipt_caption(payment, user.username or "", user.full_name)
    try:
        await message.bot.send_photo(
            chat_id=config.admin_id,
            photo=payment.receipt_file_id,
            caption=caption,
            reply_markup=review_keyboard(payment.id),
        )
    except TelegramAPIError:
        logger.exception("Chekni adminga yuborib bo'lmadi: %s", payment.id)
        await message.answer(
            "⚠️ Chek saqlandi, ammo adminga yuborishda xatolik bo'ldi. "
            "Administrator bilan bog'laning."
        )


@router.message(ShopStates.waiting_receipt)
async def receipt_expected(message: Message) -> None:
    """Rasm o'rniga matn kelsa, qayta so'raydi."""
    await message.answer("📸 Iltimos, chekni rasm (skrinshot) ko'rinishida yuboring.")


async def _review(callback: CallbackQuery, approve: bool) -> None:
    config = get_config()
    if not config.admin_id or callback.from_user.id != config.admin_id:
        await callback.answer("⛔ Bu amal faqat admin uchun.", show_alert=True)
        return

    prefix = PAY_OK_PREFIX if approve else PAY_NO_PREFIX
    request_id = (callback.data or "")[len(prefix) :]
    economy = get_economy()
    try:
        payment = (
            economy.approve_payment(request_id, callback.from_user.id)
            if approve
            else economy.reject_payment(request_id, callback.from_user.id)
        )
    except EconomyError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    if approve:
        user_text = (
            f"✅ To'lovingiz tasdiqlandi! Hisobingizga "
            f"+{format_price(payment.package_coins)} tanga qo'shildi 🎉"
        )
        admin_note = "✅ Tasdiqlandi"
    else:
        user_text = (
            "❌ To'lovingiz rad etildi. Savollar bo'lsa administrator bilan "
            "bog'laning."
        )
        admin_note = "❌ Rad etildi"

    await callback.answer("Bajarildi")
    if isinstance(callback.message, Message):
        old_caption = callback.message.caption or "🧾 To'lov cheki"
        try:
            await callback.message.edit_caption(
                caption=f"{old_caption}\n\n{admin_note}",
                reply_markup=None,
            )
        except TelegramAPIError:
            pass
    try:
        await callback.bot.send_message(payment.user_id, user_text)
    except TelegramAPIError:
        logger.exception("To'lov natijasini o'yinchiga yuborib bo'lmadi: %s", payment.user_id)


@router.callback_query(F.data.startswith(PAY_OK_PREFIX))
async def approve_payment(callback: CallbackQuery) -> None:
    await _review(callback, approve=True)


@router.callback_query(F.data.startswith(PAY_NO_PREFIX))
async def reject_payment(callback: CallbackQuery) -> None:
    await _review(callback, approve=False)
