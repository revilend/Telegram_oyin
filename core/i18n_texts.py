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
    # --- O'yinlar katalogi (tugmalar) -------------------------------------
    "catalog_btn_bunker": {"uz": "🛡️ Bunker — /bunker", "ru": "🛡️ Бункер — /bunker", "en": "🛡️ Bunker — /bunker"},
    "catalog_btn_mafia": {"uz": "🕵️ Mafiya — /mafia", "ru": "🕵️ Мафия — /mafia", "en": "🕵️ Mafia — /mafia"},
    "catalog_btn_spy": {"uz": "🔍 Josus (Spyfall) — /spy", "ru": "🔍 Шпион (Spyfall) — /spy", "en": "🔍 Spyfall — /spy"},
    "catalog_btn_alias": {"uz": "🐊 Alias / Krokodil — /alias", "ru": "🐊 Alias / Крокодил — /alias", "en": "🐊 Alias / Crocodile — /alias"},
    "catalog_btn_bomb": {"uz": "💣 Portlovçi Bomba — /bomb", "ru": "💣 Взрывная бомба — /bomb", "en": "💣 Ticking Bomb — /bomb"},
    "catalog_btn_tournaments": {"uz": "🏆 Haftalik turnirlar", "ru": "🏆 Еженедельные турниры", "en": "🏆 Weekly tournaments"},
    "catalog_btn_add_group": {"uz": "➕ Botni guruhga qöşiş", "ru": "➕ Добавить бота в группу", "en": "➕ Add the bot to a group"},
    "catalog_btn_add_group_small": {"uz": "➕ Guruhga qöşiş", "ru": "➕ Добавить в группу", "en": "➕ Add to group"},
    # --- Do'kon -----------------------------------------------------------
    "shop_pack_button": {
        "uz": "{coins} tanga — {price} söm",
        "ru": "{coins} монет — {price} сум",
        "en": "{coins} coins — {price} UZS",
    },
    "shop_cancel": {"uz": "❌ Bekor qiliş", "ru": "❌ Отмена", "en": "❌ Cancel"},
    "shop_home_title": {"uz": "🪙 <b>Tangalar dökoni</b>", "ru": "🪙 <b>Магазин монет</b>", "en": "🪙 <b>Coin shop</b>"},
    "shop_balance": {
        "uz": "Balans: <b>{balance}</b> tanga",
        "ru": "Баланс: <b>{balance}</b> монет",
        "en": "Balance: <b>{balance}</b> coins",
    },
    "shop_pick_section": {
        "uz": "Kerakli bölumni tanlang:",
        "ru": "Выберите нужный раздел:",
        "en": "Choose the section you need:",
    },
    "shop_btn_pay": {
        "uz": "💳 Tangalar xarid qiliş (Humo/Uzcard)",
        "ru": "💳 Купить монеты (Humo/Uzcard)",
        "en": "💳 Buy coins (Humo/Uzcard)",
    },
    "shop_btn_items": {
        "uz": "🛍️ Buyumlar va Imkoniyatlar dökoni",
        "ru": "🛍️ Магазин предметов и возможностей",
        "en": "🛍️ Items & perks shop",
    },
    "shop_packages_title": {
        "uz": "💳 <b>Tangalar xarid qiliş</b>",
        "ru": "💳 <b>Покупка монет</b>",
        "en": "💳 <b>Buying coins</b>",
    },
    "shop_packages_hint": {
        "uz": "Paketni tanlang — karta raqami va summa keyingi xabarda körinadi.",
        "ru": "Выберите пакет — номер карты и сумма придут в следующем сообщении.",
        "en": "Pick a package — the card number and amount arrive in the next message.",
    },
    "shop_package_line": {
        "uz": "• <b>{coins} tanga</b> — {price} söm",
        "ru": "• <b>{coins} монет</b> — {price} сум",
        "en": "• <b>{coins} coins</b> — {price} UZS",
    },
    "shop_items_text": {
        "uz": "🛍️ <b>Buyumlar va Imkoniyatlar dökoni</b>\n\nBalans: <b>{balance}</b> tanga\n\nBölumni tanlang: busterlar, ramkalar, unvonlar va maxsus sovğalar.",
        "ru": "🛍️ <b>Магазин предметов и возможностей</b>\n\nБаланс: <b>{balance}</b> монет\n\nВыберите раздел: бустеры, рамки, титулы и особые подарки.",
        "en": "🛍️ <b>Items & perks shop</b>\n\nBalance: <b>{balance}</b> coins\n\nChoose a section: boosters, frames, titles and special gifts.",
    },
    "shop_section_line": {
        "uz": "{emoji} <b>{title}</b> — {price} tanga\n<i>{description}</i>",
        "ru": "{emoji} <b>{title}</b> — {price} монет\n<i>{description}</i>",
        "en": "{emoji} <b>{title}</b> — {price} coins\n<i>{description}</i>",
    },
    "shop_special_hint": {
        "uz": "Kuniga bir marta bepul; keyingi aylantiriş 20 tanga yoki çipta.",
        "ru": "Один раз в день бесплатно; следующее вращение — 20 монет или билет.",
        "en": "Free once a day; the next spin costs 20 coins or a ticket.",
    },
    "shop_spin_button": {"uz": "🎰 Aylantiriş", "ru": "🎰 Вращать", "en": "🎰 Spin"},
    "shop_item_button": {
        "uz": "{emoji} {title} — {price}",
        "ru": "{emoji} {title} — {price}",
        "en": "{emoji} {title} — {price}",
    },
    "shop_payment_text": {
        "uz": "💳 <b>Tölov uçun karta</b>\n<code>{card}</code> ({holder})\nSumma: <b>{price} söm</b>\n\nTölovni amalga oşirgaç, çek (skrinşot) rasmini şu yerga yuboring!",
        "ru": "💳 <b>Карта для оплаты</b>\n<code>{card}</code> ({holder})\nСумма: <b>{price} сум</b>\n\nПосле оплаты отправьте сюда чек (скриншот)!",
        "en": "💳 <b>Card for payment</b>\n<code>{card}</code> ({holder})\nAmount: <b>{price} UZS</b>\n\nAfter paying, send the receipt (screenshot) here!",
    },
    "shop_no_card": {"uz": "Karta kiritilmagan", "ru": "Карта не указана", "en": "No card set"},
    "shop_no_holder": {"uz": "Karta egasi kiritilmagan", "ru": "Владелец карты не указан", "en": "Card holder not set"},
    "shop_receipt_caption": {
        "uz": "🧾 <b>Yangi tölov çeki</b>\n\n👤 {name} (@{username})\n🆔 <code>{user_id}</code>\n🪙 {coins} tanga\n💵 {price} söm\n🔖 Çek: <code>{receipt}</code>",
        "ru": "🧾 <b>Новый чек об оплате</b>\n\n👤 {name} (@{username})\n🆔 <code>{user_id}</code>\n🪙 {coins} монет\n💵 {price} сум\n🔖 Чек: <code>{receipt}</code>",
        "en": "🧾 <b>New payment receipt</b>\n\n👤 {name} (@{username})\n🆔 <code>{user_id}</code>\n🪙 {coins} coins\n💵 {price} UZS\n🔖 Receipt: <code>{receipt}</code>",
    },
    "shop_no_username": {"uz": "username yöq", "ru": "нет username", "en": "no username"},
    "shop_no_name": {"uz": "Ismsiz", "ru": "Без имени", "en": "No name"},
    "shop_btn_approve": {"uz": "✅ Tasdiqlaş", "ru": "✅ Подтвердить", "en": "✅ Approve"},
    "shop_btn_reject": {"uz": "❌ Rad etiş", "ru": "❌ Отклонить", "en": "❌ Reject"},
    "shop_not_ready": {
        "uz": "⚠️ Tölov hozirça sozlanmagan. Administrator «👑 Admin panel» → «💳 Karta raqamini sozlaş» orqali kartani kiritişi kerak.",
        "ru": "⚠️ Оплата пока не настроена. Администратор должен указать карту в «👑 Админ-панель» → «💳 Указать номер карты».",
        "en": "⚠️ Payment is not set up yet. The administrator must add a card via “👑 Admin panel” → “💳 Set card number”.",
    },
    "shop_group_only": {
        "uz": "🪙 Tangalar dökoni şaxsiy çatda işlaydi. Botga ötib /shop yuboring.",
        "ru": "🪙 Магазин монет работает в личном чате. Перейдите в бота и отправьте /shop.",
        "en": "🪙 The coin shop works in a private chat. Open the bot and send /shop.",
    },
    "shop_section_missing": {"uz": "Bölum topilmadi", "ru": "Раздел не найден", "en": "Section not found"},
    "shop_item_missing": {"uz": "Buyum topilmadi", "ru": "Предмет не найден", "en": "Item not found"},
    "shop_buy_ok": {
        "uz": "✅ {title} sotib olindi!\nBalans: {balance} tanga",
        "ru": "✅ {title} куплено!\nБаланс: {balance} монет",
        "en": "✅ {title} purchased!\nBalance: {balance} coins",
    },
    "shop_spin_result": {
        "uz": "🎰 {emoji} {reward}\n({source})",
        "ru": "🎰 {emoji} {reward}\n({source})",
        "en": "🎰 {emoji} {reward}\n({source})",
    },
    "shop_spin_free": {"uz": "bepul aylantiriş", "ru": "бесплатное вращение", "en": "free spin"},
    "shop_spin_ticket": {"uz": "çipta işlatildi", "ru": "использован билет", "en": "ticket used"},
    "shop_bad_package": {"uz": "Notöğri paket.", "ru": "Неверный пакет.", "en": "Wrong package."},
    "shop_cancelled_answer": {"uz": "Bekor qilindi", "ru": "Отменено", "en": "Cancelled"},
    "shop_cancelled_text": {
        "uz": "❌ Tölov bekor qilindi.",
        "ru": "❌ Оплата отменена.",
        "en": "❌ Payment cancelled.",
    },
    "shop_no_package": {
        "uz": "⚠️ Paket aniqlanmadi. /shop orqali qaytadan boşlang.",
        "ru": "⚠️ Пакет не определён. Начните заново через /shop.",
        "en": "⚠️ Package not found. Start over with /shop.",
    },
    "shop_no_admin": {
        "uz": "⚠️ ADMIN_ID sozlanmagan, çekni yuborib bölmaydi.",
        "ru": "⚠️ ADMIN_ID не настроен, чек отправить нельзя.",
        "en": "⚠️ ADMIN_ID is not configured, the receipt cannot be sent.",
    },
    "shop_receipt_error": {
        "uz": "⚠️ Çekni qabul qilişda vaqtinça xatolik yuz berdi. Iltimos, qayta yuboring yoki administratorga yozing.",
        "ru": "⚠️ Временная ошибка при приёме чека. Отправьте его ещё раз или напишите администратору.",
        "en": "⚠️ A temporary error occurred while accepting the receipt. Please resend it or contact the admin.",
    },
    "shop_receipt_ok": {
        "uz": "✅ Çekingiz qabul qilindi! Administrator tasdiqlaşini kuting.",
        "ru": "✅ Ваш чек принят! Дождитесь подтверждения администратора.",
        "en": "✅ Your receipt has been received! Wait for the admin's confirmation.",
    },
    "shop_receipt_admin_error": {
        "uz": "⚠️ Çek saqlandi, ammo adminga yuborişda vaqtinça xatolik yuz berdi. Administrator tez orada körib çiqadi.",
        "ru": "⚠️ Чек сохранён, но отправить его админу не удалось. Администратор скоро его увидит.",
        "en": "⚠️ The receipt is saved, but sending it to the admin failed. The admin will review it shortly.",
    },
    "shop_need_photo": {
        "uz": "📸 Iltimos, çekni rasm (skrinşot) yoki PDF fayl körinişida yuboring. Bekor qiliş uçun /cancel yuboring.",
        "ru": "📸 Отправьте чек как фото (скриншот) или PDF. Чтобы отменить, отправьте /cancel.",
        "en": "📸 Send the receipt as a photo (screenshot) or a PDF file. To cancel, send /cancel.",
    },
    "shop_admin_only": {
        "uz": "⛔ Bu amal faqat admin uçun.",
        "ru": "⛔ Это действие только для админа.",
        "en": "⛔ This action is for the admin only.",
    },
    "shop_approved_user": {
        "uz": "✅ Tölovingiz tasdiqlandi! Hisobingizga +{coins} tanga qöşildi 🎉",
        "ru": "✅ Ваша оплата подтверждена! На счёт добавлено +{coins} монет 🎉",
        "en": "✅ Your payment is confirmed! +{coins} coins were added to your account 🎉",
    },
    "shop_rejected_user": {
        "uz": "❌ Tölovingiz rad etildi. Savollar bölsa administrator bilan boğlaning.",
        "ru": "❌ Ваша оплата отклонена. По вопросам свяжитесь с администратором.",
        "en": "❌ Your payment was rejected. Contact the admin if you have questions.",
    },
    "shop_admin_approved": {"uz": "✅ Tasdiqlandi", "ru": "✅ Подтверждено", "en": "✅ Approved"},
    "shop_admin_rejected": {"uz": "❌ Rad etildi", "ru": "❌ Отклонено", "en": "❌ Rejected"},
    "shop_done": {"uz": "Bajarildi", "ru": "Выполнено", "en": "Done"},
    "shop_receipt_default": {"uz": "🧾 Tölov çeki", "ru": "🧾 Чек об оплате", "en": "🧾 Payment receipt"},


    # --- Turnirlar (bot/handlers/tournaments.py) --------------------------
    "tourn_poster_title": {
        "uz": "🏆 <b>Revilend Haftalik Turnirlar</b>",
        "ru": "🏆 <b>Еженедельные турниры Revilend</b>",
        "en": "🏆 <b>Revilend Weekly Tournaments</b>",
    },
    "tourn_poster_empty": {
        "uz": "Hozirça röyxatga oliş oçiq turnir yöq. Tez orada yangi çempionat e'lon qilinadi!",
        "ru": "Сейчас нет турниров с открытой регистрацией. Скоро будет объявлен новый чемпионат!",
        "en": "There are no tournaments open for registration right now. A new championship is coming soon!",
    },
    "tourn_poster_lede": {
        "uz": "Haftalik çempionatlarda kuçingizni sinang — sovrin fondi va şön-şöhrat sizni kutmoqda.",
        "ru": "Проверьте силы в еженедельных чемпионатах — призовой фонд и слава ждут вас.",
        "en": "Test your strength in weekly championships — prize pools and glory await you.",
    },
    "tourn_poster_line_title": {
        "uz": "🏆 <b>{title}!</b>",
        "ru": "🏆 <b>{title}!</b>",
        "en": "🏆 <b>{title}!</b>",
    },
    "tourn_poster_line_game": {
        "uz": "🎮 Öyin: <b>{game}</b>",
        "ru": "🎮 Игра: <b>{game}</b>",
        "en": "🎮 Game: <b>{game}</b>",
    },
    "tourn_poster_line_prize": {
        "uz": "💰 Sovrin fondi: <b>{prize} tanga</b>",
        "ru": "💰 Призовой фонд: <b>{prize} монет</b>",
        "en": "💰 Prize pool: <b>{prize} coins</b>",
    },
    "tourn_poster_line_slots": {
        "uz": "👥 Örinlar: <b>{joined} / {total} kişi</b>",
        "ru": "👥 Места: <b>{joined} / {total} человек</b>",
        "en": "👥 Slots: <b>{joined} / {total} players</b>",
    },
    "tourn_poster_line_start": {
        "uz": "⏰ Boşlaniş vaqti: <b>{when}</b> ({countdown})",
        "ru": "⏰ Начало: <b>{when}</b> ({countdown})",
        "en": "⏰ Starts at: <b>{when}</b> ({countdown})",
    },
    "tourn_poster_line_status": {
        "uz": "📌 Holati: <b>{status}</b>",
        "ru": "📌 Статус: <b>{status}</b>",
        "en": "📌 Status: <b>{status}</b>",
    },
    "tourn_poster_joined": {
        "uz": "✅ Siz bu turnirga röyxatdan ötgansiz.",
        "ru": "✅ Вы зарегистрированы в этом турнире.",
        "en": "✅ You are registered for this tournament.",
    },
    "tourn_poster_fee": {
        "uz": "🎟 Qatnaşiş narxi: <b>{fee} tanga</b> yoki turnir çiptasi.",
        "ru": "🎟 Стоимость участия: <b>{fee} монет</b> или турнирный билет.",
        "en": "🎟 Entry fee: <b>{fee} coins</b> or a tournament ticket.",
    },
    "tourn_poster_tickets": {
        "uz": "🎟 Sizda <b>{count}</b> ta turnir çiptasi bor.",
        "ru": "🎟 У вас <b>{count}</b> турнирных билетов.",
        "en": "🎟 You have <b>{count}</b> tournament tickets.",
    },
    "tourn_poster_hurry": {
        "uz": "Örinlar çeklangan — hoziroq yoziling!",
        "ru": "Места ограничены — регистрируйтесь сейчас!",
        "en": "Slots are limited — register now!",
    },
    "tourn_poster_wait": {
        "uz": "Turnir boşlanişini kuting — barça öyinçilarga xabar beriladi.",
        "ru": "Ждите начала турнира — все игроки получат уведомление.",
        "en": "Wait for the tournament to start — every player will be notified.",
    },
    "tourn_btn_started": {
        "uz": "▶️ Turnir boşlangan",
        "ru": "▶️ Турнир начался",
        "en": "▶️ Tournament started",
    },
    "tourn_btn_joined": {
        "uz": "✅ Siz röyxatdan ötgansiz",
        "ru": "✅ Вы зарегистрированы",
        "en": "✅ You are registered",
    },
    "tourn_btn_leave": {
        "uz": "❌ Röyxatdan çiqiş",
        "ru": "❌ Отменить регистрацию",
        "en": "❌ Unregister",
    },
    "tourn_btn_full": {
        "uz": "⛔ Joylar töldi",
        "ru": "⛔ Мест нет",
        "en": "⛔ Full",
    },
    "tourn_btn_join": {
        "uz": "✍️ Turnirga röyxatdan ötiş",
        "ru": "✍️ Зарегистрироваться",
        "en": "✍️ Register for the tournament",
    },
    "tourn_btn_mini_app": {
        "uz": "🌐 Mini App'da köriş",
        "ru": "🌐 Открыть в Mini App",
        "en": "🌐 Open in Mini App",
    },
    "tourn_btn_reload": {
        "uz": "🔄 Yangilaş",
        "ru": "🔄 Обновить",
        "en": "🔄 Refresh",
    },
    "tourn_btn_back": {
        "uz": "⬅️ Öyinlar röyxati",
        "ru": "⬅️ Список игр",
        "en": "⬅️ Games list",
    },
    "tourn_admin_only": {
        "uz": "⛔ Bu buyruq faqat administrator uçun.",
        "ru": "⛔ Эта команда только для администратора.",
        "en": "⛔ This command is for the administrator only.",
    },
    "tourn_new_format": {
        "uz": "Format: <code>/new_tournament bunker 50 1000 2d</code>\nÖyin: bunker, mafiya, josus, alias, mixed. Vaqt: <code>2h</code>, <code>3d</code> yoki ISO sana.",
        "ru": "Формат: <code>/new_tournament bunker 50 1000 2d</code>\nИгра: bunker, mafiya, josus, alias, mixed. Время: <code>2h</code>, <code>3d</code> или дата ISO.",
        "en": "Format: <code>/new_tournament bunker 50 1000 2d</code>\nGame: bunker, mafiya, josus, alias, mixed. Time: <code>2h</code>, <code>3d</code> or an ISO date.",
    },
    "tourn_new_bad_input": {
        "uz": "⚠️ Narx, sovrin yoki vaqt notöğri kiritildi.",
        "ru": "⚠️ Неверно указана цена, приз или время.",
        "en": "⚠️ The price, prize or time is invalid.",
    },
    "tourn_new_error": {
        "uz": "⚠️ {error}",
        "ru": "⚠️ {error}",
        "en": "⚠️ {error}",
    },
    "tourn_new_created": {
        "uz": "✅ <b>Yangi turnir yaratildi!</b>\n\n🔥 {title}\n🎮 Öyin: {game}\n💰 Sovrin: {prize} tanga\n🎟 Qatnaşiş: {fee} tanga\n🕒 Boşlaniş: {start}",
        "ru": "✅ <b>Новый турнир создан!</b>\n\n🔥 {title}\n🎮 Игра: {game}\n💰 Приз: {prize} монет\n🎟 Участие: {fee} монет\n🕒 Начало: {start}",
        "en": "✅ <b>New tournament created!</b>\n\n🔥 {title}\n🎮 Game: {game}\n💰 Prize: {prize} coins\n🎟 Entry: {fee} coins\n🕒 Starts: {start}",
    },
    "tourn_reloaded": {
        "uz": "Yangilandi",
        "ru": "Обновлено",
        "en": "Refreshed",
    },
    "tourn_join_success": {
        "uz": "✅ <b>Muvaffaqiyatli röyxatdan ötdingiz!</b>\n\n🏆 Turnir: <b>{title}</b>\n🕒 Boşlaniş: <b>{start}</b>\n\nBoşlanişidan 15 daqiqa oldin bot sizga xona havolasini yuboradi.",
        "ru": "✅ <b>Вы успешно зарегистрированы!</b>\n\n🏆 Турнир: <b>{title}</b>\n🕒 Начало: <b>{start}</b>\n\nЗа 15 минут до начала бот пришлёт ссылку на комнату.",
        "en": "✅ <b>You are registered successfully!</b>\n\n🏆 Tournament: <b>{title}</b>\n🕒 Starts: <b>{start}</b>\n\nThe bot will send the room link 15 minutes before the start.",
    },
    "tourn_not_found": {
        "uz": "Turnir topilmadi.",
        "ru": "Турнир не найден.",
        "en": "Tournament not found.",
    },
    "tourn_already_joined": {
        "uz": "✅ Siz allaqaçon röyxatdan ötgansiz!",
        "ru": "✅ Вы уже зарегистрированы!",
        "en": "✅ You are already registered!",
    },
    "tourn_joined_ok": {
        "uz": "✅ Röyxatdan ötdingiz!",
        "ru": "✅ Вы зарегистрированы!",
        "en": "✅ You are registered!",
    },
    "tourn_leave_error": {
        "uz": "⚠️ {error}",
        "ru": "⚠️ {error}",
        "en": "⚠️ {error}",
    },
    "tourn_left": {
        "uz": "❌ Siz turnir röyxatidan çiqdingiz.",
        "ru": "❌ Вы отменили регистрацию в турнире.",
        "en": "❌ You have unregistered from the tournament.",
    },
    "tourn_noop_info": {
        "uz": "Ma'lumot yangilandi",
        "ru": "Информация обновлена",
        "en": "Information updated",
    },
    "tourn_room_started": {
        "uz": "🏆 <b>Turnir boşlandi!</b>\n\n🔥 <b>{title}</b>\n🎮 Öyin: <b>{game}</b>\n🕒 Boşlaniş: <b>{start}</b>\n💰 Sovrin fondi: <b>{prize} tanga</b>\n\n🔗 <b>Xona havolasi:</b> {link}\n\nXonaga kirib, öyinni başlang. Omad! 🍀",
        "ru": "🏆 <b>Турнир начался!</b>\n\n🔥 <b>{title}</b>\n🎮 Игра: <b>{game}</b>\n🕒 Начало: <b>{start}</b>\n💰 Призовой фонд: <b>{prize} монет</b>\n\n🔗 <b>Ссылка на комнату:</b> {link}\n\nЗаходите в комнату и начинайте игру. Удачи! 🍀",
        "en": "🏆 <b>The tournament has started!</b>\n\n🔥 <b>{title}</b>\n🎮 Game: <b>{game}</b>\n🕒 Starts: <b>{start}</b>\n💰 Prize pool: <b>{prize} coins</b>\n\n🔗 <b>Room link:</b> {link}\n\nJoin the room and start the game. Good luck! 🍀",
    },
    "tourn_btn_room": {
        "uz": "🚪 Xonaga kiriş",
        "ru": "🚪 Войти в комнату",
        "en": "🚪 Join the room",
    },
    "tourn_reminder": {
        "uz": "🏆 <b>Turnir boşlanişiga 15 daqiqa qoldi!</b>\n\n🔥 <b>{title}</b>\n🎮 Öyin: <b>{game}</b>\n🕒 Boşlaniş: <b>{start}</b>\n💰 Sovrin fondi: <b>{prize} tanga</b>\n\nGuruhda öyin boşlanişini kuting va tayyor turing. Omad! 🍀",
        "ru": "🏆 <b>До начала турнира 15 минут!</b>\n\n🔥 <b>{title}</b>\n🎮 Игра: <b>{game}</b>\n🕒 Начало: <b>{start}</b>\n💰 Призовой фонд: <b>{prize} монет</b>\n\nЖдите начала игры в группе и будьте готовы. Удачи! 🍀",
        "en": "🏆 <b>15 minutes until the tournament starts!</b>\n\n🔥 <b>{title}</b>\n🎮 Game: <b>{game}</b>\n🕒 Starts: <b>{start}</b>\n💰 Prize pool: <b>{prize} coins</b>\n\nWait for the game to start in the group and be ready. Good luck! 🍀",
    },
}
