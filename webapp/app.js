/* MOOD — персональный психолог. Multi-user PWA. */
const tg = window.Telegram?.WebApp;
try { tg?.ready?.(); tg?.expand?.(); } catch (_) {}

const $ = (id) => document.getElementById(id);
const haptic = (k = "light") => { try { tg?.HapticFeedback?.impactOccurred(k); } catch (_) {} };
const hapticOk = () => { try { tg?.HapticFeedback?.notificationOccurred("success"); } catch (_) {} };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ───────── единые монохромные иконки (lucide) ───────── */
const ICONS = {
  "message-circle": '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
  "book-open": '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>',
  "sparkles": '<path d="M9.94 14.06A2 2 0 0 0 8.5 12.6l-6.14-1.58a.5.5 0 0 1 0-.96L8.5 8.48A2 2 0 0 0 9.94 7.04l1.58-6.14a.5.5 0 0 1 .96 0l1.58 6.14A2 2 0 0 0 15.5 8.48l6.14 1.58a.5.5 0 0 1 0 .96L15.5 12.6a2 2 0 0 0-1.44 1.46l-1.58 6.14a.5.5 0 0 1-.96 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/><path d="M4 17v2"/><path d="M5 18H3"/>',
  "mic": '<path d="M12 19v3"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><rect x="9" y="2" width="6" height="13" rx="3"/>',
  "square": '<rect width="14" height="14" x="5" y="5" rx="2"/>',
  "arrow-up": '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
  "feather": '<path d="M12.67 19a2 2 0 0 0 1.42-.59l6.15-6.17a6 6 0 0 0-8.49-8.49L5.59 9.91A2 2 0 0 0 5 11.33V18a1 1 0 0 0 1 1z"/><path d="M16 8 2 22"/><path d="M17.5 15H9"/>',
  "lock": '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  "file-text": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  "flame": '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.07-2.14-.22-4.05 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.15.43-2.29 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
  "chevron-down": '<path d="m6 9 6 6 6-6"/>',
  "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  // монохромные лица настроения (единый размер 24×24)
  "face-1": '<circle cx="12" cy="12" r="10"/><path d="M16 16s-1.5-2-4-2-4 2-4 2"/><path d="M7.5 8 10 9"/><path d="m14 9 2.5-1"/><path d="M9 10h.01"/><path d="M15 10h.01"/>',
  "face-2": '<circle cx="12" cy="12" r="10"/><path d="M16 16s-1.5-2-4-2-4 2-4 2"/><path d="M9 9h.01"/><path d="M15 9h.01"/>',
  "face-3": '<circle cx="12" cy="12" r="10"/><path d="M8 15h8"/><path d="M9 9h.01"/><path d="M15 9h.01"/>',
  "face-4": '<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><path d="M9 9h.01"/><path d="M15 9h.01"/>',
  "face-5": '<circle cx="12" cy="12" r="10"/><path d="M18 13a6 6 0 0 1-12 0Z"/><path d="M9 9h.01"/><path d="M15 9h.01"/>',
};
function ico(name) {
  return `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg>`;
}
function injectIcons(root = document) {
  root.querySelectorAll("[data-ico]").forEach((el) => { el.innerHTML = ico(el.dataset.ico); });
}

/* count-up: плавно гонит число от текущего к target */
function animateNum(el, target, dur = 900) {
  if (!el) return;
  const from = parseInt(el.textContent, 10);
  const start = isNaN(from) ? 0 : from;
  if (start === target) { el.textContent = target; return; }
  const t0 = performance.now();
  const ease = (t) => 1 - Math.pow(1 - t, 3);
  const step = (now) => {
    const p = Math.min(1, (now - t0) / dur);
    el.textContent = Math.round(start + (target - start) * ease(p));
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// PWA: ловим событие установки как можно раньше (оно прилетает до initApp)
let deferredInstall = null;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredInstall = e; });

const TOKEN_KEY = "mood_token";
const getToken = () => localStorage.getItem(TOKEN_KEY) || "";
const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
const clearToken = () => localStorage.removeItem(TOKEN_KEY);

async function api(path, { method = "GET", body = null, auth = true, timeout = 60000 } = {}) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  if (auth && getToken()) headers["Authorization"] = "Bearer " + getToken();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  let res;
  try {
    res = await fetch(path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : null,
      cache: "no-store",
      signal: ctrl.signal,
    });
  } catch (e) {
    clearTimeout(timer);
    if (e.name === "AbortError") throw new Error("превышено время ожидания");
    throw new Error("нет связи");
  }
  clearTimeout(timer);
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) throw Object.assign(new Error(data.error || ("HTTP " + res.status)), { status: res.status, data });
  return data;
}

function show(screen) {
  for (const id of ["authScreen", "onboardScreen", "app"]) $(id).hidden = (id !== screen);
  if (screen === "authScreen") initNeural();
  else stopNeural();
}

/* mdLite: **bold** → <b>, экранирование html */
function mdLite(text) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  let out = esc(text || "");
  out = out.replace(/\*\*([^*\n]{1,80}?)\*\*/g, "<b>$1</b>");
  out = out.replace(/\*([^*\n]+?)\*/g, "$1"); // одиночные звёзды (без lookbehind — Safari < 16.4)
  return out;
}

/* реально ли мы внутри Telegram. SDK telegram-web-app.js в ОБЫЧНОМ браузере
   тоже создаёт window.Telegram.WebApp с рабочим openLink — поэтому проверяем
   initData/platform, а не наличие методов. */
function isInTelegram() {
  return !!(tg && ((tg.initData && tg.initData.length > 0) || (tg.platform && tg.platform !== "unknown")));
}

/* ───────── GATE ───────── */
async function boot() {
  // токен из Google-редиректа: /?token=...&onb=0
  const params = new URLSearchParams(location.search);
  const urlToken = params.get("token");
  if (urlToken) {
    setToken(urlToken);
    history.replaceState({}, "", location.pathname);
  }
  if (params.get("auth_error")) {
    initAuth(); show("authScreen");
    const err = $("authError"); err.textContent = "google-вход не удался, попробуй ещё раз"; err.hidden = false;
    return;
  }
  // нативный вход из Telegram mini-app (Google OAuth там блокируется webview)
  if (!getToken() && tg && tg.initData) {
    try {
      const r = await api("/api/auth/telegram", { method: "POST", auth: false, body: { initData: tg.initData } });
      if (r.token) { setToken(r.token); window.__me = r.user; }
    } catch (_) {}
  }
  if (!getToken()) { initAuth(); show("authScreen"); return; }
  try {
    const me = await api("/api/me");
    window.__me = me.user;
    if (!me.onboarded) { startOnboarding(); show("onboardScreen"); }
    else { initApp(); show("app"); }
  } catch (e) {
    clearToken();
    initAuth();
    show("authScreen");
  }
}

/* ───────── AUTH (только Google) ───────── */
function initAuth() {
  const gbtn = $("googleBtn");
  if (!gbtn) return;
  const inTG = isInTelegram();
  if (inTG) {
    // Google блокирует OAuth внутри Telegram-webview → уводим всё приложение в обычный браузер
    gbtn.innerHTML = '<span class="g-icon">G</span> войти в браузере';
    const hint = $("authHint");
    if (hint) hint.hidden = false;
    gbtn.onclick = (e) => {
      e.preventDefault();
      haptic("medium");
      tg.openLink(location.origin, { try_instant_view: false });
    };
  } else {
    gbtn.onclick = null; // обычный браузер — простой переход по href=/api/auth/google
  }
}

/* ───────── ONBOARDING ───────── */
let obQuestions = [];
let obIndex = 0;
let obAnswers = {};

