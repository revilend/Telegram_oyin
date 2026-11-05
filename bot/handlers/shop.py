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
from bot.handlers.admin import is_admin
from core.economy import (
    COIN_PACKAGES,
    EconomyError,
    format_price,
    get_economy,
    package_price,
)
from core.settings import format_card_number, get_settings_store

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
                text=f"{format_price(coins)} tanga — {format_price(price)} söm",
                callback_data=f"{PACK_PREFIX}{coins}",
            )
        ]
        for coins, price in COIN_PACKAGES.items()
    ]
    rows.append([InlineKeyboardButton(text="❌ Bekor qiliş", callback_data=CANCEL_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shop_text() -> str:
    """Do'konning birinchi xabari."""
    return (
        "🪙 <b>Tangalar dökoni</b>\n\n"
        "Tangalar Mini App'da boosterlar uçun işlatiladi.\n"
        "Kerakli paketni tanlang:\n\n"
        + "\n".join(
            f"• <b>{format_price(coins)} tanga</b> — {format_price(price)} söm"
            for coins, price in COIN_PACKAGES.items()
        )
    )


def payment_text(coins: int, price: int) -> str:
    """Karta ma'lumotlari (``system_settings``dan) va chek yuborish ko'rsatmasi."""
    number, holder = get_settings_store().payment_card()
    return (
        "💳 <b>Tölov uçun karta</b>\n"
        f"<code>{escape(format_card_number(number) or 'Karta kiritilmagan')}</code>"
        f" ({escape(holder or 'Karta egasi kiritilmagan')})\n"
        f"Summa: <b>{format_price(price)} söm</b>\n\n"
        "Tölovni amalga oşirgaç, çek (skrinşot) rasmini şu yerga yuboring!"
    )


def receipt_caption(payment, username: str, full_name: str) -> str:
    """Admin ko'radigan chek izohi."""
    return (
        "🧾 <b>Yangi tölov çeki</b>\n\n"
        f"👤 {escape(full_name or 'Ismsiz')}"
        f" (@{escape(username) if username else 'username yöq'})\n"
        f"🆔 <code>{payment.user_id}</code>\n"
        f"🪙 {format_price(payment.package_coins)} tanga\n"
        f"💵 {format_price(payment.price_uzs)} söm\n"
        f"🔖 Çek: <code>{payment.id}</code>"
    )


def review_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlaş", callback_data=f"{PAY_OK_PREFIX}{request_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Rad etiş", callback_data=f"{PAY_NO_PREFIX}{request_id}"
                ),
            ]
        ]
    )


def _shop_ready() -> bool:
    """To'lov uchun karta (``system_settings``) va admin sozlanganmi?"""
    number, holder = get_settings_store().payment_card()
    return bool(number and holder and get_config().admin_id)


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
            "⚠️ Tölov hozirça sozlanmagan. Administrator «👑 Admin panel» → "
            "«💳 Karta raqamini sozlaş» orqali kartani kiritişi kerak."
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


async def send_shop(message: Message, state: FSMContext | None = None) -> None:
    """Do'kon xabarini yuboradi (``/shop`` va pastki menyu uchun umumiy)."""
    if state is not None:
        await state.clear()
    await message.answer(shop_text(), reply_markup=packages_keyboard())


@router.message(F.chat.type == "private", Command("shop"))
async def shop_command(message: Message, state: FSMContext) -> None:
    """/shop — shaxsiy chatda tanga paketlari."""
    await send_shop(message, state)


