"""Shaxsiy chatdagi umumiy handlerlar: /start, /help, referallar va taklif menyusi.

«ℹ️ Qoidalar / Yordam» bo'limi shu modulda: barcha to'rt o'yin va tangalar
bo'yicha inline qo'llanma menyusi.
"""

from __future__ import annotations

import logging
from html import escape
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from bot.config import get_config
from bot.handlers.admin import is_admin
from bot.keyboards.main_menu import (
    INVITE_BUTTON,
    RULES_BUTTON,
    build_main_menu,
    mini_app_url_for,
)
from core.economy import (
    REFERRAL_BONUS,
    EconomyError,
    UserAccount,
    format_price,
    get_economy,
    referral_earnings,
)
from core.login_codes import issue_login_code

logger = logging.getLogger(__name__)

router = Router(name="common")

# Yuqori ustuvorlikdagi bekor qilish routeri: Dispatcher'ga birinchi ulanadi,
# shuning uchun FSM holatidagi handlerlardan oldin ishlaydi.
cancel_router = Router(name="cancel")

REFERRAL_PREFIX = "ref_"

CANCEL_TEXTS: frozenset[str] = frozenset(
    {"❌ Bekor qiliş", "/cancel", "Bekor qiliş", "❌ Tölov bekor qilindi."}
)
CANCELLED_TEXT = "❌ Jarayon bekor qilindi."

WELCOME_TEXT = (
    "Salom, <b>{name}</b>! 👋\n\n"
    "<b>Revilend Games</b> — Telegram içida öynaladigan stol öyinlari platformasi.\n\n"
    "🛡️ <b>Bunker</b> — falokatdan keyin kartalar böyiça bahslaşib, bunkerga "
    "kim tuşişini hal qilasiz.\n"
    "🕵️ <b>Mafiya</b> — tunda yaşirin rollar, kunduzi ovoz beriş.\n"
    "🔍 <b>Josus</b> — hamma joyni biladi, faqat josus bilmaydi.\n\n"
    "🎮 Öyinlarni oçiş uçun pastdagi menyudan foydalaning yoki "
    "«🎲 Öyinlar röyxati»ni bosing.\n"
    "➕ Guruhda yangi öyin oçiş uçun: /bunker, /mafia yoki /spy"
)

WELCOME_ONLY_TEXT = (
    "Salom, <b>{name}</b>! 👋\n\n"
    "Öyinni faqat guruhda oçiş mumkin: botni guruhga qöşib, /bunker yuboring."
)


# ----------------------------------------------------------------------
# Referal havolalari
# ----------------------------------------------------------------------
def referral_link(bot_username: str, user_id: int) -> str:
    """Taklif havolasi: ``https://t.me/<bot>?start=ref_<user_id>``."""
    return f"https://t.me/{bot_username}?start={REFERRAL_PREFIX}{int(user_id)}"


def parse_referral_arg(args: str | None) -> int | None:
    """``/start ref_12345`` argumentidan taklif qiluvchining id'sini ajratadi."""
    raw = (args or "").strip()
    if not raw:
        return None
    first = raw.split()[0]
    if not first.lower().startswith(REFERRAL_PREFIX):
        return None
    digits = first[len(REFERRAL_PREFIX) :].strip()
    if not digits.isdigit():
        return None
    inviter_id = int(digits)
    return inviter_id if inviter_id > 0 else None


def invite_text(account: UserAccount, bot_username: str) -> str:
    """«👥 Do'stlarni taklif qilish» xabari."""
    link = referral_link(bot_username, account.user_id)
    count = account.referral_count
    return (
        "👥 <b>Döstlarni taklif qiling va tanga işlang!</b>\n\n"
        f"Har bir taklif qilgan yangi döstingiz uçun "
        f"<b>+{REFERRAL_BONUS} tanga</b> olasiz!\n\n"
        "🔗 <b>Sizning taklif havolangiz:</b>\n"
        f"<code>{link}</code>\n\n"
        f"📊 Siz taklif qilganlar: <b>{format_price(count)}</b> kişi\n"
        f"🪙 Işlangan tangalar: <b>{format_price(referral_earnings(account))}</b> tanga"
    )


