// Seção "Modelo": cartão do campeão, importância das features e saúde dos dados (drift). Só DOM seguro (textContent).
import { importanceChart } from "./charts.js";
import { clear, dateLong, h, monthLabel, num, pct } from "./util.js";

const PARAMS_SOURCE = {
  tuned: "Ajustados com Optuna, em validação cruzada temporal",
  random_search: "Melhor de um sorteio simples, escolhido na validação",
};
const HIDDEN_PARAMS = new Set(["log_target", "seed"]); // aparecem numa linha própria
const number = new Intl.NumberFormat("pt-BR", { maximumSignificantDigits: 3 });
const isoParts = (win) => win?.match(/(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})(?: \((\d+) linhas\))?/);

/** "1993-01-31..1997-10-31 (122618 linhas)" -> "jan/1993 a out/1997 · 122.618 linhas". */
function windowText(win) {
  const m = isoParts(win);
  if (!m) return win ?? "—";
  return `${monthLabel(m[1])} a ${monthLabel(m[2])}${m[3] ? ` · ${num(Number(m[3]))} linhas` : ""}`;
}
const paramValue = (v) => (v !== "" && Number.isFinite(Number(v)) ? number.format(Number(v)) : v);

const dl = (rows) => h("dl", { class: "dl" }, rows.filter(Boolean).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));

function paramsBlock(m) {
  const shown = Object.entries(m.params ?? {}).filter(([k]) => !HIDDEN_PARAMS.has(k));
  if (!shown.length) return h("p", { class: "note" }, "Este modelo não tem hiperparâmetros registrados (ou o run não os guardou).");
  const log = m.params?.log_target;
  return h("div", {},
    h("div", { class: "table-wrap" }, h("table", { class: "plain" },
      h("caption", {}, m.params_source ? PARAMS_SOURCE[m.params_source] ?? m.params_source : "Origem não registrada (run anterior ao registro da origem)"),
      h("tbody", {}, shown.map(([k, v]) => h("tr", { style: { cursor: "default" } }, h("td", {}, h("code", {}, k)), h("td", {}, paramValue(v))))))),
    log != null ? h("p", { class: "note" }, `Alvo treinado em escala log: ${log === "True" || log === "true" ? "sim" : "não"}${m.params?.seed ? ` · semente ${m.params.seed}` : ""}.`) : null);
}

function modelCard(m) {
  const w = m.windows ?? {};
  return h("div", { class: "card reveal", style: { "--d": 1 } },
    h("h3", {}, "Cartão do modelo"),
    h("p", { class: "sub" }, "De onde vem o campeão e com que dados ele foi medido."),
    dl([
      ["Algoritmo", m.algorithm_label],
      ["Registro", `${m.name} · versão ${m.version}`],
      ["Treinado em", dateLong(m.trained_at)],
      ["Treino", windowText(w.train_window)],
      ["Validação", windowText(w.val_window)],
      ["Teste", h("span", {}, windowText(w.test_window), " ", h("span", { class: "badge test" }, "nunca visto no treino"))],
    ]),
    h("h4", { class: "mini" }, "Hiperparâmetros"),
    paramsBlock(m));
}

function importanceCard(m) {
  const withImp = (m.features ?? []).filter((f) => f.importance != null);
  if (!withImp.length) {
    return h("div", { class: "card reveal", style: { "--d": 2 } }, h("h3", {}, "O que mais pesa no modelo"),
      h("p", { class: "note" }, `O ${m.algorithm_label} não expõe importância de features.`));
  }
  const sorted = [...withImp].sort((a, b) => b.importance - a.importance);
  const top = sorted.slice(0, 10);
  const groups = new Map();
  for (const f of withImp) groups.set(f.group, (groups.get(f.group) ?? 0) + f.importance);
  const groupRows = [...groups].sort((a, b) => b[1] - a[1]);
  const chart = h("div", { class: "chart", id: "chart-importance", style: { marginTop: "14px" } });
  const card = h("div", { class: "card reveal", style: { "--d": 2 } },
    h("h3", {}, "O que mais pesa no modelo"),
    h("p", { class: "sub" }, "As 10 informações de maior importância; em azul, as 5 primeiras."),
    chart,
    h("h4", { class: "mini" }, "Por grupo de informação"),
    h("ul", { class: "groupbars" }, groupRows.map(([g, v]) => h("li", {}, h("span", { class: "g" }, g), h("span", { class: "gb" }, h("i", { style: { width: `${(v / groupRows[0][1]) * 100}%` } })), h("b", { class: "num" }, pct(v, 0))))),
    h("p", { class: "note" }, "Importância média em todas as contas: mostra o que o modelo usa, não explica uma previsão individual."),
    h("details", { class: "asTable" }, h("summary", {}, "Ver como tabela"),
      h("div", { class: "table-wrap" }, h("table", { class: "plain" },
        h("thead", {}, h("tr", {}, ["Informação", "Grupo", "Importância"].map((t) => h("th", { scope: "col" }, t)))),
        h("tbody", {}, top.map((f) => h("tr", { style: { cursor: "default" } }, h("td", {}, f.label), h("td", {}, f.group), h("td", {}, pct(f.importance, 1)))))))));
  // o gráfico precisa estar no DOM para medir a largura
  queueMicrotask(() => importanceChart(chart, top.map((f, i) => ({ label: f.label, value: f.importance, hot: i < 5 }))));
  return card;
}