async function startOnboarding() {
  obAnswers = {};
  obIndex = 0;
  try {
    const r = await api("/api/onboarding/questions", { auth: false });
    obQuestions = r.questions || [];
  } catch (_) { obQuestions = []; }
  $("obBack").onclick = () => { if (obIndex > 0) { obIndex--; renderQuestion(); } };
  $("obNext").onclick = obNext;
  const skip = $("obSkip");
  if (skip) skip.onclick = skipOnboarding;
  renderQuestion();
}

/* пропустить первичный тест — входим в приложение, тест остаётся доступным в профиле */
function skipOnboarding() {
  haptic("medium");
  try {
    api("/api/onboarding/submit", { method: "POST", body: { answers: {}, raw_info: "" } }).catch(() => {});
  } catch (_) {}
  try { initApp(); } catch (_) {}
  show("app");
}

/* перезапуск первичного теста из профиля (когда пропустил) */
function startOnboardingAgain() {
  haptic("medium");
  startOnboarding();
  show("onboardScreen");
}

function renderQuestion() {
  const q = obQuestions[obIndex];
  if (!q) return;
  $("obFill").style.width = ((obIndex) / obQuestions.length * 100) + "%";
  $("obStep").textContent = `${obIndex + 1} / ${obQuestions.length}`;
  $("obQuestion").textContent = q.q;
  $("obBack").hidden = obIndex === 0;
  const box = $("obAnswer");
  box.innerHTML = "";

  if (q.type === "scale") {
    // на шкалах кнопка "дальше" не нужна — тап варианта сразу ведёт дальше
    $("obNext").style.display = "none";
    const wrap = document.createElement("div");
    wrap.className = "scale-wrap";
    (q.labels || ["1","2","3","4","5"]).forEach((label, i) => {
      const b = document.createElement("button");
      b.className = "scale-btn" + (obAnswers[q.id] === i + 1 ? " sel" : "");
      b.innerHTML = `<span class="scale-num">${i + 1}</span><span class="scale-lbl">${label}</span>`;
      b.onclick = () => { haptic(); obAnswers[q.id] = i + 1; setTimeout(obNext, 160); };
      wrap.appendChild(b);
    });
    box.appendChild(wrap);
  } else {
    $("obNext").style.display = "";
    const ta = document.createElement("textarea");
    ta.className = "field area";
    ta.rows = q.short ? 1 : 4;
    ta.placeholder = "напиши здесь…";
    ta.value = obAnswers[q.id] || "";
    ta.oninput = () => { obAnswers[q.id] = ta.value; };
    box.appendChild(ta);
    setTimeout(() => ta.focus(), 100);
    $("obNext").textContent = obIndex === obQuestions.length - 1 ? "готово" : "дальше";
  }
}

async function obNext() {
  if (obIndex < obQuestions.length - 1) {
    obIndex++;
    renderQuestion();
    return;
  }
  // fire-and-forget: НЕ ждём ответа сервера, портрет собирается в фоне.
  // Мгновенно пускаем в приложение — никакого блокирующего overlay.
  try {
    api("/api/onboarding/submit", { method: "POST", body: { answers: obAnswers, raw_info: "" }, timeout: 90000 })
      .catch((e) => console.warn("submit bg error:", e));
  } catch (e) { console.warn(e); }
  hapticOk();
  try { initApp(); } catch (e) { console.warn("initApp error:", e); }
  show("app");
}

/* ───────── APP (chat + profile) ───────── */
let appInited = false;
function initApp() {
  stopNeural();
  fetch("/api/health", { cache: "no-store" }).catch(() => {});  // будим спящий инстанс заранее
  if (!appInited) {
    appInited = true;
    injectIcons();
    document.querySelectorAll(".tab-item").forEach((b) => {
      b.addEventListener("click", () => { haptic("medium"); switchView(b.dataset.view, true); });
    });
    setupChat();
    $("profSave").onclick = saveProfileInfo;
    $("profCompile").onclick = compilePortrait;
    $("profExport").onclick = exportPortrait;
    $("pfLikeBtn").onclick = () => { haptic(); const b = $("pfBox"); b.hidden = !b.hidden; if (!b.hidden) $("pfText").focus(); };
    $("pfSend").onclick = sendPortraitFeedback;
    $("weeklyBtn").onclick = genWeekly;
    $("logoutBtn").onclick = () => { clearToken(); location.reload(); };
    $("fileBtn").onclick = () => $("fileInput").click();
    $("fileInput").onchange = (e) => uploadFiles(e.target.files);
    $("diarySave").onclick = saveDiaryFromTab;
    const dh = $("dossierHead");
    if (dh) dh.onclick = () => {
      haptic();
      const c = $("dossierCard");
      c.classList.toggle("collapsed");
      dh.setAttribute("aria-expanded", c.classList.contains("collapsed") ? "false" : "true");
    };
    $("tmClose").onclick = closeTest;
    const mib = $("moodInfoBtn");
    if (mib) mib.onclick = (e) => { e.stopPropagation(); haptic(); const b = $("moodInfo"); b.innerHTML = mdLite(MOOD_EXPLAIN); b.hidden = !b.hidden; };
    const moodInfoEl = $("moodInfo");
    if (moodInfoEl) moodInfoEl.onclick = (e) => e.stopPropagation();  // клик внутри попапа не закрывает
    document.addEventListener("click", () => {
      document.querySelectorAll(".diary-menu").forEach((m) => { m.hidden = true; });
      const mi = $("moodInfo"); if (mi) mi.hidden = true;
    });
    setupThemes();
    setupInstallPrompt();
    loadExtraTests();
  }
  setupSwipe();
  switchView("chat");
}

const VIEWS = ["chat", "diary", "profile"];   // порядок = порядок вкладок в навигации
let curView = "chat";
const viewEl = (v) => $(v === "chat" ? "chatView" : v === "diary" ? "diaryView" : "profileView");

function switchView(view, animate) {
  const dir = VIEWS.indexOf(view) - VIEWS.indexOf(curView); // >0 — вправо, <0 — влево
  document.querySelectorAll(".tab-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $("chatView").hidden = view !== "chat";
  $("profileView").hidden = view !== "profile";
  $("diaryView").hidden = view !== "diary";
  if (animate && dir !== 0) {
    const el = viewEl(view);
    el.classList.remove("view-slide-right", "view-slide-left");
    void el.offsetWidth;                       // рестарт анимации
    el.classList.add(dir > 0 ? "view-slide-right" : "view-slide-left");
    setTimeout(() => el.classList.remove("view-slide-right", "view-slide-left"), 300);
  }
  curView = view;
  if (view === "profile") loadProfile();
  if (view === "chat") hydrateChat();
  if (view === "diary") loadDiary();
}

/* палец-фолоу свайп: страница едет за пальцем, соседняя въезжает сбоку.
   оверлей-слой ставится ТОЛЬКО на время жеста — вне свайпа вёрстка не меняется. */
function setupSwipe() {
  const app = $("app");
  let sx = 0, sy = 0, locked = null, vw = 0, from = null, to = null, sign = 0, dragging = false;

  const reHide = () => {
    $("chatView").hidden = curView !== "chat";
    $("diaryView").hidden = curView !== "diary";
    $("profileView").hidden = curView !== "profile";
  };

  app.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1) { locked = "v"; return; }
    if (e.target.closest("input, textarea, .mood-chart, .bar-chart, .trend-wrap, .diary-menu, .test-modal, .test-sheet, .pf-box")) { locked = "v"; return; }
    sx = e.touches[0].clientX; sy = e.touches[0].clientY; vw = window.innerWidth;
    locked = null; dragging = false;
  }, { passive: true });

  app.addEventListener("touchmove", (e) => {
    if (locked === "v") return;
    const dx = e.touches[0].clientX - sx, dy = e.touches[0].clientY - sy;
    if (!locked) {
      if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
      if (Math.abs(dx) <= Math.abs(dy)) { locked = "v"; return; }   // вертикаль → нативный скролл
      const i = VIEWS.indexOf(curView), ti = dx < 0 ? i + 1 : i - 1;
      if (ti < 0 || ti >= VIEWS.length) { locked = "v"; return; }    // нет соседа
      locked = "h"; dragging = true; sign = dx < 0 ? 1 : -1;
      from = viewEl(curView); to = viewEl(VIEWS[ti]);
      to.hidden = false;
      from.classList.add("swipe-layer"); to.classList.add("swipe-layer");
      to.style.transform = `translateX(${sign * vw}px)`;
    }
    if (locked === "h") {
      e.preventDefault();
      let d = Math.max(-vw, Math.min(vw, e.touches[0].clientX - sx));
      if ((sign > 0 && d > 0) || (sign < 0 && d < 0)) d = 0;        // не тянуть в пустую сторону
      from.style.transform = `translateX(${d}px)`;
      to.style.transform = `translateX(${sign * vw + d}px)`;
    }
  }, { passive: false });

  app.addEventListener("touchend", (e) => {
    if (locked !== "h" || !dragging) { locked = null; return; }
    const d = e.changedTouches[0].clientX - sx;
    const commit = Math.abs(d) > vw * 0.28;
    const fEl = from, tEl = to, s = sign;
    const target = commit ? VIEWS[VIEWS.indexOf(curView) + (s > 0 ? 1 : -1)] : null;
    fEl.classList.add("animate"); tEl.classList.add("animate");
    fEl.style.transform = `translateX(${commit ? -s * vw : 0}px)`;
    tEl.style.transform = `translateX(${commit ? 0 : s * vw}px)`;
    if (commit) haptic();
    setTimeout(() => {
      fEl.classList.remove("swipe-layer", "animate"); tEl.classList.remove("swipe-layer", "animate");
      fEl.style.transform = ""; tEl.style.transform = "";
      if (commit && target) switchView(target, false);
      reHide();
    }, 270);
    locked = null; dragging = false; from = to = null;
  }, { passive: true });
}

