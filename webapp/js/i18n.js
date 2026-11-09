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
      buy_confirm_title: "Xaridni tasdiqlang",
      buy_confirm_yes: "Ha, sotib olaman",
      buy_confirm_cancel: "Bekor qilish",
      my_inventory: "Mening inventarim",
      daily_bonus: "Kunlik bonus",
      missions: "Missiyalar",
      purchase_history: "Xaridlar tarixi",
      weekly_league: "Haftalik liga",
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
      buy_confirm_title: "Подтвердите покупку",
      buy_confirm_yes: "Да, купить",
      buy_confirm_cancel: "Отмена",
      my_inventory: "Мой инвентарь",
      daily_bonus: "Ежедневный бонус",
      missions: "Задания",
      purchase_history: "История покупок",
      weekly_league: "Недельная лига",
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
      buy_confirm_title: "Confirm purchase",
      buy_confirm_yes: "Yes, buy it",
      buy_confirm_cancel: "Cancel",
      my_inventory: "My Inventory",
      daily_bonus: "Daily Bonus",
      missions: "Missions",
      purchase_history: "Purchase History",
      weekly_league: "Weekly League",
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

  function getLanguage() {
    if (_current) return _current;
    return initialFromStorage() || telegramLanguage() || DEFAULT;
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
    applyI18n();
    renderSwitcher();
    if (typeof global.__onLanguageChanged__ === "function") {
      global.__onLanguageChanged__(lang);
    }
  }

  /* server'dan kelgan saqlangan tilni birinchi render'dan oldin qo'llash */
  function initFromServer(code) {
    var stored = initialFromStorage();
    if (stored) { _current = stored; return; }
    if (code) { _current = normalizeLanguage(code); persist(_current); }
  }

  global.I18N = {
    translations: translations,
    normalizeLanguage: normalizeLanguage,
    getLanguage: getLanguage,
    setLanguage: setLanguage,
    t: t,
    applyI18n: applyI18n,
    initFromServer: initFromServer,
    switcherHtml: switcherHtml,
    renderSwitcher: renderSwitcher,
    SUPPORTED: SUPPORTED
  };
})(typeof window !== "undefined" ? window : this);
