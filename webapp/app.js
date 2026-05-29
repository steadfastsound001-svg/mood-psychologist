/* MOOD — персональный психолог. Multi-user PWA. */
const tg = window.Telegram?.WebApp;
try { tg?.ready?.(); tg?.expand?.(); } catch (_) {}

const $ = (id) => document.getElementById(id);
const haptic = (k = "light") => { try { tg?.HapticFeedback?.impactOccurred(k); } catch (_) {} };
const hapticOk = () => { try { tg?.HapticFeedback?.notificationOccurred("success"); } catch (_) {} };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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
}

/* mdLite: **bold** → <b>, экранирование html */
function mdLite(text) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  let out = esc(text || "");
  out = out.replace(/\*\*([^*\n]{1,80}?)\*\*/g, "<b>$1</b>");
  out = out.replace(/\*([^*\n]+?)\*/g, "$1"); // одиночные звёзды (без lookbehind — Safari < 16.4)
  return out;
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

/* ───────── AUTH ───────── */
let authMode = "login"; // login | register
function initAuth() {
  const submit = $("authSubmit");
  const switchBtn = $("authSwitchBtn");
  const setMode = (m) => {
    authMode = m;
    $("authName").hidden = m !== "register";
    submit.textContent = m === "login" ? "войти" : "создать аккаунт";
    $("authSwitchText").textContent = m === "login" ? "нет аккаунта?" : "уже есть аккаунт?";
    switchBtn.textContent = m === "login" ? "создать" : "войти";
    $("authError").hidden = true;
  };
  switchBtn.onclick = () => { haptic(); setMode(authMode === "login" ? "register" : "login"); };
  submit.onclick = doAuth;
  $("authPass").addEventListener("keydown", (e) => { if (e.key === "Enter") doAuth(); });
  setMode("login");
  // показать кнопку Google если настроен
  api("/api/auth/google/enabled", { auth: false }).then((r) => {
    if (r.enabled) { $("googleBtn").hidden = false; $("authOr").hidden = false; }
  }).catch(() => {});
}

async function doAuth() {
  const email = $("authEmail").value.trim();
  const pass = $("authPass").value;
  const name = $("authName").value.trim();
  const err = $("authError");
  err.hidden = true;
  if (!email || pass.length < 4) { err.textContent = "нужен email и пароль от 4 символов"; err.hidden = false; return; }
  $("authSubmit").disabled = true;
  try {
    const path = authMode === "login" ? "/api/auth/login" : "/api/auth/register";
    const r = await api(path, { method: "POST", auth: false, body: { email, password: pass, name } });
    setToken(r.token);
    window.__me = r.user;
    hapticOk();
    if (authMode === "register" || !r.onboarded) { startOnboarding(); show("onboardScreen"); }
    else { initApp(); show("app"); }
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    $("authSubmit").disabled = false;
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
  renderQuestion();
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
  if (!appInited) {
    appInited = true;
    document.querySelectorAll(".tab-item").forEach((b) => {
      b.addEventListener("click", () => { haptic("medium"); switchView(b.dataset.view); });
    });
    setupChat();
    $("profSave").onclick = saveProfileInfo;
    $("profCompile").onclick = compilePortrait;
    $("profExport").onclick = exportPortrait;
    $("weeklyBtn").onclick = genWeekly;
    $("logoutBtn").onclick = () => { clearToken(); location.reload(); };
    $("fileBtn").onclick = () => $("fileInput").click();
    $("fileInput").onchange = (e) => uploadFiles(e.target.files);
    $("tmClose").onclick = closeTest;
    loadExtraTests();
  }
  switchView("chat");
}

function switchView(view) {
  document.querySelectorAll(".tab-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $("chatView").hidden = view !== "chat";
  $("profileView").hidden = view !== "profile";
  if (view === "profile") loadProfile();
  if (view === "chat") chatRender();
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
    maybeOpener();
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
  mic.classList.add("rec"); mic.textContent = "⏹"; haptic("medium");
}
function stopVoice() {
  recording = false;
  try { mediaRec && mediaRec.state !== "inactive" && mediaRec.stop(); } catch (_) {}
  try { recStream && recStream.getTracks().forEach((t) => t.stop()); } catch (_) {}
  const mic = $("chatMic"); mic.classList.remove("rec"); mic.textContent = "🎙";
}
async function sendVoice(input, upd) {
  const mic = $("chatMic");
  const type = (recChunks[0] && recChunks[0].type) || "audio/webm";
  const blob = new Blob(recChunks, { type });
  if (!blob.size) return;
  mic.classList.add("busy"); mic.textContent = "…";
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
    mic.classList.remove("busy"); mic.textContent = "🎙";
    if (input.placeholder === "распознаю…") input.placeholder = prevPh;
  }
}

let streaming = false;
async function sendMessage() {
  if (streaming) return;
  const input = $("chatInput");
  const text = input.value.trim();
  if (!text) return;
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

  let acc = "";
  const done = () => {
    agentEl.classList.remove("streaming");
    streaming = false; hapticOk();
    const f = loadChat();
    f[f.length - 1].text = acc || "(пусто)";
    saveChat(f);
  };
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 120000);
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
      agentEl.innerHTML = mdLite(acc);
      box.scrollTop = box.scrollHeight;
    }
    clearTimeout(timer);
    done();
  } catch (e) {
    if (!acc) acc = "сломалось: " + e.message;
    agentEl.innerHTML = mdLite(acc);
    done();
  }
}

