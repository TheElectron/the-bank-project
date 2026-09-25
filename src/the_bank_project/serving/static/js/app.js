// Interface do The Bank Project: escolher contas, ver as features e comparar previsto x real.
import { barsChart, hbarChart, lineChart, monthBars, scatterChart } from "./charts.js";
import { $, FREQ, GENDER, clear, h, money, monthLabel, monthLong, num, one, pct, signed, signedPct, svg } from "./util.js";

const MAX_SELECTED = 10;
const state = {
  model: null,
  report: null, // desempenho no teste inteiro (quando pronto)
  months: [],
  monthKey: "latest", // 'latest' ou 'YYYY-MM-DD'
  selected: new Map(), // id -> AccountInfo
  page: { items: [], total: 0, offset: 0, loading: false },
  search: "",
  response: null, // PredictResponse
  detailId: null,
  history: new Map(), // `${id}|${T}` -> History
  loading: false,
  error: null,
};
let predictToken = 0;
let listToken = 0;

/* ---------- API ---------- */
async function request(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* corpo não é JSON */ }
    const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    err.status = res.status;
    throw err;
  }
  return res.json();
}
const get = (path) => request(path);
const post = (path, body) => request(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const refMonth = () => (state.monthKey === "latest" ? null : state.monthKey);
const monthInfo = () => state.months.find((m) => (m.reference_month ?? "latest") === state.monthKey);

/* ---------- tema ---------- */
$("#theme").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("tbp-theme", root.dataset.theme); } catch { /* armazenamento indisponível */ }
});

/* ---------- herói: o modelo campeão ---------- */
function renderModel() {
  const m = state.model;
  $("#model-chip").hidden = false;
  $("#model-chip-text").replaceChildren(h("span", {}, "Campeão "), h("strong", {}, `v${m.version}`), h("span", {}, ` · ${m.algorithm_label}`));
  $("#hero-eyebrow").textContent = `Modelo campeão · ${m.algorithm_label} · versão ${m.version}`;
  const naive = m.comparison.filter((c) => c.kind === "baseline");
  const bestNaive = naive.length ? Math.min(...naive.map((c) => c.test_mae)) : null;
  const skill = m.skill_vs_naive;
  const title = $("#hero-title");
  clear(title);
  if (skill != null && skill > 0) {
    title.append("Erra ", h("span", { class: "hl" }, `${pct(skill)} menos`), " que a média dos últimos 3 meses");
  } else {
    title.append("Ainda não supera a média dos últimos 3 meses");
  }
  const win = m.windows.test_window ?? "";
  const dates = win.match(/(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})/);
  const period = dates ? `${monthLabel(dates[1])} a ${monthLabel(dates[2])}` : "o conjunto de teste";
  $("#hero-lede").textContent = `Medido em contas e meses que o modelo nunca viu (${period}). Para cada conta, ele prevê o total de saídas do mês seguinte a partir do comportamento recente.`;
  const tiles = [
    { k: "Erro médio no teste (MAE)", v: [num(m.metrics.test_mae), h("small", {}, "Kč")], n: bestNaive ? `contra ${money(bestNaive)} da média de 3 meses` : "" },
    { k: "Parte da variação das saídas que o modelo explica (R²)", v: [String(m.metrics.test_r2.toFixed(2)).replace(".", ",")], n: "0 = não explica nada · 1 = explica tudo" },
    { k: "Contas-mês em que erra menos que a média de 3 meses", v: ["…"], n: "calculando no teste inteiro", id: "tile-win" },
  ];
  const stats = $("#hero-stats");
  clear(stats);
  tiles.forEach((t, i) => stats.append(h("div", { class: "stat reveal", style: { "--d": i + 1 } }, h("div", { class: "k" }, t.k), h("div", { class: "v num", id: t.id }, ...t.v), h("div", { class: "n", id: t.id ? `${t.id}-n` : null }, t.n))));
  hbarChart($("#chart-models"), m.comparison.map((c) => ({ label: c.label, value: c.test_mae, kind: c.kind, champion: c.champion })));
}

