"""Bot va backend xabarlari uchun markaziy uch tilli lug'at.

Qo'llab-quvvatlanadi:
* ``uz`` — O'zbekcha (yangi alifbo: ö, ğ, ş, ç)
* ``ru`` — Русский
* ``en`` — English

Telegram ``language_code`` "uz", "uz-Latn", "ru", "en" bo'lishi mumkin;
noma'lum kodda default ``uz`` ishlaydi. Mini App (`webapp/`) bu modulga
tegishli emas.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

LANGUAGES: tuple[str, ...] = ("uz", "ru", "en")
DEFAULT_LANGUAGE = "uz"

LANGUAGE_NAMES: dict[str, str] = {
    "uz": "🇺🇿 Özbekça",
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
}

# Pastki menyu tugmalari (callback emas — faqat matn).
BUTTONS: dict[str, dict[str, str]] = {
    "games": {
        "uz": "🌐 Mini App (Portal)",
        "ru": "🌐 Мини-приложение (Портал)",
        "en": "🌐 Mini App (Portal)",
    },
    "quick_game": {
        "uz": "🎮 Tezkor öyin",
        "ru": "🎮 Быстрая игра",
        "en": "🎮 Quick Game",
    },
    "games_list": {
        "uz": "📋 Öyinlar",
        "ru": "📋 Игры",
        "en": "📋 Games",
    },
    "missions": {
        "uz": "🎯 Missiyalar",
        "ru": "🎯 Задания",
        "en": "🎯 Missions",
    },
    "bonus": {
        "uz": "🎁 Kunlik bonus",
        "ru": "🎁 Ежедневный бонус",
        "en": "🎁 Daily Bonus",
    },
    "shop": {
        "uz": "🛍️ Dökon",
        "ru": "🛍️ Магазин",
        "en": "🛍️ Shop",
    },
    "tournaments": {
        "uz": "🏆 Turnirlar",
        "ru": "🏆 Турниры",
        "en": "🏆 Tournaments",
    },
    "profile": {
        "uz": "👤 Profilim",
        "ru": "👤 Мой профиль",
        "en": "👤 My Profile",
    },
    "leaderboard": {
        "uz": "👑 Reyting",
        "ru": "👑 Рейтинг",
        "en": "👑 Leaderboard",
    },
    "promo": {
        "uz": "🎟️ Promo kod",
        "ru": "🎟️ Промокод",
        "en": "🎟️ Promo code",
    },
    "invite": {
        "uz": "👥 Döstlar",
        "ru": "👥 Друзья",
        "en": "👥 Friends",
    },
    "rules": {
        "uz": "ℹ️ Qoidalar / Yordam",
        "ru": "ℹ️ Правила / Помощь",
        "en": "ℹ️ Rules / Help",
    },
    "admin": {
        "uz": "👑 Admin panel",
        "ru": "👑 Панель администратора",
        "en": "👑 Admin panel",
    },
    "change_language": {
        "uz": "🌐 Tilni özgartiriş",
        "ru": "🌐 Сменить язык",
        "en": "🌐 Change language",
    },
}


def default_label(key: str, language: Any = None) -> str:
    """Pastki menyu tugmasi matni (berilgan tilda)."""
    lang = normalize_language(language)
    return BUTTONS.get(key, {}).get(lang, key)


def all_button_texts(key: str | None = None) -> frozenset[str]:
    """Barcha tillardagi tugma matnlari to'plami (handler filtri uchun)."""
    keys = [key] if key else list(BUTTONS.keys())
    texts: set[str] = set()
    for item in keys:
        for lang in LANGUAGES:
            text = BUTTONS.get(item, {}).get(lang)
            if text:
                texts.add(text)
    return frozenset(texts)


def normalize_language(code: Any) -> str:
    """Telegram/baza til kodini ``uz``/``ru``/``en`` ga keltiradi."""
    text = str(code or "").strip().lower()
    if not text:
        return DEFAULT_LANGUAGE
    if text.startswith("ru"):
        return "ru"
    if text.startswith("en"):
        return "en"
    if text.startswith("uz") or text.startswith("uzbek"):
        return "uz"
    return DEFAULT_LANGUAGE


def t(lang: Any, key: str, **params: Any) -> str:
    """``STRINGS`` dan matnni oladi; topilmasa uz → en ga qaytadi."""
    language = normalize_language(lang)
    value = STRINGS.get(key, {}).get(language) or STRINGS.get(key, {}).get(
        DEFAULT_LANGUAGE
    )
    if value is None:
        value = STRINGS.get(key, {}).get("en", key)
    try:
        return value.format(**params) if params else value
    except (KeyError, IndexError, ValueError):
        return value