/* история чата живёт в БД (одна на все устройства). локалка — лишь мгновенный кэш.
   рисуем кэш сразу, потом подтягиваем канон с сервера и сверяем. */
async function hydrateChat() {
  if (streaming) return;            // не трогаем во время стрима
  chatRender();                     // мгновенно из кэша
  let r = null;
  try { r = await api("/api/v2/messages"); } catch (_) {}
  if (streaming) return;
  if (r && Array.isArray(r.messages)) {
    const h = r.messages.map((m) => ({ role: m.role === "user" ? "user" : "agent", text: m.content }));
    saveChat(h);
    chatRender();
  }
  if (!loadChat().length) maybeOpener();
}

/* ── chat ── */
const CHAT_KEY = () => "mood_chat_" + (window.__me?.id || "x");
function loadChat() { try { return JSON.parse(localStorage.getItem(CHAT_KEY()) || "[]"); } catch (_) { return []; } }
function saveChat(a) { try { localStorage.setItem(CHAT_KEY(), JSON.stringify(a.slice(-100))); } catch (_) {} }

function chatRender() {
  const box = $("chatMessages");
  const h = loadChat();
  box.innerHTML = "";
  if (!h.length) {
    const e = document.createElement("div");
    e.className = "chat-empty";
    e.textContent = "напиши что внутри — разберём вместе";
    box.appendChild(e);
    return;
  }
  for (const m of h) {
    const el = document.createElement("div");
    el.className = "msg " + (m.role === "user" ? "user" : "agent");
    el.innerHTML = mdLite(m.text);
    box.appendChild(el);
  }
  box.scrollTop = box.scrollHeight;
}

/* проактивное приветствие: психолог сам начинает разговор (раз в день) */
let openerTried = false;
async function maybeOpener() {
  if (openerTried || streaming) return;
  openerTried = true;
  const key = "mood_opener_" + (window.__me?.id || "x");
  const today = new Date().toISOString().slice(0, 10);
  if (localStorage.getItem(key) === today) return;
  try {
    const r = await api("/api/v2/opener");
    const text = (r.text || "").trim();
    if (!text) return;
    if (loadChat().length) return; // юзер уже написал, пока грузилось
    localStorage.setItem(key, today);
    const h = [{ role: "agent", text }];
    saveChat(h);
    chatRender();
  } catch (_) {}
}

function setupChat() {
  const input = $("chatInput"), send = $("chatSend");
  const upd = () => { send.disabled = !input.value.trim(); input.style.height = "auto"; input.style.height = Math.min(120, input.scrollHeight) + "px"; };
  input.addEventListener("input", upd);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!send.disabled) sendMessage(); } });
  send.addEventListener("click", sendMessage);
  setupVoice(input, upd);
  const db = $("chatDiaryBtn");
  if (db) db.onclick = toggleDiaryMode;
}

/* ── режим записи в дневник прямо из чата ── */
let diaryMode = false;
function toggleDiaryMode() {
  diaryMode = !diaryMode;
  haptic("medium");
  const btn = $("chatDiaryBtn"), bar = $("chatInputBar"), hint = $("diaryHint"), input = $("chatInput");
  btn.classList.toggle("on", diaryMode);
  bar.classList.toggle("diary-mode", diaryMode);
  hint.hidden = !diaryMode;
  input.placeholder = diaryMode ? "пиши запись в дневник…" : "напиши что внутри…";
  input.focus();
}
async function saveDiaryEntry(text) {
  const input = $("chatInput"), send = $("chatSend");
  send.disabled = true; input.placeholder = "сохраняю…";
  try {
    const r = await api("/api/diary", { method: "POST", body: { text } });
    input.value = ""; input.style.height = "auto";
    hapticOk();
    toggleDiaryMode();
    if (r.entries) { saveDiaryCache(r.entries); renderDiary(r.entries); }
    setTimeout(refreshDiaryQuietly, 6000);
    setTimeout(refreshDiaryQuietly, 14000);
    switchView("diary");
  } catch (e) {
    input.placeholder = "ошибка сохранения";
    setTimeout(() => { input.placeholder = "пиши запись в дневник…"; }, 2500);
  } finally { send.disabled = !input.value.trim(); }
}

/* ── вкладка дневника ── */
const DIARY_KEY = () => "mood_diary_" + (window.__me?.id || "x");
function loadDiaryCache() { try { return JSON.parse(localStorage.getItem(DIARY_KEY()) || "[]"); } catch (_) { return []; } }
function saveDiaryCache(a) { try { localStorage.setItem(DIARY_KEY(), JSON.stringify((a || []).slice(0, 100))); } catch (_) {} }

async function loadDiary() {
  renderDiary(loadDiaryCache());                 // кэш мгновенно
  try { lastStats = await api("/api/stats"); } catch (_) {}
  renderPulse(lastStats);
  try {
    const r = await api("/api/diary");
    if (r.entries) { saveDiaryCache(r.entries); renderDiary(r.entries); }
  } catch (_) {}
}
async function refreshDiaryQuietly() {           // незаметно подтягиваем отклик/чистку из фона
  if ($("diaryView").hidden) return;
  try {
    const r = await api("/api/diary");
    if (r.entries) { saveDiaryCache(r.entries); renderDiary(r.entries); }
  } catch (_) {}
}
async function saveDiaryFromTab() {
  const input = $("diaryInput"), btn = $("diarySave");
  const text = input.value.trim();
  if (!text) return;
  btn.disabled = true; btn.textContent = "сохраняю…";
  try {
    const r = await api("/api/diary", { method: "POST", body: { text } });
    input.value = "";
    $("diarySaved").hidden = false;
    hapticOk();
    setTimeout(() => { $("diarySaved").hidden = true; }, 2200);
    if (r.entries) { saveDiaryCache(r.entries); renderDiary(r.entries); }
    setTimeout(refreshDiaryQuietly, 6000);       // отклик психолога приходит в фоне
    setTimeout(refreshDiaryQuietly, 14000);
  } catch (e) {
    btn.textContent = "ошибка — ещё раз";
    setTimeout(() => { btn.textContent = "сохранить запись"; }, 2200);
    return;
  } finally {
    btn.disabled = false; btn.textContent = "сохранить запись";
  }
}

