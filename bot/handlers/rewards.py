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
from core.i18n import all_button_texts, resolve_language, t

logger = logging.getLogger(__name__)

router = Router(name="rewards")

PRIVATE = F.chat.type == "private"

PROMO_PROMPT = t("uz", "promo_prompt")


class RewardStates(StatesGroup):
    """Promo kod kutilayotgan holat."""

    waiting_promo = State()


def bonus_table_text(streak: int, language: str = "uz") -> str:
    """1–7 kunlik mukofotlar jadvali (hozirgi kun belgilanadi)."""
    lines = [t(language, "bonus_table_title")]
    for day, amount in enumerate(DAILY_BONUS_TABLE, start=1):
        label = t(language, "bonus_day", day=day)
        if day == 7:
            label += t(language, "bonus_day_big")
        mark = (
            t(language, "bonus_now")
            if day == min(max(1, int(streak)), 7)
            else ""
        )
        lines.append(f"{label}: +{format_price(amount)} 🪙{mark}")
    return "\n".join(lines)


def bonus_text(claim: DailyBonusClaim, language: str = "uz") -> str:
    """Muvaffaqiyatli bonus xabari: seriya, jadval va ertangi mukofot."""
    next_amount = claim.next_amount or claim.amount
    return t(
        language,
        "bonus_claim",
        streak=claim.streak,
        amount=format_price(claim.amount),
        balance=format_price(claim.account.coins),
        table=bonus_table_text(claim.streak, language),
        next=format_price(next_amount),
    )


def bonus_wait_text(
    reason: str, status: DailyBonusStatus, language: str = "uz"
) -> str:
    """Bonus hali mavjud bo'lmaganda ko'rsatiladigan xabar."""
    next_amount = status.next_amount or status.amount
    return t(
        language,
        "bonus_wait",
        streak=status.streak,
        reason=escape(reason),
        next=format_price(next_amount),
        table=bonus_table_text(status.streak, language),
    )


@router.message(PRIVATE, Command("bonus"))
@router.message(PRIVATE, F.text.in_(all_button_texts("bonus")))
async def claim_bonus(message: Message) -> None:
    """Kunlik bonusni oladi yoki qolgan vaqtni aytadi."""
    user = message.from_user
    if user is None:
        return
    language = resolve_language(user.id, getattr(user, "language_code", None))
    economy = get_economy()
    try:
        claim = economy.claim_daily_bonus(user.id)
    except EconomyError as exc:
        try:
            status = economy.daily_bonus_status(user.id)
            wait_text = bonus_wait_text(str(exc), status, language)
        except Exception:
            logger.exception("Bonus holatini öqib bölmadi: %s", user.id)
            wait_text = f"⏳ {escape(str(exc))}"
        await message.answer(wait_text)
        return
    except Exception:
        logger.exception("Kunlik bonusni berib bölmadi: %s", user.id)
        await message.answer(t(language, "bonus_error"))
        return
    await message.answer(bonus_text(claim, language))


@router.message(PRIVATE, Command("promo"))
@router.message(PRIVATE, F.text.in_(all_button_texts("promo")))
async def ask_promo(message: Message, state: FSMContext) -> None:
    """Promo kod kiritishni so'raydi."""
    user = message.from_user
    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    await state.set_state(RewardStates.waiting_promo)
    await message.answer(t(language, "promo_prompt"))


@router.message(RewardStates.waiting_promo)
async def save_promo(message: Message, state: FSMContext) -> None:
    """Kiritilgan promo kodni ishlatadi."""
    user = message.from_user
    code = (message.text or "").strip()
    if user is None:
        return
    language = resolve_language(user.id, getattr(user, "language_code", None))
    if not code:
        await message.answer(t(language, "promo_send_text"))
        return
    try:
        result = get_economy().redeem_promo_code(user.id, code)
    except EconomyError as exc:
        await message.answer(
            t(language, "promo_invalid", error=escape(str(exc)))
        )
        return
    except Exception:
        logger.exception("Promo kodni işlatib bölmadi: %s", user.id)
        await message.answer(t(language, "promo_check_error"))
        return
    await state.clear()
    await message.answer(
        t(
            language,
            "promo_accepted",
            code=escape(result.code),
            coins=format_price(result.coins),
            balance=format_price(result.account.coins),
        )
    )