def resolve_language(user_id: int | None, telegram_code: Any = None) -> str:
    """Foydalanuvchi tilini bazadan (``users.language_code``) hal qiladi.

    Topilmasa telegram koddan, u ham bo'lmasa ``uz``.
    """
    uid = int(user_id or 0)
    if uid > 0:
        try:
            from core.economy import get_economy

            account = get_economy().find_user(uid)
            if account is not None and account.language_code:
                return normalize_language(account.language_code)
        except Exception:
            logger.exception("Foydalanuvchi tilini o'qib bo'lmadi: %s", uid)
    return normalize_language(telegram_code)


def set_language(user_id: int, language: str) -> str:
    """Tilni Supabase `users.language_code` ga saqlaydi, normallashtirib qaytaradi."""
    normalized = normalize_language(language)
    from core.economy import get_economy

    get_economy().set_language(int(user_id), normalized)
    return normalized


STRINGS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------
    # Tilni tanlash / xush kelibsiz
    # ------------------------------------------------------------------
    "language_prompt": {
        "uz": "🌐 **Iltimos, tilni tanlang / Пожалуйста, выберите язык / Please select language:**",
        "ru": "🌐 **Iltimos, tilni tanlang / Пожалуйста, выберите язык / Please select language:**",
        "en": "🌐 **Iltimos, tilni tanlang / Пожалуйста, выберите язык / Please select language:**",
    },
    "language_changed": {
        "uz": "🌐 Til muvaffaqiyatli özgartirildi! Endi bot {language} tilida gaplaşadi.",
        "ru": "🌐 Язык успешно изменён! Теперь бот будет говорить на {language}.",
        "en": "🌐 Language successfully changed! The bot will now speak {language}.",
    },
    "welcome": {
        "uz": (
            "Salom, <b>{name}</b>! 👋\n\n"
            "🎮 <b>Revilend Games</b> — Telegram içidagi premium stol o'yinlari portali!\n"
            "🛡️ <b>Bunker</b> — Falokatdan keyin omon qolish va bahslashuv.\n"
            "🕵️ <b>Mafiya</b> — Tungi rollar va kunduzgi tergov.\n"
            "🕶️ <b>Josus (Spyfall)</b> — Hamma joyni biladi, josus esa qidiradi.\n"
            "🐊 <b>Alias / Krokodil</b> — Söz tushuntirish poygasi.\n"
            "💣 <b>Portlovçi Bomba</b> — Xavfli karta o'yini, bombani zararsizlantir va tirik qol!\n"
            "➕ Guruhda o'yin ochish uchun:\n"
            "/bunker, /mafia, /spy, /alias yoki /bomb yuboring."
        ),
        "ru": (
            "Привет, <b>{name}</b>! 👋\n\n"
            "🎮 <b>Revilend Games</b> — портал премиальных настольных игр в Telegram!\n"
            "🛡️ <b>Бункер</b> — выживание после катастрофы и жаркие споры.\n"
            "🕵️ <b>Мафия</b> — ночные роли и дневное расследование.\n"
            "🕶️ <b>Шпион (Spyfall)</b> — все знают место, а шпион ищет его.\n"
            "🐊 <b>Alias / Крокодил</b> — гонка объяснений без запрещённых слов.\n"
            "💣 <b>Взрывная бомба</b> — опасная карточная игра: обезвредь бомбу и выживи!\n"
            "➕ Чтобы открыть игру в группе:\n"
            "отправьте /bunker, /mafia, /spy, /alias или /bomb."
        ),
        "en": (
            "Hello, <b>{name}</b>! 👋\n\n"
            "🎮 <b>Revilend Games</b> — a premium board-game portal inside Telegram!\n"
            "🛡️ <b>Bunker</b> — survive the disaster and argue your case.\n"
            "🕵️ <b>Mafia</b> — night roles and day-time investigation.\n"
            "🕶️ <b>Spyfall</b> — everyone knows the place, the spy must find it.\n"
            "🐊 <b>Alias / Crocodile</b> — a word-explaining race.\n"
            "💣 <b>Ticking Bomb</b> — a dangerous card game: defuse the bomb and stay alive!\n"
            "➕ To open a game in a group:\n"
            "send /bunker, /mafia, /spy, /alias or /bomb."
        ),
    },
    "welcome_group_only": {
        "uz": "Öyinni faqat guruhda oçiş mumkin: botni guruhga qöşib, /bunker yuboring.",
        "ru": "Игру можно открыть только в группе: добавьте бота в группу и отправьте /bunker.",
        "en": "Games can only be opened in a group: add the bot to a group and send /bunker.",
    },
    "registered_bonus": {
        "uz": "🎁 Röyxatdan ötganingiz uçun <b>{amount}</b> bepul tanga berildi!",
        "ru": "🎁 За регистрацию вам начислено <b>{amount}</b> бесплатных монет!",
        "en": "🎁 You received <b>{amount}</b> free coins for registering!",
    },
    "cancelled": {
        "uz": "❌ Jarayon bekor qilindi.",
        "ru": "❌ Процесс отменён.",
        "en": "❌ Process cancelled.",
    },
    # ------------------------------------------------------------------
    # Profil
    # ------------------------------------------------------------------
    "profile_title": {
        "uz": "👤 <b>Mening profilim</b>",
        "ru": "👤 <b>Мой профиль</b>",
        "en": "👤 <b>My profile</b>",
    },
    "profile_name": {"uz": "Ism", "ru": "Имя", "en": "Name"},
    "profile_username": {"uz": "Username", "ru": "Username", "en": "Username"},
    "profile_coins": {"uz": "Tangalar", "ru": "Монеты", "en": "Coins"},
    "profile_games": {"uz": "O'ynalgan o'yinlar", "ru": "Сыграно игр", "en": "Games played"},
    "profile_wins": {"uz": "G'alabalar", "ru": "Победы", "en": "Wins"},
    "profile_bunker": {"uz": "Bunker", "ru": "Бункер", "en": "Bunker"},
    "profile_mafia": {"uz": "Mafiya", "ru": "Мафия", "en": "Mafia"},
    "profile_spy": {"uz": "Josus", "ru": "Шпион", "en": "Spyfall"},
    "profile_alias": {"uz": "Alias", "ru": "Alias", "en": "Alias"},
    "profile_bomb": {"uz": "Bomba", "ru": "Бомба", "en": "Bomb"},
    "profile_total_wins": {"uz": "Umumiy g'alabalar", "ru": "Всего побед", "en": "Total wins"},
    "profile_rating": {"uz": "Reyting", "ru": "Рейтинг", "en": "Rating"},
    "profile_title_label": {"uz": "Unvon", "ru": "Титул", "en": "Title"},
    "profile_free_coins": {
        "uz": "🎁 Röyxatdan ötganingiz uçun <b>{amount}</b> bepul tanga berildi!",
        "ru": "🎁 За регистрацию вам начислено <b>{amount}</b> бесплатных монет!",
        "en": "🎁 You received <b>{amount}</b> free coins for registering!",
    },
    "profile_error": {
        "uz": "⚠️ Profil xatosi: {error}",
        "ru": "⚠️ Ошибка профиля: {error}",
        "en": "⚠️ Profile error: {error}",
    },
    # ------------------------------------------------------------------
    # O'yinlar katalogi
    # ------------------------------------------------------------------
    "catalog_title": {
        "uz": "🎲 <b>Öyinlar röyxati</b>\n\nPlatformadagi barça öyinlar: 🛡️ Bunker, 🕵️ Mafiya, 🔍 Josus (Spyfall), 🐊 Alias, 💣 Portlovçi Bomba — har biri guruhda öynaladi.",
        "ru": "🎲 <b>Список игр</b>\n\nВсе игры на платформе: 🛡️ Бункер, 🕵️ Мафия, 🔍 Шпион (Spyfall), 🐊 Alias, 💣 Взрывная бомба — каждая играется в группе.",
        "en": "🎲 <b>Game list</b>\n\nAll games on the platform: 🛡️ Bunker, 🕵️ Mafia, 🔍 Spyfall, 🐊 Alias, 💣 Ticking Bomb — each played in a group.",
    },
    "catalog_back": {"uz": "⬅️ Orqaga", "ru": "⬅️ Назад", "en": "⬅️ Back"},
    "catalog_bunker": {
        "uz": "🛡️ <b>Bunker</b>\n\nFalokatdan keyin faqat bir neça kişi bunkerga siğadi. Kartalar böyiça omon qolişga loyiqligini birgalikda hal qilasiz.\n\n🎮 <b>Guruhda boşlaş:</b> botni guruhga qöşing, /bunker yuboring, «Guruh orqali qösiliş»ni bosing, xona egasi öyinni boşlaydi.",
        "ru": "🛡️ <b>Бункер</b>\n\nПосле катастрофы в бункер поместится лишь горсть людей. По картам вместе решаете, кто достоин выжить.\n\n🎮 <b>Старт в группе:</b> добавьте бота в группу, отправьте /bunker, нажмите «Присоединиться через группу», владелец комнаты запускает игру.",
        "en": "🛡️ <b>Bunker</b>\n\nAfter the disaster only a few can fit in the bunker. Use your cards to decide together who deserves to survive.\n\n🎮 <b>Start in a group:</b> add the bot to your group, send /bunker, press “Join via group”, the room owner starts the game.",
    },
    "catalog_mafia": {
        "uz": "🕵️ <b>Mafiya</b>\n\nTunda yaşirin rollar taqsimlanadi, kunduzi şahar ovoz beradi. Mafiyani toping yoki şaharni qutqaring!\n\n🎮 <b>Guruhda boşlaş:</b> botni guruhga qöşing, /mafia yuboring, «Qöşiliş»ni bosing (kamida 4 kişi kerak), xona egasi öyinni boşlaydi — rollar şaxsiy xabarda keladi.",
        "ru": "🕵️ <b>Мафия</b>\n\nНочью раздаются секретные роли, днём город голосует. Найдите мафию или спасите город!\n\n🎮 <b>Старт в группе:</b> добавьте бота в группу, отправьте /mafia, нажмите «Присоединиться» (нужно минимум 4 чел.), владелец комнаты запускает игру — роли придут в личные сообщения.",
        "en": "🕵️ <b>Mafia</b>\n\nAt night secret roles are dealt, by day the city votes. Find the mafia or save the city!\n\n🎮 <b>Start in a group:</b> add the bot to your group, send /mafia, press “Join” (at least 4 players needed), the room owner starts the game — roles arrive in private messages.",
    },
    "catalog_spy": {
        "uz": "🔍 <b>Josus (Spyfall)</b>\n\nHamma joy nomini biladi, bitta josus bilmaydi. Savol-javob orqali josusni toping.",
        "ru": "🔍 <b>Шпион (Spyfall)</b>\n\nВсе знают название места, кроме одного шпиона. Найдите его вопросами и ответами.",
        "en": "🔍 <b>Spyfall</b>\n\nEveryone knows the location except one spy. Find the spy through questions and answers.",
    },
    "catalog_alias": {
        "uz": "🐊 <b>Alias</b>\n\nSözni aytmasdan, taqiqlangan sözlarsiz tuşuntirasiz. Jamoa bilan eng köp sözni toping.",
        "ru": "🐊 <b>Alias</b>\n\nОбъясняйте слово без запрещённых слов. Угадывайте как можно больше слов в команде.",
        "en": "🐊 <b>Alias</b>\n\nExplain the word without using forbidden words. Guess as many words as possible as a team.",
    },
    "catalog_bomb": {
        "uz": "💣 <b>Portlovçi Bomba</b>\n\nBombani zararsizlantirib, oxirgi tirik qoling. Risk miqdorini özingiz tanlang.",
        "ru": "💣 <b>Взрывная бомба</b>\n\nОбезвредьте бомбу и останьтесь последним в живых. Сами выбираете уровень риска.",
        "en": "💣 <b>Ticking Bomb</b>\n\nDefuse the bomb and be the last one standing. You choose the risk level.",
    },
    # ------------------------------------------------------------------
    # Reyting
    # ------------------------------------------------------------------
    "leaderboard_title": {
        "uz": "🏆 <b>Reyting va Top</b>",
        "ru": "🏆 <b>Рейтинг и топ</b>",
        "en": "🏆 <b>Leaderboard</b>",
    },
    "leaderboard_empty": {
        "uz": "Hozirça reyting böş. Birinçi bölib öyin boşlang!",
        "ru": "Пока рейтинг пуст. Начните игру первым!",
        "en": "The leaderboard is empty. Start the first game!",
    },
    "leaderboard_you": {"uz": "(siz)", "ru": "(вы)", "en": "(you)"},
    # ------------------------------------------------------------------
    # Taklif / login
    # ------------------------------------------------------------------
    "invite_title": {
        "uz": "👥 <b>Döstlarni taklif qiling va tanga işlang!</b>",
        "ru": "👥 <b>Приглашайте друзей и зарабатывайте монеты!</b>",
        "en": "👥 <b>Invite friends and earn coins!</b>",
    },
    "invite_body": {
        "uz": "Har bir taklif qilingan yangi döstingiz uçun <b>+{bonus} tanga</b> olasiz!\n\n🔗 <b>Sizning taklif havolangiz:</b>\n<code>{link}</code>\n\n📊 Siz taklif qilganlar: <b>{count}</b> kişi\n🪙 Işlangan tangalar: <b>{earned}</b> tanga",
        "ru": "За каждого приглашённого друга вы получаете <b>+{bonus}</b> монет!\n\n🔗 <b>Ваша реферальная ссылка:</b>\n<code>{link}</code>\n\n📊 Приглашено: <b>{count}</b> чел.\n🪙 Заработано: <b>{earned}</b> монет",
        "en": "For every friend you invite you get <b>+{bonus}</b> coins!\n\n🔗 <b>Your referral link:</b>\n<code>{link}</code>\n\n📊 Invited: <b>{count}</b> people\n🪙 Earned: <b>{earned}</b> coins",
    },
    "login_title": {
        "uz": "🔐 <b>Profilingizga kiriş tayyor!</b>",
        "ru": "🔐 <b>Вход в профиль готов!</b>",
        "en": "🔐 <b>Profile login is ready!</b>",
    },
    "login_body": {
        "uz": "🔑 Kiriş kodingiz: <code>{code}</code>\n(Yoki pastdagi tugmani bosing — profil avtomatik oçiladi)",
        "ru": "🔑 Ваш код входа: <code>{code}</code>\n(Или нажмите кнопку ниже — профиль откроется автоматически)",
        "en": "🔑 Your login code: <code>{code}</code>\n(Or press the button below — your profile opens automatically)",
    },
    # ------------------------------------------------------------------
    # Turnirlar
    # ------------------------------------------------------------------
    "tournament_rules": {
        "uz": "🏆 <b>Turnir qoidalari</b>\n\n1. Röyxatdan ötiş: çipta yoki 50 tanga.\n2. Turnir belgilangan vaqtda boşlanadi.\n3. Ğolib sovrin yutadi.\n4. Har bir öyin ğalabasi ball qöşadi.",
        "ru": "🏆 <b>Правила турниров</b>\n\n1. Регистрация: билет или 50 монет.\n2. Турнир стартует в назначенное время.\n3. Победитель забирает призовой фонд.\n4. Каждая победа даёт очки.",
        "en": "🏆 <b>Tournament rules</b>\n\n1. Registration: a ticket or 50 coins.\n2. The tournament starts at the scheduled time.\n3. The winner takes the prize pool.\n4. Every win earns points.",
    },
    # ------------------------------------------------------------------
    # Guruh o'yinlari (xona hayot sikli)
    # ------------------------------------------------------------------
    "room_created": {
        "uz": "🎮 <b>{game} xonasi oçildi!</b>\n\nKutilmoqda: {waiting} kişi. Öynaş uçun guruhga qöşiling.",
        "ru": "🎮 <b>Комната {game} создана!</b>\n\nОжидаем: {waiting} чел. Чтобы играть, присоединяйтесь в группе.",
        "en": "🎮 <b>{game} room created!</b>\n\nWaiting for: {waiting} player(s). Join in the group to play.",
    },
    "room_waiting": {
        "uz": "⏳ Hozirça {count} kişi bor. Yana {need} kişi kerak.",
        "ru": "⏳ Пока {count} чел. Нужно ещё {need}.",
        "en": "⏳ Currently {count} player(s). Need {need} more.",
    },
    "room_joined": {
        "uz": "✅ {name} öyinga qöşildi!",
        "ru": "✅ {name} присоединился к игре!",
        "en": "✅ {name} joined the game!",
    },
    "room_started": {
        "uz": "🚀 <b>{game} öyini boşlandi!</b> Omad!",
        "ru": "🚀 <b>Игра {game} началась!</b> Удачи!",
        "en": "🚀 <b>{game} game started!</b> Good luck!",
    },
    "room_finished": {
        "uz": "🏁 <b>{game} öyini tugadi!</b>\n\n🏆 Ğolib: {winner}",
        "ru": "🏁 <b>Игра {game} завершена!</b>\n\n🏆 Победитель: {winner}",
        "en": "🏁 <b>{game} game finished!</b>\n\n🏆 Winner: {winner}",
    },
    "room_cancelled": {
        "uz": "❌ {game} öyini bekor qilindi.",
        "ru": "❌ Игра {game} отменена.",
        "en": "❌ {game} game cancelled.",
    },
    # ------------------------------------------------------------------
    # Umumiy
    # ------------------------------------------------------------------
    "menu_placeholder": {
        "uz": "Menyudan tanlang yoki /bunker, /mafia, /spy, /alias, /bomb yozing",
        "ru": "Выберите в меню или напишите /bunker, /mafia, /spy, /alias, /bomb",
        "en": "Choose from the menu or type /bunker, /mafia, /spy, /alias, /bomb",
    },
    "portal_title": {
        "uz": "🎮 <b>Öyinlar portali</b>\n\nBunker, Mafiya, Josus, Alias va Portlovçi Bomba öyinlarini şu yerda oçing. Balansingiz va statistikangiz Mini App'da körinadi.",
        "ru": "🎮 <b>Портал игр</b>\n\nОткрывайте здесь Бункер, Мафию, Шпиона, Alias и Взрывную бомбу. Баланс и статистика видны в мини-приложении.",
        "en": "🎮 <b>Game portal</b>\n\nOpen Bunker, Mafia, Spyfall, Alias and Ticking Bomb here. Your balance and stats are shown in the Mini App.",
    },
    "miniapp_unconfigured": {
        "uz": "⚠️ Mini App manzili sozlanmagan. Administratorga murojaat qiling.",
        "ru": "⚠️ Адрес мини-приложения не настроен. Обратитесь к администратору.",
        "en": "⚠️ Mini App URL is not configured. Please contact the administrator.",
    },
    "blocked_title": {
        "uz": "🚫 <b>Hisobingiz bloklangan.</b>",
        "ru": "🚫 <b>Ваш аккаунт заблокирован.</b>",
        "en": "🚫 <b>Your account is blocked.</b>",
    },
    "help_text": {
        "uz": "ℹ️ <b>Qoidalar / Yordam</b>\n\nRevilend Games — Telegram içida guruh bilan öynaladigan stol öyinlari platformasi.\n\n🛡️ <b>Bunker</b> — kartalar böyiça bahslaşib, bunkerga kim tuşişini hal qilasiz.\n🕵️ <b>Mafiya</b> — tunda yaşirin rollar, kunduzi ovoz beriş.\n🔍 <b>Josus (Spyfall)</b> — hamma joyni biladi, faqat josus bilmaydi.\n🐊 <b>Alias / Krokodil</b> — sözni aytmasdan tuşuntiriş.\n💣 <b>Portlovçi Bomba</b> — bombani zararsizlantiriş.\n\nPastdagi bölimlardan birini tanlang. Har bir öyin guruhda boşlanadi: /bunker, /mafia, /spy, /alias yoki /bomb yuboring.",
        "ru": "ℹ️ <b>Правила / Помощь</b>\n\nRevilend Games — платформа настольных игр в Telegram, в которые играют в группе.\n\n🛡️ <b>Бункер</b> — по картам решаете, кто попадёт в бункер.\n🕵️ <b>Мафия</b> — ночью секретные роли, днём голосование.\n🔍 <b>Шпион (Spyfall)</b> — все знают место, кроме шпиона.\n🐊 <b>Alias / Крокодил</b> — объясняйте слово, не называя его.\n💣 <b>Взрывная бомба</b> — обезвредьте бомбу.\n\nВыберите раздел ниже. Каждая игра стартует в группе: отправьте /bunker, /mafia, /spy, /alias или /bomb.",
        "en": "ℹ️ <b>Rules / Help</b>\n\nRevilend Games — a board-game platform in Telegram, played in groups.\n\n🛡️ <b>Bunker</b> — use your cards to decide who gets into the bunker.\n🕵️ <b>Mafia</b> — secret roles at night, voting by day.\n🔍 <b>Spyfall</b> — everyone knows the location except the spy.\n🐊 <b>Alias / Crocodile</b> — explain the word without saying it.\n💣 <b>Ticking Bomb</b> — defuse the bomb.\n\nPick a section below. Every game starts in a group: send /bunker, /mafia, /spy, /alias or /bomb.",
    },
}


__all__ = [
    "BUTTONS",
    "DEFAULT_LANGUAGE",
    "LANGUAGES",
    "LANGUAGE_NAMES",
    "STRINGS",
    "normalize_language",
    "resolve_language",
    "set_language",
    "t",
]
