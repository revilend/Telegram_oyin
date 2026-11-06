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
from core.shop import (
    CATALOG_BY_SLUG,
    SECTION_ORDER,
    SECTION_TITLES,
    SPIN,
    ShopError,
    get_shop_store,
)

logger = logging.getLogger(__name__)

router = Router(name="shop")

PACK_PREFIX = "shop_pack_"
CANCEL_CALLBACK = "shop_cancel"
PAY_OK_PREFIX = "pay_ok_"
PAY_NO_PREFIX = "pay_no_"

# Mega Store navigatsiyasi: bosh menyu → ikki bölum → buyumlar.
HOME_CALLBACK = "shop_home"
PAY_SECTION_CALLBACK = "shopsection_pay"
ITEMS_CALLBACK = "shopsection_items"
SECTION_PREFIX = "shopsec_"
BUY_PREFIX = "shopbuy_"
SPIN_CALLBACK = "shop_spin_wheel"

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
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=HOME_CALLBACK)])
    rows.append([InlineKeyboardButton(text="❌ Bekor qiliş", callback_data=CANCEL_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def balance_of(user_id: int) -> int:
    """Foydalanuvchining joriy tanga balansi."""
    return get_economy().ensure_user(int(user_id)).coins


def shop_text(user_id: int | None = None) -> str:
    """Do'konning bosh menyusi: ikki katta bölum."""
    lines = ["🪙 <b>Tangalar dökoni</b>", ""]
    if user_id is not None:
        lines.append(f"Balans: <b>{format_price(balance_of(user_id))}</b> tanga")
        lines.append("")
    lines.append("Kerakli bölumni tanlang:")
    return "\n".join(lines)


def shop_keyboard() -> InlineKeyboardMarkup:
    """Bosh menyu: tanga xaridi yoki buyumlar dökoni."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Tangalar xarid qiliş (Humo/Uzcard)",
                    callback_data=PAY_SECTION_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛍️ Buyumlar va Imkoniyatlar dökoni",
                    callback_data=ITEMS_CALLBACK,
                )
            ],
        ]
    )


def packages_text(user_id: int | None = None) -> str:
    """Tanga paketlari bölumi matni."""
    lines = ["💳 <b>Tangalar xarid qiliş</b>", ""]
    if user_id is not None:
        lines.append(f"Balans: <b>{format_price(balance_of(user_id))}</b> tanga")
        lines.append("")
    lines.append("Paketni tanlang — karta raqami va summa keyingi xabarda körinadi.")
    lines.append("")
    lines.extend(
        f"• <b>{format_price(coins)} tanga</b> — {format_price(price)} söm"
        for coins, price in COIN_PACKAGES.items()
    )
    return "\n".join(lines)


def items_text(user_id: int) -> str:
    """Buyumlar dökoni bosh sahifasi."""
    return (
        "🛍️ <b>Buyumlar va Imkoniyatlar dökoni</b>\n\n"
        f"Balans: <b>{format_price(balance_of(user_id))}</b> tanga\n\n"
        "Bölumni tanlang: ramkalar, unvonlar, boosterlar va çiptalar."
    )


def items_keyboard() -> InlineKeyboardMarkup:
    """Bölumlar ro'yxati va orqaga qaytish."""
    rows = [
        [InlineKeyboardButton(text=SECTION_TITLES[section], callback_data=f"{SECTION_PREFIX}{section}")]
        for section in SECTION_ORDER
        if any(item.section == section for item in CATALOG_BY_SLUG.values())
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=HOME_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def section_text(user_id: int, section: str) -> str:
    """Bitta bölumdagi buyumlar ro'yxati."""
    items = [item for item in CATALOG_BY_SLUG.values() if item.section == section]
    lines = [f"<b>{SECTION_TITLES.get(section, section)}</b>", ""]
    lines.append(f"Balans: <b>{format_price(balance_of(user_id))}</b> tanga")
    lines.append("")
    for item in items:
        lines.append(
            f"{item.emoji} <b>{item.title}</b> — {format_price(item.price)} tanga\n"
            f"<i>{item.description}</i>"
        )
    if section == SPIN:
        lines.append("")
        lines.append("Kuniga bir marta bepul; keyingi aylantiriş 20 tanga yoki çipta.")
    return "\n".join(lines)


def section_keyboard(section: str) -> InlineKeyboardMarkup:
    """Bölumdagi buyumlarni sotib olish tugmalari."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{item.emoji} {item.title} — {format_price(item.price)}",
                callback_data=f"{BUY_PREFIX}{item.slug}",
            )
        ]
        for item in CATALOG_BY_SLUG.values()
        if item.section == section
    ]
    if section == SPIN:
        rows.append(
            [InlineKeyboardButton(text="🎰 Aylantiriş", callback_data=SPIN_CALLBACK)]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=ITEMS_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    """Do'kon bosh menyusini yuboradi (``/shop`` va pastki menyu uchun)."""
    if state is not None:
        await state.clear()
    user_id = message.from_user.id if message.from_user is not None else None
    await message.answer(shop_text(user_id), reply_markup=shop_keyboard())


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
        await send_shop(message, state)
        return
    await _begin_payment(message, state, coins)


async def _show(callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
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


@router.callback_query(F.data == HOME_CALLBACK)
async def shop_home(callback: CallbackQuery) -> None:
    """Do'kon bosh menyusiga qaytish."""
    await callback.answer()
    await _show(
        callback, shop_text(callback.from_user.id), shop_keyboard()
    )


@router.callback_query(F.data == PAY_SECTION_CALLBACK)
async def shop_pay_section(callback: CallbackQuery) -> None:
    """Tanga paketlari bölumi (Humo/Uzcard cheki)."""
    await callback.answer()
    await _show(
        callback, packages_text(callback.from_user.id), packages_keyboard()
    )


@router.callback_query(F.data == ITEMS_CALLBACK)
async def shop_items_section(callback: CallbackQuery) -> None:
    """Buyumlar va Imkoniyatlar dökoni bosh sahifasi."""
    await callback.answer()
    await _show(
        callback, items_text(callback.from_user.id), items_keyboard()
    )


@router.callback_query(F.data.startswith(SECTION_PREFIX))
async def shop_section(callback: CallbackQuery) -> None:
    """Bölumdagi buyumlarni körsatadi."""
    section = (callback.data or "")[len(SECTION_PREFIX) :]
    if section not in SECTION_TITLES:
        await callback.answer("Bölum topilmadi", show_alert=True)
        return
    await callback.answer()
    await _show(
        callback,
        section_text(callback.from_user.id, section),
        section_keyboard(section),
    )


@router.callback_query(F.data.startswith(BUY_PREFIX))
async def shop_buy_item(callback: CallbackQuery) -> None:
    """Buyumni tangalarga sotib oladi."""
    slug = (callback.data or "")[len(BUY_PREFIX) :]
    item = CATALOG_BY_SLUG.get(slug)
    if item is None:
        await callback.answer("Buyum topilmadi", show_alert=True)
        return
    try:
        result = get_shop_store().buy(callback.from_user.id, slug)
    except ShopError as exc:
        await callback.answer(f"⚠️ {exc}", show_alert=True)
        return
    await callback.answer(
        f"✅ {result.item.title} sotib olindi!\n"
        f"Balans: {format_price(result.account.coins)} tanga",
        show_alert=True,
    )
    await _show(
        callback,
        section_text(callback.from_user.id, item.section),
        section_keyboard(item.section),
    )


@router.callback_query(F.data == SPIN_CALLBACK)
async def shop_spin_wheel(callback: CallbackQuery) -> None:
    """Omad ğildiragini aylantiradi."""
    try:
        result = get_shop_store().spin(callback.from_user.id)
    except ShopError as exc:
        await callback.answer(f"⚠️ {exc}", show_alert=True)
        return
    reward = (
        f"+{format_price(result.segment.coins)} tanga"
        if result.segment.coins
        else result.segment.label
    )
    if result.free:
        source = "bepul aylantiriş"
    elif result.ticket_used:
        source = "çipta işlatildi"
    else:
        source = f"{format_price(result.expense)} tanga"
    await callback.answer(
        f"🎰 {result.segment.emoji} {reward}\n({source})",
        show_alert=True,
    )
    await _show(
        callback,
        section_text(callback.from_user.id, SPIN),
        section_keyboard(SPIN),
    )


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