/* ---------- seleção: mês e contas ---------- */
const SPLIT_TEXT = { teste: "teste", validacao: "validação", treino: "treino", folga: "folga" };
function renderPicker() {
  const p = $("#picker");
  clear(p);
  const quick = [state.months[0], ...state.months.slice(1, 5)];
  const quickKeys = new Set(quick.map((m) => m.reference_month ?? "latest"));
  const others = state.months.filter((m) => !quickKeys.has(m.reference_month ?? "latest"));
  const monthChips = quick.map((m) => {
    const key = m.reference_month ?? "latest";
    return h("button", { class: "month-btn", type: "button", "aria-pressed": String(state.monthKey === key), onClick: () => setMonth(key) },
      m.reference_month ? monthLabel(m.reference_month) : monthLabel(latestIso()), h("small", {}, m.reference_month ? SPLIT_TEXT[m.split] : "futuro"));
  });
  const sel = h("select", { "aria-label": "Outro mês de referência", "data-active": String(!quickKeys.has(state.monthKey)), onChange: (e) => e.target.value && setMonth(e.target.value) },
    h("option", { value: "" }, "Outro mês…"),
    others.map((m) => h("option", { value: m.reference_month, selected: state.monthKey === m.reference_month }, `${monthLabel(m.reference_month)} · ${SPLIT_TEXT[m.split]}`)));
  p.append(
    h("div", { class: "step" },
      h("h3", {}, h("span", { class: "no" }, "1"), "Mês de referência"),
      h("p", {}, "O modelo só enxerga dados até o fim deste mês e prevê o seguinte."),
      h("div", { class: "months" }, monthChips, h("span", { class: "select-wrap" }, sel))),
    h("div", { class: "step" },
      h("h3", {}, h("span", { class: "no" }, "2"), "Contas"),
      h("p", {}, `Escolha até ${MAX_SELECTED} para comparar.`),
      h("label", { class: "search" },
        svg("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2, "stroke-linecap": "round", "aria-hidden": "true" }, svg("circle", { cx: 11, cy: 11, r: 7 }), svg("path", { d: "M20 20l-3.5-3.5" })),
        h("span", { class: "sr" }, "Buscar conta pelo número"),
        h("input", { type: "search", inputmode: "numeric", placeholder: "Buscar pelo número da conta", autocomplete: "off", value: state.search, onInput: debounce((e) => { state.search = e.target.value.trim(); loadAccounts(true); }, 220) })),
      h("div", { class: "actions" },
        h("button", { class: "btn primary", type: "button", onClick: sampleAccounts }, "Sortear 5 contas"),
        h("button", { class: "btn ghost", type: "button", onClick: clearSelection, disabled: state.selected.size === 0 }, "Limpar")),
      h("div", { class: "chosen", id: "chosen" }),
      h("p", { class: "count", id: "list-count" }),
      h("ul", { class: "acct-list", id: "acct-list", "aria-label": "Contas disponíveis" }),
      h("button", { class: "btn more", type: "button", id: "more", hidden: true, onClick: () => loadAccounts(false) }, "Mostrar mais contas")),
  );
  renderChosen();
  renderList();
}
const latestIso = () => {
  const first = state.months.find((m) => m.reference_month);
  const [y, mo] = first.reference_month.split("-").map(Number);
  const nm = mo === 12 ? 1 : mo + 1, ny = mo === 12 ? y + 1 : y;
  return `${ny}-${String(nm).padStart(2, "0")}-01`;
};

function renderChosen() {
  const box = $("#chosen");
  if (!box) return;
  clear(box);
  for (const [id] of state.selected) {
    box.append(h("span", { class: "pill" }, `Conta ${id}`, h("button", { type: "button", "aria-label": `Remover conta ${id}`, onClick: () => toggleAccount(state.selected.get(id)) }, "×")));
  }
  const btn = $(".actions .ghost");
  if (btn) btn.disabled = state.selected.size === 0;
}

function acctSub(a) {
  const bits = [a.district_name, a.owner_gender ? GENDER[a.owner_gender] : null].filter(Boolean);
  return bits.join(" · ") || "Sem cadastro";
}
function renderList() {
  const ul = $("#acct-list");
  if (!ul) return;
  clear(ul);
  if (!state.page.items.length) ul.append(h("li", { class: "empty-list" }, state.page.loading ? "Buscando…" : "Nenhuma conta encontrada para este mês."));
  const full = state.selected.size >= MAX_SELECTED;
  for (const a of state.page.items) {
    const on = state.selected.has(a.account_id);
    ul.append(h("li", {}, h("button", { class: "acct", type: "button", "aria-pressed": String(on), disabled: !on && full, onClick: () => toggleAccount(a) },
      h("span", { class: "box" }),
      h("span", {}, h("b", {}, `Conta ${a.account_id}`), h("span", { class: "sub" }, acctSub(a))),
      h("span", { class: "tags" }, a.has_loan ? h("span", { class: "tag" }, "empréstimo") : null, a.has_card ? h("span", { class: "tag" }, "cartão") : null))));
  }
  $("#list-count").replaceChildren(h("span", {}, `${num(state.page.total)} contas disponíveis`), h("span", {}, `${state.selected.size}/${MAX_SELECTED} escolhidas`));
  const more = $("#more");
  more.hidden = state.page.items.length >= state.page.total;
}

async function loadAccounts(reset) {
  const token = ++listToken;
  if (reset) state.page = { items: [], total: state.page.total, offset: 0, loading: true };
  else state.page.loading = true;
  renderList();
  const q = new URLSearchParams({ limit: "30", offset: String(state.page.offset), search: state.search });
  if (refMonth()) q.set("reference_month", refMonth());
  try {
    const data = await get(`/api/accounts?${q}`);
    if (token !== listToken) return;
    state.page = { items: reset ? data.items : [...state.page.items, ...data.items], total: data.total, offset: state.page.offset + data.items.length, loading: false };
  } catch (e) {
    if (token !== listToken) return;
    state.page.loading = false;
  }
  renderList();
}

function toggleAccount(a) {
  if (state.selected.has(a.account_id)) state.selected.delete(a.account_id);
  else if (state.selected.size < MAX_SELECTED) state.selected.set(a.account_id, a);
  renderChosen();
  renderList();
  schedulePredict();
}
function clearSelection() { state.selected.clear(); state.response = null; state.detailId = null; renderChosen(); renderList(); renderResults(); }
async function sampleAccounts() {
  const q = new URLSearchParams({ n: "5", seed: String(Math.floor(Math.random() * 1e6)) });
  if (refMonth()) q.set("reference_month", refMonth());
  const items = await get(`/api/accounts/sample?${q}`);
  state.selected = new Map(items.map((a) => [a.account_id, a]));
  state.detailId = null;
  renderChosen();
  renderList();
  runPredict();
}
function setMonth(key) {
  if (key === state.monthKey) return;
  state.monthKey = key;
  renderPicker();
  loadAccounts(true);
  schedulePredict();
}

/* ---------- previsão ---------- */
const schedulePredict = debounce(() => runPredict(), 160);
async function runPredict() {
  if (!state.selected.size) { state.response = null; renderResults(); return; }
  const token = ++predictToken;
  state.loading = true;
  state.error = null;
  $("#results").dataset.loading = "true";
  try {
    const res = await post("/predict", { account_ids: [...state.selected.keys()], reference_month: refMonth(), include_features: true });
    if (token !== predictToken) return;
    state.response = res;
    const ids = res.predictions.map((p) => p.account_id);
    if (!ids.includes(state.detailId)) state.detailId = ids[0] ?? null;
  } catch (e) {
    if (token !== predictToken) return;
    state.error = e.message;
    state.response = null;
  }
  state.loading = false;
  $("#results").dataset.loading = "false";
  renderResults();
}

/* ---------- resultados ---------- */
function splitBadge(pred, info) {
  const icon = (d) => svg("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2.2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" }, svg("path", { d }));
  if (!pred.split) return h("span", { class: "badge future" }, icon("M12 3v18M3 12h18"), "Previsão do futuro do dataset");
  if (pred.split === "teste") return h("span", { class: "badge test" }, icon("M5 12l4 4 10-10"), "Mês de teste · o modelo nunca viu estes valores");
  if (pred.split === "folga") return h("span", { class: "badge train" }, icon("M5 12h14"), "Mês fora do treino (folga)");
  return h("span", { class: "badge train" }, icon("M12 8v5M12 17h.01"), "Mês usado no treino · resultado tende a ser otimista");
}

