/* MOOD — персональный психолог. Multi-user PWA. */
const tg = window.Telegram?.WebApp;
try { tg?.ready?.(); tg?.expand?.(); } catch (_) {}

const $ = (id) => document.getElementById(id);
const haptic = (k = "light") => { try { tg?.HapticFeedback?.impactOccurred(k); } catch (_) {} };
const hapticOk = () => { try { tg?.HapticFeedback?.notificationOccurred("success"); } catch (_) {} };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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
    const wrap = document.createElement("div");
    wrap.className = "scale-wrap";
    (q.labels || ["1","2","3","4","5"]).forEach((label, i) => {
      const b = document.createElement("button");
      b.className = "scale-btn" + (obAnswers[q.id] === i + 1 ? " sel" : "");
      b.innerHTML = `<span class="scale-num">${i + 1}</span><span class="scale-lbl">${label}</span>`;
      b.onclick = () => { haptic(); obAnswers[q.id] = i + 1; renderQuestion(); setTimeout(obNext, 180); };
      wrap.appendChild(b);
    });
    box.appendChild(wrap);
    $("obNext").textContent = "пропустить";
  } else {
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
    $("logoutBtn").onclick = () => { clearToken(); location.reload(); };
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

function setupChat() {
  const input = $("chatInput"), send = $("chatSend");
  const upd = () => { send.disabled = !input.value.trim(); input.style.height = "auto"; input.style.height = Math.min(120, input.scrollHeight) + "px"; };
  input.addEventListener("input", upd);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!send.disabled) sendMessage(); } });
  send.addEventListener("click", sendMessage);
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
    const r = await api("/api/v2/chat", { method: "POST", body: { q: text } });
    const full = (r.reply || "(пусто)").trim();
    const toks = full.split(/(\s+)/);
    for (const t of toks) { acc += t; agentEl.innerHTML = mdLite(acc); box.scrollTop = box.scrollHeight; await sleep(20); }
    done();
  } catch (e) {
    acc = "сломалось: " + e.message;
    agentEl.innerHTML = mdLite(acc);
    done();
  }
}

/* ── profile ── */
async function loadProfile() {
  $("profName").textContent = window.__me?.name || "—";
  $("profEmail").textContent = window.__me?.email || "—";
  try {
    const me = await api("/api/me");
    $("profCompiled").innerHTML = me.compiled ? mdLite(me.compiled) : "портрет появится после онбординга";
  } catch (_) {
    $("profCompiled").textContent = "—";
  }
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

boot().catch((e) => {
  try { initAuth(); show("authScreen"); } catch (_) {}
  const err = $("authError");
  if (err) { err.textContent = "ошибка загрузки: " + (e && e.message || e); err.hidden = false; }
});