/* символ настроения дня: mood_history (день → балл → значок пульса) */
function moodSymbolForTs(ts) {
  const hist = (lastStats && lastStats.mood_history) || [];
  if (!hist.length) return "";
  const day = Math.floor((ts || 0) / 86400);
  const row = hist.find((h) => h.day === day);
  if (!row) return "";
  const idx = PULSE_SCORES.indexOf(row.score);
  return idx >= 0 ? PULSE[idx].ic : "";   // имя иконки-лица
}

let diaryEditId = null;
function renderDiary(entries) {
  const box = $("diaryList");
  if (!box) return;
  box.innerHTML = "";
  if (!entries.length) {
    box.innerHTML = '<div class="diary-empty">пока пусто — напиши первую запись выше</div>';
    return;
  }
  entries.forEach((e) => {
    const el = document.createElement("div");
    el.className = "diary-entry";
    const d = new Date((e.ts || 0) * 1000);
    const date = isNaN(d) ? "" : d.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
    const sym = moodSymbolForTs(e.ts);
    const editing = diaryEditId === e.id;
    el.innerHTML = `
      <div class="diary-head">
        <div class="diary-date">${sym ? `<span class="diary-mood">${ico(sym)}</span>` : ""}${date}</div>
        <button class="diary-menu-btn" title="ещё">⋮</button>
        <div class="diary-menu" hidden>
          <button data-act="edit">редактировать</button>
          <button data-act="del">удалить</button>
        </div>
      </div>
      ${editing
        ? `<textarea class="field area diary-edit"></textarea>
           <div class="diary-edit-actions">
             <button class="btn-ghost" data-act="cancel">отмена</button>
             <button class="btn-primary" data-act="save">сохранить</button>
           </div>`
        : `<div class="diary-text"></div>${e.feedback
            ? `<div class="diary-feedback"><span class="diary-fb-label">психолог</span><span class="diary-fb-text"></span></div>`
            : ""}`}`;
    if (editing) {
      el.querySelector(".diary-edit").value = e.text;
    } else {
      el.querySelector(".diary-text").textContent = e.text;
      if (e.feedback) el.querySelector(".diary-fb-text").textContent = e.feedback;
    }
    const menuBtn = el.querySelector(".diary-menu-btn");
    const menu = el.querySelector(".diary-menu");
    menuBtn.onclick = (ev) => {
      ev.stopPropagation();
      document.querySelectorAll(".diary-menu").forEach((m) => { if (m !== menu) m.hidden = true; });
      menu.hidden = !menu.hidden;
      haptic();
    };
    menu.querySelector('[data-act="edit"]').onclick = () => { diaryEditId = e.id; renderDiary(entries); };
    menu.querySelector('[data-act="del"]').onclick = () => delDiary(e.id);
    if (editing) {
      el.querySelector('[data-act="cancel"]').onclick = () => { diaryEditId = null; renderDiary(entries); };
      el.querySelector('[data-act="save"]').onclick = async () => {
        const val = el.querySelector(".diary-edit").value.trim();
        if (!val) return;
        diaryEditId = null;
        try {
          const r = await api("/api/diary/update", { method: "POST", body: { id: e.id, text: val } });
          if (r.entries) { saveDiaryCache(r.entries); renderDiary(r.entries); }
          hapticOk();
        } catch (_) { renderDiary(entries); }
      };
    }
    box.appendChild(el);
  });
}
async function delDiary(id) {
  haptic("medium");
  try {
    const r = await api("/api/diary/delete", { method: "POST", body: { id } });
    if (r.entries) saveDiaryCache(r.entries);
    renderDiary(r.entries || []);
  } catch (_) {}
}

/* ── темы: тёмная / светлая, переключатель всегда сверху ── */
const THEME_KEY = "mood_theme";
let curTheme = "dark";
function applyTheme(name) {
  curTheme = name === "light" ? "light" : "dark";
  document.documentElement.classList.toggle("dark", curTheme === "dark");
  try { localStorage.setItem(THEME_KEY, curTheme); } catch (_) {}
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", curTheme === "dark" ? "#2d2621" : "#f5f1e6");
  const tog = $("themeToggle");
  if (tog) {
    // показываем иконку цели переключения
    tog.innerHTML = ico(curTheme === "dark" ? "sun" : "moon");
    tog.title = curTheme === "dark" ? "светлая тема" : "тёмная тема";
  }
}
/* ── предложение «добавить на домашний экран» (PWA) ── */
function setupInstallPrompt() {
  const banner = $("installBanner");
  if (!banner) return;
  const KEY = "mood_install_dismissed";
  const standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const inTG = !!(tg && tg.initData);
  let dismissed = false; try { dismissed = localStorage.getItem(KEY) === "1"; } catch (_) {}
  if (standalone || dismissed || inTG) return;          // уже апка / отклонил / внутри Telegram
  const close = () => { banner.hidden = true; try { localStorage.setItem(KEY, "1"); } catch (_) {} };
  $("installClose").onclick = close;
  const reveal = () => { banner.hidden = false; };

  if (/iphone|ipad|ipod/i.test(navigator.userAgent)) {  // iOS: программного prompt нет — инструкция
    $("installText").textContent = "добавь MOOD на экран «Домой»: «Поделиться» → «На экран Домой»";
    $("installBtn").hidden = true;
    setTimeout(reveal, 1500);
    return;
  }
  $("installBtn").onclick = async () => {
    if (!deferredInstall) { close(); return; }
    deferredInstall.prompt();
    try { await deferredInstall.userChoice; } catch (_) {}
    deferredInstall = null; close();
  };
  if (deferredInstall) reveal();                          // событие уже прилетело
  else window.addEventListener("beforeinstallprompt", reveal);
}

function setupThemes() {
  const saved = (() => { try { return localStorage.getItem(THEME_KEY); } catch (_) { return null; } })() || "dark";
  applyTheme(saved);
  const tog = $("themeToggle");
  if (tog) tog.onclick = () => { haptic("medium"); applyTheme(curTheme === "dark" ? "light" : "dark"); };
}

/* ── нейросетевой фон на экране входа (particle network) ── */
let neuralRAF = 0, neuralResize = null;
function stopNeural() {
  if (neuralRAF) { cancelAnimationFrame(neuralRAF); neuralRAF = 0; }
  if (neuralResize) { window.removeEventListener("resize", neuralResize); neuralResize = null; }
}
function initNeural() {
  stopNeural();
  const cv = $("authCanvas");
  if (!cv) return;
  const ctx = cv.getContext("2d");
  let W = 0, H = 0, dpr = Math.min(2, window.devicePixelRatio || 1);
  const accent = (getComputedStyle(document.documentElement).getPropertyValue("--accent-rgb") || "166,124,82").trim();
  let pts = [];
  const resize = () => {
    W = cv.clientWidth || window.innerWidth;
    H = cv.clientHeight || window.innerHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const target = Math.min(64, Math.round((W * H) / 14000));
    pts = [];
    for (let i = 0; i < target; i++) {
      pts.push({ x: Math.random() * W, y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.35, vy: (Math.random() - 0.5) * 0.35 });
    }
  };
  neuralResize = resize;
  window.addEventListener("resize", resize);
  resize();
  const LINK = 130;
  const frame = () => {
    ctx.clearRect(0, 0, W, H);
    for (const p of pts) {
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0 || p.x > W) p.vx *= -1;
      if (p.y < 0 || p.y > H) p.vy *= -1;
    }
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y;
        const d = Math.hypot(dx, dy);
        if (d < LINK) {
          ctx.strokeStyle = `rgba(${accent},${(1 - d / LINK) * 0.22})`;
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(pts[i].x, pts[i].y); ctx.lineTo(pts[j].x, pts[j].y); ctx.stroke();
        }
      }
    }
    ctx.fillStyle = `rgba(${accent},0.55)`;
    for (const p of pts) { ctx.beginPath(); ctx.arc(p.x, p.y, 1.6, 0, 6.2832); ctx.fill(); }
    neuralRAF = requestAnimationFrame(frame);
  };
  frame();
}