function renderResults() {
  const root = $("#results");
  clear(root);
  if (state.error) { root.append(h("div", { class: "err-box", role: "alert" }, `Não foi possível prever: ${state.error}`)); return; }
  if (!state.selected.size) {
    root.append(h("div", { class: "empty reveal" }, h("p", { class: "big" }, "Escolha algumas contas para começar"),
      h("p", {}, "Ou deixe que a gente sorteie: você verá o que o modelo previu, o que de fato aconteceu e o quanto ele errou."),
      h("button", { class: "btn primary", type: "button", onClick: sampleAccounts }, "Sortear 5 contas")));
    return;
  }
  const res = state.response;
  if (!res) { root.append(h("p", { class: "loading-line" }, "Calculando previsões…")); return; }
  const preds = res.predictions;
  const hasActual = preds.some((p) => p.actual_next_month_outflow != null);
  const first = preds[0];
  if (!first) { root.append(h("div", { class: "err-box" }, "Nenhuma das contas escolhidas tem dados neste mês. Escolha outro mês ou outras contas.")); return; }
  const info = monthInfo();

  // contexto
  root.append(h("div", { class: "card banner reveal" },
    h("div", {},
      h("p", { class: "eyebrow" }, "Contexto da previsão"),
      h("p", { class: "flow", style: { marginTop: "8px" } }, "Com dados até ", h("em", {}, monthLong(first.features_as_of)), ", prevemos as saídas de ", h("em", {}, monthLong(first.target_month)), "."),
      h("p", { class: "note" }, hasActual
        ? "A barra laranja é o que de fato aconteceu naquele mês. O traço cinza é uma regra simples: repetir a média de saídas dos últimos 3 meses. Se o modelo não a superar, ele não agrega valor."
        : "Este mês ainda não existe no dataset, então não há valor real para comparar: é uma previsão do que vem a seguir. Escolha um mês anterior para ver o modelo contra a realidade.")),
    splitBadge(first, info)));
  if (res.not_found.length) {
    root.append(h("div", { class: "err-box" }, `Sem dados neste mês para: ${res.not_found.map((i) => `conta ${i}`).join(", ")}. Elas foram ignoradas.`));
  }

  // indicadores da seleção
  root.append(kpis(preds, hasActual));

  // gráfico + tabela
  const chartBox = h("div", { class: "chart", id: "chart-bars" });
  const legend = h("div", { class: "legend" }, h("span", {}, h("i", { class: "s-pred" }), "Previsto pelo modelo"),
    hasActual ? h("span", {}, h("i", { class: "s-real" }), "Real (o que aconteceu)") : null,
    h("span", {}, h("i", { class: "line", style: { borderColor: "var(--baseline)" } }), "Média de saídas dos 3 meses"));
  root.append(h("div", { class: "card reveal", style: { "--d": 1 } },
    h("h3", {}, hasActual ? "Previsto × real, conta a conta" : "Saídas previstas, conta a conta"),
    h("p", { class: "sub" }, "Clique em uma conta para ver o histórico e as informações que o modelo usou."),
    chartBox, legend, resultsTable(preds, hasActual)));
  barsChart(chartBox, preds.map((p) => ({ id: p.account_id, predicted: p.predicted_next_month_outflow, actual: p.actual_next_month_outflow, baseline: p.baseline_next_month_outflow })), { selected: state.detailId, hasActual, onSelect: selectDetail });

  // detalhe
  const detail = preds.find((p) => p.account_id === state.detailId) ?? first;
  root.append(detailCard(detail));
  loadHistory(detail);
}

