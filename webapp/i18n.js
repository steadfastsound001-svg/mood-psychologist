/* i18n: русский (база) ↔ английский. Подключается ДО app.js.
   Принцип: UI написан по-русски; при lang=en обходчик переводит текстовые узлы
   и атрибуты по точному словарю + регэксп-правилам. MutationObserver ловит всё,
   что app.js вставляет динамически. Контент клиента/LLM в словарь не попадает —
   точное совпадение делает перевод безопасным. */
(function () {
  var LANG = "ru";
  try { LANG = localStorage.getItem("mood_lang") || "ru"; } catch (e) {}
  window.APP_LANG = LANG;

  window.setAppLang = function (l) {
    try { localStorage.setItem("mood_lang", l === "en" ? "en" : "ru"); } catch (e) {}
    location.reload();
  };

  /* ── точный словарь ── */
  var D = {
    /* шапки/вкладки */
    "психолог": "psychologist",
    "ДНЕВНИК": "DIARY",
    "сменить тему": "switch theme",
    "светлая тема": "light theme",
    "тёмная тема": "dark theme",

    /* auth */
    "персональный психолог": "personal psychologist",
    "войти через Google": "sign in with Google",
    "войти в браузере": "sign in via browser",
    "вход через Google работает только в обычном браузере — Telegram его блокирует. откроем в браузере.":
      "Google sign-in only works in a regular browser — Telegram blocks it. We'll open your browser.",
    "google-вход не удался, попробуй ещё раз": "Google sign-in failed, try again",
    "вход…": "signing in…",

    /* lock */
    "введи код": "enter passcode",
    "придумай код": "create a passcode",
    "повтори код": "repeat the passcode",
    "коды разные": "codes don't match",
    "неверный код": "wrong passcode",
    "приложи Face ID": "use Face ID",
    "Face ID не прошёл": "Face ID failed",
    "коснись для входа · Face ID": "tap to unlock · Face ID",
    "коснись, чтобы ввести код": "tap to enter passcode",
    "отмена": "cancel",
    "выключена": "off",
    "код": "passcode",

    /* onboarding chrome */
    "назад": "back",
    "дальше": "next",
    "готово": "done",
    "закрыть": "close",
    "пропустить — пройду потом": "skip — I'll do it later",
    "напиши здесь…": "write here…",

    /* chat */
    "напиши что внутри…": "what's inside…",
    "напиши что внутри — разберём вместе": "write what's inside — we'll sort it out together",
    "режим дневника — пиши запись, психолог почистит и сохранит":
      "diary mode — write an entry, the psychologist will polish and save it",
    "пиши запись в дневник…": "write a diary entry…",
    "запись в дневник": "diary entry",
    "голосом": "voice",
    "отправить": "send",
    "скопировано": "copied",
    "нет доступа к микрофону": "no microphone access",
    "распознаю…": "transcribing…",
    "не расслышал — попробуй ещё": "didn't catch that — try again",
    "ошибка распознавания": "transcription error",
    "просыпаюсь, секунду…": "waking up, one sec…",
    "связь сорвалась — попробуй ещё раз": "connection dropped — try again",
    "превышено время ожидания": "request timed out",
    "нет связи": "no connection",
    "(пусто)": "(empty)",

    /* MOOD card */
    "как считается оценка": "how the score works",
    "оценка MOOD": "MOOD score",
    "откроется после 10 сеансов": "unlocks after 10 sessions",
    "оценка MOOD под замком": "MOOD score is locked",
    "скоро — нужно чуть больше данных": "soon — a bit more data needed",
    "ты в ресурсе": "you're in resource",
    "в целом устойчиво": "mostly steady",
    "качает, но держишься": "shaky, but you're holding",
    "тяжёлый период": "rough patch",
    "ритм по дням недели": "weekly rhythm",
    "ритм недели проявится, когда наберётся пара дней — отмечай настроение в дневнике":
      "your weekly rhythm will show after a few days — log your mood in the diary",
    "из чего складывается": "what it's made of",
    "база": "baseline",
    "тесты о тебе": "tests about you",
    "сейчас": "now",
    "дневник + разговоры": "diary + conversations",
    "пн": "mo", "вт": "tu", "ср": "we", "чт": "th", "пт": "fr", "сб": "sa", "вс": "su",

    /* dynmood */
    "настрой за 10 дней": "state over 10 days",
    "психолог читает твой дневник и обновляет раз в 10 дней":
      "the psychologist reads your diary and updates this every 10 days",
    "считаю…": "calculating…",
    "считаю настрой по дневнику — загляни через минуту": "reading your diary — check back in a minute",
    "веди дневник — настрой посчитается за 10 дней": "keep a diary — your state will be scored over 10 days",

    /* weekly */
    "итоги недели": "week in review",
    "психолог подводит черту по твоим разговорам за неделю":
      "the psychologist sums up your conversations for the week",
    "собрать итоги недели": "sum up the week",
    "собираю…": "working on it…",
    "пока мало разговоров для итогов — возвращайся через пару сеансов":
      "not enough conversations yet — come back after a couple of sessions",

    /* портрет */
    "твой портрет": "your portrait",
    "портрет ещё не собран": "portrait not built yet",
    "портрет ещё не собран — нажми кнопку ниже": "portrait not built yet — tap the button below",
    "собрать портрет": "build portrait",
    "пересобрать портрет": "rebuild portrait",
    "поделиться портретом": "share portrait",
    "нравится портрет": "like the portrait",
    "что зашло, а что нет? психолог учится на этом и напишет следующий портрет точнее":
      "what hit home and what missed? the psychologist learns from this and writes the next portrait sharper",
    "например: в точку про слепое пятно, но «опора» — мимо…":
      "e.g.: spot on about the blind spot, but “support” missed…",
    "отправить психологу": "send to psychologist",
    "спасибо — учту и перепишу портрет точнее ✓": "thanks — noted, the next portrait will be sharper ✓",
    "отправляю…": "sending…",
    "загружаю…": "loading…",
    "твой психологический портрет": "your psychological portrait",
    "Мой портрет MOOD": "My MOOD portrait",
    "soul — личный психолог в кармане": "soul — a psychologist in your pocket",

    /* аналитика */
    "аналитика": "analytics",
    "сеансов": "sessions",
    "сообщений": "messages",
    "дней подряд": "day streak",

    /* основа */
    "основа": "foundation",
    "из чего психолог собирает тебя": "what the psychologist builds you from",
    "тесты пройдены · досье · о себе": "tests done · dossier · about you",
    "пройди — психолог узнает тебя со всех сторон": "take them — the psychologist gets to know you from every side",
    "досье": "dossier",
    "тексты, переписки, заметки. до 1 МБ на файл, 5 МБ всего.":
      "texts, chats, notes. up to 1 MB per file, 5 MB total.",
    "+ добавить файл": "+ add file",
    "о себе": "about you",
    "контекст, прошлое, отношения, цели…": "context, past, relationships, goals…",
    "сохранить и обновить портрет": "save & update portrait",
    "обновил портрет ✓": "portrait updated ✓",

    /* тесты */
    "первичный тест о тебе": "primary test about you",
    "пройден": "done",
    "пройти →": "take →",
    "Тест уже пройден. Пройти заново?": "Already completed. Take it again?",
    "ценности": "values",
    "ценности раскрыты": "values uncovered",
    "стресс и опора": "stress & support",
    "карта стресса": "stress map",
    "эмоции": "emotions",
    "эмоциональный профиль": "emotional profile",
    "вкусы": "tastes",
    "вкусовой профиль": "taste profile",
    "сохраняю ответы…": "saving your answers…",
    "подстраиваюсь под тебя…": "adapting to you…",
    "почти готово": "almost there",

    /* онбординг: вопросы */
    "как тебя зовут? как к тебе обращаться?": "what's your name? how should I address you?",
    "сколько тебе лет и чем занимаешься?": "how old are you and what do you do?",
    "что привело тебя сюда? что хочешь понять или изменить в себе?":
      "what brought you here? what do you want to understand or change about yourself?",
    "расскажи коротко о себе: что важное происходит в жизни сейчас, кто рядом.":
      "tell me briefly about yourself: what's important in your life right now, who's around you.",
    "легко завязываю разговор, заряжаюсь от людей": "I start conversations easily, people energize me",
    "доверяю людям, легко прощаю": "I trust people and forgive easily",
    "довожу дела до конца, дисциплинирован": "I finish what I start, disciplined",
    "часто тревожусь, трудно успокоиться": "I worry a lot, hard to calm down",
    "люблю новые идеи, эксперименты, необычное": "I love new ideas, experiments, the unusual",
    "мне легко быть близким и открытым с людьми": "being close and open with people comes easy to me",
    "боюсь, что меня бросят или отвергнут": "I fear being abandoned or rejected",
    "часто сравниваю себя с другими, и не в свою пользу": "I often compare myself to others, not in my favor",
    "моя ценность сильно зависит от достижений и результата": "my self-worth depends heavily on achievements and results",
    "когда плохо — закрываюсь и ухожу в себя": "when things are bad, I shut down and withdraw",
    "что ещё психологу важно знать о тебе, чтобы понять тебя быстрее?":
      "what else should the psychologist know to understand you faster?",
    "совсем не про меня": "not me at all",
    "скорее нет": "mostly no",
    "когда как": "depends",
    "скорее да": "mostly yes",
    "точно про меня": "definitely me",
    "развитие и новый опыт важнее стабильности": "growth and new experience matter more than stability",
    "близкие отношения — главное в жизни": "close relationships are the main thing in life",
    "хочу признания и весомых достижений": "I want recognition and serious achievements",
    "свобода и независимость превыше всего": "freedom and independence above all",
    "ищу смысл, а не просто комфорт": "I'm after meaning, not just comfort",
    "часто чувствую, что не справляюсь": "I often feel I can't cope",
    "могу влиять на то, что со мной происходит": "I can influence what happens to me",
    "стресс бьёт по сну и телу": "stress hits my sleep and body",
    "быстро восстанавливаюсь после трудностей": "I bounce back quickly after hard times",
    "откладываю проблемы вместо решения": "I postpone problems instead of solving them",
    "хорошо понимаю, что именно чувствую": "I understand exactly what I'm feeling",
    "могу открыто выражать эмоции": "I can express emotions openly",
    "эмоции часто захватывают меня целиком": "emotions often take me over completely",
    "умею себя успокоить, когда накрывает": "I know how to calm myself when it hits",
    "легко считываю чувства других людей": "I read other people's feelings easily",
    "в музыке и кино мне важнее смысл и текст, чем фон и настроение":
      "in music and film, meaning and lyrics matter more to me than vibe",
    "люблю то, что выбивает из колеи и цепляет, а не просто развлекает":
      "I love what unsettles and hooks me, not just entertains",
    "постоянно ищу новое — артистов, фильмы, жанры": "I'm always hunting for new artists, films, genres",
    "часто возвращаюсь к старому любимому, оно меня держит": "I keep returning to old favorites, they ground me",
    "мои вкусы — часть меня; важно, чтобы близкие их понимали":
      "my tastes are part of me; it matters that close people get them",

    /* дневник */
    "как ты сегодня?": "how are you today?",
    "отметь настроение — это рисует твою динамику": "log your mood — it draws your dynamics",
    "отмечено сегодня — можно поменять": "logged today — you can change it",
    "тяжело": "rough", "так себе": "meh", "норм": "okay", "хорошо": "good", "отлично": "great",
    "новая запись": "new entry",
    "что сегодня на душе…": "what's on your soul today…",
    "сохранить запись": "save entry",
    "сохранено ✓": "saved ✓",
    "сохраняю…": "saving…",
    "ошибка сохранения": "saving failed",
    "ошибка — ещё раз": "error — try again",
    "прошлые записи": "past entries",
    "пока пусто — напиши первую запись выше": "empty so far — write your first entry above",
    "ещё": "more",

    /* аккаунт */
    "аккаунт": "account",
    "имя": "name",
    "язык": "language",
    "русский": "Russian",
    "защита входа": "app lock",
    "поставить код / Face ID": "set passcode / Face ID",
    "Защитить вход по Face ID?": "Protect sign-in with Face ID?",
    "Защитить вход кодом?": "Protect sign-in with a passcode?",
    "Защита включена. Выключить?": "Lock is on. Turn it off?",
    "Face ID + код": "Face ID + passcode",
    "выйти": "sign out",

    /* установка */
    "добавь soul на домашний экран": "add soul to your home screen",
    "добавь soul на экран «Домой»: «Поделиться» → «На экран Домой»":
      "add soul to your Home Screen: “Share” → “Add to Home Screen”",
    "установить": "install",
  };

  /* ── регэксп-правила для составных строк (целиком узел) ── */
  var R = [
    [/^по (\d+) запис(?:и|ям) · обновится через (\d+) (?:день|дня|дней)$/, "from $1 entries · updates in $2 days"],
    [/^пройди все тесты для анализа · осталось (\d+) из (\d+)$/, "take all tests for analysis · $1 of $2 left"],
    [/^🔒 портрет под замком\. пройди все тесты ниже \(первичный \+ доп\) — осталось (\d+) из (\d+)\. на их основе психолог соберёт глубокий разбор тебя\.$/,
      "🔒 portrait is locked. take all tests below (primary + extra) — $1 of $2 left. the psychologist will build a deep read of you from them."],
    [/^тесты (\d+)\/(\d+) · досье · о себе$/, "tests $1/$2 · dossier · about you"],
    [/^откроется через (\d+) (?:день|дня|дней)$/, "unlocks in $1 days"],
    [/^откроется после (\d+) сеансов?$/, "unlocks after $1 sessions"],
    [/^всего: (.+) \/ 5 МБ$/, "total: $1 / 5 MB"],
    [/^(\d+(?:[.,]\d+)?) КБ$/, "$1 KB"],
    [/^(\d+(?:[.,]\d+)?) МБ$/, "$1 MB"],
    [/^(.+): больше 1 МБ, пропускаю$/, "$1: over 1 MB, skipping"],
    [/^ошибка: ([\s\S]*)$/, "error: $1"],
    [/^ошибка загрузки: ([\s\S]*)$/, "loading error: $1"],
    [/^не удалось: ([\s\S]*)$/, "failed: $1"],
    [/^не удалось собрать: ([\s\S]*)$/, "couldn't build: $1"],
  ];

  function tr(s) {
    if (!s) return s;
    var core = s.trim();
    if (!core || !/[а-яёА-ЯЁ]/.test(core)) return s;
    var hit = D[core];
    if (hit === undefined) {
      for (var i = 0; i < R.length; i++) {
        if (R[i][0].test(core)) { hit = core.replace(R[i][0], R[i][1]); break; }
      }
    }
    if (hit === undefined) return s;
    return s.replace(core, hit);
  }
  window.t = LANG === "en" ? function (s) { return tr(s); } : function (s) { return s; };

  if (LANG !== "en") {
    document.addEventListener("DOMContentLoaded", bindLangBtn);
    return; // русский = исходник, ничего не трогаем
  }

  var ATTRS = ["placeholder", "title", "aria-label"];

  function trAttrs(el) {
    for (var a = 0; a < ATTRS.length; a++) {
      var at = ATTRS[a];
      if (el.hasAttribute(at)) {
        var av = el.getAttribute(at), nv = tr(av);
        if (nv !== av) el.setAttribute(at, nv);
      }
    }
  }

  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) { var v = tr(root.nodeValue); if (v !== root.nodeValue) root.nodeValue = v; return; }
    if (root.nodeType !== 1 && root.nodeType !== 11) return;
    if (root.nodeType === 1) {
      if (root.tagName === "SCRIPT" || root.tagName === "STYLE") return;
      trAttrs(root);
    }
    if (root.querySelectorAll) {
      var els = root.querySelectorAll("[placeholder],[title],[aria-label]");
      for (var i = 0; i < els.length; i++) trAttrs(els[i]);
    }
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var n;
    while ((n = w.nextNode())) {
      var p = n.parentNode && n.parentNode.tagName;
      if (p === "SCRIPT" || p === "STYLE") continue;
      var nv2 = tr(n.nodeValue);
      if (nv2 !== n.nodeValue) n.nodeValue = nv2;
    }
  }

  function boot() {
    document.documentElement.lang = "en";
    document.title = "soul — personal psychologist";
    var md = document.querySelector('meta[name="description"]');
    if (md) md.setAttribute("content", "soul — a psychologist in your pocket. Honest talk, personality portrait, state dynamics.");
    walk(document.body);
    // всё, что app.js дорисовывает — переводим на лету
    new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var m = muts[i];
        if (m.type === "childList") {
          for (var j = 0; j < m.addedNodes.length; j++) walk(m.addedNodes[j]);
        } else if (m.type === "characterData") {
          var v = tr(m.target.nodeValue);
          if (v !== m.target.nodeValue) m.target.nodeValue = v;
        } else if (m.type === "attributes") {
          var el = m.target, at = m.attributeName, av = el.getAttribute(at);
          if (av) { var nv = tr(av); if (nv !== av) el.setAttribute(at, nv); }
        }
      }
    }).observe(document.body, {
      childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ATTRS,
    });
    bindLangBtn();
  }

  function bindLangBtn() {
    var st = document.getElementById("langState");
    var btn = document.getElementById("langBtn");
    if (st) st.textContent = LANG === "en" ? "English" : "русский";
    if (btn) {
      btn.textContent = LANG === "en" ? "переключить на русский" : "switch to English";
      btn.addEventListener("click", function () { window.setAppLang(LANG === "en" ? "ru" : "en"); });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