/* ── profile / MOOD ── */
let lastStats = null;

async function loadProfile() {
  $("profName").textContent = window.__me?.name || "—";
  $("profEmail").textContent = window.__me?.email || "—";
  let compiled = "";
  try {
    const me = await api("/api/me");
    compiled = me.compiled || "";
    $("profCompiled").innerHTML = compiled ? mdLite(compiled) : "портрет ещё не собран — нажми кнопку ниже";
  } catch (_) {
    $("profCompiled").textContent = "—";
  }
  // кнопка «собрать портрет» исчезает после сборки
  window.__portraitText = compiled.trim();
  $("profCompile").hidden = !!compiled.trim();
  $("profExport").hidden = !compiled.trim();
  loadStats();
  loadDocuments();
}

async function loadStats() {
  try {
    lastStats = await api("/api/stats");
  } catch (_) { lastStats = null; }
  renderMood(lastStats);
  renderPulse(lastStats);
  renderTests(lastStats);
  renderAch(lastStats);
  renderAnalytics(lastStats);
  // итоги недели открываются после 3 сеансов
  if ($("weeklyCard")) $("weeklyCard").hidden = !(lastStats && lastStats.sessions >= 3);
}

/* ── пульс настроения ── */
const PULSE = [
  { e: "😞", l: "тяжело" },
  { e: "😕", l: "так себе" },
  { e: "😐", l: "норм" },
  { e: "🙂", l: "хорошо" },
  { e: "😄", l: "отлично" },
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
    b.innerHTML = `<span class="pulse-e">${p.e}</span><span class="pulse-l">${p.l}</span>`;
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

const MOOD_WORD = (m) => m >= 75 ? "ты в ресурсе" : m >= 55 ? "в целом устойчиво" : m >= 40 ? "качает, но держишься" : "тяжёлый период";
function renderMood(s) {
  const locked = $("moodLocked"), ready = $("moodReady");
  if (!s || s.mood == null) {
    locked.hidden = false; ready.hidden = true;
    if (s) $("moodProg").textContent = `осталось ${s.mood_remaining} ${plural(s.mood_remaining, "сеанс", "сеанса", "сеансов")}`;
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
  if (!extraTests.length) { box.textContent = "—"; return; }
  extraTests.forEach((t) => {
    const done = s && s.tests && s.tests[t.id];
    const el = document.createElement("button");
    el.className = "test-item" + (done ? " done" : "");
    el.innerHTML = `<span class="test-emoji">${t.emoji}</span><span class="test-title">${t.title}</span><span class="test-state">${done ? "✓ пройден" : "пройти →"}</span>`;
    el.onclick = () => { haptic(); openTest(t); };
    box.appendChild(el);
  });
}

function renderAch(s) {
  const box = $("achList");
  box.innerHTML = "";
  const list = (s && s.achievements) || [];
  list.forEach((a) => {
    const el = document.createElement("div");
    el.className = "ach" + (a.got ? " got" : "");
    el.innerHTML = `<span class="ach-ico">${a.got ? a.icon : "🔒"}</span><span class="ach-lbl">${a.label}</span>`;
    box.appendChild(el);
  });
}

function renderAnalytics(s) {
  const box = $("analyticsBox");
  if (!s) { box.innerHTML = '<div class="card-note">—</div>'; return; }
  if (!s.analytics_unlocked) {
    box.innerHTML = `<div class="locked"><div class="locked-ico">🔒</div>
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
    ${stat("дней подряд", streak > 0 ? "🔥 " + streak : "—")}
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
      $("profCompiled").innerHTML = mdLite(r.compiled);
      window.__portraitText = r.compiled.trim();
      btn.hidden = true;
      $("profExport").hidden = false;
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
    if (r.stats) { lastStats = r.stats; renderMood(r.stats); renderTests(r.stats); renderAch(r.stats); renderAnalytics(r.stats); }
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
    el.innerHTML = `<span class="file-name">📄 ${escapeHtml(d.name)}</span><span class="file-size">${kb(d.size)}</span><button class="file-del" data-id="${d.id}">✕</button>`;
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