function kpis(preds, hasActual) {
  const n = preds.length;
  if (!hasActual) {
    const total = preds.reduce((s, p) => s + p.predicted_next_month_outflow, 0);
    const base = preds.filter((p) => p.baseline_next_month_outflow != null);
    return h("div", { class: "kpis reveal" },
      kpi("Total previsto", money(total), `soma das ${n} contas`),
      kpi("Previsto por conta (média)", money(total / n), "no mês seguinte"),
      kpi("Referência: média de 3 meses", money(base.reduce((s, p) => s + p.baseline_next_month_outflow, 0) / (base.length || 1)), "por conta, no mesmo período"));
  }
  const err = preds.map((p) => Math.abs(p.predicted_next_month_outflow - p.actual_next_month_outflow));
  const base = preds.map((p) => Math.abs((p.baseline_next_month_outflow ?? 0) - p.actual_next_month_outflow));
  const mae = err.reduce((a, b) => a + b, 0) / n, bmae = base.reduce((a, b) => a + b, 0) / n;
  const better = err.filter((e, i) => e < base[i]).length;
  const rel = bmae ? 1 - mae / bmae : 0;
  return h("div", { class: "kpis reveal" },
    kpi("Erro médio do modelo", money(mae), `nas ${n} contas escolhidas`, rel > 0),
    kpi("Erro médio da média de 3 meses", money(bmae), rel > 0 ? `o modelo errou ${pct(rel)} menos` : `nesta seleção o modelo errou ${pct(-rel)} mais`),
    kpi("Contas em que o modelo foi melhor", `${better} de ${n}`, better * 2 >= n ? "vantagem nesta seleção" : overallHint()));
}
const overallHint = () => (state.report ? `com poucas contas isso acontece: no teste inteiro o modelo erra menos em ${pct(state.report.win_rate)} dos casos` : "com poucas contas isso acontece: veja o teste inteiro abaixo");
const kpi = (k, v, n, good) => h("div", { class: `kpi${good ? " good" : ""}` }, h("div", { class: "k" }, k), h("div", { class: "v num" }, v), h("div", { class: "n" }, n));

