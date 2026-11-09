"""Kunlik bonus va promo kodlar uchun bot handlerlari."""

from __future__ import annotations

import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from core.economy import (
    DAILY_BONUS_TABLE,
    DailyBonusClaim,
    DailyBonusStatus,
    EconomyError,
    format_price,
    get_economy,
)
from core.i18n import all_button_texts

logger = logging.getLogger(__name__)

router = Router(name="rewards")

PRIVATE = F.chat.type == "private"

PROMO_PROMPT = (
    "🎟 <b>Promo kod</b>\n\n"
    "Admin bergan kodni yuboring (masalan <code>YANGIYIL</code>).\n"
    "Har bir foydalanuvçi kodni bir marta işlatadi."
)


class RewardStates(StatesGroup):
    """Promo kod kutilayotgan holat."""

    waiting_promo = State()


def bonus_table_text(streak: int) -> str:
    """1–7 kunlik mukofotlar jadvali (hozirgi kun belgilanadi)."""
    lines = ["📅 <b>Kunlik mukofotlar jadvali:</b>"]
    for day, amount in enumerate(DAILY_BONUS_TABLE, start=1):
        label = f"{day}-kun" + (" (Katta mukofot!)" if day == 7 else "")
        mark = " ← hozir" if day == min(max(1, int(streak)), 7) else ""
        lines.append(f"{label}: +{format_price(amount)} 🪙{mark}")
    return "\n".join(lines)


def bonus_text(claim: DailyBonusClaim) -> str:
    """Muvaffaqiyatli bonus xabari: seriya, jadval va ertangi mukofot."""
    next_amount = claim.next_amount or claim.amount
    return (
        "🎁 <b>Kunlik bonus olindi!</b>\n\n"
        f"🔥 Hozirgi seriya: <b>{claim.streak}-kun</b>\n"
        f"🪙 Olgan bonusingiz: <b>+{format_price(claim.amount)}</b> tanga\n"
        f"💰 Balans: <b>{format_price(claim.account.coins)}</b> tanga\n\n"
        f"{bonus_table_text(claim.streak)}\n\n"
        f"«Ertaga kirsangiz sizni <b>+{format_price(next_amount)}</b> tanga "
        "kutmoqda! Seriyani uzib qöymang!»"
    )


def bonus_wait_text(reason: str, status: DailyBonusStatus) -> str:
    """Bonus hali mavjud bo'lmaganda ko'rsatiladigan xabar."""
    next_amount = status.next_amount or status.amount
    return (
        "🎁 <b>Kunlik bonus</b>\n\n"
        f"🔥 Hozirgi seriya: <b>{status.streak}-kun</b>\n"
        f"⏳ {escape(reason)}\n\n"
        f"📅 Keyingi bonus: <b>+{format_price(next_amount)}</b> tanga\n\n"
        f"{bonus_table_text(status.streak)}\n\n"
        "Seriyani uzmaslik uçun ertaga ham kirib oling!"
    )


@router.message(PRIVATE, Command("bonus"))
@router.message(PRIVATE, F.text.in_(all_button_texts("bonus")))
async def claim_bonus(message: Message) -> None:
    """Kunlik bonusni oladi yoki qolgan vaqtni aytadi."""
    user = message.from_user
    if user is None:
        return
    economy = get_economy()
    try:
        claim = economy.claim_daily_bonus(user.id)
    except EconomyError as exc:
        try:
            status = economy.daily_bonus_status(user.id)
            wait_text = bonus_wait_text(str(exc), status)
        except Exception:
            logger.exception("Bonus holatini öqib bölmadi: %s", user.id)
            wait_text = f"⏳ {escape(str(exc))}"
        await message.answer(wait_text)
        return
    except Exception:
        logger.exception("Kunlik bonusni berib bölmadi: %s", user.id)
        await message.answer(
            "⚠️ Bonusni hozirça olib bölmadi. Birozdan keyin urinib köring."
        )
        return
    await message.answer(bonus_text(claim))


@router.message(PRIVATE, Command("promo"))
@router.message(PRIVATE, F.text.in_(all_button_texts("promo")))
async def ask_promo(message: Message, state: FSMContext) -> None:
    """Promo kod kiritishni so'raydi."""
    await state.set_state(RewardStates.waiting_promo)
    await message.answer(PROMO_PROMPT)


@router.message(RewardStates.waiting_promo)
async def save_promo(message: Message, state: FSMContext) -> None:
    """Kiritilgan promo kodni ishlatadi."""
    user = message.from_user
    code = (message.text or "").strip()
    if user is None:
        return
    if not code:
        await message.answer(
            "Promo kodni matn körinişida yuboring yoki /cancel yozing."
        )
        return
    try:
        result = get_economy().redeem_promo_code(user.id, code)
    except EconomyError as exc:
        await message.answer(
            f"⚠️ {escape(str(exc))}\n\nBoşqa kodni yuboring yoki /cancel yozing."
        )
        return
    except Exception:
        logger.exception("Promo kodni işlatib bölmadi: %s", user.id)
        await message.answer(
            "⚠️ Kodni tekşirib bölmadi. Birozdan keyin urinib köring."
        )
        return
    await state.clear()
    await message.answer(
        "🎉 <b>Promo kod qabul qilindi!</b>\n\n"
        f"🎟 <code>{escape(result.code)}</code>\n"
        f"🪙 <b>+{format_price(result.coins)}</b> tanga\n"
        f"💰 Balans: <b>{format_price(result.account.coins)}</b> tanga"
    )