@router.message(Command("shop"))
async def shop_group(message: Message) -> None:
    """Guruhda /shop — shaxsiy chatga yo'naltirish."""
    await message.answer(
        "🪙 Tangalar dökoni şaxsiy çatda işlaydi. Botga ötib /shop yuboring."
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
        await callback.answer("Notöğri paket.", show_alert=True)
        return
    await _begin_payment(callback, state, coins)


@router.callback_query(F.data == CANCEL_CALLBACK)
async def cancel_payment(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Bekor qilindi")
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text("❌ Tölov bekor qilindi.")
        except TelegramAPIError:
            pass


def receipt_file_id(message: Message) -> str | None:
    """Chek fayli id'sini oladi (rasm yoki hujjat)."""
    if message.photo:
        return message.photo[-1].file_id
    if message.document:
        return message.document.file_id
    return None


async def _send_receipt_to_admin(message: Message, payment) -> None:
    """Chekni adminga rasm yoki hujjat sifatida yuboradi."""
    config = get_config()
    if not config.admin_id:
        raise RuntimeError("ADMIN_ID sozlanmagan")
    user = message.from_user
    caption = receipt_caption(
        payment,
        (user.username or "") if user is not None else "",
        (user.full_name if user is not None else "") or "",
    )
    keyboard = review_keyboard(payment.id)
    if message.photo:
        try:
            await message.bot.send_photo(
                chat_id=config.admin_id,
                photo=payment.receipt_file_id,
                caption=caption,
                reply_markup=keyboard,
            )
            return
        except TelegramAPIError:
            logger.exception(
                "Çekni rasm sifatida yuborib bölmadi: %s", payment.id
            )
    try:
        await message.bot.send_document(
            chat_id=config.admin_id,
            document=payment.receipt_file_id,
            caption=caption,
            reply_markup=keyboard,
        )
        return
    except TelegramAPIError:
        logger.exception(
            "Çekni hujjat sifatida yuborib bölmadi: %s", payment.id
        )
    # Oxirgi chora: fayl yuborilmasa ham chek matni va tasdiqlash tugmalari
    # adminga yetib boradi — chek hech qachon yo'qolmaydi.
    await message.bot.send_message(
        chat_id=config.admin_id,
        text=caption,
        reply_markup=keyboard,
    )


@router.message(ShopStates.waiting_receipt, F.photo | F.document)
async def receipt_file(message: Message, state: FSMContext) -> None:
    """Chek (rasm yoki hujjat)ni qabul qilib, adminga yuboradi."""
    try:
        data = await state.get_data()
        coins = data.get("package_coins")
        file_id = receipt_file_id(message)
        user = message.from_user
        if not coins or not file_id or user is None:
            await message.answer(
                "⚠️ Paket aniqlanmadi. /shop orqali qaytadan boşlang."
            )
            await state.clear()
            return

        if not get_config().admin_id:
            await message.answer("⚠️ ADMIN_ID sozlanmagan, çekni yuborib bölmaydi.")
            return

        payment = get_economy().create_payment(
            user_id=user.id,
            username=user.username or "",
            full_name=user.full_name or "",
            package_coins=int(coins),
            receipt_file_id=file_id,
        )
    except Exception:  # foydalanuvchi jim qolmasligi kerak
        logger.exception("Çekni qayta işlaşda xatolik")
        # Texnik tafsilot (PGRST204 va h.k.) foydalanuvchiga ko'rsatilmaydi.
        await message.answer(
            "⚠️ Çekni qabul qilişda vaqtinça xatolik yuz berdi. "
            "Iltimos, qayta yuboring yoki administratorga yozing."
        )
        return

    await state.clear()
    await message.answer(
        "✅ Çekingiz qabul qilindi! Administrator tasdiqlaşini kuting."
    )

    try:
        await _send_receipt_to_admin(message, payment)
    except Exception:
        logger.exception("Çekni adminga yuborib bölmadi: %s", payment.id)
        await message.answer(
            "⚠️ Çek saqlandi, ammo adminga yuborişda vaqtinça xatolik yuz berdi. "
            "Administrator tez orada körib çiqadi."
        )


@router.message(ShopStates.waiting_receipt)
async def receipt_expected(message: Message) -> None:
    """Matn kelsa, chekni rasm yoki fayl sifatida so'raydi."""
    await message.answer(
        "📸 Iltimos, çekni rasm (skrinşot) yoki PDF fayl körinişida "
        "yuboring. Bekor qiliş uçun /cancel yuboring."
    )


async def _review(callback: CallbackQuery, approve: bool) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Bu amal faqat admin uçun.", show_alert=True)
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
            f"✅ Tölovingiz tasdiqlandi! Hisobingizga "
            f"+{format_price(payment.package_coins)} tanga qöşildi 🎉"
        )
        admin_note = "✅ Tasdiqlandi"
    else:
        user_text = (
            "❌ Tölovingiz rad etildi. Savollar bölsa administrator bilan "
            "boğlaning."
        )
        admin_note = "❌ Rad etildi"

    await callback.answer("Bajarildi")
    if isinstance(callback.message, Message):
        old_caption = callback.message.caption or "🧾 Tölov çeki"
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
        logger.exception("Tölov natijasini öyinçiga yuborib bölmadi: %s", payment.user_id)


@router.callback_query(F.data.startswith(PAY_OK_PREFIX))
async def approve_payment(callback: CallbackQuery) -> None:
    await _review(callback, approve=True)


@router.callback_query(F.data.startswith(PAY_NO_PREFIX))
async def reject_payment(callback: CallbackQuery) -> None:
    await _review(callback, approve=False)