function resultsTable(preds, hasActual) {
  const head = ["Conta", "Previsto", ...(hasActual ? ["Real", "Erro do modelo", "Erro da média de 3 meses"] : ["Média de 3 meses"])];
  const rows = preds.map((p) => {
    const info = state.selected.get(p.account_id);
    const a = p.actual_next_month_outflow, pr = p.predicted_next_month_outflow, b = p.baseline_next_month_outflow;
    const cells = [h("td", {}, h("span", { class: "who" }, h("b", {}, `Conta ${p.account_id}`), info ? h("span", {}, acctSub(info)) : null)), h("td", {}, money(pr))];
    if (hasActual) {
      const em = Math.abs(pr - a), eb = b == null ? null : Math.abs(b - a);
      const modelWins = eb == null || em < eb;
      cells.push(h("td", {}, money(a)),
        h("td", { class: `err ${modelWins ? "win" : "lose"}` }, `${signed(pr - a)} Kč`, h("small", {}, a ? signedPct((pr - a) / a) : "—")),
        h("td", { class: `err ${modelWins ? "lose" : "win"}` }, eb == null ? "—" : `${signed(b - a)} Kč`, h("small", {}, eb == null || !a ? "" : signedPct((b - a) / a))));
    } else {
      cells.push(h("td", {}, money(b)));
    }
    return h("tr", { tabindex: 0, "aria-selected": String(p.account_id === state.detailId), onClick: () => selectDetail(p.account_id), onKeydown: (e) => { if (e.key === "Enter") selectDetail(p.account_id); } }, cells);
  });
  return h("div", { class: "table-wrap" }, h("table", {},
    h("caption", {}, hasActual ? "Erro = previsto − real. Em azul, quem errou menos em cada conta." : "Valores em coroas tchecas (Kč)."),
    h("thead", {}, h("tr", {}, head.map((t) => h("th", { scope: "col" }, t)))),
    h("tbody", {}, rows)));
}

function selectDetail(id) {
  if (id === state.detailId) return;
  state.detailId = id;
  renderResults();
  document.getElementById("detail")?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
}