def invite_keyboard(account: UserAccount, bot_username: str) -> InlineKeyboardMarkup:
    """Do'stlarga ulashish tugmasi."""
    link = referral_link(bot_username, account.user_id)
    share_text = (
        "Revilend Games — Bunker öyinini birga öynaymiz! 🎮 "
        f"Taklif havolam: {link}"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Döstlarga yuboriş",
                    url=(
                        "https://t.me/share/url"
                        f"?url={quote(link, safe='')}"
                        f"&text={quote(share_text, safe='')}"
                    ),
                )
            ]
        ]
    )


LOGIN_START_ARG = "login"


def login_text(code: str) -> str:
    """Mini App'ga kirish kodi va avtomatik kirish haqidagi xabar."""
    return (
        "🔐 <b>Profilingizga kiriş tayyor!</b>\n\n"
        f"🔑 Kiriş kodingiz: <code>{code}</code>\n"
        "(Yoki kod terib ötirmasdan pastdagi tugmani bosing — avtomatik "
        "profilingiz bilan oçiladi)"
    )


def login_keyboard(user: UserAccount) -> InlineKeyboardMarkup | None:
    """Mini App'ni foydalanuvchi profili bilan avtomatik ochuvchi tugma."""
    config = get_config()
    url = mini_app_url_for(
        config.mini_app_url or "",
        user_id=user.user_id,
        username=user.username,
        full_name=user.full_name,
    )
    if not url.startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎮 Profilingiz bilan kiriş",
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )


async def send_login_code(
    message: Message, account: UserAccount | None = None
) -> None:
    """Foydalanuvchiga yangi bir martalik kod va kirish tugmasini yuboradi."""
    user = message.from_user
    if user is None:
        return
    if account is None:
        account = get_economy().ensure_user(
            user.id, user.username or "", user.full_name
        )
    code = issue_login_code(user.id)
    await message.answer(login_text(code), reply_markup=login_keyboard(account))


async def _notify_inviter(
    bot: Bot, result, invited_name: str
) -> None:
    """Taklif qilganga bot nomidan minnatdorchilik xabarini yuboradi."""
    text = (
        f"🎉 Döstingiz ({escape(invited_name)}) taklifingiz bilan qöşildi! "
        f"Sizga +{format_price(result.bonus)} tanga berildi 🪙"
    )
    try:
        await bot.send_message(result.inviter_id, text)
    except TelegramAPIError:
        logger.info("Taklif egasiga xabar yuborilmadi: %s", result.inviter_id)
    except Exception:
        logger.exception("Taklif egasiga xabar yuborişda xatolik")


# ----------------------------------------------------------------------
# Global bekor qilish
# ----------------------------------------------------------------------
@cancel_router.message(Command("cancel"))
@cancel_router.message(F.text.in_(CANCEL_TEXTS))
async def cancel_process(message: Message, state: FSMContext) -> None:
    """Har qanday FSM holatida ishlaydi: holatni tozalab, menyuga qaytaradi."""
    try:
        await state.clear()
    except Exception:  # holat yo'q bo'lsa ham xabar yuborilishi kerak
        logger.exception("FSM holatini tozalab bölmadi")

    if message.chat.type in {"group", "supergroup"}:
        # Guruhda /cancel faol Alias o'yinini ham to'xtatadi (ega yoki admin).
        from bot.handlers import alias_group as alias_handlers

        user = message.from_user
        if user is not None and alias_handlers.has_active_room(message.chat.id):
            await alias_handlers.stop_alias_for_chat(
                message.bot, message.chat.id, user.id
            )
            return

    if message.chat.type == "private":
        user = message.from_user
        try:
            menu_kwargs: dict[str, object] = {
                "is_admin": is_admin(user.id) if user is not None else False
            }
            if user is not None:
                menu_kwargs.update(
                    user_id=user.id,
                    username=user.username or "",
                    full_name=user.full_name,
                )
            await message.answer(
                CANCELLED_TEXT,
                reply_markup=build_main_menu(**menu_kwargs),
            )
            return
        except TelegramAPIError:
            logger.exception("Bekor qiliş xabarini menyu bilan yuborib bölmadi")
    await message.answer(CANCELLED_TEXT)


