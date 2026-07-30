/* Портрет личности: во что складываются все настройки разом.
 *
 * Считает не «сумму ползунков», а взаимодействие четырёх источников:
 *   1. ручки характера       — прямое намерение владельца
 *   2. порядок слоёв промпта — поздний слой держит внимание модели сильнее (спека §5.1),
 *                              поэтому его тема звучит в ответах громче
 *   3. модель на должности   — темперамент: глубина, темп, тепло, острота
 *   4. второй проход         — редактор шлифует голос, добавляя живости и такта
 *
 * Ключевое: черты не независимы. Ирония без тепла читается как сарказм, прямота
 * без тепла — как нападение, напор при высокой инициативе давит. Формула считает
 * эти произведения явно и возвращает предупреждения — чтобы владелец видел не
 * только «что выкручено», но и «во что это сложится у живого человека».
 *
 * Всё чистое: ни одного запроса, пересчёт мгновенный при любом изменении.
 */
(function (root) {
  "use strict";

  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const lerp = (a, b, t) => a + (b - a) * t;

  /* Профиль слоя: какие оси характера он усиливает, когда стоит в промпте.
     Значения — вклад слоя в ось при среднем весе позиции. */
  const LAYER_PROFILE = {
    "system/00-intro.md":      { authority: .8, honesty: .7 },
    "system/01-identity.md":   { depth: .7, focus: .6 },
    "system/02-therapy.md":    { craft: .9, adaptivity: .7, depth: .4 },
    "system/03-voice.md":      { warmth: .5, irony: .5, melancholy: .6, tact: .7 },
    "system/04-behavior.md":   { tempo: .7, questions: .6, structure: .6 },
    "system/05-boundaries.md": { restraint: .8, safety: .5 },
    "system/06-memory.md":     { continuity: .9, engagement: .6 },
    "system/07-scope.md":      { safety: 1.0, restraint: .6 },
  };

  /* Вес позиции: первый слой 0.75, последний 1.25. Хвост промпта модель держит
     вниманием сильнее — поэтому перестановка слоёв реально меняет портрет. */
  function positionWeights(order) {
    const n = Math.max(1, order.length);
    const w = {};
    order.forEach((file, i) => { w[file] = n === 1 ? 1 : lerp(0.75, 1.25, i / (n - 1)); });
    return w;
  }

  /* Сумма вкладов слоёв по осям, с учётом позиции. */
  function layerAxes(order) {
    const w = positionWeights(order);
    const ax = {};
    for (const file of order) {
      const prof = LAYER_PROFILE[file];
      if (!prof) continue;
      for (const [k, v] of Object.entries(prof)) ax[k] = (ax[k] || 0) + v * w[file];
    }
    // нормируем к 0..1 по разумному потолку (сумма профилей ~1.5 на ось)
    for (const k of Object.keys(ax)) ax[k] = clamp(ax[k] / 1.6);
    return ax;
  }

  const NEUTRAL_TEMPER = { depth: .5, tempo: .5, warmth: .5, edge: .5 };

  function temperOf(modelId, known) {
    const m = (known || []).find(x => x.id === modelId);
    return (m && m.temperament) ? m.temperament : NEUTRAL_TEMPER;
  }

  /* ── главная функция ── */
  function compute(input) {
    const { dialsSpec = [], dialsValue = {}, order = [], models = {}, known = [] } = input;

    // ручки → 0..1
    const d = {};
    for (const s of dialsSpec) {
      const raw = Number.isInteger(dialsValue[s.key]) ? dialsValue[s.key] : (s.default ?? 2);
      const max = Math.max(1, (s.levels || []).length - 1);
      d[s.key] = clamp(raw / max);
    }
    const dv = (k, fallback = .5) => (k in d ? d[k] : fallback);

    const ax = layerAxes(order);
    const axv = (k) => ax[k] ?? 0;

    const chat = temperOf(models.model_chat, known);
    const editorOn = models.humanize_on === "1" && !!(models.humanizer_model || "").trim();
    const editor = editorOn ? temperOf(models.humanizer_model, known) : null;

    // голос клиенту формирует последний, кто трогает текст: редактор, иначе сама модель
    const voice = editor || chat;
    const mix = (a, b, t) => lerp(a, b, t);

    // ── производные черты ──
    const warmth = clamp(
      dv("warmth") * .52 + axv("warmth") * .16 + voice.warmth * .22 + (editorOn ? .10 : 0));

    const edgeRaw = dv("directness") * .45 + dv("irony") * .22 + voice.edge * .18;
    const edge = clamp(edgeRaw * (1 - warmth * .35));            // тепло приглушает остроту

    const depth = clamp(
      dv("melancholy") * .22 + chat.depth * .40 + axv("depth") * .20 + axv("craft") * .18);

    const tempo = clamp(
      dv("brevity") * .40 + chat.tempo * .40 - (editorOn ? .12 : 0) + .12);

    const engagement = clamp(
      dv("questions") * .34 + dv("initiative") * .34 + axv("engagement") * .16 + axv("continuity") * .16);

    const steadiness = clamp(
      axv("safety") * .40 + axv("restraint") * .25 + axv("tact") * .15
      + (1 - dv("irony")) * .10 + (editorOn ? .10 : 0));

    const aliveness = clamp(
      (editorOn ? .26 : .08) + dv("irony") * .24 + voice.warmth * .18
      + axv("adaptivity") * .14 + (1 - Math.abs(dv("brevity") - .5)) * .18);

    const traits = { warmth, edge, depth, tempo, engagement, steadiness, aliveness };

    // ── взаимодействия: то, что не видно по отдельным ручкам ──
    const sarcasm = clamp(dv("irony") * (1 - warmth) * 1.35);        // ирония без тепла
    const pressure = clamp(dv("directness") * dv("initiative") * (1 - warmth) * 1.5);
    const coldCut = clamp(dv("directness") * (1 - warmth) * (1 - axv("tact")) * 1.4);
    const smother = clamp(dv("questions") * dv("initiative") * 1.15);  // заваливает вопросами
    const flatness = clamp((1 - dv("irony")) * (1 - depth) * (1 - warmth) * 1.3);
    const risks = { sarcasm, pressure, coldCut, smother, flatness };

    // ── предупреждения ──
    const warn = [];
    if (sarcasm > .62) warn.push("ирония при таком тепле прочитается как сарказм");
    if (pressure > .55) warn.push("прямота с напором без тепла ощущается как давление");
    if (coldCut > .58) warn.push("режет по-живому: такт не успевает смягчить прямоту");
    if (smother > .70) warn.push("много вопросов подряд — это допрос, а не разговор");
    if (flatness > .55) warn.push("характер выцветает: ни тепла, ни иронии, ни глубины");
    if (tempo > .82 && depth > .7) warn.push("глубокая модель на коротком поводке — мысль не помещается");
    if (!editorOn && chat.tempo > .8) warn.push("быстрая модель без редактора: почерк модели вылезет");

    // ── словесный слепок ──
    const NAMES = {
      warmth:     ["ледяной", "сдержанный", "ровный", "тёплый", "обнимающий"],
      edge:       ["мягкий", "тактичный", "прямой", "острый", "режущий"],
      depth:      ["поверхностный", "простой", "вдумчивый", "глубокий", "проникающий"],
      tempo:      ["обстоятельный", "неспешный", "собранный", "быстрый", "отрывистый"],
      engagement: ["отстранённый", "спокойный", "внимательный", "вовлечённый", "неотступный"],
      steadiness: ["зыбкий", "гибкий", "устойчивый", "надёжный", "непоколебимый"],
      aliveness:  ["механический", "суховатый", "живой", "яркий", "искрящий"],
    };
    const band = (v) => v < .2 ? 0 : v < .4 ? 1 : v < .6 ? 2 : v < .8 ? 3 : 4;
    const word = (k) => NAMES[k][band(traits[k])];

    // ведущие черты = самые отклонённые от середины
    const lead = Object.keys(traits)
      .map(k => ({ k, dist: Math.abs(traits[k] - .5) }))
      .sort((a, b) => b.dist - a.dist).slice(0, 3).map(x => word(x.k));

    let essence = `${word("warmth")}, ${word("edge")}, ${word("depth")}`;
    if (sarcasm > .62) essence += " — с колючей кромкой";
    else if (warmth > .72 && edge < .4) essence += " — почти бережный";
    else if (steadiness > .78) essence += " — и очень устойчивый";

    const summary =
      `${word("depth")} собеседник: ${word("warmth")} в подаче и ${word("edge")} по существу. ` +
      `${word("engagement")} в разговоре, ${word("tempo")} в ритме. ` +
      (editorOn ? "финал шлифует редактор — голос звучит ровнее и живее."
                : "говорит одним проходом, без редактора: слышен характер самой модели.");

    return { traits, risks, warn, lead, essence, summary,
             meta: { editorOn, voiceModel: editorOn ? models.humanizer_model : models.model_chat } };
  }

  root.Persona = { compute, LAYER_PROFILE, positionWeights };
})(typeof window !== "undefined" ? window : globalThis);