/* ---------- detalhe da conta ---------- */
function detailCard(p) {
  const info = state.selected.get(p.account_id);
  const tags = info ? [info.district_name, info.region, info.owner_gender ? GENDER[info.owner_gender] : null, FREQ[info.frequency] ?? info.frequency, info.has_loan ? "Com empréstimo" : null, info.has_card ? "Com cartão" : null, info.dependent_count ? `${info.dependent_count} dependente` : null].filter(Boolean) : [];
  const top = new Set([...state.model.features].filter((f) => f.importance != null).sort((a, b) => b.importance - a.importance).slice(0, 5).map((f) => f.name));
  const groups = new Map();
  for (const f of state.model.features) { if (!groups.has(f.group)) groups.set(f.group, []); groups.get(f.group).push(f); }
  const featBlocks = [...groups].map(([g, list]) => h("div", { class: "feat-group" }, h("h5", {}, g),
    list.map((f) => {
      const v = p.features?.[f.name];
      return h("div", { class: `feat${top.has(f.name) ? " hot" : ""}`, title: f.help }, h("span", { class: "l" }, f.label), h("span", { class: "dots" }), h("span", { class: `v${v == null ? " na" : ""}` }, formatFeature(f.unit, v)));
    })));
  const chartBox = h("div", { class: "chart", id: "chart-line" }, h("p", { class: "loading-line" }, "Carregando histórico…"));
  return h("div", { class: "card reveal", id: "detail", style: { "--d": 2 } },
    h("div", { class: "detail-head" },
      h("div", {}, h("p", { class: "eyebrow" }, "Detalhe da conta"), h("h3", { style: { marginTop: "8px", fontSize: "1.5rem" } }, `Conta ${p.account_id}`),
        h("div", { class: "tags" }, tags.map((t) => h("span", { class: "tag" }, t)))),
      splitBadge(p, monthInfo())),
    h("div", { class: "detail-grid" },
      h("div", {}, h("h4", {}, "Saídas nos últimos 12 meses"), chartBox,
        h("div", { class: "legend" }, h("span", {}, h("i", { class: "line", style: { borderColor: "var(--ink-2)" } }), "Saídas do mês"), h("span", {}, h("i", { class: "ring hollow" }), "Previsto"), p.actual_next_month_outflow != null ? h("span", {}, h("i", { class: "ring s-real" }), "Real") : null),
        detailNote(p)),
      h("div", {}, h("h4", {}, `O que o modelo viu em ${monthLabel(p.features_as_of)}`),
        state.model.features.some((f) => f.importance != null) ? h("p", { class: "note", style: { margin: "-4px 0 12px" } }, "Em azul, as 5 informações de maior peso no modelo (importância média em todas as contas, não uma explicação desta previsão).") : null,
        featBlocks)));
}
function detailNote(p) {
  if (p.actual_next_month_outflow == null) return h("div", { class: "formula" }, `O modelo prevê ${money(p.predicted_next_month_outflow)} de saídas em ${monthLabel(p.target_month)}. Como esse mês ainda não está no dataset, não há valor real para comparar.`);
  const e = p.predicted_next_month_outflow - p.actual_next_month_outflow;
  const b = p.baseline_next_month_outflow;
  const eb = b == null ? null : b - p.actual_next_month_outflow;
  const words = e === 0 ? "acertou em cheio" : e > 0 ? `superestimou em ${money(e)}` : `subestimou em ${money(-e)}`;
  const vs = eb == null ? "" : Math.abs(e) < Math.abs(eb) ? ` A média de 3 meses errou mais (${money(Math.abs(eb))}).` : ` Aqui a média de 3 meses errou menos (${money(Math.abs(eb))}).`;
  return h("div", { class: "formula" }, `Em ${monthLabel(p.target_month)} a conta gastou ${money(p.actual_next_month_outflow)}. O modelo previu ${money(p.predicted_next_month_outflow)}: ${words}.${vs}`);
}
function formatFeature(unit, v) {
  if (v == null) return "sem dado";
  if (unit === "pct") return signedPct(v, 1);
  if (unit === "count") return one(v).replace(/,0$/, "");
  return money(v);
}
async function loadHistory(p) {
  const key = `${p.account_id}|${p.features_as_of}`;
  const draw = (hist) => {
    const box = $("#chart-line");
    if (!box || state.detailId !== p.account_id) return;
    clear(box);
    lineChart(box, { points: hist.points, target: p.target_month, predicted: p.predicted_next_month_outflow, actual: p.actual_next_month_outflow });
  };
  if (state.history.has(key)) return draw(state.history.get(key));
  try {
    const hist = await get(`/api/accounts/${encodeURIComponent(p.account_id)}/history?reference_month=${p.features_as_of}`);
    state.history.set(key, hist);
    draw(hist);
  } catch (e) {
    const box = $("#chart-line");
    if (box) box.replaceChildren(h("p", { class: "loading-line" }, `Histórico indisponível: ${e.message}`));
  }
}

