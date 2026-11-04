"""Doimiy pastki menyu tugmalari uchun handlerlar.

«👤 Mening profilim» ``bot.handlers.profile``da, «🏆 Reyting va Top»
``bot.handlers.leaderboard``da, «👑 Admin panel» ``bot.handlers.admin``da,
«👥 Do'stlarni taklif qilish» (referallar) ``bot.handlers.common``da ishlaydi.
Bu modul qolgan tugmalarni ulaydi.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from bot.config import get_config
from bot.handlers import admin, games_catalog, missions, shop
from bot.keyboards.main_menu import (
    ADMIN_BUTTON,
    GAME_LIST_BUTTON,
    GAMES_BUTTON,
    MISSIONS_BUTTON,
    RULES_BUTTON,
    SHOP_BUTTON,
    mini_app_url_for,
)

logger = logging.getLogger(__name__)

router = Router(name="menu")

PRIVATE = F.chat.type == "private"


RULES_BUNKER = "rules_bunker"
RULES_MAFIA = "rules_mafia"
RULES_SPY = "rules_spy"
RULES_ECONOMY = "rules_economy"
RULES_BACK = "rules_back"

RULES_TEXT = (
    "ℹ️ <b>Qoidalar / Yordam</b>\n\n"
    "Revilend Games — Telegram ichida guruh bilan o'ynaladigan stol "
    "o'yinlari platformasi.\n\n"
    "🛡️ <b>Bunker</b> — falokatdan keyin kartalar bo'yicha bahslashib, "
    "bunkerga kim tushishini hal qilasiz.\n"
    "🕵️ <b>Mafiya</b> — tunda yashirin rollar, kunduzi ovoz berish.\n"
    "🔍 <b>Josus</b> — hamma joyni biladi, faqat josus bilmaydi.\n\n"
    "Pastdagi bo'limlardan birini tanlab, batafsil qo'llanmani o'qing. "
    "Har bir o'yin guruhda boshlanadi: botni guruhga qo'shing va "
    "<code>/bunker</code>, <code>/mafia</code> yoki <code>/spy</code> "
    "yuboring."
)

BUNKER_RULES_TEXT = (
    "🛡️ <b>Bunker qoidalari va kartalari</b>\n\n"
    "Falokatdan keyin bunkerga faqat bir necha kishi sig'adi. Har bir "
    "o'yinchi o'z kartalari bilan o'zini tanishtiradi va kim omon qolishga "
    "loyiqligi birgalikda hal qilinadi.\n\n"
    "<b>Kartalar (6 ta):</b>\n"
    "• <b>Kasb</b> — sizning mutaxassisligingiz (shifokor, injener, oshpaz...).\n"
    "• <b>Biologiya</b> — yosh, jins va tana tuzilishi.\n"
    "• <b>Sog'liq</b> — kasalliklar yoki sog'lom holat.\n"
    "• <b>Bagaj</b> — o'zingiz bilan olgan asbob-uskuna.\n"
    "• <b>Xobbi</b> — qiziqish va ko'nikmalar.\n"
    "• <b>Fakt</b> — siz haqingizdagi qo'shimcha ma'lumot.\n\n"
    "<b>Maxsus kartalar</b> va <b>falokat</b> kartasi har raundda vaziyatni "
    "o'zgartiradi: ba'zi kartalar boshqalarni fosh qiladi yoki himoya beradi.\n\n"
    "<b>Qanday o'ynaladi:</b>\n"
    "1. Har kim kartalarini birma-bir ochadi va o'zini tanishtiradi.\n"
    "2. Muhokamada kim bunkerga tushishini isbotlaysiz.\n"
    "3. Ovoz berishda ortiqcha o'yinchi haydaladi.\n"
    "4. Bunker sig'imiga yetganda o'yin tugaydi.\n\n"
    "<b>Boosters:</b> «🛡 Bunker Qalqoni» 50 tangaga haydalishdan bir marta "
    "saqlaydi; «✖️ 2 karra ovoz» ovozingizni ikkilantiradi. Qalqon faqat "
    "o'z vaqtida ishlatiladi va bir marta amal qiladi.\n\n"
    "🎮 Guruhda boshlash: <code>/bunker</code> yoki <code>/newgame</code>."
)

MAFIA_RULES_TEXT = (
    "🕵️ <b>Mafiya qoidalari va rollari</b>\n\n"
    "Shahar mafiya changalida. <b>Tun</b>da yashirin rollar harakat qiladi, "
    "<b>kun</b>da hamma ovoz berib mafiyani topadi.\n\n"
    "<b>Shaharliklar:</b>\n"
    "• 👮 <b>Komissar</b> — tunda bir kishini tekshiradi.\n"
    "• 🩺 <b>Doktor</b> — tunda bir kishini davolaydi.\n"
    "• 💂 <b>Soqchi</b> — bir o'yinchini o'z joniga qasd qilib himoya qiladi.\n"
    "• 🔄 <b>Putanka</b> — tunda bir o'yinchining harakatini bloklaydi.\n"
    "• 🎯 <b>Snayper</b> — tunda aniq o'q uzadi.\n"
    "• 🧪 <b>Jodugar</b> — tunda bir kishiga la'nat yoki himoya qo'llaydi.\n"
    "• 🎩 <b>Hokim</b> — kunduzgi ovozni bekor qilish huquqiga ega.\n"
    "• 💥 <b>Kamikadze</b> — o'ldirilganda o'zi bilan bir kishini olib ketadi.\n\n"
    "<b>Mafiya:</b>\n"
    "• 👑 <b>Don</b> — mafiya boshlig'i, qaror qabul qiladi.\n"
    "• 🔪 <b>Mafioz</b> — tunda o'ldirishda qatnashadi.\n"
    "• ⚖️ <b>Advokat</b> — mafiyani ovozdan himoya qiladi.\n"
    "• 🕶 <b>Shantajchi</b> — bir o'yinchining ovozini o'ziga bo'ysundiradi.\n\n"
    "<b>Neytral:</b>\n"
    "• 🔪 <b>Maniak</b> — yolg'iz o'z maqsadi uchun o'ldiradi.\n"
    "• 🃏 <b>Masxaraboz</b> — osilib qolsa g'alaba qozonadi.\n\n"
    "<b>Qo'shimcha qoidalar:</b>\n"
    "• 🦺 <b>Kevlar jilet</b> (40 tanga) — bir marta o'limdan saqlaydi.\n"
    "• 💬 <b>So'nggi so'z</b> — halok bo'lgan o'yinchi bir marta guruhda "
    "xayrlashib, ma'lumot berish imkoniga ega.\n"
    "• Tun va kun davrlari taymer bilan chegaralangan; ovoz berish yakunida "
    "eng ko'p ovoz olgan o'yinchi shahardan haydaladi.\n\n"
    "🎮 Guruhda boshlash: <code>/mafia</code>."
)

SPY_RULES_TEXT = (
    "🔍 <b>Josus (Spyfall) qoidalari</b>\n\n"
    "Hamma bitta joyda — masalan, to'yxonada, shifoxonada yoki kosmik "
    "stantsiyada. Faqat josus qayerda ekanligini bilmaydi.\n\n"
    "<b>Katalog:</b> 25 dan ortiq o'zbekcha joylashuv (Samolyot, Shifoxona, "
    "Harbiy baza, Bank, To'yxona, Choyxona, Kosmik stantsiya, Titanik, "
    "Politsiya bo'limi, Universitet, Qamoqxona, Kino studiyasi, Suv osti "
    "kemasi, Elchixona, Chorsu bozori va boshqalar). Har bir joyda 6–8 ta "
    "maxsus rol bor.\n\n"
    "<b>Rollar:</b> o'yin boshlanganda tinch ishtirokchilarga joy nomi va "
    "shu joyga mos rol (masalan, «To'yxona» — «Oshpaz») ko'rsatiladi. "
    "Josusga joy yashiriladi: «🕵️ SIZ JOSUSSIZ!» degan ogohlantirish "
    "beriladi.\n\n"
    "<b>O'yinchilar:</b> 3–12 kishi. 3–6 kishida 1 ta, 7 va undan ko'p "
    "kishida 2 ta josus bo'ladi.\n\n"
    "<b>Maqsad:</b> savol-javob orqali josusni topish. Josus esa savollarga "
    "ehtiyotkorlik bilan javob berib, joyni aniqlashga harakat qiladi.\n\n"
    "<b>Josusning taxmini:</b> josus istalgan payt Mini App'dagi joylar "
    "ro'yxatidan birini tanlab «Men joyni topdim!» tugmasini bosadi. To'g'ri "
    "topsa — josus g'alaba qozonadi. Xato qilsa — tinch aholi g'alaba "
    "qozonadi.\n\n"
    "<b>Ovoz berish:</b> muhokama tugagach hamma josus deb kimnidir tanlaydi. "
    "Josus topilsa tinch aholi +25 tanga, begunoh haydalsa josus +35 tanga "
    "oladi.\n\n"
    "🛰 <b>Booster:</b> «Josus radari» 20 tangaga 3 ta noto'g'ri joyni "
    "o'chiradi.\n\n"
    "🎮 Guruhda boshlash: <code>/spy</code> yoki <code>/josus</code>."
)

ECONOMY_RULES_TEXT = (
    "🪙 <b>Tangalar, bonus va boosterlar</b>\n\n"
    "<b>Tangalarni qanday yig'ish mumkin:</b>\n"
    "• 🎁 Kunlik bonus — har kuni kirib oling (seriya uzilsa 1-kundan "
    "boshlanadi).\n"
    "• 🎯 Missiyalar — topshiriqlarni bajarib bir martalik mukofot oling.\n"
    "• 🏆 O'yin g'alabalari — Bunker/Mafiya g'oliblari va Josus mukofotlari.\n"
    "• 👥 Do'stlarni taklif qilish — har bir yangi do'st uchun +50 tanga.\n"
    "• 🎟 Promo kodlar — admin bergan kodni kiriting.\n"
    "• 🪙 Tangalar do'koni — chek orqali tanga paketlarini sotib oling.\n\n"
    "<b>Boosterlar:</b>\n"
    "• 🛡 Bunker Qalqoni (50 🪙) — haydalishdan bir marta saqlaydi.\n"
    "• ✖️ 2 karra ovoz (15 🪙) — ovozingizni ikkilantiradi.\n"
    "• 🦺 Kevlar jilet (40 🪙) — Mafiyada bir marta o'limdan saqlaydi.\n"
    "• 🛰 Josus radari (20 🪙) — 3 ta noto'g'ri joyni o'chiradi.\n\n"
    "<b>Kunlik bonus jadvali:</b> 1-kun +25, 2-kun +35, 3-kun +50, "
    "4-kun +70, 5-kun +100, 6-kun +150, 7-kun +250 (katta mukofot).\n\n"
    "Tangalar Mini App'dagi kartochkalar va boosterlarda ishlatiladi; "
    "balansni «👤 Mening profilim» bo'limida ko'rasiz."
)


def rules_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛡️ Bunker qoidalari va kartalari",
                    callback_data=RULES_BUNKER,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🕵️ Mafiya qoidalari va rollari",
                    callback_data=RULES_MAFIA,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Josus (Spyfall) qoidalari",
                    callback_data=RULES_SPY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🪙 Tangalar, Bonus va Boosterlar",
                    callback_data=RULES_ECONOMY,
                )
            ],
        ]
    )


def rules_section_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Bo'limlar ro'yxati", callback_data=RULES_BACK
                )
            ]
        ]
    )


async def _edit_or_send(
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup
) -> None:
    message = callback.message
    if message is not None and hasattr(message, "edit_text"):
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            logger.debug("Qoidalar xabarini tahrirlab bo'lmadi")
    await callback.bot.send_message(
        callback.from_user.id, text, reply_markup=keyboard
    )


@router.message(PRIVATE, F.text == GAMES_BUTTON)
async def menu_games(message: Message) -> None:
    """🎮 O'yinlar — Mini App'ni inline web_app tugmasi orqali ochadi.

    Pastki (reply) klaviaturadagi ``web_app`` tugmasi initData yubormasligi
    mumkin, shuning uchun havolaga foydalanuvchi id'si va ismi qo'shiladi.
    """
    config = get_config()
    user = message.from_user
    url = mini_app_url_for(
        config.mini_app_url or "",
        user_id=user.id if user is not None else None,
        username=(user.username or "") if user is not None else "",
        full_name=(user.full_name or "") if user is not None else "",
    )
    from bot.handlers import common as common_handlers

    if not url.startswith("https://"):
        await message.answer(
            "⚠️ Mini App manzili sozlanmagan. Administratorga murojaat qiling."
        )
        await common_handlers.send_login_code(message)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 O'yinlar portaliga kirish",
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )
    await message.answer(
        "🎮 <b>O'yinlar portali</b>\n\n"
        "Bunker, Mafiya va Josus o'yinlarini shu yerda oching. "
        "Balansingiz va statistikangiz Mini App'da ko'rinadi.",
        reply_markup=keyboard,
    )
    # Mini App initData'siz ochilganda ham profilga kirish uchun kod.
    await common_handlers.send_login_code(message)


@router.message(PRIVATE, F.text == SHOP_BUTTON)
async def menu_shop(message: Message, state: FSMContext) -> None:
    """🪙 Tangalar do'koni — /shop menyusini ochadi."""
    await shop.send_shop(message, state)