/* ── голосовой ввод: запись → распознавание (Groq Whisper на сервере) ── */
let mediaRec = null, recChunks = [], recStream = null, recording = false;
function setupVoice(input, upd) {
  const mic = $("chatMic");
  if (!mic) return;
  const hasRec = typeof MediaRecorder !== "undefined" && navigator.mediaDevices && navigator.mediaDevices.getUserMedia;
  if (!hasRec) return;
  mic.hidden = false;
  mic.onclick = () => { recording ? stopVoice() : startVoice(input, upd); };
}
function pickMime() {
  const cands = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
  for (const m of cands) { try { if (MediaRecorder.isTypeSupported(m)) return m; } catch (_) {} }
  return "";
}
async function startVoice(input, upd) {
  const mic = $("chatMic");
  try {
    recStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (_) {
    input.placeholder = "нет доступа к микрофону";
    setTimeout(() => { input.placeholder = "напиши что внутри…"; }, 2500);
    return;
  }
  const mime = pickMime();
  recChunks = [];
  try { mediaRec = new MediaRecorder(recStream, mime ? { mimeType: mime } : undefined); }
  catch (_) { mediaRec = new MediaRecorder(recStream); }
  mediaRec.ondataavailable = (e) => { if (e.data && e.data.size) recChunks.push(e.data); };
  mediaRec.onstop = () => sendVoice(input, upd);
  mediaRec.start();
  recording = true;
  mic.classList.add("rec"); mic.innerHTML = ico("square"); haptic("medium");
}
function stopVoice() {
  recording = false;
  try { mediaRec && mediaRec.state !== "inactive" && mediaRec.stop(); } catch (_) {}
  try { recStream && recStream.getTracks().forEach((t) => t.stop()); } catch (_) {}
  const mic = $("chatMic"); mic.classList.remove("rec"); mic.innerHTML = ico("mic");
}
async function sendVoice(input, upd) {
  const mic = $("chatMic");
  const type = (recChunks[0] && recChunks[0].type) || "audio/webm";
  const blob = new Blob(recChunks, { type });
  if (!blob.size) return;
  mic.classList.add("busy"); mic.innerHTML = ico("mic");
  const prevPh = input.placeholder; input.placeholder = "распознаю…";
  try {
    const res = await fetch("/api/v2/transcribe", {
      method: "POST",
      headers: { "Content-Type": type, "Authorization": "Bearer " + getToken() },
      body: blob, cache: "no-store",
    });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(j.error || ("HTTP " + res.status));
    const text = (j.text || "").trim();
    if (text) { input.value = input.value ? input.value + " " + text : text; upd(); input.focus(); hapticOk(); }
    else { input.placeholder = "не расслышал — попробуй ещё"; setTimeout(() => { input.placeholder = prevPh; }, 2500); }
  } catch (e) {
    input.placeholder = "ошибка распознавания";
    setTimeout(() => { input.placeholder = prevPh; }, 2800);
  } finally {
    mic.classList.remove("busy"); mic.innerHTML = ico("mic");
    if (input.placeholder === "распознаю…") input.placeholder = prevPh;
  }
}

let streaming = false;
async function sendMessage() {
  if (streaming) return;
  const input = $("chatInput");
  const text = input.value.trim();
  if (!text) return;
  if (diaryMode) { saveDiaryEntry(text); return; }
  streaming = true; haptic("medium");
  const h = loadChat();
  h.push({ role: "user", text });
  h.push({ role: "agent", text: "" });
  saveChat(h);
  chatRender();
  const box = $("chatMessages");
  const agentEl = box.lastElementChild;
  agentEl.classList.add("streaming");
  input.value = ""; input.style.height = "auto"; $("chatSend").disabled = true;

  let acc = "";            // полный полученный с сервера текст
  let shown = 0;           // сколько символов уже показано (посимвольная доводка)
  let typing = false;
  const render = (s) => { agentEl.innerHTML = mdLite(s); };  // mdLite экранирует html (см. mdLite)
  // автоскролл только если юзер у низа — иначе не мешаем листать вверх
  const nearBottom = () => box.scrollHeight - box.scrollTop - box.clientHeight < 90;
  // посимвольный вывод: показ догоняет буфер плавно, не зависит от рывков сети
  const typer = () => {
    if (shown < acc.length) {
      const stick = nearBottom();
      shown += Math.max(1, Math.ceil((acc.length - shown) / 18));
      render(acc.slice(0, shown));
      if (stick) box.scrollTop = box.scrollHeight;
      requestAnimationFrame(typer);
    } else { typing = false; }
  };
  const pump = () => { if (!typing) { typing = true; requestAnimationFrame(typer); } };
  const done = () => {
    const stick = nearBottom();
    shown = acc.length; render(acc); if (stick) box.scrollTop = box.scrollHeight;  // дописать остаток
    agentEl.classList.remove("streaming");
    streaming = false; hapticOk();
    const f = loadChat();
    f[f.length - 1].text = acc || "(пусто)";
    saveChat(f);
  };
  const runStream = async () => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 120000);
    try {
      const res = await fetch("/api/v2/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + getToken() },
        body: JSON.stringify({ q: text }),
        cache: "no-store",
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) {
        let msg = "HTTP " + res.status;
        try { const j = await res.json(); msg = j.error || msg; } catch (_) {}
        throw new Error(msg);
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      while (true) {
        const { value, done: rdone } = await reader.read();
        if (rdone) break;
        acc += dec.decode(value, { stream: true });
        pump();
      }
    } finally { clearTimeout(timer); }
  };
  try {
    await runStream();
    done();
  } catch (e) {
    // Render free спит, просыпается ~50с — первая попытка часто падает (Load failed/abort).
    if (!acc) {
      agentEl.textContent = "просыпаюсь, секунду…";
      try { await fetch("/api/health", { cache: "no-store" }); } catch (_) {}
      await sleep(1800);
      try { acc = ""; shown = 0; await runStream(); done(); return; }
      catch (_) { acc = "связь сорвалась — попробуй ещё раз"; }
    }
    done();
  }
}

/* ── profile / MOOD ── */
let lastStats = null;

const PROF_KEY = () => "mood_portrait_" + (window.__me?.id || "x");
function setPortrait(compiled) {
  const c = (compiled || "").trim();
  $("profCompiled").innerHTML = c ? mdLite(c) : "портрет ещё не собран — нажми кнопку ниже";
  window.__portraitText = c;
  // кнопка всегда доступна: «собрать» если пусто, «пересобрать» если есть
  $("profCompile").textContent = c ? "пересобрать портрет" : "собрать портрет";
  $("profCompile").hidden = false;
  $("profExport").hidden = !c;
  // лайк/фидбек на портрет — только когда портрет есть
  const pf = $("pfLike");
  if (pf) {
    pf.hidden = !c;
    if (!c) { $("pfBox").hidden = true; $("pfDone").hidden = true; }
  }
}
async function loadProfile() {
  $("profName").textContent = window.__me?.name || "—";
  $("profEmail").textContent = window.__me?.email || "—";
  let cached = "";
  try { cached = localStorage.getItem(PROF_KEY()) || ""; } catch (_) {}
  setPortrait(cached || "");                       // мгновенно из кэша
  if (!cached) $("profCompiled").textContent = "загружаю…";
  try {
    const me = await api("/api/me");
    const compiled = me.compiled || "";
    try { localStorage.setItem(PROF_KEY(), compiled); } catch (_) {}
    setPortrait(compiled);
  } catch (_) {
    if (!cached) $("profCompiled").textContent = "—";
  }
  loadStats();
  loadDynMood();
  loadDocuments();
}