# ----------------------------------------------------------------------
# Handlerlar
# ----------------------------------------------------------------------
@router.message(CommandStart())
async def start_command(message: Message, command: CommandObject | None = None) -> None:
    """/start — xush kelibsiz xabari, doimiy menyu va referal hisobi."""
    user = message.from_user
    if message.chat.type != "private":
        await message.answer(
            "Öyinni oçiş uçun /bunker, /mafia yoki /spy buyruğini yuboring."
        )
        return

    name = escape(user.full_name if user else "döstim")
    economy = get_economy()
    notes: list[str] = []
    account: UserAccount | None = None

    if user is not None:
        inviter_id = parse_referral_arg(command.args if command is not None else None)
        try:
            is_new = not economy.has_user(user.id)
            account = economy.ensure_user(
                user.id, user.username or "", user.full_name
            )
            if is_new:
                notes.append(
                    f"🎁 Röyxatdan ötganingiz uçun <b>{format_price(account.coins)}</b> "
                    "bepul tanga berildi!"
                )
                if inviter_id is not None and inviter_id != user.id:
                    result = economy.register_referral(inviter_id, user.id)
                    if result is not None:
                        await _notify_inviter(message.bot, result, user.full_name)
        except EconomyError as exc:
            logger.exception("Foydalanuvçini saqlab bölmadi: %s", user.id)
            notes.append(f"⚠️ {escape(str(exc))}")
        except Exception:
            logger.exception("Foydalanuvçini saqlab bölmadi: %s", user.id)

    args = (command.args if command is not None else "") or ""
    if args.strip().split()[:1] == [LOGIN_START_ARG]:
        if user is None:
            return
        await send_login_code(message, account)
        return

    text = WELCOME_TEXT.format(name=name)
    if notes:
        text = f"{text}\n\n" + "\n".join(notes)

    await _send_welcome(message, text, is_admin(user.id) if user else False)


async def _send_welcome(message: Message, text: str, admin: bool) -> None:
    """Menyuni yuboradi; web_app tugmasi rad etilsa, oddiy menyuga qaytadi.

    Mini App havolasiga foydalanuvchi id'si va ismi qo'shiladi, shuning uchun
    pastki klaviaturadan ochilganda ham profil haqiqiy ma'lumot bilan to'ladi.
    """
    user = message.from_user
    menu_kwargs: dict[str, object] = {"is_admin": admin}
    if user is not None:
        menu_kwargs.update(
            user_id=user.id,
            username=user.username or "",
            full_name=user.full_name,
        )
    try:
        await message.answer(
            text,
            reply_markup=build_main_menu(**menu_kwargs),
        )
    except TelegramAPIError:
        # Masalan MINI_APP_URL http bo'lsa Telegram web_app tugmasini rad etadi.
        logger.exception("Menyu bilan xabar yuborilmadi, web_app'siz qayta uriniş")
        await message.answer(
            text,
            reply_markup=build_main_menu(
                include_web_app=False, **menu_kwargs
            ),
        )


@router.message(F.chat.type == "private", Command("login"))
async def login_command(message: Message) -> None:
    """``/login`` — Mini App uchun yangi 6 xonali kirish kodi."""
    user = message.from_user
    if user is None:
        return
    try:
        account = get_economy().ensure_user(
            user.id, user.username or "", user.full_name
        )
    except Exception:
        logger.exception("Kiriş kodini yaratib bölmadi: %s", user.id)
        await message.answer(
            "⚠️ Kiriş kodini hozirça yaratib bölmadi. Birozdan keyin "
            "urinib köring."
        )
        return
    await send_login_code(message, account)


