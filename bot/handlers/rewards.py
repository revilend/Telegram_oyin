"""Kunlik bonus va promo kodlar uchun bot handlerlari."""

from __future__ import annotations

import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.keyboards.main_menu import BONUS_BUTTON, PROMO_BUTTON
from core.economy import DailyBonusClaim, EconomyError, format_price, get_economy

logger = logging.getLogger(__name__)

router = Router(name="rewards")

PRIVATE = F.chat.type == "private"

PROMO_PROMPT = (
    "🎟 <b>Promo kod</b>\n\n"
    "Admin bergan kodni yuboring (masalan <code>WELCOME2026</code>).\n"
    "Har bir kod faqat bir marta ishlaydi."
)


class RewardStates(StatesGroup):
    """Promo kod kutilayotgan holat."""

    waiting_promo = State()


def bonus_text(claim: DailyBonusClaim) -> str:
    """Muvaffaqiyatli bonus xabari."""
    streak_line = (
        f"\n🔥 Ketma-ket kunlar: <b>{claim.streak}</b>"
        if claim.streak > 1
        else ""
    )
    return (
        "🎁 <b>Kunlik bonus olindi!</b>\n\n"
        f"🪙 <b>+{format_price(claim.amount)}</b> tanga hisobingizga qo'shildi."
        f"{streak_line}\n"
        f"💰 Balans: <b>{format_price(claim.account.coins)}</b> tanga\n\n"
        "Ertaga yana kelib, bonusni oling!"
    )


def bonus_wait_text(reason: str, coins: int) -> str:
    """Bonus hali mavjud bo'lmaganda ko'rsatiladigan xabar."""
    return (
        "🎁 <b>Kunlik bonus</b>\n\n"
        f"⏳ {escape(reason)}\n\n"
        f"💰 Balans: <b>{format_price(coins)}</b> tanga"
    )


@router.message(PRIVATE, Command("bonus"))
@router.message(PRIVATE, F.text == BONUS_BUTTON)
async def claim_bonus(message: Message) -> None:
    """Kunlik bonusni oladi yoki qolgan vaqtni aytadi."""
    user = message.from_user
    if user is None:
        return
    economy = get_economy()
    try:
        claim = economy.claim_daily_bonus(user.id)
    except EconomyError as exc:
        await message.answer(
            bonus_wait_text(str(exc), economy.get_user(user.id).coins)
        )
        return
    except Exception:
        logger.exception("Kunlik bonusni berib bo'lmadi: %s", user.id)
        await message.answer(
            "⚠️ Bonusni hozircha olib bo'lmadi. Birozdan keyin urinib ko'ring."
        )
        return
    await message.answer(bonus_text(claim))


@router.message(PRIVATE, Command("promo"))
@router.message(PRIVATE, F.text == PROMO_BUTTON)
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
            "Promo kodni matn ko'rinishida yuboring yoki /cancel yozing."
        )
        return
    try:
        result = get_economy().redeem_promo_code(user.id, code)
    except EconomyError as exc:
        await message.answer(
            f"⚠️ {escape(str(exc))}\n\nBoshqa kodni yuboring yoki /cancel yozing."
        )
        return
    except Exception:
        logger.exception("Promo kodni ishlatib bo'lmadi: %s", user.id)
        await message.answer(
            "⚠️ Kodni tekshirib bo'lmadi. Birozdan keyin urinib ko'ring."
        )
        return
    await state.clear()
    await message.answer(
        "🎉 <b>Promo kod qabul qilindi!</b>\n\n"
        f"🎟 <code>{escape(result.code)}</code>\n"
        f"🪙 <b>+{format_price(result.coins)}</b> tanga\n"
        f"💰 Balans: <b>{format_price(result.account.coins)}</b> tanga"
    )