/* динамичный MOOD — настрой за 10 дней по дневнику */
const DYN_KEY = () => "mood_dyn_" + (window.__me?.id || "x");
function renderDynMood(d, tries = 0) {
  const num = $("dynMoodNum"), bar = $("dynMoodBar"), note = $("dynMoodNote"), foot = $("dynMoodFoot"), desc = $("dynMoodDesc");
  if (!num) return;
  if (!d || d.score == null) {
    num.textContent = "—";
    bar.style.width = "0%";
    note.textContent = (d && d.note) || "веди дневник — настрой посчитается за 10 дней";
    if (desc) desc.textContent = "";
    foot.textContent = "";
    if (d && d.pending && tries < 5) {
      setTimeout(() => { if (!$("profileView").hidden) loadDynMood(tries + 1); }, 12000);
    }
    return;
  }
  if (desc) desc.textContent = d.desc || "";
  animateNum(num, d.score);
  bar.style.width = d.score + "%";
  bar.style.background = d.score >= 65 ? "#30d158" : d.score >= 45 ? "#ffd60a" : "#ff9f0a";
  note.textContent = d.note || "";
  const left = d.days_left || 0;
  foot.textContent = `по ${d.n || 0} ${plural(d.n || 0, "записи", "записям", "записям")} · обновится через ${left} ${plural(left, "день", "дня", "дней")}`;
}
async function loadDynMood(tries = 0) {
  if (!$("dynMoodCard")) return;
  if (tries === 0) {                                  // мгновенно из кэша
    try { const c = JSON.parse(localStorage.getItem(DYN_KEY()) || "null"); if (c) renderDynMood(c); } catch (_) {}
  }
  let d;
  try { d = await api("/api/v2/dynamic-mood", { timeout: 15000 }); } catch (_) { d = null; }
  if (d && d.score != null) { try { localStorage.setItem(DYN_KEY(), JSON.stringify(d)); } catch (_) {} }
  renderDynMood(d, tries);
}

const STATS_KEY = () => "mood_stats_" + (window.__me?.id || "x");
function renderAllStats(s) {
  renderMood(s);
  renderTests(s);
  renderAnalytics(s);
  gatePortrait(s);
  if ($("weeklyCard")) $("weeklyCard").hidden = !(s && s.sessions >= 3);
}

/* портрет под замком, пока не пройдены все тесты */
function gatePortrait(s) {
  if (!s || s.all_tests_done) {
    if (s) setPortrait(window.__portraitText || localStorage.getItem(PROF_KEY()) || "");
    return;
  }
  const left = (s.tests_total || 0) - (s.tests_passed || 0);
  $("profCompiled").textContent = `🔒 портрет под замком. пройди все тесты ниже (первичный + доп) — осталось ${left} из ${s.tests_total}. на их основе психолог соберёт глубокий разбор тебя.`;
  $("profCompile").hidden = true;
  $("profExport").hidden = true;
}
async function loadStats() {
  let cached = null;
  try { cached = JSON.parse(localStorage.getItem(STATS_KEY()) || "null"); } catch (_) {}
  if (cached) { lastStats = cached; renderAllStats(cached); }   // мгновенно из кэша
  try {
    lastStats = await api("/api/stats");
    try { localStorage.setItem(STATS_KEY(), JSON.stringify(lastStats)); } catch (_) {}
  } catch (_) { if (!cached) lastStats = null; }
  renderAllStats(lastStats);
}

/* ── пульс настроения ── */
const PULSE = [
  { ic: "face-1", l: "тяжело" },
  { ic: "face-2", l: "так себе" },
  { ic: "face-3", l: "норм" },
  { ic: "face-4", l: "хорошо" },
  { ic: "face-5", l: "отлично" },
];
const PULSE_SCORES = [12, 32, 55, 78, 95]; // зеркало server.py
function renderPulse(s) {
  const row = $("pulseRow"), note = $("pulseNote");
  if (!row) return;
  row.innerHTML = "";
  // mood_today хранится в MOOD-шкале → маппим обратно в индекс 1..5
  const raw = s && s.mood_today;
  const today = raw != null ? PULSE_SCORES.indexOf(raw) + 1 : 0;
  PULSE.forEach((p, i) => {
    const n = i + 1;
    const b = document.createElement("button");
    b.className = "pulse-btn" + (today === n ? " sel" : "");
    b.innerHTML = `<span class="pulse-e">${ico(p.ic)}</span><span class="pulse-l">${p.l}</span>`;
    b.onclick = () => doPulse(n);
    row.appendChild(b);
  });
  if (note) note.textContent = today ? "отмечено сегодня — можно поменять" : "отметь настроение — это рисует твою динамику";
}
async function doPulse(n) {
  haptic("medium");
  document.querySelectorAll("#pulseRow .pulse-btn").forEach((b, i) => b.classList.toggle("sel", i + 1 === n));
  try {
    const r = await api("/api/mood/checkin", { method: "POST", body: { score: n } });
    if (r.stats) { lastStats = r.stats; renderPulse(r.stats); renderAnalytics(r.stats); }
    hapticOk();
  } catch (e) { console.warn("pulse:", e); }
}

const MOOD_EXPLAIN = `**как считается оценка MOOD**

устойчивый индекс 0–100. подстраивается под тебя и складывается из двух частей:

**база** — ответы на тесты. валидированные шкалы мировой психологии: эмоц. устойчивость (нейротизм, Big Five), тревога привязанности, самоценность, эмоц. регуляция, восприятие стресса и контроля, переносимость трудностей.

**актуальное состояние** — то, что психолог видит в твоём **дневнике** и **ваших разговорах** за последние дни.

обе части усредняются в одну оценку. чем больше тестов, записей и общения — тем точнее, и тем сильнее оценка адаптируется под тебя. выше — больше внутренней опоры. мало данных — оценка не показывается.`;
const MOOD_WORD = (m) => m >= 75 ? "ты в ресурсе" : m >= 55 ? "в целом устойчиво" : m >= 40 ? "качает, но держишься" : "тяжёлый период";
function renderMood(s) {
  const locked = $("moodLocked"), ready = $("moodReady");
  if (!s || s.mood == null) {
    locked.hidden = false; ready.hidden = true;
    const t = $("moodLocked").querySelector(".locked-t");
    if (s && !s.all_tests_done) {
      const left = (s.tests_total || 0) - (s.tests_passed || 0);
      if (t) t.textContent = "оценка MOOD под замком";
      $("moodProg").textContent = `пройди все тесты для анализа · осталось ${left} из ${s.tests_total}`;
    } else if (s) {
      if (t) t.textContent = "оценка MOOD";
      $("moodProg").textContent = "скоро — нужно чуть больше данных";
    }
    return;
  }
  locked.hidden = true; ready.hidden = false;
  const m = s.mood;
  const C = 2 * Math.PI * 52;
  const fill = $("mrFill");
  fill.style.strokeDasharray = C;
  fill.style.strokeDashoffset = C * (1 - m / 100);
  fill.style.stroke = m >= 65 ? "#30d158" : m >= 45 ? "#ffd60a" : "#ff9f0a";
  animateNum($("moodNum"), m);
  $("moodCap").textContent = MOOD_WORD(m);
  const hist = s.mood_history || [];
  const chart = $("moodChart");
  if (chart) {
    const spark = sparkline(hist);
    chart.innerHTML = spark
      ? `<div class="mood-chart-cap">динамика · ${hist.length} ${plural(hist.length, "отметка", "отметки", "отметок")}</div>${spark}`
      : chartLock(`динамика появится после ${Math.max(0, 2 - hist.length)} ${plural(Math.max(0, 2 - hist.length), "отметки", "отметок", "отметок")}`);
  }
  const bars = $("moodBars");
  if (bars) {
    bars.innerHTML = hist.length >= 3
      ? `<div class="mood-chart-cap">последние отметки</div>${barChart(hist)}`
      : chartLock(`график по дням — нужно ещё ${Math.max(0, 3 - hist.length)} ${plural(Math.max(0, 3 - hist.length), "отметка", "отметки", "отметок")}`);
  }
}