@router.message(F.chat.type == "private", F.text == INVITE_BUTTON)
async def invite_friends(message: Message) -> None:
    """👥 Do'stlarni taklif qilish — shaxsiy havola va ishlangan tangalar."""
    user = message.from_user
    if user is None:
        return
    config = get_config()
    try:
        account = get_economy().ensure_user(
            user.id, user.username or "", user.full_name
        )
    except Exception:
        logger.exception("Taklif ma'lumotlarini yuklab bölmadi: %s", user.id)
        await message.answer(
            "⚠️ Taklif ma'lumotlarini yuklab bölmadi. Birozdan keyin urinib köring."
        )
        return
    await message.answer(
        invite_text(account, config.bot_username),
        reply_markup=invite_keyboard(account, config.bot_username),
    )


# ----------------------------------------------------------------------
# ℹ️ Qoidalar / Yordam
# ----------------------------------------------------------------------
RULES_BUNKER = "rules_bunker"
RULES_MAFIA = "rules_mafia"
RULES_SPY = "rules_spy"
RULES_ALIAS = "rules_alias"
RULES_ECONOMY = "rules_economy"
RULES_BACK = "rules_back"

HELP_TEXT = (
    "ℹ️ <b>Qoidalar / Yordam</b>\n\n"
    "Revilend Games — Telegram içida guruh bilan öynaladigan stol "
    "öyinlari platformasi.\n\n"
    "🛡️ <b>Bunker</b> — falokatdan keyin kartalar böyiça bahslaşib, "
    "bunkerga kim tuşişini hal qilasiz.\n"
    "🕵️ <b>Mafiya</b> — tunda yaşirin rollar, kunduzi ovoz beriş.\n"
    "🔍 <b>Josus (Spyfall)</b> — hamma joyni biladi, faqat josus bilmaydi.\n"
    "🐊 <b>Alias / Krokodil</b> — sözni aytmasdan, taqiqlangan sözlarsiz "
    "tuşuntiriş.\n\n"
    "Pastdagi bölimlardan birini tanlab, batafsil qöllanmani öqing. "
    "Har bir öyin guruhda boşlanadi: botni guruhga qöşing va "
    "<code>/bunker</code>, <code>/mafia</code>, <code>/spy</code> yoki "
    "<code>/alias</code> yuboring."
)

BUNKER_HELP_TEXT = (
    "🛡️ <b>Bunker qoidalari va kartalari</b>\n\n"
    "Falokatdan keyin bunkerga faqat bir neça kişi siğadi. Har bir "
    "öyinçi öz kartalari bilan özini taniştiradi va kim omon qolişga "
    "loyiqligi birgalikda hal qilinadi.\n\n"
    "<b>Kartalar (6 ta):</b>\n"
    "• <b>Kasb</b> — mutaxassisligingiz (şifokor, injener, oşpaz...).\n"
    "• <b>Biologiya</b> — yoş, jins va tana tuzilişi.\n"
    "• <b>Soğliq</b> — kasalliklar yoki soğlom holat.\n"
    "• <b>Bagaj</b> — özingiz bilan olgan asbob-uskuna.\n"
    "• <b>Xobbi</b> — qiziqiş va könikmalar.\n"
    "• <b>Fakt</b> — siz haqingizdagi qöşimça ma'lumot.\n\n"
    "<b>Falokat va maxsus kartalar</b> har raundda vaziyatni özgartiradi: "
    "ba'zi kartalar boşqalarni foş qiladi yoki himoya beradi.\n\n"
    "<b>Bunker Qalqoni:</b> «🛡 Bunker Qalqoni» 50 tangaga haydalişdan "
    "bir marta saqlaydi; «✖️ 2 karra ovoz» ovozingizni ikkilantiradi.\n\n"
    "<b>Ovoz beriş tartibi:</b>\n"
    "1. Har kim kartalarini birma-bir oçadi va özini taniştiradi.\n"
    "2. Muhokamada kim bunkerga tuşişini isbotlaysiz.\n"
    "3. Ovoz berişda eng köp ovoz olgan öyinçi haydaladi.\n"
    "4. Bunker siğimiga yetganda öyin tugaydi.\n\n"
    "🎮 Guruhda boşlaş: <code>/bunker</code> yoki <code>/newgame</code>."
)