/* ---------- desempenho no teste inteiro ---------- */
let scatterKey = "predicted";
function renderOverall(report) {
  state.report = report;
  if (state.response) renderResults();
  const sec = $("#overall");
  sec.hidden = false;
  const win = report.window.match(/(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})/);
  $("#overall-lede").textContent = `Duas ou três contas não provam nada: o ganho do modelo é médio. Aqui estão todas as ${num(report.n_rows)} contas-mês de ${win ? `${monthLabel(win[1])} a ${monthLabel(win[2])}` : "teste"}, meses que o modelo não viu no treino, recalculados agora com o modelo carregado.`;
  const body = $("#overall-body");
  clear(body);
  const scatterBox = h("div", { class: "chart", id: "chart-scatter" });
  const scatterNote = h("p", { class: "note" });
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Preditor exibido" });
  const setKey = (k) => {
    scatterKey = k;
    [...seg.children].forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.k === k)));
    clear(scatterBox);
    scatterChart(scatterBox, { points: report.points, key: k, axisMax: report.axis_max, onCount: (n, total) => { scatterNote.textContent = `Amostra de ${num(total)} contas-mês (${num(n)} dentro dos eixos, até o percentil 99 do valor real). Quanto mais perto da diagonal, melhor; a faixa azul marca ±20% do real.`; } });
  };
  seg.append(h("button", { type: "button", "data-k": "predicted", "aria-pressed": "true", onClick: () => setKey("predicted") }, "Modelo"), h("button", { type: "button", "data-k": "baseline", "aria-pressed": "false", onClick: () => setKey("baseline") }, "Média de 3 meses"));
  const mae = report.model.mae, bmae = report.baseline.mae;
  body.append(
    h("div", { class: "kpis", style: { marginTop: "22px" } },
      kpi("Erro médio (MAE)", money(mae), `${pct(1 - mae / bmae)} menor que a média de 3 meses (${money(bmae)})`, mae < bmae),
      kpi("Previsões a até 20% do real", pct(report.within_20_model), `contra ${pct(report.within_20_baseline)} da média de 3 meses`, report.within_20_model > report.within_20_baseline),
      kpi("Contas-mês em que erra menos", pct(report.win_rate), "que a média de 3 meses, no teste inteiro", report.win_rate > 0.5)),
    h("div", { class: "two" },
      h("div", { class: "card" }, h("h3", {}, "Previsto × real no teste"), h("p", { class: "sub" }, "Cada ponto é uma conta em um mês."), seg, scatterBox, scatterNote),
      h("div", { class: "card" }, h("h3", {}, "Erro médio por mês de teste"), h("p", { class: "sub" }, "O modelo erra menos em todos os meses?"),
        h("div", { class: "chart", id: "chart-months", style: { marginTop: "14px" } }),
        h("div", { class: "legend" }, h("span", {}, h("i", { class: "s-pred" }), "Modelo"), h("span", {}, h("i", { class: "s-base" }), "Média de 3 meses")),
        monthTable(report.by_month),
        h("p", { class: "note" }, "Ainda assim, o R² de ", h("b", {}, report.model.r2.toFixed(2).replace(".", ",")), " indica que uma parte grande da variação mensal das saídas não é explicada: o modelo melhora a regra simples, não a substitui por uma bola de cristal."))));
  setKey(scatterKey);
  monthBars($("#chart-months"), report.by_month);
  const tile = $("#tile-win");
  if (tile) { tile.replaceChildren(pct(report.win_rate)); $("#tile-win-n").textContent = `de ${num(report.n_rows)} no teste inteiro`; }
}
function monthTable(rows) {
  return h("div", { class: "table-wrap" }, h("table", {},
    h("caption", {}, "Mesmos valores do gráfico, em Kč."),
    h("thead", {}, h("tr", {}, ["Mês", "Modelo", "Média de 3 meses", "Contas"].map((t) => h("th", { scope: "col" }, t)))),
    h("tbody", {}, rows.map((r) => h("tr", { style: { cursor: "default" } }, h("td", {}, monthLabel(r.month)), h("td", {}, num(r.model_mae)), h("td", {}, num(r.baseline_mae)), h("td", {}, num(r.n)))))));
}
async function pollEvaluation(tries = 0) {
  try {
    const r = await get("/api/evaluation");
    if (r.ready) return renderOverall(r.report);
  } catch { /* tenta de novo */ }
  if (tries < 40) setTimeout(() => pollEvaluation(tries + 1), 1500);
}

/* ---------- inicialização ---------- */
async function init() {
  renderResults();
  try {
    [state.model, state.months] = await Promise.all([get("/api/model"), get("/api/months")]);
  } catch (e) {
    $("#hero-eyebrow").textContent = "Modelo indisponível";
    $("#hero-title").textContent = e.status === 503 ? "Nenhum modelo campeão registrado ainda" : "Não foi possível carregar a API";
    $("#hero-lede").textContent = e.status === 503 ? "Rode o treino e o gate de promoção (make train e make promote) e recarregue a página." : e.message;
    return;
  }
  renderModel();
  // ponto de partida: o mês de teste mais recente, onde há valor real e o modelo nunca viu os dados
  const testMonth = state.months.find((m) => m.split === "teste");
  state.monthKey = testMonth?.reference_month ?? "latest";
  renderPicker();
  await loadAccounts(true);
  pollEvaluation();
  await sampleAccounts();
}
init();