/* заглушка-замок вместо пустого графика */
function chartLock(text) {
  return `<div class="chart-lock">${ico("lock")}<span>${text}</span></div>`;
}

/* barChart: столбики по последним отметкам MOOD, цвет по уровню */
function barChart(hist) {
  const last = hist.slice(-14);
  const bars = last.map((h) => {
    const v = Math.max(0, Math.min(100, h.score || 0));
    const col = v >= 65 ? "#30d158" : v >= 45 ? "#ffd60a" : "#ff9f0a";
    return `<div class="bar" style="height:${Math.max(8, v)}%;background:${col}"></div>`;
  }).join("");
  return `<div class="bar-chart">${bars}</div>`;
}

/* sparkline: SVG-полилиния по истории MOOD */
function sparkline(hist) {
  if (!hist || hist.length < 2) return "";
  const vals = hist.map((h) => h.score);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const W = 280, H = 56, pad = 4;
  const n = vals.length;
  const pts = vals.map((v, i) => {
    const x = pad + (i / (n - 1)) * (W - 2 * pad);
    const y = H - pad - ((v - min) / span) * (H - 2 * pad);
    return [x.toFixed(1), y.toFixed(1)];
  });
  const line = pts.map((p) => p.join(",")).join(" ");
  const area = `${pad},${H - pad} ${line} ${W - pad},${H - pad}`;
  const last = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <polyline class="spark-area" points="${area}"/>
    <polyline class="spark-line" points="${line}"/>
    <circle class="spark-dot" cx="${last[0]}" cy="${last[1]}" r="3.5"/>
  </svg>`;
}

function renderTests(s) {
  const box = $("testsList");
  box.innerHTML = "";
  // первичный тест: если пропущен — даём пройти отсюда в любой момент
  const obDone = !!(s && s.onboard_test_done);
  const ob = document.createElement("button");
  ob.className = "test-item" + (obDone ? " done" : "");
  ob.innerHTML = `<span class="test-emoji">${obDone ? "◆" : "◇"}</span><span class="test-title">первичный тест о тебе</span><span class="test-state">${obDone ? "пройден" : "пройти →"}</span>`;
  ob.onclick = () => { haptic(); startOnboardingAgain(); };
  box.appendChild(ob);
  if (!extraTests.length) return;
  extraTests.forEach((t) => {
    const done = s && s.tests && s.tests[t.id];
    const el = document.createElement("button");
    el.className = "test-item" + (done ? " done" : "");
    el.innerHTML = `<span class="test-emoji">${done ? "◆" : "◇"}</span><span class="test-title">${t.title}</span><span class="test-state">${done ? "пройден" : "пройти →"}</span>`;
    el.onclick = () => { haptic(); openTest(t); };
    box.appendChild(el);
  });
}

function renderAnalytics(s) {
  const box = $("analyticsBox");
  if (!s) { box.innerHTML = '<div class="card-note">—</div>'; return; }
  if (!s.analytics_unlocked) {
    box.innerHTML = `<div class="locked"><div class="locked-ico">${ico("lock")}</div>
      <div class="locked-t">графики и динамика</div>
      <div class="locked-s">откроется через ${Math.ceil(s.analytics_in_days)} ${plural(Math.ceil(s.analytics_in_days), "день", "дня", "дней")} терапии</div></div>`;
    return;
  }
  const stat = (k, v) => `<div class="stat-tile"><div class="stat-v">${v}</div><div class="stat-k">${k}</div></div>`;
  const streak = s.streak || 0;
  const spark = sparkline(s.mood_history);
  box.innerHTML = `<div class="stat-grid">
    ${stat("сеансов", s.sessions)}
    ${stat("сообщений", s.user_msgs)}
    ${stat("дней подряд", streak > 0 ? `<span class="stat-flame">${ico("flame")}</span> ` + streak : "—")}
    ${stat("MOOD", s.mood != null ? s.mood : "—")}
  </div>${spark ? `<div class="spark-wrap"><div class="spark-cap">динамика MOOD</div>${spark}</div>` : ""}`;
}

function plural(n, a, b, c) {
  n = Math.abs(n) % 100; const n1 = n % 10;
  if (n > 10 && n < 20) return c;
  if (n1 > 1 && n1 < 5) return b;
  if (n1 === 1) return a;
  return c;
}

async function compilePortrait() {
  const btn = $("profCompile");
  btn.disabled = true;
  $("profCompiling").hidden = false;
  try {
    const r = await api("/api/profile/compile", { method: "POST", body: {}, timeout: 90000 });
    if (r.compiled) {
      try { localStorage.setItem(PROF_KEY(), r.compiled); } catch (_) {}
      setPortrait(r.compiled);
    }
    hapticOk();
    loadStats();
  } catch (e) {
    $("profCompiled").textContent = "не удалось собрать: " + e.message;
  } finally {
    $("profCompiling").hidden = true;
    btn.disabled = false;
  }
}

/* ── экспорт портрета в картинку (canvas → share/download) ── */
function wrapText(ctx, text, maxW) {
  const lines = [];
  for (const para of (text || "").split("\n")) {
    if (!para.trim()) { lines.push(""); continue; }
    let line = "";
    for (const word of para.split(/\s+/)) {
      const test = line ? line + " " + word : word;
      if (ctx.measureText(test).width > maxW && line) { lines.push(line); line = word; }
      else line = test;
    }
    if (line) lines.push(line);
  }
  return lines;
}
async function exportPortrait() {
  const text = (window.__portraitText || "").replace(/\*\*/g, "");
  if (!text) return;
  haptic("medium");
  const W = 1080, pad = 90, fs = 34, lh = 50;
  const dpr = 2;
  const measure = document.createElement("canvas").getContext("2d");
  measure.font = `${fs}px Inter, sans-serif`;
  const lines = wrapText(measure, text, W - pad * 2);
  const H = Math.max(1080, pad * 2 + 200 + lines.length * lh);
  const cv = document.createElement("canvas");
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  // фон-градиент
  const g = ctx.createLinearGradient(0, 0, W, H);
  g.addColorStop(0, "#0a0a14"); g.addColorStop(1, "#15102e");
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  // акцентное свечение
  const glow = ctx.createRadialGradient(W * 0.8, 160, 0, W * 0.8, 160, 420);
  glow.addColorStop(0, "rgba(124,95,255,0.35)"); glow.addColorStop(1, "rgba(124,95,255,0)");
  ctx.fillStyle = glow; ctx.fillRect(0, 0, W, H);
  // лого / заголовок
  ctx.fillStyle = "#7c5fff"; ctx.font = "700 56px 'Space Grotesk', sans-serif";
  ctx.fillText("◆ MOOD", pad, pad + 50);
  ctx.fillStyle = "rgba(255,255,255,0.5)"; ctx.font = "400 28px Inter, sans-serif";
  ctx.fillText("твой психологический портрет", pad, pad + 95);
  // текст
  ctx.fillStyle = "rgba(255,255,255,0.92)"; ctx.font = `${fs}px Inter, sans-serif`;
  let y = pad + 200;
  for (const ln of lines) { ctx.fillText(ln, pad, y); y += lh; }
  // подвал
  ctx.fillStyle = "rgba(255,255,255,0.3)"; ctx.font = "400 24px Inter, sans-serif";
  ctx.fillText("mood — личный психолог в кармане", pad, H - pad + 20);

  const blob = await new Promise((r) => cv.toBlob(r, "image/png"));
  if (!blob) return;
  const file = new File([blob], "mood-portrait.png", { type: "image/png" });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try { await navigator.share({ files: [file], title: "Мой портрет MOOD" }); hapticOk(); return; } catch (_) {}
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = "mood-portrait.png"; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  hapticOk();
}

/* ── фидбек на портрет: агент учится писать точнее ── */
async function sendPortraitFeedback() {
  const btn = $("pfSend"), txt = $("pfText");
  const text = (txt.value || "").trim();
  btn.disabled = true; btn.textContent = "отправляю…";
  try {
    await api("/api/profile/feedback", { method: "POST", body: { liked: true, text } });
    txt.value = "";
    $("pfDone").hidden = false;
    hapticOk();
    setTimeout(() => { $("pfBox").hidden = true; $("pfDone").hidden = true; }, 2600);
  } catch (e) {
    $("pfDone").hidden = false; $("pfDone").textContent = "не удалось: " + e.message;
  } finally {
    btn.disabled = false; btn.textContent = "отправить психологу";
  }
}

/* ── итоги недели ── */
async function genWeekly() {
  const btn = $("weeklyBtn"), box = $("weeklyBox");
  btn.disabled = true; btn.textContent = "собираю…";
  try {
    const r = await api("/api/v2/weekly", { method: "POST", body: {}, timeout: 90000 });
    box.innerHTML = r.text ? mdLite(r.text) : "пока мало разговоров для итогов — возвращайся через пару сеансов";
    hapticOk();
  } catch (e) {
    box.textContent = "не удалось: " + e.message;
  } finally {
    btn.disabled = false; btn.textContent = "собрать итоги недели";
  }
}

/* ── tests ── */
let extraTests = [];
let tmTest = null, tmIndex = 0, tmAnswers = {};

async function loadExtraTests() {
  try { const r = await api("/api/tests", { auth: false }); extraTests = r.tests || []; }
  catch (_) { extraTests = []; }
}

function openTest(t) {
  tmTest = t; tmIndex = 0; tmAnswers = {};
  $("testModal").hidden = false;
  renderTestQ();
}
function closeTest() { $("testModal").hidden = true; tmTest = null; }

function renderTestQ() {
  const t = tmTest; if (!t) return;
  const q = t.questions[tmIndex];
  $("tmFill").style.width = (tmIndex / t.questions.length * 100) + "%";
  $("tmStep").textContent = `${t.emoji} ${t.title} · ${tmIndex + 1}/${t.questions.length}`;
  $("tmQuestion").textContent = q.q;
  const box = $("tmAnswer"); box.innerHTML = "";
  const wrap = document.createElement("div"); wrap.className = "scale-wrap";
  (t.labels || ["1","2","3","4","5"]).forEach((label, i) => {
    const b = document.createElement("button");
    b.className = "scale-btn" + (tmAnswers[q.id] === i + 1 ? " sel" : "");
    b.innerHTML = `<span class="scale-num">${i + 1}</span><span class="scale-lbl">${label}</span>`;
    b.onclick = () => { haptic(); tmAnswers[q.id] = i + 1; setTimeout(tmNext, 160); };
    wrap.appendChild(b);
  });
  box.appendChild(wrap);
}

async function tmNext() {
  if (tmIndex < tmTest.questions.length - 1) { tmIndex++; renderTestQ(); return; }
  const tid = tmTest.id;
  closeTest();
  hapticOk();
  try {
    const r = await api("/api/tests/submit", { method: "POST", body: { test_id: tid, answers: tmAnswers } });
    if (r.stats) { lastStats = r.stats; renderMood(r.stats); renderTests(r.stats); renderAnalytics(r.stats); }
  } catch (e) { console.warn("test submit:", e); }
}

/* ── documents (досье) ── */
async function loadDocuments() {
  try { const r = await api("/api/documents"); renderDocs(r.documents || [], r.total || 0); }
  catch (_) {}
}
function renderDocs(docs, total) {
  const box = $("fileList"); box.innerHTML = "";
  if (!docs.length) return;
  const kb = (n) => n > 1024 * 1024 ? (n / 1048576).toFixed(1) + " МБ" : Math.max(1, Math.round(n / 1024)) + " КБ";
  docs.forEach((d) => {
    const el = document.createElement("div"); el.className = "file-row";
    el.innerHTML = `<span class="file-name">${ico("file-text")} ${escapeHtml(d.name)}</span><span class="file-size">${kb(d.size)}</span><button class="file-del" data-id="${d.id}">${ico("x")}</button>`;
    el.querySelector(".file-del").onclick = () => deleteDoc(d.id);
    box.appendChild(el);
  });
  const t = document.createElement("div"); t.className = "card-note"; t.style.marginTop = "8px";
  t.textContent = `всего: ${kb(total)} / 5 МБ`;
  box.appendChild(t);
}
function escapeHtml(s) { return (s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

async function uploadFiles(files) {
  for (const f of files) {
    if (f.size > 1024 * 1024) { alert(`${f.name}: больше 1 МБ, пропускаю`); continue; }
    let text = "";
    try { text = await f.text(); } catch (_) { continue; }
    if (!text.trim()) continue;
    try {
      const r = await api("/api/documents", { method: "POST", body: { name: f.name, content: text } });
      renderDocs(r.documents || [], r.total || 0);
      hapticOk();
    } catch (e) { alert("ошибка: " + e.message); break; }
  }
  $("fileInput").value = "";
}

async function deleteDoc(id) {
  try { const r = await api("/api/documents/delete", { method: "POST", body: { id } }); renderDocs(r.documents || [], r.total || 0); haptic(); }
  catch (e) { alert("ошибка: " + e.message); }
}

async function saveProfileInfo() {
  const info = $("profInfo").value.trim();
  if (!info) return;
  $("profSave").disabled = true;
  try {
    await api("/api/profile/info", { method: "POST", body: { raw_info: info } });
    $("profSaved").hidden = false;
    hapticOk();
    setTimeout(() => { $("profSaved").hidden = true; }, 2500);
  } catch (e) {
    alert("ошибка: " + e.message);
  } finally {
    $("profSave").disabled = false;
  }
}

/* ───────── кастомный курсор (desktop, fine pointer) ───────── */
function initCursor() {
  if (!window.matchMedia || !window.matchMedia("(pointer: fine)").matches) return;
  const dot = $("cursorDot"), ring = $("cursorRing");
  if (!dot || !ring) return;
  document.body.classList.add("has-cursor");
  let rx = 0, ry = 0, dx = 0, dy = 0;
  document.addEventListener("mousemove", (e) => {
    dx = e.clientX; dy = e.clientY;
    dot.style.transform = `translate(${dx}px, ${dy}px)`;
    const t = e.target.closest("button, a, .test-item, .scale-btn, .tab-item, .file-del, textarea, input");
    ring.classList.toggle("hot", !!t);
  });
  const loop = () => { rx += (dx - rx) * 0.18; ry += (dy - ry) * 0.18; ring.style.transform = `translate(${rx}px, ${ry}px)`; requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
  document.addEventListener("mousedown", () => ring.classList.add("down"));
  document.addEventListener("mouseup", () => ring.classList.remove("down"));
}

initCursor();
boot().catch((e) => {
  try { initAuth(); show("authScreen"); } catch (_) {}
  const err = $("authError");
  if (err) { err.textContent = "ошибка загрузки: " + (e && e.message || e); err.hidden = false; }
});