@router.message(PRIVATE, F.text == GAME_LIST_BUTTON)
async def menu_game_list(message: Message) -> None:
    """🎲 O'yinlar ro'yxati — platformadagi barcha o'yinlar."""
    await games_catalog.show_games(message)


@router.message(PRIVATE, F.text == MISSIONS_BUTTON)
@router.message(PRIVATE, Command("missions"))
async def menu_missions(message: Message) -> None:
    """🎯 Missiyalar — topshiriqlar va mukofotlar."""
    await missions.show_missions(message)


@router.message(PRIVATE, Command("rules"))
@router.message(PRIVATE, F.text == RULES_BUTTON)
async def menu_rules(message: Message) -> None:
    """ℹ️ Qoidalar / Yordam — umumiy qo'llanma va bo'limlar."""
    await message.answer(RULES_TEXT, reply_markup=rules_keyboard())


@router.callback_query(F.data == RULES_BUNKER)
async def rules_bunker(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit_or_send(callback, BUNKER_RULES_TEXT, rules_section_keyboard())


@router.callback_query(F.data == RULES_MAFIA)
async def rules_mafia(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit_or_send(callback, MAFIA_RULES_TEXT, rules_section_keyboard())


@router.callback_query(F.data == RULES_SPY)
async def rules_spy(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit_or_send(callback, SPY_RULES_TEXT, rules_section_keyboard())


@router.callback_query(F.data == RULES_ECONOMY)
async def rules_economy(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit_or_send(callback, ECONOMY_RULES_TEXT, rules_section_keyboard())


@router.callback_query(F.data == RULES_BACK)
async def rules_back(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit_or_send(callback, RULES_TEXT, rules_keyboard())


@router.message(PRIVATE, F.text == ADMIN_BUTTON)
async def menu_admin(message: Message, state: FSMContext | None = None) -> None:
    """👑 Admin panel — statistika va inline boshqaruv tugmalari."""
    await admin.admin_panel(message, state)
