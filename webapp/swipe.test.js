/* Порог свайпа между вкладками. Гоняет НАСТОЯЩИЙ код из app.js — функция берётся
   из исходника между маркерами swipeTarget:start/end, копии логики здесь нет.
   Настоящим жестом это не проверить: WebKit не даёт собрать TouchEvent руками.
   node webapp/swipe.test.js */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const src = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
const body = src.split("/* swipeTarget:start")[1].split("/* swipeTarget:end */")[0].replace(/^[^\n]*\n/, "");
const sandbox = {};
vm.runInNewContext(body, sandbox, { filename: "app.js#swipeTarget" });
const swipeTarget = sandbox.swipeTarget;

const V = ["chat", "diary", "profile"];
let fails = 0;
const eq = (name, got, want) => {
  if (got !== want) { fails++; console.log(`✗ ${name}\n  got: ${got}\n  want: ${want}`); }
  else console.log("✓", name);
};

// медленное короткое движение — это не свайп, а дрожь пальца при скролле
eq("30px за 400мс — вкладка не меняется", swipeTarget(V, "chat", -30, 400), null);

// длинное медленное протаскивание засчитывается
eq("120px медленно — переход", swipeTarget(V, "chat", -120, 600), "diary");

// резкий флик засчитывается даже коротким: раньше порог был только по
// расстоянию (25% ширины экрана), и быстрый смах просто ничего не делал
eq("40px за 50мс (флик) — переход", swipeTarget(V, "chat", -40, 50), "diary");
eq("флик вправо с середины — назад", swipeTarget(V, "diary", 40, 50), "chat");

// направление
eq("влево — следующая вкладка", swipeTarget(V, "diary", -120, 300), "profile");
eq("вправо — предыдущая", swipeTarget(V, "profile", 120, 300), "diary");

// края цикла
eq("вправо с первой — некуда", swipeTarget(V, "chat", 120, 300), null);
eq("влево с последней — некуда", swipeTarget(V, "profile", -120, 300), null);

// экран вне цикла вкладок
eq("неизвестная вкладка — null", swipeTarget(V, "settings", -200, 100), null);

// нулевое время не делит на ноль
eq("мгновенный жест не ломает счёт скорости", swipeTarget(V, "chat", -200, 0), "diary");

console.log(fails ? `\n${fails} провал(ов)` : "\nвсе проверки прошли");
process.exit(fails ? 1 : 0);
