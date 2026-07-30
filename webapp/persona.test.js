// Проверка формулы портрета: реагирует ли она на то, на что должна.
const g = globalThis;
require('/Users/johny/Desktop/CLAUDE/psychologist-bot/webapp/persona.js');
const P = g.Persona;

const SPEC = [
  { key:"warmth", default:2, levels:new Array(5).fill({}) },
  { key:"directness", default:2, levels:new Array(5).fill({}) },
  { key:"brevity", default:2, levels:new Array(5).fill({}) },
  { key:"questions", default:2, levels:new Array(5).fill({}) },
  { key:"irony", default:2, levels:new Array(5).fill({}) },
  { key:"melancholy", default:2, levels:new Array(5).fill({}) },
  { key:"initiative", default:2, levels:new Array(5).fill({}) },
];
const ORDER = ["system/00-intro.md","system/01-identity.md","system/02-therapy.md",
  "system/03-voice.md","system/04-behavior.md","system/05-boundaries.md",
  "system/06-memory.md","system/07-scope.md"];
const KNOWN = [
  { id:"anthropic/claude-opus-5", temperament:{depth:1.0,tempo:0.15,warmth:0.75,edge:0.6} },
  { id:"google/gemini-3-flash-preview", temperament:{depth:0.35,tempo:1.0,warmth:0.5,edge:0.45} },
  { id:"anthropic/claude-sonnet-4.6", temperament:{depth:0.7,tempo:0.5,warmth:0.85,edge:0.5} },
];
const run = (o) => P.compute({ dialsSpec:SPEC, dialsValue:o.dials||{}, order:o.order||ORDER,
  models:o.models||{model_chat:"google/gemini-3-flash-preview",humanizer_model:"anthropic/claude-sonnet-4.6",humanize_on:"1"},
  known:KNOWN });
const r2 = (x) => Math.round(x*100)/100;
let fails = 0;
const check = (name, cond, extra="") => { if(!cond){fails++;console.log("  ПРОВАЛ:",name,extra);} else console.log("  ok:",name,extra); };

console.log("=== базовое состояние ===");
const base = run({});
console.log("  черты:", Object.fromEntries(Object.entries(base.traits).map(([k,v])=>[k,r2(v)])));
console.log("  суть:", base.essence);

console.log("\n=== 1. ручки двигают свои черты ===");
const warm = run({dials:{warmth:4}});
check("тепло вверх", warm.traits.warmth > base.traits.warmth + .1, `${r2(base.traits.warmth)}→${r2(warm.traits.warmth)}`);
check("острота падает при тепле", warm.traits.edge < base.traits.edge, `${r2(base.traits.edge)}→${r2(warm.traits.edge)}`);

console.log("\n=== 2. ПОРЯДОК СЛОЁВ влияет на портрет ===");
const scopeLast = run({order:ORDER});                                  // 07-scope последний
const scopeFirst = run({order:["system/07-scope.md",...ORDER.filter(f=>f!=="system/07-scope.md")]});
check("опора выше, когда границы в хвосте",
  scopeLast.traits.steadiness > scopeFirst.traits.steadiness + .02,
  `${r2(scopeFirst.traits.steadiness)} (первым) → ${r2(scopeLast.traits.steadiness)} (последним)`);
const voiceLast = run({order:[...ORDER.filter(f=>f!=="system/03-voice.md"),"system/03-voice.md"]});
check("голос в хвосте греет", voiceLast.traits.warmth > scopeLast.traits.warmth,
  `${r2(scopeLast.traits.warmth)}→${r2(voiceLast.traits.warmth)}`);

console.log("\n=== 3. модель меняет глубину и темп ===");
const opus = run({models:{model_chat:"anthropic/claude-opus-5",humanizer_model:"",humanize_on:"1"}});
check("Opus глубже flash", opus.traits.depth > base.traits.depth + .15, `${r2(base.traits.depth)}→${r2(opus.traits.depth)}`);
check("Opus медленнее", opus.traits.tempo < base.traits.tempo, `${r2(base.traits.tempo)}→${r2(opus.traits.tempo)}`);
check("без редактора живость падает", opus.traits.aliveness < base.traits.aliveness,
  `${r2(base.traits.aliveness)}→${r2(opus.traits.aliveness)}`);
check("видит, что редактора нет", opus.meta.editorOn === false);

console.log("\n=== 4. взаимодействия ловят риски ===");
const cold = run({dials:{warmth:0, directness:4, irony:4, initiative:4}});
check("сарказм пойман", cold.risks.sarcasm > .62, `sarcasm=${r2(cold.risks.sarcasm)}`);
check("давление поймано", cold.risks.pressure > .55, `pressure=${r2(cold.risks.pressure)}`);
check("есть предупреждения", cold.warn.length >= 2, `(${cold.warn.length})`);
cold.warn.forEach(w => console.log("     ⚠", w));
const flat = run({dials:{warmth:1, irony:0, melancholy:0, brevity:2}, models:{model_chat:"google/gemini-3-flash-preview",humanizer_model:"",humanize_on:"0"}});
check("выцветание поймано", flat.risks.flatness > .5, `flatness=${r2(flat.risks.flatness)}`);

console.log("\n=== 5. границы значений ===");
const extreme = run({dials:{warmth:4,directness:4,brevity:4,questions:4,irony:4,melancholy:4,initiative:4}});
const allIn = Object.values(extreme.traits).every(v => v >= 0 && v <= 1);
check("все черты в 0..1 на максимуме", allIn);
const zero = run({dials:{warmth:0,directness:0,brevity:0,questions:0,irony:0,melancholy:0,initiative:0}});
check("все черты в 0..1 на минимуме", Object.values(zero.traits).every(v => v >= 0 && v <= 1));
check("пустой ввод не падает", !!run({dialsSpec:[],order:[],models:{},known:[]}).essence);

console.log("\n=== 6. описания читаются ===");
console.log("  тёплый:", warm.essence);
console.log("  холодный:", cold.essence);
console.log("  opus:", opus.essence);
console.log("  резюме:", opus.summary);

console.log(fails ? `\nПРОВАЛОВ: ${fails}` : "\nвсе проверки пройдены");
process.exit(fails ? 1 : 0);