MAFIA_HELP_TEXT = (
    "🕵️ <b>Mafiya qoidalari va rollari</b>\n\n"
    "Şahar mafiya çangalida. <b>Tun</b>da yaşirin rollar harakat qiladi, "
    "<b>kun</b>da hamma ovoz berib mafiyani topadi.\n\n"
    "<b>Tinç aholi (9 ta rol):</b>\n"
    "• 🧑 <b>Tinç fuqaro</b> — tunda harakati yöq; kunduzi muhokamada "
    "qatnaşadi.\n"
    "• 👮 <b>Komissar</b> — tunda bir kişini tekşiradi va uning mafiya "
    "yoki tinç aholi ekanini biladi.\n"
    "• 🩺 <b>Şifokor</b> — tunda bir kişini davolaydi va uni ölimdan "
    "saqlaydi.\n"
    "• 💂 <b>Soqçi</b> — bir öyinçini qöriqlaydi; unga qilingan hujumni "
    "öziga oladi.\n"
    "• 🔄 <b>Putanka</b> — tunda bir öyinçining harakatini bloklaydi.\n"
    "• 🎯 <b>Snayper</b> — tunda aniq öq uzadi; tinç aholini öldirsa özi "
    "halok böladi.\n"
    "• 🧪 <b>Jodugar</b> — tunda bir kişini öldirişi yoki tiriltirişi "
    "mumkin.\n"
    "• 🎩 <b>Hokim</b> — kunduzgi ovozini ikki barobar kuçli qiladi.\n"
    "• 💥 <b>Kamikadze</b> — öldirilsa qotilni ham özi bilan olib ketadi.\n\n"
    "<b>Mafiya (4 ta rol):</b>\n"
    "• 👑 <b>Don</b> — mafiya sardori; qurbonni tanlaydi va tekşiruvda "
    "begunoh körinadi.\n"
    "• 🔪 <b>Mafioz</b> — tunda boşqa mafiya a'zolari bilan qurbon "
    "tanlaydi.\n"
    "• ⚖️ <b>Advokat</b> — mafiyani himoya qilib, tekşiruv natijasini "
    "çalgitadi.\n"
    "• 🕶 <b>Şantajçi</b> — bir öyinçini şantaj qiladi; u ertasi kuni ovoz "
    "bera olmaydi.\n\n"
    "<b>Yolğizlar (2 ta rol):</b>\n"
    "• 🔪 <b>Maniak</b> — yolğiz qotil; tunda öldiradi va faqat özi "
    "ğalaba qozonişni istaydi.\n"
    "• 🃏 <b>Masxaraboz</b> — kunduzi ovoz bilan haydalsa öyinda ğalaba "
    "qozonadi.\n\n"
    "<b>Qöşimça qoidalar:</b>\n"
    "• 🦺 <b>Kevlar jilet</b> (40 tanga) — bir marta ölimdan saqlaydi.\n"
    "• 💬 <b>Sönggi söz / Arvoh</b> — halok bölgan öyinçi bir marta "
    "guruhda xayrlaşib, ma'lumot beriş imkoniga ega.\n"
    "• Tun va kun davrlari taymer bilan çegaralangan; ovoz beriş yakunida "
    "eng köp ovoz olgan öyinçi şahardan haydaladi.\n\n"
    "🎮 Guruhda boşlaş: <code>/mafia</code>."
)

