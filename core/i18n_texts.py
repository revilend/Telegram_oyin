"""Handler matnlari: reyting, missiyalar, bonus, booster, matchmaking, blok.

``core/i18n.py`` dagi ``STRINGS`` lug'atiga qo'shiladi.
"""

from __future__ import annotations

HANDLER_STRINGS: dict[str, dict[str, str]] = {
    # --- Bloklangan foydalanuvchi ----------------------------------------
    "blocked_reason_missing": {
        "uz": "Sabab körsatilmagan",
        "ru": "Причина не указана",
        "en": "No reason given",
    },
    "blocked_appeal_link": {
        "uz": "admin bilan böğlaniş",
        "ru": "связаться с админом",
        "en": "contact the admin",
    },
    "blocked_appeal_plain": {
        "uz": "admin bilan böğlaning",
        "ru": "свяжитесь с админом",
        "en": "contact the admin",
    },
    "blocked_message": {
        "uz": "🚫 <b>Hisobingiz bloklangan.</b>\n\n📋 <b>Sabab:</b> {reason}\n\n✍️ <b>Murojaat:</b> {appeal}.",
        "ru": "🚫 <b>Ваш аккаунт заблокирован.</b>\n\n📋 <b>Причина:</b> {reason}\n\n✍️ <b>Обращение:</b> {appeal}.",
        "en": "🚫 <b>Your account is blocked.</b>\n\n📋 <b>Reason:</b> {reason}\n\n✍️ <b>Appeal:</b> {appeal}.",
    },
    # --- Test laboratoriyasi ----------------------------------------------
    "testlab_admin_only": {
        "uz": "⛔ Bu buyruq faqat administrator uçun.",
        "ru": "⛔ Эта команда только для администратора.",
        "en": "⛔ This command is for the administrator only.",
    },
    "testlab_pick": {
        "uz": "🎮 Qaysi öyinni sinaymiz?\nMavjud: {games}\nMasalan: <code>/test_game bunker</code> yoki <code>/test_game all</code>",
        "ru": "🎮 Какую игру тестируем?\nДоступно: {games}\nНапример: <code>/test_game bunker</code> или <code>/test_game all</code>",
        "en": "🎮 Which game should we test?\nAvailable: {games}\nFor example: <code>/test_game bunker</code> or <code>/test_game all</code>",
    },
    "testlab_running": {
        "uz": "🧪 Virtual botlar öyinni öynayapti, biroz kuting…",
        "ru": "🧪 Виртуальные боты играют партию, немного подождите…",
        "en": "🧪 Virtual bots are playing the game, please wait…",
    },
    "testlab_failed": {
        "uz": "❌ Test işlamadi: {error}",
        "ru": "❌ Тест не сработал: {error}",
        "en": "❌ The test failed: {error}",
    },
    "testlab_report_error": {
        "uz": "✅ Test tugadi, lekin hisobotni formatlaşda xato böldi.",
        "ru": "✅ Тест завершён, но при форматировании отчёта произошла ошибка.",
        "en": "✅ The test finished, but formatting the report failed.",
    },
    # --- Reyting ----------------------------------------------------------
    "leaderboard_row": {
        "uz": "{place} {name} — <b>{rating}</b> reyting · {wins} ğalaba",
        "ru": "{place} {name} — <b>{rating}</b> рейтинг · {wins} побед",
        "en": "{place} {name} — <b>{rating}</b> rating · {wins} wins",
    },
    "leaderboard_me": {
        "uz": "📊 Sizning reytingingiz: <b>{rating}</b> ({wins} ğalaba, {games} öyin)",
        "ru": "📊 Ваш рейтинг: <b>{rating}</b> ({wins} побед, {games} игр)",
        "en": "📊 Your rating: <b>{rating}</b> ({wins} wins, {games} games)",
    },
    # --- Missiyalar -------------------------------------------------------
    "missions_title": {
        "uz": "🎯 <b>Missiyalar</b>",
        "ru": "🎯 <b>Миссии</b>",
        "en": "🎯 <b>Missions</b>",
    },
    "missions_intro": {
        "uz": "Topşiriqlarni bajaring va tanga işlang!",
        "ru": "Выполняйте задания и зарабатывайте монеты!",
        "en": "Complete tasks and earn coins!",
    },
    "missions_claimed": {
        "uz": "✅ olindi",
        "ru": "✅ получено",
        "en": "✅ claimed",
    },
    "missions_ready": {
        "uz": "🎁 tayyor",
        "ru": "🎁 готово",
        "en": "🎁 ready",
    },
    "missions_ready_count": {
        "uz": "🎁 Olinişi mumkin: <b>{count}</b> ta mukofot",
        "ru": "🎁 Можно получить: <b>{count}</b> наград",
        "en": "🎁 Ready to claim: <b>{count}</b> rewards",
    },
    "missions_none_ready": {
        "uz": "Hozirça tayyor mukofot yöq — öynab davom eting!",
        "ru": "Пока готовых наград нет — продолжайте играть!",
        "en": "No rewards ready yet — keep playing!",
    },
    "missions_claim_button": {
        "uz": "🎁 +{reward} tangani oliş",
        "ru": "🎁 Забрать +{reward} монет",
        "en": "🎁 Claim +{reward} coins",
    },
    "missions_claim_alert": {
        "uz": "🎁 +{reward} tanga! Balans: {balance}",
        "ru": "🎁 +{reward} монет! Баланс: {balance}",
        "en": "🎁 +{reward} coins! Balance: {balance}",
    },
    "missions_load_error": {
        "uz": "⚠️ Missiyalarni yuklab bölmadi. Birozdan keyin urinib köring.",
        "ru": "⚠️ Не удалось загрузить миссии. Попробуйте чуть позже.",
        "en": "⚠️ Could not load missions. Please try again in a moment.",
    },
    "missions_claim_error": {
        "uz": "⚠️ Mukofotni hozirça olib bölmadi. Qayta urinib köring.",
        "ru": "⚠️ Не удалось получить награду. Попробуйте ещё раз.",
        "en": "⚠️ Could not claim the reward right now. Please try again.",
    },
    # --- Kunlik bonus va promo -------------------------------------------
    "promo_prompt": {
        "uz": "🎟 <b>Promo kod</b>\n\nAdmin bergan kodni yuboring (masalan <code>YANGIYIL</code>).\nHar bir foydalanuvçi kodni bir marta işlatadi.",
        "ru": "🎟 <b>Промокод</b>\n\nОтправьте код от администратора (например <code>YANGIYIL</code>).\nКаждый игрок может использовать код один раз.",
        "en": "🎟 <b>Promo code</b>\n\nSend the code from the admin (for example <code>YANGIYIL</code>).\nEach player can use a code once.",
    },
    "bonus_table_title": {
        "uz": "📅 <b>Kunlik mukofotlar jadvali:</b>",
        "ru": "📅 <b>Таблица ежедневных наград:</b>",
        "en": "📅 <b>Daily reward table:</b>",
    },
    "bonus_day": {
        "uz": "{day}-kun",
        "ru": "{day}-й день",
        "en": "Day {day}",
    },
    "bonus_day_big": {
        "uz": " (Katta mukofot!)",
        "ru": " (Большая награда!)",
        "en": " (Big reward!)",
    },
    "bonus_now": {
        "uz": " ← hozir",
        "ru": " ← сейчас",
        "en": " ← now",
    },
    "bonus_claim": {
        "uz": "🎁 <b>Kunlik bonus olindi!</b>\n\n🔥 Hozirgi seriya: <b>{streak}-kun</b>\n🪙 Olgan bonusingiz: <b>+{amount}</b> tanga\n💰 Balans: <b>{balance}</b> tanga\n\n{table}\n\n«Ertaga kirsangiz sizni <b>+{next}</b> tanga kutmoqda! Seriyani uzib qöymang!»",
        "ru": "🎁 <b>Ежедневный бонус получен!</b>\n\n🔥 Текущая серия: <b>{streak}-й день</b>\n🪙 Ваш бонус: <b>+{amount}</b> монет\n💰 Баланс: <b>{balance}</b> монет\n\n{table}\n\n«Завтра вас ждёт <b>+{next}</b> монет! Не прерывайте серию!»",
        "en": "🎁 <b>Daily bonus claimed!</b>\n\n🔥 Current streak: <b>day {streak}</b>\n🪙 Your bonus: <b>+{amount}</b> coins\n💰 Balance: <b>{balance}</b> coins\n\n{table}\n\n“Come back tomorrow for <b>+{next}</b> coins! Don't break the streak!”",
    },
    "bonus_wait": {
        "uz": "🎁 <b>Kunlik bonus</b>\n\n🔥 Hozirgi seriya: <b>{streak}-kun</b>\n⏳ {reason}\n\n📅 Keyingi bonus: <b>+{next}</b> tanga\n\n{table}\n\nSeriyani uzmaslik uçun ertaga ham kirib oling!",
        "ru": "🎁 <b>Ежедневный бонус</b>\n\n🔥 Текущая серия: <b>{streak}-й день</b>\n⏳ {reason}\n\n📅 Следующий бонус: <b>+{next}</b> монет\n\n{table}\n\nЗаходите и завтра, чтобы не прервать серию!",
        "en": "🎁 <b>Daily bonus</b>\n\n🔥 Current streak: <b>day {streak}</b>\n⏳ {reason}\n\n📅 Next bonus: <b>+{next}</b> coins\n\n{table}\n\nCome back tomorrow so the streak continues!",
    },
    "bonus_error": {
        "uz": "⚠️ Bonusni hozirça olib bölmadi. Birozdan keyin urinib köring.",
        "ru": "⚠️ Не удалось получить бонус. Попробуйте чуть позже.",
        "en": "⚠️ Could not claim the bonus right now. Please try again in a moment.",
    },
    "promo_send_text": {
        "uz": "Promo kodni matn körinişida yuboring yoki /cancel yozing.",
        "ru": "Отправьте промокод текстом или напишите /cancel.",
        "en": "Send the promo code as text or type /cancel.",
    },
    "promo_invalid": {
        "uz": "⚠️ {error}\n\nBoşqa kodni yuboring yoki /cancel yozing.",
        "ru": "⚠️ {error}\n\nОтправьте другой код или напишите /cancel.",
        "en": "⚠️ {error}\n\nSend another code or type /cancel.",
    },
    "promo_check_error": {
        "uz": "⚠️ Kodni tekşirib bölmadi. Birozdan keyin urinib köring.",
        "ru": "⚠️ Не удалось проверить код. Попробуйте чуть позже.",
        "en": "⚠️ Could not verify the code. Please try again in a moment.",
    },
    "promo_accepted": {
        "uz": "🎉 <b>Promo kod qabul qilindi!</b>\n\n🎟 <code>{code}</code>\n🪙 <b>+{coins}</b> tanga\n💰 Balans: <b>{balance}</b> tanga",
        "ru": "🎉 <b>Промокод принят!</b>\n\n🎟 <code>{code}</code>\n🪙 <b>+{coins}</b> монет\n💰 Баланс: <b>{balance}</b> монет",
        "en": "🎉 <b>Promo code accepted!</b>\n\n🎟 <code>{code}</code>\n🪙 <b>+{coins}</b> coins\n💰 Balance: <b>{balance}</b> coins",
    },
    # --- Bunker Qalqoni (booster) ----------------------------------------
    "shield_button_yes": {
        "uz": "🛡️ Bunker Qalqonini işlatiş ({price} 🪙)",
        "ru": "🛡️ Использовать Щит бункера ({price} 🪙)",
        "en": "🛡️ Use Bunker Shield ({price} 🪙)",
    },
    "shield_button_no": {
        "uz": "❌ Rad etiş",
        "ru": "❌ Отказаться",
        "en": "❌ Decline",
    },
    "shield_offer": {
        "uz": "🛡️ <b>Sizni bunkerdan haydaşmoqçi!</b>\n\nXona: <code>{code}</code>\nEng köp ovoz sizga berildi. <b>{price} tanga</b> evaziga «Bunker Qalqoni»ni faollaştirib, omon qolasizmi?\n\nQalqon har bir xonada faqat bir marta işlaydi.",
        "ru": "🛡️ <b>Вас хотят изгнать из бункера!</b>\n\nКомната: <code>{code}</code>\nБольше всего голосов у вас. Активировать «Щит бункера» за <b>{price} монет</b> и остаться?\n\nЩит работает только один раз в комнате.",
        "en": "🛡️ <b>They want to expel you from the bunker!</b>\n\nRoom: <code>{code}</code>\nYou got the most votes. Activate the “Bunker Shield” for <b>{price} coins</b> and survive?\n\nThe shield works only once per room.",
    },
    "booster_wrong_button": {
        "uz": "Notöğri tugma.",
        "ru": "Неверная кнопка.",
        "en": "Wrong button.",
    },
    "booster_not_yours": {
        "uz": "Bu qalqon taklifi sizga tegişli emas.",
        "ru": "Это предложение щита не для вас.",
        "en": "This shield offer is not for you.",
    },
    "shield_activated_answer": {
        "uz": "Qalqon faollaştirildi!",
        "ru": "Щит активирован!",
        "en": "Shield activated!",
    },
    "shield_activated": {
        "uz": "🛡️ <b>Bunker Qalqoni faollaştirildi!</b>\n\nBalansdan <b>{price}</b> tanga yeçildi.\nQolgan balans: <b>{balance}</b> tanga.",
        "ru": "🛡️ <b>Щит бункера активирован!</b>\n\nСписано <b>{price}</b> монет.\nОстаток: <b>{balance}</b> монет.",
        "en": "🛡️ <b>Bunker Shield activated!</b>\n\n<b>{price}</b> coins were deducted.\nRemaining balance: <b>{balance}</b> coins.",
    },
    "shield_activated_eliminated": {
        "uz": "\n\nNavbatdagi nomzod <b>{name}</b> bunkerdan haydaldi.",
        "ru": "\n\nСледующий кандидат <b>{name}</b> изгнан из бункера.",
        "en": "\n\nThe next candidate, <b>{name}</b>, was expelled from the bunker.",
    },
    "shield_activated_tie": {
        "uz": "\n\nOvozlar teng bölgani uçun bu raundda boşqa heç kim haydalmadi.",
        "ru": "\n\nГолоса разделились, поэтому в этом раунде больше никого не изгнали.",
        "en": "\n\nThe votes were tied, so nobody else was expelled this round.",
    },
    "shield_rejected_answer": {
        "uz": "Qalqon rad etildi",
        "ru": "Щит отклонён",
        "en": "Shield declined",
    },
    "shield_rejected": {
        "uz": "❌ Qalqon işlatilmadi.\n\n<b>{name}</b> bunkerdan haydaldi.",
        "ru": "❌ Щит не использован.\n\n<b>{name}</b> изгнан из бункера.",
        "en": "❌ Shield not used.\n\n<b>{name}</b> was expelled from the bunker.",
    },
    # --- Matchmaking ------------------------------------------------------
    "mm_pick": {
        "uz": "🌐 <b>Global öyin qidiruvi</b>\n\nQaysi öyin uçun şerik qidirasiz? Navbat tölişi bilan barça iştirokçilarga xona havolasi yuboriladi.",
        "ru": "🌐 <b>Глобальный поиск игры</b>\n\nДля какой игры ищете напарников? Когда очередь заполнится, всем участникам придёт ссылка на комнату.",
        "en": "🌐 <b>Global game search</b>\n\nWhich game are you looking for teammates in? When the queue fills, everyone gets a room link.",
    },
    "mm_game_bunker": {"uz": "🛡️ Bunker", "ru": "🛡️ Бункер", "en": "🛡️ Bunker"},
    "mm_game_mafia": {"uz": "🕵️ Mafiya", "ru": "🕵️ Мафия", "en": "🕵️ Mafia"},
    "mm_game_spyfall": {"uz": "🕶️ Josus (Spyfall)", "ru": "🕶️ Шпион (Spyfall)", "en": "🕶️ Spyfall"},
    "mm_game_alias": {"uz": "🐊 Alias", "ru": "🐊 Alias", "en": "🐊 Alias"},
    "mm_game_bomb": {"uz": "💣 Portlovçi Bomba", "ru": "💣 Взрывная бомба", "en": "💣 Ticking Bomb"},
    "mm_game_default": {"uz": "Öyin", "ru": "Игра", "en": "Game"},
    "mm_cancel_queue": {
        "uz": "❌ Qidiruvni bekor qiliş",
        "ru": "❌ Отменить поиск",
        "en": "❌ Cancel search",
    },
    "mm_other_game": {"uz": "◀️ Boşqa öyin", "ru": "◀️ Другая игра", "en": "◀️ Another game"},
    "mm_join_game": {"uz": "🎮 Öyinga kiriş", "ru": "🎮 Войти в игру", "en": "🎮 Enter game"},
    "mm_match": {
        "uz": "✅ <b>{title}: jamoa yiğildi!</b>\n\nXona kodi: <code>{code}</code>\nÖyinçilar: {players} kişi\n\nHavola orqali darhol qöşiling.",
        "ru": "✅ <b>{title}: команда собрана!</b>\n\nКод комнаты: <code>{code}</code>\nИгроков: {players}\n\nЗаходите по ссылке прямо сейчас.",
        "en": "✅ <b>{title}: your team is ready!</b>\n\nRoom code: <code>{code}</code>\nPlayers: {players}\n\nJoin right away via the link.",
    },
    "mm_queue": {
        "uz": "⏳ Navbatga qöşildingiz! Odamlar yiğilişi bilan xabar beramiz (Hozir navbatda: {count} kişi)...\n\n🎮 Öyin: <b>{title}</b>\nKerakli öyinçi: {minimum} kişi",
        "ru": "⏳ Вы в очереди! Сообщим, когда игроки соберутся (сейчас в очереди: {count})...\n\n🎮 Игра: <b>{title}</b>\nНужно игроков: {minimum}",
        "en": "⏳ You joined the queue! We'll let you know when players gather (currently in queue: {count})...\n\n🎮 Game: <b>{title}</b>\nPlayers needed: {minimum}",
    },
    "mm_queue_need": {
        "uz": "\nYana {need} kişi kerak.",
        "ru": "\nНужно ещё {need} игроков.",
        "en": "\n{need} more players needed.",
    },
    "mm_unknown_game": {
        "uz": "Noma'lum öyin turi",
        "ru": "Неизвестный тип игры",
        "en": "Unknown game type",
    },
    "mm_join_failed": {
        "uz": "Navbatga qöşilib bölmadi",
        "ru": "Не удалось встать в очередь",
        "en": "Could not join the queue",
    },
    "mm_joined": {
        "uz": "Navbatga qöşildingiz!",
        "ru": "Вы в очереди!",
        "en": "You joined the queue!",
    },
    "mm_error": {
        "uz": "Xatolik yuz berdi",
        "ru": "Произошла ошибка",
        "en": "An error occurred",
    },
    "mm_queue_cancelled": {
        "uz": "❌ Qidiruv bekor qilindi.",
        "ru": "❌ Поиск отменён.",
        "en": "❌ Search cancelled.",
    },
    "mm_not_in_queue": {
        "uz": "❌ Siz navbatda emassiz.",
        "ru": "❌ Вас нет в очереди.",
        "en": "❌ You are not in the queue.",
    },
    # --- Menyu ------------------------------------------------------------
    "miniapp_open_button": {
        "uz": "🚀 Öyinlar portaliga kiriş",
        "ru": "🚀 Войти в портал игр",
        "en": "🚀 Open the game portal",
    },
}
