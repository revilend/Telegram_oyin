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

from core.i18n_common import COMMON_STRINGS

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
    # Guruh o'yinlari e'lonlari (dvigatel matnlari) — uch tilda
    # ------------------------------------------------------------------
    "mafia_lobby": {
        "uz": "🕵️‍♂️ <b>MAFIYA ÖYINI BOŞLANMOQDA!</b>\nŞahar mafiyalar çangalida qoldi. Kim omon qoladi?\n\n👥 Qatnaşuvçilar: {players} (jami {total} kişi)",
        "ru": "🕵️‍♂️ <b>ИГРА В МАФИЮ НАЧИНАЕТСЯ!</b>\nГород попал в лапы мафии. Кто выживет?\n\n👥 Участники: {players} (всего {total} чел.)",
        "en": "🕵️‍♂️ <b>MAFIA GAME STARTING!</b>\nThe city is in the mafia's grip. Who will survive?\n\n👥 Players: {players} (total {total})",
    },
    "mafia_night": {
        "uz": "🌃 <b>ŞAHARGA TUN ÇÖKDI!</b>\nMafiya öz qurbonini tanlaydi. Rolli öyinçilar Mini App orqali harakat qiladi.",
        "ru": "🌃 <b>НА ГОРОД ОПУСТИЛАСЬ НОЧЬ!</b>\nМафия выбирает жертву. Игроки с ролями действуют через мини-приложение.",
        "en": "🌃 <b>NIGHT FALLS ON THE CITY!</b>\nThe mafia picks its victim. Role players act via the Mini App.",
    },
    "mafia_day_head": {
        "uz": "🌅 <b>TONG OTDI!</b>\nŞahar uyğondi. Tungi natijalar:",
        "ru": "🌅 <b>РАССВЕТ!</b>\nГород проснулся. Итоги ночи:",
        "en": "🌅 <b>DAYBREAK!</b>\nThe city wakes up. Night results:",
    },
    "mafia_day_none": {
        "uz": "Tunda heç kim halok bölmadi.",
        "ru": "Ночью никто не погиб.",
        "en": "Nobody died last night.",
    },
    "mafia_day_deaths": {
        "uz": "Tunda halok böldilar: {names}.",
        "ru": "Ночью погибли: {names}.",
        "en": "Died last night: {names}.",
    },
    "mafia_day_tail": {
        "uz": "⚖️ Guruhda muhokama boşlandi!",
        "ru": "⚖️ Началось обсуждение в группе!",
        "en": "⚖️ Discussion in the group has started!",
    },
    "mafia_execution": {
        "uz": "⚰️ Şahar aholisi qaroriga köra {who} qatl qilindi! Uning roli: <b>{role}</b> edi!",
        "ru": "⚰️ По решению города {who} казнён! Его роль была: <b>{role}</b>!",
        "en": "⚰️ By the city's verdict {who} was executed! Their role was: <b>{role}</b>!",
    },
    "mafia_end": {
        "uz": "🏆 <b>ÖYIN YAKUNLANDI!</b>\n{winner} ğalaba qozondi!",
        "ru": "🏆 <b>ИГРА ЗАВЕРШЕНА!</b>\nПобедили: {winner}!",
        "en": "🏆 <b>GAME OVER!</b>\n{winner} win!",
    },
    "mafia_role": {
        "uz": "🕵️ <b>Sizning rolingiz: {name}</b>\n\n{description}\n\n🎯 Jamoa: <b>{faction}</b>\n🌙 {action}\n🔑 Xona kodi: <code>{code}</code>",
        "ru": "🕵️ <b>Ваша роль: {name}</b>\n\n{description}\n\n🎯 Команда: <b>{faction}</b>\n🌙 {action}\n🔑 Код комнаты: <code>{code}</code>",
        "en": "🕵️ <b>Your role: {name}</b>\n\n{description}\n\n🎯 Team: <b>{faction}</b>\n🌙 {action}\n🔑 Room code: <code>{code}</code>",
    },
    "mafia_role_unknown": {"uz": "Noma'lum", "ru": "Неизвестно", "en": "Unknown"},
    "role_name_citizen": {"uz": "Tinch fuqaro", "ru": "Мирный житель", "en": "Citizen"},
    "role_desc_citizen": {"uz": "Tunda maxsus harakati yo'q. Kunduzi muhokamada qatnashadi va mafiyani topishga yordam beradi.", "ru": "Нет особых ночных действий. Днём участвует в обсуждении и помогает найти мафию.", "en": "No special night actions. By day you join discussions and help find the mafia."},
    "role_name_sheriff": {"uz": "Komissar Katani", "ru": "Комиссар", "en": "Sheriff"},
    "role_desc_sheriff": {"uz": "Har tunda bitta o'yinchini tekshiradi yoki o'q uzib o'ldiradi. Tekshiruvda uning mafiya yoki tinch aholi ekanini bilib oladi.", "ru": "Каждую ночь проверяет или убивает одного игрока. Проверка показывает, мафия он или мирный житель.", "en": "Each night checks or shoots one player. A check reveals whether they are mafia or a civilian."},
    "role_name_doctor": {"uz": "Doktor", "ru": "Доктор", "en": "Doctor"},
    "role_desc_doctor": {"uz": "Har tunda bitta o'yinchini davolaydi va uni o'ldirilishdan saqlaydi.", "ru": "Каждую ночь лечит одного игрока (может лечиться ещё раз), спасая его от убийства мафии.", "en": "Each night heals one player (may heal himself), saving them from the mafia's kill."},
    "role_name_bodyguard": {"uz": "Tansoqchi", "ru": "Телохранитель", "en": "Bodyguard"},
    "role_desc_bodyguard": {"uz": "Tunda bir o'yinchini qo'riqlaydi; unga qilingan hujumni o'ziga oladi.", "ru": "Каждую ночь защищает игрока, принимая удар на себя. Героически жертвует собой.", "en": "Each night protects a player, taking the hit for them. A heroic sacrifice."},
    "role_name_blocker": {"uz": "Kezuvchi (Putana)", "ru": "Ловушка (Путана)", "en": "Trap (Putana)"},
    "role_desc_blocker": {"uz": "Tunda bir o'yinchiga mehmonga boradi va uning tungi harakatini muzlatadi: tekshiruv, otish yoki davolash o'sha kecha bajarilmaydi.", "ru": "Каждую ночь блокирует действия одного игрока: жертва не сможет действовать этой ночью.", "en": "Each night blocks one player's actions: the target cannot act tonight."},
    "role_name_kamikaze": {"uz": "Kamikadze", "ru": "Камикадзе", "en": "Kamikaze"},
    "role_desc_kamikaze": {"uz": "Tunda harakati yo'q. Tunda o'ldirilsa qotilni, kunduzi ovoz bilan haydalsa o'ziga ovoz berganlardan birini o'zi bilan olib ketadi.", "ru": "Днём может взорвать себя, убив голосовавших за него. Опасная жертва.", "en": "By day may blow himself up, killing everyone who voted for him. A dangerous sacrifice."},
    "role_name_sniper": {"uz": "Snayper", "ru": "Снайпер", "en": "Sniper"},
    "role_desc_sniper": {"uz": "Tunda bitta o'yinchini otadi, lekin tinch aholini o'ldirsa o'zi halok bo'ladi.", "ru": "Один раз за игру может ночью застрелить любого игрока. Высокая точность.", "en": "Once per game may shoot any player at night. High precision."},
    "role_name_witch": {"uz": "Jodugar", "ru": "Ведьма", "en": "Witch"},
    "role_desc_witch": {"uz": "Tunda bitta o'yinchini o'ldirishi yoki tiriltirishi mumkin (cheklangan miqdorda).", "ru": "Раз за игру может воскресить убитого и раз — убить любого. Мощная магия.", "en": "Once per game can resurrect a killed player and once kill anyone. Powerful magic."},
    "role_name_mayor": {"uz": "Mer", "ru": "Мэр", "en": "Mayor"},
    "role_desc_mayor": {"uz": "Kunduzgi ovozini ikki barobar kuchli qilishi mumkin; tunda harakati yo'q.", "ru": "Если убит, город узнает, что он был мэром. Утром имеет решающий голос.", "en": "If killed, the city learns he was the mayor. Has the deciding vote in the morning."},
    "role_name_don": {"uz": "Don", "ru": "Дон", "en": "Don"},
    "role_desc_don": {"uz": "Mafiya sardori: tunda qurbonni tanlaydi yoki Komissar Katanini qidiradi. Komissar tekshiruvida begunoh ko'rinadi.", "ru": "Узнаёт результаты проверок комисра. Глава мафии с расширенными возможностями.", "en": "Learns the sheriff's check results. The mafia boss with extra powers."},
    "role_name_mafia": {"uz": "Mafiya", "ru": "Мафия", "en": "Mafioso"},
    "role_desc_mafia": {"uz": "Tunda boshqa mafiya a'zolari bilan birga qurbon tanlaydi.", "ru": "Каждую ночь вместе с мафией выбирает жертву для убийства.", "en": "Each night chooses a victim with the mafia."},
    "role_name_lawyer": {"uz": "Advokat", "ru": "Адвокат", "en": "Lawyer"},
    "role_desc_lawyer": {"uz": "Mafiya advokati: tunda bir o'yinchini himoya qilib, tekshiruv natijasini chalg'itadi.", "ru": "Выступает в защиту клиента: один раз может спасти его от казни городом.", "en": "Defends a client: once can save them from the town's execution."},
    "role_name_blackmailer": {"uz": "Shantajchi", "ru": "Шантажист", "en": "Blackmailer"},
    "role_desc_blackmailer": {"uz": "Tunda bir o'yinchini shantaj qiladi; u ertasi kuni ovoz bera olmaydi.", "ru": "Шантажирует: жертва не сможет говорить на следующий день.", "en": "Blackmails: the target cannot speak the next day."},
    "role_name_maniac": {"uz": "Maniak", "ru": "Маньяк", "en": "Maniac"},
    "role_desc_maniac": {"uz": "Yolg'iz qotil: tunda o'ldiradi va faqat o'zi g'alaba qozonishni istaydi.", "ru": "Действует один. Каждую ночь убивает одного игрока. Побеждает один.", "en": "Acts alone. Each night kills one player. Wins alone."},
    "role_name_jester": {"uz": "Hazilkash", "ru": "Шут", "en": "Jester"},
    "role_desc_jester": {"uz": "Kunduzi ovoz bilan haydalsa o'yinda g'alaba qozonadi; tunda harakati yo'q.", "ru": "Хочет, чтобы его казнили городом. Тогда шут победит.", "en": "Wants the town to execute him. Then the jester wins."},
    "role_name_amnesiac": {"uz": "Amneziya", "ru": "Амнезик", "en": "Amnesiac"},
    "role_desc_amnesiac": {"uz": "Tunda halok bo'lgan o'yinchining rolini eslab qoladi va shu rolni egallaydi.", "ru": "Не помнит, кто он. В середине игры вспомнить роль может кто угодно.", "en": "Doesn't remember who he is. Mid-game anyone may claim the role."},
    "spy_lobby": {
        "uz": "🕶️ <b>JOSUS (SPYFALL) ÖYINI!</b>\nHamma joyni biladi — faqat Josus bilmaydi. Savol-javob orqali uni toping!\n\n👥 Qatnaşuvçilar: {players}\n🔢 Jami: {count}/{maximum} kişi\n🕵️ Josuslar: {spies} ta\n🔑 Xona kodi: <code>{code}</code>\n\nℹ️ {minimum}–6 kişida 1 ta, {double_min}+ kişida 2 ta Josus böladi.",
        "ru": "🕶️ <b>ИГРА «ШПИОН» (SPYFALL)!</b>\nВсе знают место — кроме шпиона. Найдите его вопросами!\n\n👥 Участники: {players}\n🔢 Всего: {count}/{maximum} чел.\n🕵️ Шпионов: {spies}\n🔑 Код комнаты: <code>{code}</code>\n\nℹ️ При {minimum}–6 игроках 1 шпион, при {double_min}+ — 2.",
        "en": "🕶️ <b>SPYFALL GAME!</b>\nEveryone knows the location — except the spy. Find them with questions!\n\n👥 Players: {players}\n🔢 Total: {count}/{maximum}\n🕵️ Spies: {spies}\n🔑 Room code: <code>{code}</code>\n\nℹ️ {minimum}–6 players: 1 spy; {double_min}+: 2 spies.",
    },
    "alias_lobby": {
        "uz": "🐊 <b>ALIAS / KROKODIL</b>\n\n👥 <b>Öyinçilar ({count}/{maximum}):</b>\n{players}\n\n🔑 Xona kodi: <code>{code}</code>\n⏱ Har raund {round_seconds} soniya · kamida {minimum} kişi kerak.\n💤 {round_seconds} soniya faollik bölmasa navbat avtomatik keyingi öyinçiga ötadi.\n💬 Sözni çatda töğri yozgan öyinçi darhol topadi va oçko oladi.\n🔁 Har bir iştirokçi {rounds} martadan tuşuntiradi (jami {total} raund).\n🏆 Topgan öyinçiga +{guess_reward}, tuşuntiruvçiga +{explainer_reward} tanga, umumiy ğolibga +{winner_reward} tanga.",
        "ru": "🐊 <b>ALIAS / КРОКОДИЛ</b>\n\n👥 <b>Игроки ({count}/{maximum}):</b>\n{players}\n\n🔑 Код комнаты: <code>{code}</code>\n⏱ Каждый раунд {round_seconds} сек. · нужно минимум {minimum} чел.\n💤 Если нет активности {round_seconds} сек., ход переходит следующему игроку.\n💬 Кто первым правильно напишет слово в чат — сразу угадывает и получает очки.\n🔁 Каждый участник объясняет {rounds} раз (всего {total} раундов).\n🏆 Угадавшему +{guess_reward}, объясняющему +{explainer_reward} монет, общему победителю +{winner_reward}.",
        "en": "🐊 <b>ALIAS / CROCODILE</b>\n\n👥 <b>Players ({count}/{maximum}):</b>\n{players}\n\n🔑 Room code: <code>{code}</code>\n⏱ Each round {round_seconds} sec. · at least {minimum} players needed.\n💤 If there is no activity for {round_seconds} sec., the turn passes to the next player.\n💬 The first to type the word correctly in chat guesses it and scores.\n🔁 Each participant explains {rounds} times ({total} rounds in all).\n🏆 Guesser +{guess_reward}, explainer +{explainer_reward} coins, overall winner +{winner_reward}.",
    },
    "alias_round_started": {
        "uz": "🐊 <b>ALIAS ÖYINI BOŞLANDI!</b>\n🎤 Hozir <b>{explainer}</b> söz tuşuntirmoqda! ({number}/{total}-raund)\n⏳ Sizda {duration} soniya bor. Sözni birinçi bölib toping!",
        "ru": "🐊 <b>ИГРА ALIAS НАЧАЛАСЬ!</b>\n🎤 Сейчас <b>{explainer}</b> объясняет слово! (раунд {number}/{total})\n⏳ У вас {duration} сек. Угадайте слово первым!",
        "en": "🐊 <b>ALIAS GAME STARTED!</b>\n🎤 Now <b>{explainer}</b> is explaining the word! (round {number}/{total})\n⏳ You have {duration} sec. Guess the word first!",
    },
    "alias_explainer_dm": {
        "uz": "🎯 <b>Sizning sözingiz:</b>\n<b>{word}</b>\n\n{forbidden}\n⏳ {duration} soniya. Sözni va taqiqlangan sözlarni aytmasdan tuşuntiring!\n🔑 Xona: <code>{code}</code> · {number}/{total}-raund",
        "ru": "🎯 <b>Ваше слово:</b>\n<b>{word}</b>\n\n{forbidden}\n⏳ {duration} сек. Объясните слово, не называя его и запрещённые!\n🔑 Комната: <code>{code}</code> · раунд {number}/{total}",
        "en": "🎯 <b>Your word:</b>\n<b>{word}</b>\n\n{forbidden}\n⏳ {duration} sec. Explain it without saying the word or the forbidden ones!\n🔑 Room: <code>{code}</code> · round {number}/{total}",
    },
    "alias_forbidden": {
        "uz": "🚫 <b>Taqiqlangan sözlar:</b>\n{words}",
        "ru": "🚫 <b>Запрещённые слова:</b>\n{words}",
        "en": "🚫 <b>Forbidden words:</b>\n{words}",
    },
    "bomb_lobby": {
        "uz": "💣 <b>PORTLOVÇI BOMBA</b>\nBombani zararsizlantir, raqiblarga hujum qil va tirik qol!\n\n👥 Qatnaşuvçilar: {players}\n🔢 Jami: {count}/{maximum} kişi\n🔑 Xona kodi: <code>{code}</code>\n\nℹ️ {minimum}–{maximum} kişi. Xona egasi öyinni boşlaydi, qolganlar Mini App'dagi qöllarini oçadi.",
        "ru": "💣 <b>ВЗРЫВНАЯ БОМБА</b>\nОбезвредь бомбу, атакуй соперников и выживи!\n\n👥 Участники: {players}\n🔢 Всего: {count}/{maximum} чел.\n🔑 Код комнаты: <code>{code}</code>\n\nℹ️ {minimum}–{maximum} чел. Владелец комнаты запускает игру, остальные открывают руки в мини-приложении.",
        "en": "💣 <b>TICKING BOMB</b>\nDefuse the bomb, attack your rivals and stay alive!\n\n👥 Players: {players}\n🔢 Total: {count}/{maximum}\n🔑 Room code: <code>{code}</code>\n\nℹ️ {minimum}–{maximum} players. The room owner starts the game; the rest open their hands in the Mini App.",
    },
    "btn_enter_mafia": {"uz": "🚪 Mafiyaga kiriş", "ru": "🚪 Войти в мафию", "en": "🚪 Enter Mafia"},
    "btn_enter_spy": {"uz": "🚪 Josusga kiriş", "ru": "🚪 Войти к шпиону", "en": "🚪 Enter Spyfall"},
    "btn_enter_bomb": {"uz": "🚪 Bombaga kiriş", "ru": "🚪 Войти к бомбе", "en": "🚪 Enter Bomb"},
    "btn_join": {"uz": "➕ Qöşiliş", "ru": "➕ Присоединиться", "en": "➕ Join"},
    "btn_start": {"uz": "▶️ Öyinni boşlaş", "ru": "▶️ Начать игру", "en": "▶️ Start game"},
    "btn_end": {"uz": "🛑 Öyinni tugatiş", "ru": "🛑 Завершить игру", "en": "🛑 End game"},
    "btn_vote": {"uz": "🗳 Ovoz beriş", "ru": "🗳 Голосовать", "en": "🗳 Vote"},
    "btn_open_card": {"uz": "🃏 Kartani oçiş / ovoz beriş", "ru": "🃏 Открыть карту / голосовать", "en": "🃏 Open card / vote"},
    "btn_open_hand": {"uz": "🃏 Qölni oçiş / karta öynaş", "ru": "🃏 Открыть руку / играть", "en": "🃏 Open hand / play"},
    "bunker_new_head": {
        "uz": "🆘 <b>Yangi Bunker öyini</b>",
        "ru": "🆘 <b>Новая игра «Бункер»</b>",
        "en": "🆘 <b>New Bunker game</b>",
    },
    "bunker_started_head": {
        "uz": "🎬 <b>Öyin boşlandi!</b>",
        "ru": "🎬 <b>Игра началась!</b>",
        "en": "🎬 <b>Game started!</b>",
    },
    "bunker_supplies": {
        "uz": "📦 <b>Bunkerdagi zaxiralar:</b>",
        "ru": "📦 <b>Запасы в бункере:</b>",
        "en": "📦 <b>Bunker supplies:</b>",
    },
    "bunker_requirements": {
        "uz": "✅ <b>Omon qoliş talablari:</b>",
        "ru": "✅ <b>Требования к выживанию:</b>",
        "en": "✅ <b>Survival requirements:</b>",
    },
    "bunker_room_code": {
        "uz": "🔑 <b>Xona kodi:</b> <code>{code}</code>",
        "ru": "🔑 <b>Код комнаты:</b> <code>{code}</code>",
        "en": "🔑 <b>Room code:</b> <code>{code}</code>",
    },
    "bunker_players": {
        "uz": "👥 <b>Öyinçilar:</b> {count}/{maximum}",
        "ru": "👥 <b>Игроки:</b> {count}/{maximum}",
        "en": "👥 <b>Players:</b> {count}/{maximum}",
    },
    "bunker_capacity": {
        "uz": "🏠 <b>Bunker siğimi:</b> {capacity} kişi",
        "ru": "🏠 <b>Вместимость бункера:</b> {capacity} чел.",
        "en": "🏠 <b>Bunker capacity:</b> {capacity}",
    },
    "bunker_round": {
        "uz": "🔄 <b>Raund:</b> {number}",
        "ru": "🔄 <b>Раунд:</b> {number}",
        "en": "🔄 <b>Round:</b> {number}",
    },
    "btn_enter_bunker": {"uz": "🚪 Bunkerga kiriş", "ru": "🚪 Войти в бункер", "en": "🚪 Enter Bunker"},
    "btn_join_group": {"uz": "➕ Guruh orqali qöşiliş", "ru": "➕ Присоединиться через группу", "en": "➕ Join via group"},
    "btn_alias_start": {"uz": "▶️ Boşlaş", "ru": "▶️ Начать", "en": "▶️ Start"},
    "btn_kevlar": {
        "uz": "🦺 Kevlar oliş ({price} tanga)",
        "ru": "🦺 Купить бронежилет ({price} монет)",
        "en": "🦺 Get Kevlar ({price} coins)",
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


# Umumiy handlerlarning uzun matnlari (qoidalar, taklif, kirish).
STRINGS.update(COMMON_STRINGS)


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
