"""Umumiy handlerlarning uzun uch tilli matnlari (qoidalar, taklif, kirish).

``core/i18n.py`` dagi ``STRINGS`` lug'atiga qo'shiladi, shuning uchun
``t(language, "rules_bunker")`` kabi chaqiruvlar ishlaydi.
"""

from __future__ import annotations

COMMON_STRINGS: dict[str, dict[str, str]] = {
    # --- Qoidalar menyusidagi tugmalar -----------------------------------
    "rules_tab_bunker": {
        "uz": "🛡️ Bunker",
        "ru": "🛡️ Бункер",
        "en": "🛡️ Bunker",
    },
    "rules_tab_mafia": {
        "uz": "🕵️ Mafiya",
        "ru": "🕵️ Мафия",
        "en": "🕵️ Mafia",
    },
    "rules_tab_spy": {
        "uz": "🔍 Josus (Spyfall)",
        "ru": "🔍 Шпион (Spyfall)",
        "en": "🔍 Spyfall",
    },
    "rules_tab_alias": {
        "uz": "🐊 Alias / Krokodil",
        "ru": "🐊 Alias / Крокодил",
        "en": "🐊 Alias / Crocodile",
    },
    "rules_tab_economy": {
        "uz": "🪙 Tangalar va Dökon",
        "ru": "🪙 Монеты и магазин",
        "en": "🪙 Coins & Shop",
    },
    "rules_tab_back": {
        "uz": "⬅️ Bölümlar röyxati",
        "ru": "⬅️ К разделам",
        "en": "⬅️ Back to sections",
    },
    # --- Taklif va kirish -------------------------------------------------
    "invite_share_button": {
        "uz": "📤 Döstlarga yuboriş",
        "ru": "📤 Поделиться с друзьями",
        "en": "📤 Share with friends",
    },
    "invite_share_text": {
        "uz": "Revilend Games — Bunker öyinini birga öynaymiz! 🎮 Taklif havolam: {link}",
        "ru": "Revilend Games — сыграем в Бункер вместе! 🎮 Моя пригласительная ссылка: {link}",
        "en": "Revilend Games — let's play Bunker together! 🎮 My invite link: {link}",
    },
    "login_button": {
        "uz": "🎮 Profilingiz bilan kiriş",
        "ru": "🎮 Войти со своим профилем",
        "en": "🎮 Sign in with your profile",
    },
    "login_error": {
        "uz": "⚠️ Kiriş kodini hozirça yaratib bölmadi. Birozdan keyin urinib köring.",
        "ru": "⚠️ Не удалось создать код входа. Попробуйте ещё раз чуть позже.",
        "en": "⚠️ Could not create a login code right now. Please try again in a moment.",
    },
    "invited_notification": {
        "uz": "🎉 Döstingiz ({name}) taklifingiz bilan qöşildi! Sizga +{bonus} tanga berildi 🪙",
        "ru": "🎉 Ваш друг ({name}) присоединился по вашему приглашению! Вам начислено +{bonus} монет 🪙",
        "en": "🎉 Your friend ({name}) joined through your invite! You received +{bonus} coins 🪙",
    },
    # --- 🛡️ Bunker --------------------------------------------------------
    "rules_bunker": {
        "uz": """🛡️ <b>Bunker qoidalari va kartalari</b>

Falokatdan keyin bunkerga faqat bir neça kişi siğadi. Har bir öyinçi öz kartalari bilan özini taniştiradi va kim omon qolişga loyiqligi birgalikda hal qilinadi.

<b>Kartalar (6 ta):</b>
• <b>Kasb</b> — mutaxassisligingiz (şifokor, injener, oşpaz...).
• <b>Biologiya</b> — yoş, jins va tana tuzilişi.
• <b>Soğliq</b> — kasalliklar yoki soğlom holat.
• <b>Bagaj</b> — özingiz bilan olgan asbob-uskuna.
• <b>Xobbi</b> — qiziqiş va könikmalar.
• <b>Fakt</b> — siz haqingizdagi qöşimça ma'lumot.

<b>Falokat va maxsus kartalar</b> har raundda vaziyatni özgartiradi: ba'zi kartalar boşqalarni foş qiladi yoki himoya beradi.

<b>Bunker Qalqoni:</b> «🛡 Bunker Qalqoni» 50 tangaga haydalişdan bir marta saqlaydi; «✖️ 2 karra ovoz» ovozingizni ikkilantiradi.

<b>Ovoz beriş tartibi:</b>
1. Har kim kartalarini birma-bir oçadi va özini taniştiradi.
2. Muhokamada kim bunkerga tuşişini isbotlaysiz.
3. Ovoz berişda eng köp ovoz olgan öyinçi haydaladi.
4. Bunker siğimiga yetganda öyin tugaydi.

🎮 Guruhda boşlaş: <code>/bunker</code> yoki <code>/newgame</code>.""",
        "ru": """🛡️ <b>Правила и карты «Бункера»</b>

После катастрофы в бункер помещается лишь несколько человек. Каждый игрок представляет себя по своим картам, а вместе вы решаете, кто достоин выжить.

<b>Карты (6 шт.):</b>
• <b>Профессия</b> — ваша специальность (врач, инженер, повар...).
• <b>Биология</b> — возраст, пол и телосложение.
• <b>Здоровье</b> — болезни или крепкое состояние.
• <b>Багаж</b> — инструменты и вещи, которые вы взяли с собой.
• <b>Хобби</b> — увлечения и навыки.
• <b>Факт</b> — дополнительная информация о вас.

<b>Катастрофа и особые карты</b> меняют ситуацию каждый раунд: некоторые карты раскрывают других или дают защиту.

<b>Щит бункера:</b> «🛡 Щит бункера» за 50 монет один раз спасает от изгнания; «✖️ Двойной голос» удваивает ваш голос.

<b>Порядок голосования:</b>
1. Каждый по очереди открывает карты и представляет себя.
2. В обсуждении вы доказываете, почему вам место в бункере.
3. На голосовании изгоняется игрок с наибольшим числом голосов.
4. Игра заканчивается, когда места в бункере заполнены.

🎮 Старт в группе: <code>/bunker</code> или <code>/newgame</code>.""",
        "en": """🛡️ <b>Bunker rules and cards</b>

After the disaster only a few people fit into the bunker. Each player introduces themselves through their cards, and together you decide who deserves to survive.

<b>Cards (6):</b>
• <b>Profession</b> — your specialty (doctor, engineer, cook...).
• <b>Biology</b> — age, gender and build.
• <b>Health</b> — illnesses or robust condition.
• <b>Luggage</b> — tools and gear you brought along.
• <b>Hobby</b> — interests and skills.
• <b>Fact</b> — extra information about you.

<b>Disaster and special cards</b> change the situation every round: some cards expose others or grant protection.

<b>Bunker Shield:</b> “🛡 Bunker Shield” costs 50 coins and saves you from one expulsion; “✖️ Double vote” doubles your vote.

<b>Voting order:</b>
1. Everyone opens their cards one by one and introduces themselves.
2. In the discussion you prove why you belong in the bunker.
3. The player with the most votes is expelled.
4. The game ends when the bunker is full.

🎮 Start in a group: <code>/bunker</code> or <code>/newgame</code>.""",
    },
    # --- 🕵️ Mafiya -------------------------------------------------------
    "rules_mafia": {
        "uz": """🕵️ <b>Mafiya qoidalari va rollari</b>

Şahar mafiya çangalida. <b>Tun</b>da yaşirin rollar harakat qiladi, <b>kun</b>da hamma ovoz berib mafiyani topadi.

<b>Tinç aholi (9 ta rol):</b>
• 🧑 <b>Tinç fuqaro</b> — tunda harakati yöq; kunduzi muhokamada qatnaşadi.
• 👮 <b>Komissar</b> — tunda bir kişini tekşiradi va uning mafiya yoki tinç aholi ekanini biladi.
• 🩺 <b>Şifokor</b> — tunda bir kişini davolaydi va uni ölimdan saqlaydi.
• 💂 <b>Soqçi</b> — bir öyinçini qöriqlaydi; unga qilingan hujumni öziga oladi.
• 🔄 <b>Putanka</b> — tunda bir öyinçining harakatini bloklaydi.
• 🎯 <b>Snayper</b> — tunda aniq öq uzadi; tinç aholini öldirsa özi halok böladi.
• 🧪 <b>Jodugar</b> — tunda bir kişini öldirişi yoki tiriltirişi mumkin.
• 🎩 <b>Hokim</b> — kunduzgi ovozini ikki barobar kuçli qiladi.
• 💥 <b>Kamikadze</b> — öldirilsa qotilni ham özi bilan olib ketadi.

<b>Mafiya (4 ta rol):</b>
• 👑 <b>Don</b> — mafiya sardori; qurbonni tanlaydi va tekşiruvda begunoh körinadi.
• 🔪 <b>Mafioz</b> — tunda boşqa mafiya a'zolari bilan qurbon tanlaydi.
• ⚖️ <b>Advokat</b> — mafiyani himoya qilib, tekşiruv natijasini çalgitadi.
• 🕶 <b>Şantajçi</b> — bir öyinçini şantaj qiladi; u ertasi kuni ovoz bera olmaydi.

<b>Yolğizlar (2 ta rol):</b>
• 🔪 <b>Maniak</b> — yolğiz qotil; tunda öldiradi va faqat özi ğalaba qozonişni istaydi.
• 🃏 <b>Masxaraboz</b> — kunduzi ovoz bilan haydalsa öyinda ğalaba qozonadi.

<b>Qöşimça qoidalar:</b>
• 🦺 <b>Kevlar jilet</b> (40 tanga) — bir marta ölimdan saqlaydi.
• 💬 <b>Sönggi söz / Arvoh</b> — halok bölgan öyinçi bir marta guruhda xayrlaşib, ma'lumot beriş imkoniga ega.
• Tun va kun davrlari taymer bilan çegaralangan; ovoz beriş yakunida eng köp ovoz olgan öyinçi şahardan haydaladi.

🎮 Guruhda boşlaş: <code>/mafia</code>.""",
        "ru": """🕵️ <b>Правила и роли «Мафии»</b>

Город в лапах мафии. <b>Ночью</b> действуют секретные роли, <b>днём</b> все голосуют и ищут мафию.

<b>Мирные жители (9 ролей):</b>
• 🧑 <b>Мирный житель</b> — ночью не действует, днём участвует в обсуждении.
• 👮 <b>Комиссар</b> — ночью проверяет одного игрока и узнаёт, мафия он или мирный.
• 🩺 <b>Врач</b> — ночью лечит одного игрока и спасает его от смерти.
• 💂 <b>Телохранитель</b> — охраняет одного игрока и принимает удар на себя.
• 🔄 <b>Путаник</b> — ночью блокирует действие одного игрока.
• 🎯 <b>Снайпер</b> — ночью стреляет точно; если убьёт мирного, погибнет сам.
• 🧪 <b>Ведьма</b> — ночью может убить или воскресить одного игрока.
• 🎩 <b>Мэр</b> — его дневной голос считается двойным.
• 💥 <b>Камикадзе</b> — если его убьют, он забирает убийцу с собой.

<b>Мафия (4 роли):</b>
• 👑 <b>Дон</b> — главарь мафии; выбирает жертву и при проверке выглядит невиновным.
• 🔪 <b>Мафиози</b> — ночью вместе с другими мафиози выбирает жертву.
• ⚖️ <b>Адвокат</b> — защищает мафию и искажает результат проверки.
• 🕶 <b>Шантажист</b> — шантажирует игрока, и тот не может голосовать на следующий день.

<b>Одиночки (2 роли):</b>
• 🔪 <b>Маньяк</b> — убийца-одиночка; ночью убивает и хочет победить один.
• 🃏 <b>Шут</b> — если его изгонят голосованием днём, он побеждает в игре.

<b>Дополнительные правила:</b>
• 🦺 <b>Кевларовый жилет</b> (40 монет) — один раз спасает от смерти.
• 💬 <b>Последнее слово / Призрак</b> — погибший игрок один раз может попрощаться в группе и передать информацию.
• Ночь и день ограничены таймером; по итогам голосования игрок с наибольшим числом голосов изгоняется из города.

🎮 Старт в группе: <code>/mafia</code>.""",
        "en": """🕵️ <b>Mafia rules and roles</b>

The city is in the grip of the mafia. <b>At night</b> secret roles act, <b>by day</b> everyone votes to find the mafia.

<b>Townsfolk (9 roles):</b>
• 🧑 <b>Citizen</b> — no night action; joins the daytime discussion.
• 👮 <b>Commissioner</b> — checks one player at night and learns whether they are mafia or townsfolk.
• 🩺 <b>Doctor</b> — heals one player at night and saves them from death.
• 💂 <b>Bodyguard</b> — guards one player and takes the hit instead.
• 🔄 <b>Trickster</b> — blocks one player's action at night.
• 🎯 <b>Sniper</b> — fires a precise shot at night; killing a townsperson kills the sniper too.
• 🧪 <b>Witch</b> — may kill or revive one player at night.
• 🎩 <b>Mayor</b> — their daytime vote counts double.
• 💥 <b>Kamikaze</b> — when killed, takes the killer down with them.

<b>Mafia (4 roles):</b>
• 👑 <b>Don</b> — mafia boss; picks the victim and appears innocent when checked.
• 🔪 <b>Mafioso</b> — picks the victim together with the other mafiosi at night.
• ⚖️ <b>Lawyer</b> — shields the mafia and distorts check results.
• 🕶 <b>Blackmailer</b> — blackmails a player, who cannot vote the next day.

<b>Lone wolves (2 roles):</b>
• 🔪 <b>Maniac</b> — a lone killer; strikes at night and wants to win alone.
• 🃏 <b>Jester</b> — wins the game if voted out during the day.

<b>Extra rules:</b>
• 🦺 <b>Kevlar vest</b> (40 coins) — saves you from death once.
• 💬 <b>Last word / Ghost</b> — a dead player may say goodbye in the group once and share information.
• Night and day are timer-bound; at the end of voting the player with the most votes is expelled from the city.

🎮 Start in a group: <code>/mafia</code>.""",
    },
    # --- 🔍 Josus ---------------------------------------------------------
    "rules_spy": {
        "uz": """🔍 <b>Josus (Spyfall) qoidalari</b>

Hamma bitta joyda — masalan, töyxonada, şifoxonada yoki kosmik stantsiyada. Faqat josus qayerda ekanligini bilmaydi.

<b>Lokatsiyalar:</b> 25 ta özbekça joy (Samolyot, Şifoxona, Harbiy baza, Bank, Töyxona, Çoyxona, Kosmik stantsiya, Titanik, Politsiya bölimi, Universitet, Qamoqxona, Kino studiyasi, Suv osti kemasi, Elçixona, Çorsu bozori va boşqalar). Har bir joyda 6–8 ta maxsus rol bor.

<b>Rollar:</b> öyin boşlanganda tinç iştirokçilarga joy nomi va şu joyga mos rol (masalan, «Töyxona» — «Oşpaz») körsatiladi. Josusga joy yaşiriladi: «🕵️ SIZ JOSUSSIZ!» degan ogohlantiriş beriladi.

<b>Öyinçilar:</b> 3–12 kişi. 3–6 kişida 1 ta, 7 va undan köp kişida 2 ta josus böladi.

<b>Maqsad:</b> savol-javob orqali josusni topiş. Josus esa savollarga ehtiyotkorlik bilan javob berib, joyni aniqlaşga harakat qiladi.

<b>Josusning vazifasi:</b> josus istalgan payt Mini App'dagi joylar röyxatidan birini tanlab «Men joyni topdim!» tugmasini bosadi. Töğri topsa — josus ğalaba qozonadi. Xato qilsa — tinç aholi ğalaba qozonadi.

<b>Ovoz beriş:</b> muhokama tugagaç hamma josus deb kimnidir tanlaydi. Josus topilsa tinç aholi +25 tanga, begunoh haydalsa josus +35 tanga oladi.

🛰 <b>Booster:</b> «Josus radari» 20 tangaga 3 ta notöğri joyni öçiradi.

🎮 Guruhda boşlaş: <code>/spy</code> yoki <code>/josus</code>.""",
        "ru": """🔍 <b>Правила «Шпиона» (Spyfall)</b>

Все находятся в одном месте — например, в ресторане, больнице или на космической станции. Только шпион не знает, где он.

<b>Локации:</b> 25 узбекских мест (Самолёт, Больница, Военная база, Банк, Ресторан, Чайхана, Космическая станция, Титаник, Отделение полиции, Университет, Тюрьма, Киностудия, Подводная лодка, Посольство, Чорсу и другие). В каждом месте есть 6–8 особых ролей.

<b>Роли:</b> в начале игры мирным участникам показываются название места и подходящая роль (например, «Ресторан» — «Повар»). От шпиона место скрыто: он получает предупреждение «🕵️ ВЫ ШПИОН!».

<b>Игроки:</b> 3–12 человек. При 3–6 игроках один шпион, при 7 и больше — два.

<b>Цель:</b> найти шпиона вопросами и ответами. Шпион же отвечает осторожно и пытается определить место.

<b>Задача шпиона:</b> в любой момент шпион выбирает место из списка в Mini App и нажимает «Я нашёл место!». Угадал — шпион побеждает. Ошибся — побеждают мирные.

<b>Голосование:</b> после обсуждения все выбирают, кто шпион. Если шпион найден, мирные получают +25 монет; если изгнан невиновный, шпион получает +35 монет.

🛰 <b>Бустер:</b> «Радар шпиона» за 20 монет убирает 3 неверных места.

🎮 Старт в группе: <code>/spy</code> или <code>/josus</code>.""",
        "en": """🔍 <b>Spyfall rules</b>

Everyone is in the same place — a restaurant, a hospital or a space station, for instance. Only the spy does not know where they are.

<b>Locations:</b> 25 Uzbek places (Airplane, Hospital, Military base, Bank, Wedding hall, Teahouse, Space station, Titanic, Police station, University, Prison, Film studio, Submarine, Embassy, Chorsu bazaar and more). Each place has 6–8 special roles.

<b>Roles:</b> when the game starts, townsfolk see the location name and a matching role (for example, “Wedding hall” — “Cook”). The location is hidden from the spy, who gets the warning “🕵️ YOU ARE THE SPY!”.

<b>Players:</b> 3–12. With 3–6 players there is one spy, with 7 or more there are two.

<b>Goal:</b> find the spy through questions and answers. The spy answers carefully and tries to figure out the location.

<b>The spy's task:</b> at any moment the spy picks a place from the list in the Mini App and presses “I found the place!”. If correct — the spy wins. If wrong — the townsfolk win.

<b>Voting:</b> once the discussion ends, everyone votes for who the spy is. If the spy is caught, townsfolk get +25 coins; if an innocent is expelled, the spy gets +35 coins.

🛰 <b>Booster:</b> “Spy radar” costs 20 coins and removes 3 wrong places.

🎮 Start in a group: <code>/spy</code> or <code>/josus</code>.""",
    },
    # --- 🐊 Alias ---------------------------------------------------------
    "rules_alias": {
        "uz": """🐊 <b>Alias / Krokodil qoidalari</b>

Har raundda bitta öyinçi tuşuntiruvçi böladi. U sözni aytmasdan va uçta taqiqlangan sözni işlatmasdan tuşuntiradi. Qolganlar 60 soniya içida sözni topişga harakat qiladi.

<b>Qoidalar:</b>
• Tuşuntiruvçi sözning özini, uning qismlarini yoki taqiqlangan 3 ta sözni aytmaydi.
• Sözni birinçi bölib töğri yozgan öyinçi +10 tanga, tuşuntiruvçi +5 tanga oladi.
• Har bir iştirokçi 2 martadan tuşuntiradi: 3 kişi bölsa jami 6 raund öynaladi.
• Barça raundlar tugagaç eng köp oçko töplagan öyinçi ğolib böladi va +25 tanga oladi.
• Ketma-ket 2 raundda heç kim sözni topmasa, öyin avtomatik töxtaydi va xona yopiladi.

<b>60 soniyalik taymer:</b> vaqt tugasa söz oçiladi va keyingi raund boşlanadi.

<b>Töxtatiş:</b> xona egasi yoki guruh administratori <code>/stop</code>, <code>/stopalias</code> yoki <code>/cancel</code> yuborib öyinni darhol töxtatadi.

🎮 Guruhda boşlaş: <code>/alias</code> yoki <code>/krokodil</code>.""",
        "ru": """🐊 <b>Правила «Alias / Крокодил»</b>

В каждом раунде один игрок становится объясняющим. Он объясняет слово, не называя его и не используя три запрещённых слова. Остальные за 60 секунд пытаются угадать слово.

<b>Правила:</b>
• Объясняющий не называет само слово, его части и три запрещённых слова.
• Первый, кто верно написал слово, получает +10 монет, объясняющий +5 монет.
• Каждый участник объясняет по 2 раза: при 3 игроках всего 6 раундов.
• Когда все раунды закончены, игрок с наибольшим числом очков побеждает и получает +25 монет.
• Если два раунда подряд никто не угадал слово, игра останавливается и комната закрывается.

<b>Таймер 60 секунд:</b> когда время истекает, слово раскрывается и начинается следующий раунд.

<b>Остановка:</b> владелец комнаты или администратор группы отправляет <code>/stop</code>, <code>/stopalias</code> или <code>/cancel</code> и сразу останавливает игру.

🎮 Старт в группе: <code>/alias</code> или <code>/krokodil</code>.""",
        "en": """🐊 <b>Alias / Crocodile rules</b>

Each round one player becomes the explainer. They explain a word without saying it and without using three forbidden words. Everyone else has 60 seconds to guess it.

<b>Rules:</b>
• The explainer must not say the word itself, its parts, or the three forbidden words.
• The first player to type the word correctly gets +10 coins, the explainer gets +5 coins.
• Every player explains twice: with 3 players that is 6 rounds in total.
• When all rounds are over, the player with the most points wins and gets +25 coins.
• If nobody guesses the word in 2 rounds in a row, the game stops automatically and the room closes.

<b>60-second timer:</b> when time runs out the word is revealed and the next round starts.

<b>Stopping:</b> the room owner or a group admin sends <code>/stop</code>, <code>/stopalias</code> or <code>/cancel</code> to stop the game immediately.

🎮 Start in a group: <code>/alias</code> or <code>/krokodil</code>.""",
    },
    # --- 🪙 Tangalar ------------------------------------------------------
    "rules_economy": {
        "uz": """🪙 <b>Tangalar va Dökon</b>

<b>Tangalarni qanday yiğiş mumkin:</b>
• 🎁 <b>Kunlik bonus seriyasi</b> — har kuni kirib oling. Seriya uzilmasa mukofot ösadi: 1-kun +25, 2-kun +35, 3-kun +50, 4-kun +70, 5-kun +100, 6-kun +150, 7-kun +250.
• 🎟 <b>Promokodlar</b> — «🎟 Promo kod» tugmasi orqali admin bergan kodni kiriting.
• 🎯 <b>Missiyalar</b> — «🎯 Missiyalar» bölimida topşiriqlarni bajarib, bir martalik mukofot oling.
• 🏆 <b>Öyin ğalabalari</b> — Bunker, Mafiya, Josus va Alias mukofotlari.
• 👥 <b>Döstlarni taklif qiliş</b> — har bir yangi döst uçun +50 tanga.

<b>Boosterlar:</b>
• 🛡 Bunker Qalqoni (50 🪙) — haydalişdan bir marta saqlaydi.
• ✖️ 2 karra ovoz (15 🪙) — ovozingizni ikkilantiradi.
• 🦺 Kevlar jilet (40 🪙) — Mafiyada bir marta ölimdan saqlaydi.
• 🛰 Josus radari (20 🪙) — 3 ta notöğri joyni öçiradi.

<b>Uzcard / Humo orqali tanga xarid qiliş:</b>
1. «🪙 Tangalar dökoni» tugmasini yoki <code>/shop</code> buyruğini oçing.
2. Kerakli paketni tanlang.
3. Körsatilgan Uzcard yoki Humo kartasiga tölov qiling.
4. Çek (skrinşot) rasmini botga yuboring.
5. Administrator tasdiqlagaç tangalar balansingizga qöşiladi.

Tangalar Mini App'dagi kartalar va boosterlarda işlatiladi; balansni «👤 Mening profilim» bölimida köräsiz.""",
        "ru": """🪙 <b>Монеты и магазин</b>

<b>Как заработать монеты:</b>
• 🎁 <b>Серия ежедневных бонусов</b> — заходите каждый день. Чем длиннее серия, тем больше награда: 1-й день +25, 2-й +35, 3-й +50, 4-й +70, 5-й +100, 6-й +150, 7-й +250.
• 🎟 <b>Промокоды</b> — введите код от администратора через кнопку «🎟 Промокод».
• 🎯 <b>Миссии</b> — выполняйте задания в разделе «🎯 Миссии» и получайте разовую награду.
• 🏆 <b>Победы в играх</b> — награды за Бункер, Мафию, Шпиона и Alias.
• 👥 <b>Приглашение друзей</b> — +50 монет за каждого нового друга.

<b>Бустеры:</b>
• 🛡 Щит бункера (50 🪙) — один раз спасает от изгнания.
• ✖️ Двойной голос (15 🪙) — удваивает ваш голос.
• 🦺 Кевларовый жилет (40 🪙) — один раз спасает от смерти в Мафии.
• 🛰 Радар шпиона (20 🪙) — убирает 3 неверных места.

<b>Покупка монет через Uzcard / Humo:</b>
1. Откройте кнопку «🪙 Магазин монет» или команду <code>/shop</code>.
2. Выберите нужный пакет.
3. Оплатите на указанную карту Uzcard или Humo.
4. Отправьте чек (скриншот) боту.
5. После подтверждения администратором монеты поступят на баланс.

Монеты используются для карт и бустеров в Mini App; баланс виден в разделе «👤 Мой профиль».""",
        "en": """🪙 <b>Coins & Shop</b>

<b>How to earn coins:</b>
• 🎁 <b>Daily bonus streak</b> — check in every day. The longer the streak, the bigger the reward: day 1 +25, day 2 +35, day 3 +50, day 4 +70, day 5 +100, day 6 +150, day 7 +250.
• 🎟 <b>Promo codes</b> — enter a code from the admin with the “🎟 Promo code” button.
• 🎯 <b>Missions</b> — complete tasks in the “🎯 Missions” section for one-time rewards.
• 🏆 <b>Game wins</b> — rewards for Bunker, Mafia, Spyfall and Alias.
• 👥 <b>Invite friends</b> — +50 coins for each new friend.

<b>Boosters:</b>
• 🛡 Bunker Shield (50 🪙) — saves you from expulsion once.
• ✖️ Double vote (15 🪙) — doubles your vote.
• 🦺 Kevlar vest (40 🪙) — saves you from death once in Mafia.
• 🛰 Spy radar (20 🪙) — removes 3 wrong places.

<b>Buying coins via Uzcard / Humo:</b>
1. Open the “🪙 Coin shop” button or the <code>/shop</code> command.
2. Choose the package you need.
3. Pay to the shown Uzcard or Humo card.
4. Send the receipt (screenshot) to the bot.
5. Once an admin confirms, the coins are added to your balance.

Coins are used for cards and boosters in the Mini App; your balance is shown in “👤 My profile”.""",
    },
    # --- Admin bildirishnomasi (yangi o'yinchi) ---------------------------
    "admin_new_user": {
        "uz": """🎉 <b>Yangi foydalanuvçi qöşildi!</b>

👤 <b>İsm:</b> {name}
🔗 <b>Username:</b> {username}
🆔 <b>ID:</b> <code>{user_id}</code>
🌐 <b>Til:</b> {language}
👥 <b>Referal (Kim taklif qildi):</b> {inviter}

📊 <b>Jami öyinçilar soni:</b> {total} kişi""",
        "ru": """🎉 <b>Новый пользователь присоединился!</b>

👤 <b>Имя:</b> {name}
🔗 <b>Username:</b> {username}
🆔 <b>ID:</b> <code>{user_id}</code>
🌐 <b>Язык:</b> {language}
👥 <b>Реферал (кто пригласил):</b> {inviter}

📊 <b>Всего игроков:</b> {total}""",
        "en": """🎉 <b>A new user joined!</b>

👤 <b>Name:</b> {name}
🔗 <b>Username:</b> {username}
🆔 <b>ID:</b> <code>{user_id}</code>
🌐 <b>Language:</b> {language}
👥 <b>Referral (invited by):</b> {inviter}

📊 <b>Total players:</b> {total}""",
    },
    "admin_none": {"uz": "yöq", "ru": "нет", "en": "none"},
    "admin_direct": {"uz": "Töğridan-töğri", "ru": "Напрямую", "en": "Direct"},
    "admin_unknown": {"uz": "Nomaʼlum", "ru": "Неизвестно", "en": "Unknown"},

}