SPY_HELP_TEXT = (
    "🔍 <b>Josus (Spyfall) qoidalari</b>\n\n"
    "Hamma bitta joyda — masalan, töyxonada, şifoxonada yoki kosmik "
    "stantsiyada. Faqat josus qayerda ekanligini bilmaydi.\n\n"
    "<b>Lokatsiyalar:</b> 25 ta özbekça joy (Samolyot, Şifoxona, Harbiy "
    "baza, Bank, Töyxona, Çoyxona, Kosmik stantsiya, Titanik, Politsiya "
    "bölimi, Universitet, Qamoqxona, Kino studiyasi, Suv osti kemasi, "
    "Elçixona, Çorsu bozori va boşqalar). Har bir joyda 6–8 ta maxsus rol "
    "bor.\n\n"
    "<b>Rollar:</b> öyin boşlanganda tinç iştirokçilarga joy nomi va şu "
    "joyga mos rol (masalan, «Töyxona» — «Oşpaz») körsatiladi. Josusga "
    "joy yaşiriladi: «🕵️ SIZ JOSUSSIZ!» degan ogohlantiriş beriladi.\n\n"
    "<b>Öyinçilar:</b> 3–12 kişi. 3–6 kişida 1 ta, 7 va undan köp kişida "
    "2 ta josus böladi.\n\n"
    "<b>Maqsad:</b> savol-javob orqali josusni topiş. Josus esa savollarga "
    "ehtiyotkorlik bilan javob berib, joyni aniqlaşga harakat qiladi.\n\n"
    "<b>Josusning vazifasi:</b> josus istalgan payt Mini App'dagi joylar "
    "röyxatidan birini tanlab «Men joyni topdim!» tugmasini bosadi. Töğri "
    "topsa — josus ğalaba qozonadi. Xato qilsa — tinç aholi ğalaba "
    "qozonadi.\n\n"
    "<b>Ovoz beriş:</b> muhokama tugagaç hamma josus deb kimnidir "
    "tanlaydi. Josus topilsa tinç aholi +25 tanga, begunoh haydalsa josus "
    "+35 tanga oladi.\n\n"
    "🛰 <b>Booster:</b> «Josus radari» 20 tangaga 3 ta notöğri joyni "
    "öçiradi.\n\n"
    "🎮 Guruhda boşlaş: <code>/spy</code> yoki <code>/josus</code>."
)

ALIAS_HELP_TEXT = (
    "🐊 <b>Alias / Krokodil qoidalari</b>\n\n"
    "Har raundda bitta öyinçi tuşuntiruvçi böladi. U sözni aytmasdan va "
    "uçta taqiqlangan sözni işlatmasdan tuşuntiradi. Qolganlar 60 soniya "
    "içida sözni topişga harakat qiladi.\n\n"
    "<b>Qoidalar:</b>\n"
    "• Tuşuntiruvçi sözning özini, uning qismlarini yoki taqiqlangan "
    "3 ta sözni aytmaydi.\n"
    "• Sözni birinçi bölib töğri yozgan öyinçi +10 tanga, tuşuntiruvçi "
    "+5 tanga oladi.\n"
    "• Har bir iştirokçi 2 martadan tuşuntiradi: 3 kişi bölsa jami "
    "6 raund öynaladi.\n"
    "• Barça raundlar tugagaç eng köp oçko töplagan öyinçi ğolib böladi "
    "va +25 tanga oladi.\n"
    "• Ketma-ket 2 raundda heç kim sözni topmasa, öyin avtomatik töxtaydi "
    "va xona yopiladi.\n\n"
    "<b>60 soniyalik taymer:</b> vaqt tugasa söz oçiladi va keyingi raund "
    "boşlanadi.\n\n"
    "<b>Töxtatiş:</b> xona egasi yoki guruh administratori <code>/stop</code>, "
    "<code>/stopalias</code> yoki <code>/cancel</code> yuborib öyinni "
    "darhol töxtatadi.\n\n"
    "🎮 Guruhda boşlaş: <code>/alias</code> yoki <code>/krokodil</code>."
)

