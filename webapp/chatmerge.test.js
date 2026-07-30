/* Проверка слияния истории чата. Гоняет НАСТОЯЩИЙ код из app.js — функция берётся
   из исходника между маркерами chatMerge:start/end, копии логики здесь нет.
   node webapp/chatmerge.test.js */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const src = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
const body = src.split("/* chatMerge:start")[1].split("/* chatMerge:end */")[0].replace(/^[^\n]*\n/, "");
const sandbox = {};
vm.runInNewContext(body, sandbox, { filename: "app.js#chatMerge" });
const chatMerge = sandbox.chatMerge;

const u = (t) => ({ role: "user", text: t });
const a = (t) => ({ role: "agent", text: t });
const sig = (x) => JSON.stringify((x || []).map((m) => [m.role, m.text]));

let fails = 0;
const eq = (name, got, want) => {
  const ok = got === null || want === null ? got === want : sig(got) === sig(want);
  if (!ok) { fails++; console.log("✗", name, "\n  got: ", sig(got), "\n  want:", sig(want)); }
  else console.log("✓", name);
};

eq("совпало → null",
  chatMerge([u("привет"), a("да?")], [u("привет"), a("да?")]), null);

eq("сервер впереди (написал в телеграм) → берём сервер",
  chatMerge([u("привет"), a("да?"), u("из тг")], [u("привет"), a("да?")]),
  [u("привет"), a("да?"), u("из тг")]);

eq("наше сообщение ещё не в БД → хвост сохраняется",
  chatMerge([u("привет"), a("да?")], [u("привет"), a("да?"), u("свежее")]), null);

eq("ответ дописан, БД ещё не успела → ответ не мигает",
  chatMerge([u("привет"), a("да?"), u("ещё")], [u("привет"), a("да?"), u("ещё"), a("готово")]), null);

eq("пустая ячейка стрима не обрывает хвост",
  chatMerge([u("привет")], [u("привет"), u("свежее"), a("")]), null);

// главное: реплика психолога, осевшая в локалке как сообщение клиента, вычищается
eq("дубль ответа под ролью user исчезает",
  chatMerge([u("вопрос"), a("ответ психолога")],
            [u("вопрос"), a("ответ психолога"), u("ответ психолога")]),
  [u("вопрос"), a("ответ психолога")]);

eq("две таких копии подряд исчезают обе",
  chatMerge([u("вопрос"), a("первый"), u("вопрос2"), a("второй")],
            [u("вопрос"), a("первый"), u("вопрос2"), a("второй"), u("первый"), u("второй")]),
  [u("вопрос"), a("первый"), u("вопрос2"), a("второй")]);

// окно сервера скользит (последние 100): раньше это уводило в ветку «расхождение»
eq("сдвиг окна истории — не расхождение",
  chatMerge([u("2"), a("b"), u("3")], [u("1"), a("a"), u("2"), a("b"), u("3")]),
  [u("2"), a("b"), u("3")]);

eq("свежее в локалке при пустом сервере — не теряем",
  chatMerge([], [u("свежее")]), null);

console.log(fails ? `\n${fails} провал(ов)` : "\nвсе проверки прошли");
process.exit(fails ? 1 : 0);