const featureLabel = (m, name) => m.features?.find((f) => f.name === name)?.label ?? name.replaceAll("_", " ");

function monitoringCard(m, s) {
  if (!s?.available) {
    return h("div", { class: "card reveal wide", style: { "--d": 3 } }, h("h3", {}, "Saúde dos dados"),
      h("p", { class: "sub" }, "Monitoramento de drift (Evidently)."),
      h("p", { class: "note" }, "Ainda não há relatório de drift. Ele é gerado pela DAG ", h("code", {}, "monitoring"), " (semanal) ou por ", h("code", {}, "make drift"), "."));
  }
  const detected = s.drift_detected;
  const near = !detected && s.drift_share >= 0.8 * s.drift_share_threshold;
  const win = (t) => { const p = isoParts(t); return p ? `${monthLabel(p[1])} a ${monthLabel(p[2])}` : t; };
  const meter = h("div", { class: "meter", role: "img", "aria-label": `${pct(s.drift_share)} das features com drift; limite de ${pct(s.drift_share_threshold)}` },
    h("i", { class: detected ? "warn" : "", style: { width: `${Math.min(100, s.drift_share * 100)}%` } }),
    h("b", { style: { left: `${s.drift_share_threshold * 100}%` } }));
  return h("div", { class: "card reveal wide", style: { "--d": 3 } },
    h("div", { class: "detail-head" },
      h("div", {}, h("h3", {}, "Saúde dos dados"), h("p", { class: "sub" }, "Os dados de hoje ainda se parecem com os do treino?")),
      h("span", { class: `badge ${detected ? "future" : "test"}` }, detected ? "Drift detectado" : "Sem drift no dataset")),
    h("div", { class: "mon-grid" },
      h("div", {},
        h("p", { class: "mon-big" }, h("b", { class: "num" }, `${s.n_drifted} de ${s.n_features}`), " features com drift ", h("span", { class: "num" }, `(${pct(s.drift_share)})`)),
        meter,
        h("div", { class: "meter-l" }, h("span", {}, "0%"), h("span", { style: { left: `${s.drift_share_threshold * 100}%` } }, `limite ${pct(s.drift_share_threshold)}`)),
        near ? h("p", { class: "note" }, "Perto do limite: uma janela ou um limiar diferentes mudariam o veredito.") : null,
        dl([
          ["Referência (treino)", win(s.reference_window)],
          ["Janela atual", win(s.current_window)],
          ["Relatório gerado em", dateLong(s.generated_at)],
          ["Último re-treino por drift", s.last_retrain_at ? dateLong(s.last_retrain_at) : "nunca disparado"],
        ])),
      h("div", {},
        h("h4", { class: "mini" }, "Features que mais mudaram"),
        s.top_drifted?.length ? h("ul", { class: "drifted" }, s.top_drifted.map((f) => h("li", {}, h("span", {}, featureLabel(m, f.name)), h("b", { class: "num" }, f.score.toFixed(2).replace(".", ","))))) : h("p", { class: "note" }, "Nenhuma feature acima do limiar."),
        h("p", { class: "note" }, "Score = distância de Wasserstein em desvios da referência (acima de 0,1 conta como drift). O dataset é histórico, então a janela atual é um replay temporal: os últimos meses da base contra os meses de treino, não tráfego real."))));
}

/** Preenche a seção #model. `status` pode ser nulo (API sem o endpoint ou sem relatório). */
export function renderModelSection(model, status) {
  const body = clear(document.getElementById("model-body"));
  body.append(modelCard(model), importanceCard(model), monitoringCard(model, status));
}
