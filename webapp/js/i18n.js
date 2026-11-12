/* Revilend Games — Mini App ikki tilli lug'at (UZ / RU / EN).
 * Foydalanuvchining Supabase `users.language_code` qiymatini o'qiydi,
 * localStorage `lang` ga yozadi va sahifani qayta yuklamasdan render qiladi.
 */
(function (global) {
  "use strict";

  var SUPPORTED = ["uz", "ru", "en"];
  var DEFAULT = "uz";
  var LS_KEY = "lang";

  var translations = {
    uz: {
      nav_games: "Öyinlar",
      nav_shop: "Dökon",
      nav_rating: "Reyting",
      nav_profile: "Profilim",
      games_title: "Öyinlar",
      games_sub: "Döstlar bilan birga öynang. Xona kodi yoki guruh havolasi orqali kiring.",
      games_count: "5 ta öyin mavjud",
      active_badge: "Faol (5)",
      join_by_code: "Xona kodi bilan kiriş",
      join_placeholder: "BNK482 / MAF123 / SPY123 / BMB123",
      join_button: "Kiriş",
      play: "Öynaş",
      find_match: "Odam qidiriş",
      soon: "Tez kunda",
      shop_title: "Dökon",
      boosters: "Boosterlar",
      frames: "Ramkalar",
      titles: "Unvonlar",
      specials: "Maxsus",
      wheel_banner: "Omad gʻildiragi",
      wheel_free: "kuniga bir bepul",
      wheel_spin: "Omad gʻildiragini aylantirish",
      wheel_title: "Omad gʻildiragi",
      wheel_lede: "Kuniga bir marta bepul, keyin 20 tanga yoki çipta.",
      wheel_won: "Siz yutdingiz",
      coin_unit: "tanga",
      prize: "Sovğa",
      buy_done_title: "Tabriklaymiz!",
      buy_added: "inventaringizga qoşildi.",
      buy_equip_ask: "{noun} hozirning özidayoq taqasizmi?",
      buy_equip_now: "⚡ Hozir taqish",
      buy_close: "Yopiş",
      buy_price: "Narxi",
      buy_left: "Qoladigan balans",
      buy_note: "Tasdiqlasangiz, {amount} tanga hisobingizdan darhol yechiladi.",
      buy_not_enough: "Tangalar yetarli emas — {amount} tanga yetmayapti.",
      buy_busy: "Sotib olinmoqda…",
      close: "Yopiş",
      room_code_mafia: "Mafiya xona kodi MAF123 körinişida böladi",
      room_code_spy: "Josus xona kodi SPY123 körinişida böladi",
      spy_lobby_hint: "Xona kodini döstlaringizga yuboring. Kamida 3 kişi kerak.",
      spy_lobby_title: "Josus yiğilmoqda",
      spy_finished: "Öyin yakunlandi",
      spy_question: "Josus kim?",
      spy_play_hint: "Joyni sir saqlang, savol-javob qiling va josusni toping.",
      sound_off: "Ovozni o'chirish",
      sound_on: "Ovozni yoqish",
      buy_confirm_title: "Xaridni tasdiqlang",
      buy_confirm_yes: "Ha, sotib olaman",
      buy_confirm_cancel: "Bekor qilish",
      my_inventory: "Mening inventarim",
      daily_bonus: "Kunlik bonus",
      missions: "Missiyalar",
      purchase_history: "Xaridlar tarixi",
      weekly_league: "Haftalik liga",
      tournament_sub: "Haftalik çempionat: sovrin fondi, bracket va qatnaşiş — barçasi şu yerda.",
      weekly_league_sub: "Haftalik liga, top öyinçilar va turnir afişasi.",
      all_periods: "Barcha davrlar",
      tournament_race: "Turnir poygasi",
      lang_label: "Til",
      login_lede: "Öyinlarni boşlaş va tangalaringizni boşqariş uçun profilingizga kiring.",
      login_telegram: "Telegram Bot orqali kiriş",
      login_or: "yoki",
      login_ph: "Bot bergan 6 xonali kiriş kodini (yoki Telegram ID’ingizni) kiriting",
      login_button: "Kiriş",
      login_note: "Kodni botda /start yoki /login buyruği bilan oling. Kod 10 daqiqa amal qiladi va bir marta işlatiladi.",
      brand_games: "STOL ÖYINLARI",
      brand_shop: "MEGA STORE",
      brand_rating: "HAFTALIK LIGA",
      game_bunker_name: "Bunker",
      game_bunker_desc: "Falokatdan keyin omon qoliş uçun kartalaringizni oçing, bahslaşing va bunkerga kim tuşişini hal qiling.",
      game_mafia_name: "Mafiya",
      game_mafia_desc: "Keçki şaharda mafiya va tinç aholi örtasidagi kuraş. Guruhda /mafia bilan boşlang.",
      game_spyfall_name: "Josus",
      game_spyfall_desc: "Hamma joyni biladi, faqat bitta josus bilmaydi. Savol-javob orqali uni toping.",
      game_alias_name: "Alias / Krokodil",
      game_alias_desc: "Tezkor söz tuşuntiriş va topiş poygasi. Guruhda /alias bilan boşlang.",
      game_bomb_name: "Portlovçi Bomba",
      game_bomb_desc: "Kartan ol, bombani defuz qil va raqiblaringdan qutqar. Kutilmagan burilishlar kafolatlangan."
    },
    ru: {
      nav_games: "Игры",
      nav_shop: "Магазин",
      nav_rating: "Рейтинг",
      nav_profile: "Мой профиль",
      games_title: "Игры",
      games_sub: "Играйте с друзьями. Войдите по коду комнаты или ссылке группы.",
      games_count: "Доступно 5 игр",
      active_badge: "Активно (5)",
      join_by_code: "Вход по коду комнаты",
      join_placeholder: "BNK482 / MAF123 / SPY123 / BMB123",
      join_button: "Войти",
      play: "Играть",
      find_match: "Поиск игроков",
      soon: "Скоро",
      shop_title: "Магазин",
      boosters: "Бустеры",
      frames: "Рамки",
      titles: "Титулы",
      specials: "Особые",
      wheel_banner: "Колесо удачи",
      wheel_free: "один бесплатный в день",
      wheel_spin: "Крутить колесо удачи",
      wheel_title: "Колесо удачи",
      wheel_lede: "Один раз в день бесплатно, затем 20 монет или билет.",
      wheel_won: "Вы выиграли",
      coin_unit: "монет",
      prize: "Приз",
      buy_done_title: "Поздравляем!",
      buy_added: "добавлено в ваш инвентарь.",
      buy_equip_ask: "Надеть {noun} прямо сейчас?",
      buy_equip_now: "⚡ Надеть сейчас",
      buy_close: "Закрыть",
      buy_price: "Цена",
      buy_left: "Остаток баланса",
      buy_note: "После подтверждения {amount} монет сразу спишутся с баланса.",
      buy_not_enough: "Недостаточно монет — не хватает {amount}.",
      buy_busy: "Покупаем…",
      close: "Закрыть",
      room_code_mafia: "Код комнаты мафии выглядит как MAF123",
      room_code_spy: "Код комнаты шпиона выглядит как SPY123",
      spy_lobby_hint: "Отправьте код комнаты друзьям. Нужно минимум 3 игрока.",
      spy_lobby_title: "Шпион собирается",
      spy_finished: "Игра завершена",
      spy_question: "Кто шпион?",
      spy_play_hint: "Скрывайте место, задавайте вопросы и найдите шпиона.",
      sound_off: "Выключить звук",
      sound_on: "Включить звук",
      buy_confirm_title: "Подтвердите покупку",
      buy_confirm_yes: "Да, купить",
      buy_confirm_cancel: "Отмена",
      my_inventory: "Мой инвентарь",
      daily_bonus: "Ежедневный бонус",
      missions: "Задания",
      purchase_history: "История покупок",
      weekly_league: "Недельная лига",
      tournament_sub: "Недельный чемпионат: призовой фонд, сетка и участие — всё здесь.",
      weekly_league_sub: "Недельная лига, топ игроков и афиша турниров.",
      all_periods: "Все периоды",
      tournament_race: "Гонка турнира",
      lang_label: "Язык",
      login_lede: "Войдите в профиль, чтобы запускать игры и управлять монетами.",
      login_telegram: "Войти через Telegram-бота",
      login_or: "или",
      login_ph: "Введите 6-значный код из бота (или ваш Telegram ID)",
      login_button: "Войти",
      login_note: "Получите код командой /start или /login в боте. Код действует 10 минут и одноразовый.",
      brand_games: "НАСТОЛЬНЫЕ ИГРЫ",
      brand_shop: "МЕГА-МАГАЗИН",
      brand_rating: "НЕДЕЛЬНАЯ ЛИГА",
      game_bunker_name: "Бункер",
      game_bunker_desc: "После катастрофы раскройте карты, поспорьте и решите, кто попадёт в бункер.",
      game_mafia_name: "Мафия",
      game_mafia_desc: "Борьба мафии и мирных жителей. Начните командой /mafia в группе.",
      game_spyfall_name: "Шпион",
      game_spyfall_desc: "Все знают место, только один шпион — нет. Вычислите его вопросами.",
      game_alias_name: "Alias / Крокодил",
      game_alias_desc: "Быстрые объяснения слов и гонка угадывания. Начните командой /alias.",
      game_bomb_name: "Взрывная бомба",
      game_bomb_desc: "Тяни карту, обезвреживай бомбу и спасайся от соперников. Неожиданные повороты гарантированы."
    },
    en: {
      nav_games: "Games",
      nav_shop: "Shop",
      nav_rating: "Leaderboard",
      nav_profile: "My Profile",
      games_title: "Games",
      games_sub: "Play with friends. Join by room code or group link.",
      games_count: "5 games available",
      active_badge: "Active (5)",
      join_by_code: "Join by Room Code",
      join_placeholder: "BNK482 / MAF123 / SPY123 / BMB123",
      join_button: "Join",
      play: "Play",
      find_match: "Find Match",
      soon: "Coming soon",
      shop_title: "Shop",
      boosters: "Boosters",
      frames: "Frames",
      titles: "Titles",
      specials: "Special",
      wheel_banner: "Lucky Wheel",
      wheel_free: "one free per day",
      wheel_spin: "Spin the lucky wheel",
      wheel_title: "Lucky Wheel",
      wheel_lede: "One free spin per day, then 20 coins or a ticket.",
      wheel_won: "You won",
      coin_unit: "coins",
      prize: "Prize",
      buy_done_title: "Congratulations!",
      buy_added: "was added to your inventory.",
      buy_equip_ask: "Equip {noun} right now?",
      buy_equip_now: "⚡ Equip now",
      buy_close: "Close",
      buy_price: "Price",
      buy_left: "Balance left",
      buy_note: "Once confirmed, {amount} coins will be deducted immediately.",
      buy_not_enough: "Not enough coins — {amount} short.",
      buy_busy: "Purchasing…",
      close: "Close",
      room_code_mafia: "A mafia room code looks like MAF123",
      room_code_spy: "A spy room code looks like SPY123",
      spy_lobby_hint: "Send the room code to your friends. At least 3 players needed.",
      spy_lobby_title: "Spy is gathering",
      spy_finished: "Game finished",
      spy_question: "Who is the spy?",
      spy_play_hint: "Keep the place secret, ask questions and find the spy.",
      sound_off: "Mute sound",
      sound_on: "Enable sound",
      buy_confirm_title: "Confirm purchase",
      buy_confirm_yes: "Yes, buy it",
      buy_confirm_cancel: "Cancel",
      my_inventory: "My Inventory",
      daily_bonus: "Daily Bonus",
      missions: "Missions",
      purchase_history: "Purchase History",
      weekly_league: "Weekly League",
      tournament_sub: "Weekly championship: prize pool, bracket and entry — all here.",
      weekly_league_sub: "Weekly league, top players and the tournament poster.",
      all_periods: "All Time",
      tournament_race: "Tournament Race",
      lang_label: "Language",
      login_lede: "Log in to your profile to launch games and manage your coins.",
      login_telegram: "Log in via Telegram Bot",
      login_or: "or",
      login_ph: "Enter the 6-digit code from the bot (or your Telegram ID)",
      login_button: "Log in",
      login_note: "Get the code with /start or /login in the bot. The code lasts 10 minutes and is single-use.",
      brand_games: "BOARD GAMES",
      brand_shop: "MEGA STORE",
      brand_rating: "WEEKLY LEAGUE",
      game_bunker_name: "Bunker",
      game_bunker_desc: "After the disaster, reveal cards, argue and decide who gets into the bunker.",
      game_mafia_name: "Mafia",
      game_mafia_desc: "Mafia vs peaceful town. Start with /mafia in a group.",
      game_spyfall_name: "Spyfall",
      game_spyfall_desc: "Everyone knows the location except one spy. Find them with questions.",
      game_alias_name: "Alias / Crocodile",
      game_alias_desc: "Fast word explaining and guessing race. Start with /alias.",
      game_bomb_name: "Ticking Bomb",
      game_bomb_desc: "Draw a card, defuse the bomb and dodge your rivals. Surprise twists guaranteed."
    }
  };

  /* --- Inline matnlar uchun jumla jadvali ------------------------------
   * index.html ichida tr() ga o'girilmagan inline matnlar juda ko'p.
   * Ularni renderdan keyin jadval bo'yicha almashtiramiz: manba (uz) matn
   * WeakMap'da saqlanadi, shuning uchun tilni qayta almashtirish ham,
   * uz'ga qaytish ham to'g'ri ishlaydi.
   */
  var phraseIndex = {};
  var patternRules = [];
  var textOrigins = typeof WeakMap === "function" ? new WeakMap() : null;
  var attrOrigins = typeof WeakMap === "function" ? new WeakMap() : null;
  var LOCALIZED_ATTRS = ["placeholder", "title", "aria-label"];
  var _observer = null;
  var trackedTextNodes = [];

  /* Til almashganda tarjima qilingan tugunlarni asl (uz) holatiga qaytaramiz. */
  function restoreOriginals() {
    trackedTextNodes.forEach(function (node) {
      if (!textOrigins || !textOrigins.has(node)) return;
      var base = textOrigins.get(node);
      textOrigins.delete(node);
      if (node.nodeValue !== base) node.nodeValue = base;
    });
    trackedTextNodes = [];
  }
  var _pendingSync = false;

  /* Server o'zbek matnini eski (ASCII) ko'rinishda yuboradi (o'yin, g'alaba),
   * Mini App esa yangi alifboda ko'rsatadi (öyin, ğalaba). Ikkala shaklni
   * ham jadvalga qo'shamiz, shunda tarjima har qanday holatda topiladi.
   */
  function asciiVariant(text) {
    return String(text)
      .replace(/Ö/g, "O'").replace(/ö/g, "o'")
      .replace(/Ğ/g, "G'").replace(/ğ/g, "g'")
      .replace(/Ş/g, "Sh").replace(/ş/g, "sh")
      .replace(/Ç/g, "Ch").replace(/ç/g, "ch");
  }

  /* Manba matnlar ikki alifboda keladi: "do'kon" va "dökon". */
  function newAlphabetVariant(text) {
    return String(text)
      .replace(/o[\u2018\u2019\u02BB']/g, "\u00f6")
      .replace(/O[\u2018\u2019\u02BB']/g, "\u00d6")
      .replace(/g[\u2018\u2019\u02BB']/g, "\u011f")
      .replace(/G[\u2018\u2019\u02BB']/g, "\u011e")
      .replace(/sh/g, "\u015f")
      .replace(/Sh/g, "\u015e")
      .replace(/SH/g, "\u015e")
      .replace(/ch/g, "\u00e7")
      .replace(/Ch/g, "\u00c7")
      .replace(/CH/g, "\u00c7");
  }

  function registerPhrases(list) {
    (list || []).forEach(function (row) {
      if (!row || row.length < 2) return;
      var uz = String(row[0]).trim();
      if (!uz) return;
      var entry = { ru: String(row[1] || uz), en: String(row[2] || uz) };
      phraseIndex[uz] = entry;
      var ascii = asciiVariant(uz);
      if (ascii !== uz && !phraseIndex[ascii]) phraseIndex[ascii] = entry;
      var modern = newAlphabetVariant(uz);
      if (modern !== uz && !phraseIndex[modern]) phraseIndex[modern] = entry;
      var modernAscii = newAlphabetVariant(ascii);
      if (modernAscii !== uz && modernAscii !== ascii && !phraseIndex[modernAscii]) {
        phraseIndex[modernAscii] = entry;
      }
    });
  }

  /* Dinamik matnlar: "500 tanga", "3/8 oçilgan" kabi qoliplar. */
  function registerPatterns(list) {
    (list || []).forEach(function (row) {
      if (!row || row.length < 3) return;
      try {
        patternRules.push({ re: new RegExp(row[0]), ru: String(row[1]), en: String(row[2]) });
      } catch (e) {}
    });
  }

  function phraseFor(text) {
    if (!text) return null;
    var direct = phraseIndex[text];
    if (direct) return direct;
    for (var i = 0; i < patternRules.length; i++) {
      var rule = patternRules[i];
      if (!rule.re.test(text)) continue;
      return {
        ru: text.replace(rule.re, rule.ru),
        en: text.replace(rule.re, rule.en)
      };
    }
    return null;
  }

  function localizeTextNode(node) {
    if (!node || node.nodeType !== 3) return;
    // O'zbek tilida tarjima qilinadigan matn yo'q: yangi alifbo pass'i o'zi ishlaydi.
    if (getLanguage() === "uz") return;
    var base = textOrigins && textOrigins.has(node) ? textOrigins.get(node) : node.nodeValue;
    if (!base) return;
    var core = base.trim();
    var map = phraseFor(core);
    if (!map) return;
    if (textOrigins && !textOrigins.has(node)) {
      textOrigins.set(node, base);
      if (trackedTextNodes.length < 20000) trackedTextNodes.push(node);
    }
    var lang = getLanguage();
    var translated = lang === "uz" ? core : (map[lang] || core);
    var next = base.split(core).join(translated);
    if (node.nodeValue !== next) node.nodeValue = next;
  }

  function localizeAttributes(el) {
    if (!el || el.nodeType !== 1 || !attrOrigins) return;
    var store = attrOrigins.get(el) || {};
    var lang = getLanguage();
    LOCALIZED_ATTRS.forEach(function (name) {
      if (!el.hasAttribute || !el.hasAttribute(name)) return;
      if (store[name] === undefined) store[name] = el.getAttribute(name) || "";
      var core = String(store[name]).trim();
      var map = phraseFor(core);
      if (!map) return;
      var next = lang === "uz" ? store[name] : (map[lang] || store[name]);
      // Bir xil qiymatni qayta yozish MutationObserver'ni cheksiz aylantiradi.
      if (el.getAttribute(name) === next) return;
      el.setAttribute(name, next);
    });
    attrOrigins.set(el, store);
  }

  function localizeNode(node) {
    if (!node) return;
    if (node.nodeType === 3) { localizeTextNode(node); return; }
    if (node.nodeType !== 1) return;
    localizeAttributes(node);
    localizeTree(node);
  }

  function localizeTree(root) {
    var el = root || (typeof document !== "undefined" ? document.body : null);
    if (!el || typeof el.querySelectorAll !== "function" || typeof document === "undefined") return;
    var scope = el.nodeType === 1 ? el : document.body;
    if (!scope) return;
    var walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
      acceptNode: function (node) {
        if (node.nodeType === 1) {
          var tag = node.tagName;
          if (tag === "SCRIPT" || tag === "STYLE") return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    }, false);
    var node = walker.nextNode();
    while (node) {
      if (node.nodeType === 3) localizeTextNode(node);
      else localizeAttributes(node);
      node = walker.nextNode();
    }
  }

  function startObserver() {
    if (_observer || typeof MutationObserver !== "function" || typeof document === "undefined") return;
    if (!document.body) return;
    _observer = new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var record = records[i];
        if (record.type === "characterData") {
          if (textOrigins && textOrigins.has(record.target)) localizeTextNode(record.target);
        } else if (record.type === "attributes") {
          localizeAttributes(record.target);
        } else {
          for (var j = 0; j < record.addedNodes.length; j++) localizeNode(record.addedNodes[j]);
        }
      }
    });
    _observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: LOCALIZED_ATTRS
    });
    localizeTree(document.body);
  }

  function normalizeLanguage(code) {
    if (!code) return DEFAULT;
    var c = String(code).toLowerCase().replace("_", "-").split("-")[0];
    if (SUPPORTED.indexOf(c) >= 0) return c;
    if (c === "uz") return "uz";
    return DEFAULT;
  }

  function telegramLanguage() {
    try {
      var wa = global.Telegram && global.Telegram.WebApp;
      if (wa && wa.initDataUnsafe && wa.initDataUnsafe.user) {
        return normalizeLanguage(wa.initDataUnsafe.user.language_code);
      }
    } catch (e) {}
    return null;
  }

  var _current = null;

  function initialFromStorage() {
    try {
      var v = global.localStorage.getItem(LS_KEY);
      if (v) return normalizeLanguage(v);
    } catch (e) {}
    return null;
  }

  function telegramLanguageStrict() {
    try {
      var wa = global.Telegram && global.Telegram.WebApp;
      var raw = wa && wa.initDataUnsafe && wa.initDataUnsafe.user && wa.initDataUnsafe.user.language_code;
      if (!raw) return null;
      var c = String(raw).toLowerCase().replace("_", "-").split("-")[0];
      return SUPPORTED.indexOf(c) >= 0 ? c : null;
    } catch (e) {}
    return null;
  }

  function getLanguage() {
    if (_current) return _current;
    return initialFromStorage() || telegramLanguage() || DEFAULT;
  }

  /* Birinchi ochilish: saqlangan tanlov yo'q bo'lsa Telegram tilini olamiz. */
  function bootstrap() {
    if (_current) return _current;
    var stored = initialFromStorage();
    if (stored) { _current = stored; return _current; }
    var tg = telegramLanguageStrict();
    if (tg) { _current = tg; _pendingSync = true; }
    if (typeof document !== "undefined" && document.documentElement) {
      document.documentElement.setAttribute("lang", getLanguage());
    }
    return getLanguage();
  }

  /* Telegram'dan aniqlangan tilni profil ma'lum bo'lgach serverga yozamiz. */
  function syncPending(userId) {
    if (!_pendingSync) return;
    var id = userId || global.__USER_ID__;
    if (!id) return;
    global.__USER_ID__ = id;
    _pendingSync = false;
    persist(getLanguage());
    saveToServer(getLanguage());
  }

  function t(key, params) {
    var lang = getLanguage();
    var text = (translations[lang] && translations[lang][key]) || translations[uz][key] || key;
    if (params) {
      Object.keys(params).forEach(function (k) {
        text = text.replace("{" + k + "}", String(params[k]));
      });
    }
    return text;
  }

  function persist(lang) {
    try { global.localStorage.setItem(LS_KEY, lang); } catch (e) {}
  }

  function saveToServer(lang) {
    if (typeof fetch !== "function") return;
    var api = global.__API_BASE__ || "";
    fetch(api + "/api/profile/language", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language_code: lang, user_id: global.__USER_ID__ || undefined })
    }).catch(function () {});
  }

  function applyI18n(root) {
    var doc = root || (typeof document !== "undefined" ? document : null);
    if (!doc) return;
    doc.querySelectorAll("[data-i18n]").forEach(function (el) {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    (root || document).querySelectorAll("[data-i18n-ph]").forEach(function (el) {
      el.setAttribute("placeholder", t(el.getAttribute("data-i18n-ph")));
    });
  }

  var LANGS = [
    { code: "uz", flag: "🇺🇿", short: "UZ" },
    { code: "ru", flag: "🇷🇺", short: "RU" },
    { code: "en", flag: "🇬🇧", short: "EN" }
  ];

  function switcherHtml() {
    var cur = getLanguage();
    return '<div class="lang-switcher" role="group" aria-label="' + t("lang_label") + '">' +
      LANGS.map(function (l) {
        return '<button type="button" class="lang-btn' + (l.code === cur ? " active" : "") +
          '" data-i18n-lang="' + l.code + '" aria-pressed="' + (l.code === cur) + '">' +
          l.flag + " " + l.short + "</button>";
      }).join("") + "</div>";
  }

  function renderSwitcher() {
    if (typeof document === "undefined") return;
    var host = document.getElementById("lang-switcher");
    if (host) host.innerHTML = switcherHtml();
  }

  function setLanguage(lang, opts) {
    lang = normalizeLanguage(lang);
    _current = lang;
    persist(lang);
    if (!opts || opts.save !== false) {
      try { saveToServer(lang); } catch (e) {}
    }
    restoreOriginals();
    applyI18n();
    localizeTree(document.body);
    renderSwitcher();
    if (typeof global.__onLanguageChanged__ === "function") {
      global.__onLanguageChanged__(lang);
    }
  }

  /* server'dan kelgan saqlangan tilni birinchi render'dan oldin qo'llash */
  function initFromServer(code) {
    var stored = initialFromStorage();
    if (stored) { _current = normalizeLanguage(stored); _pendingSync = false; return; }
    if (code) { _current = normalizeLanguage(code); persist(_current); _pendingSync = false; return; }
    bootstrap();
  }

  global.I18N = {
    translations: translations,
    normalizeLanguage: normalizeLanguage,
    getLanguage: getLanguage,
    setLanguage: setLanguage,
    t: t,
    applyI18n: applyI18n,
    initFromServer: initFromServer,
    bootstrap: bootstrap,
    syncPending: syncPending,
    registerPhrases: registerPhrases,
    registerPatterns: registerPatterns,
    localizeTree: localizeTree,
    restoreOriginals: restoreOriginals,
    startObserver: startObserver,
    hasPhrase: function (text) { return !!phraseFor(String(text || "").trim()); },
    lookup: function (text) { return phraseFor(String(text || "").trim()); },
    switcherHtml: switcherHtml,
    renderSwitcher: renderSwitcher,
    SUPPORTED: SUPPORTED
  };

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { startObserver(); });
    } else {
      startObserver();
    }
  }
})(typeof window !== "undefined" ? window : this);