ECONOMY_HELP_TEXT = (
    "🪙 <b>Tangalar va Dökon</b>\n\n"
    "<b>Tangalarni qanday yiğiş mumkin:</b>\n"
    "• 🎁 <b>Kunlik bonus seriyasi</b> — har kuni kirib oling. Seriya "
    "uzilmasa mukofot ösadi: 1-kun +25, 2-kun +35, 3-kun +50, 4-kun +70, "
    "5-kun +100, 6-kun +150, 7-kun +250.\n"
    "• 🎟 <b>Promokodlar</b> — «🎟 Promo kod» tugmasi orqali admin bergan "
    "kodni kiriting.\n"
    "• 🎯 <b>Missiyalar</b> — «🎯 Missiyalar» bölimida topşiriqlarni "
    "bajarib, bir martalik mukofot oling.\n"
    "• 🏆 <b>Öyin ğalabalari</b> — Bunker, Mafiya, Josus va Alias "
    "mukofotlari.\n"
    "• 👥 <b>Döstlarni taklif qiliş</b> — har bir yangi döst uçun "
    "+50 tanga.\n\n"
    "<b>Boosterlar:</b>\n"
    "• 🛡 Bunker Qalqoni (50 🪙) — haydalişdan bir marta saqlaydi.\n"
    "• ✖️ 2 karra ovoz (15 🪙) — ovozingizni ikkilantiradi.\n"
    "• 🦺 Kevlar jilet (40 🪙) — Mafiyada bir marta ölimdan saqlaydi.\n"
    "• 🛰 Josus radari (20 🪙) — 3 ta notöğri joyni öçiradi.\n\n"
    "<b>Uzcard / Humo orqali tanga xarid qiliş:</b>\n"
    "1. «🪙 Tangalar dökoni» tugmasini yoki <code>/shop</code> buyruğini "
    "oçing.\n"
    "2. Kerakli paketni tanlang.\n"
    "3. Körsatilgan Uzcard yoki Humo kartasiga tölov qiling.\n"
    "4. Çek (skrinşot) rasmini botga yuboring.\n"
    "5. Administrator tasdiqlagaç tangalar balansingizga qöşiladi.\n\n"
    "Tangalar Mini App'dagi kartalar va boosterlarda işlatiladi; balansni "
    "«👤 Mening profilim» bölimida köräsiz."
)


def rules_keyboard() -> InlineKeyboardMarkup:
    """Barcha bo'limlar uchun inline menyu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛡️ Bunker", callback_data=RULES_BUNKER
                )
            ],
            [
                InlineKeyboardButton(
                    text="🕵️ Mafiya", callback_data=RULES_MAFIA
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Josus (Spyfall)", callback_data=RULES_SPY
                )
            ],
            [
                InlineKeyboardButton(
                    text="🐊 Alias / Krokodil", callback_data=RULES_ALIAS
                )
            ],
            [
                InlineKeyboardButton(
                    text="🪙 Tangalar va Dökon", callback_data=RULES_ECONOMY
                )
            ],
        ]
    )


def rules_section_keyboard() -> InlineKeyboardMarkup:
    """Bo'lim ichidan menyuga qaytish tugmasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Bölümlar röyxati", callback_data=RULES_BACK
                )
            ]
        ]
    )


async def _edit_or_send(
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup
) -> None:
    """Bo'lim matnini tahrirlaydi, imkoni bo'lmasa yangi xabar yuboradi."""
    message = callback.message
    if message is not None and hasattr(message, "edit_text"):
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            logger.debug("Qoidalar xabarini tahrirlab bölmadi")
    await callback.bot.send_message(
        callback.from_user.id, text, reply_markup=keyboard
    )


@router.message(Command("help", "rules"))
@router.message(F.chat.type == "private", F.text == RULES_BUTTON)
async def menu_rules(message: Message) -> None:
    """ℹ️ Qoidalar / Yordam — barcha o'yinlar bo'yicha inline menyu."""
    await message.answer(HELP_TEXT, reply_markup=rules_keyboard())


@router.callback_query(F.data == RULES_BUNKER)
async def rules_bunker(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit_or_send(callback, BUNKER_HELP_TEXT, rules_section_keyboard())


@router.callback_query(F.data == RULES_MAFIA)
async def rules_mafia(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit_or_send(callback, MAFIA_HELP_TEXT, rules_section_keyboard())


@router.callback_query(F.data == RULES_SPY)
async def rules_spy(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit_or_send(callback, SPY_HELP_TEXT, rules_section_keyboard())


@router.callback_query(F.data == RULES_ALIAS)
async def rules_alias(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit_or_send(callback, ALIAS_HELP_TEXT, rules_section_keyboard())


@router.callback_query(F.data == RULES_ECONOMY)
async def rules_economy(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit_or_send(callback, ECONOMY_HELP_TEXT, rules_section_keyboard())


@router.callback_query(F.data == RULES_BACK)
async def rules_back(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit_or_send(callback, HELP_TEXT, rules_keyboard())
