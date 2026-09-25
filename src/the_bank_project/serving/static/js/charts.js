// Gráficos em SVG puro (sem dependências), seguindo as regras de dataviz: marcas finas, grade recessiva,
// vão de 2px entre barras, legenda sempre presente, tooltip que enriquece mas nunca é a única via
// (todos os valores também estão nas tabelas ao lado).

import { clear, h, monthLabel, monthShort, money, moneyShort, niceTicks, num, pct, scale, signed, svg } from "./util.js";

/* ---------- tooltip único ---------- */
const tipEl = h("div", { class: "tip", role: "presentation" });
document.body.append(tipEl);
export const tip = {
  show(x, y, title, rows = [], foot) {
    clear(tipEl);
    if (title) tipEl.append(h("div", { class: "t" }, title));
    for (const r of rows) {
      tipEl.append(
        h("div", { class: "r" },
          h("span", {}, r.color ? h("i", { style: { borderColor: r.color } }) : null, r.label),
          h("b", {}, r.value)),
      );
    }
    if (foot) tipEl.append(h("div", { class: "foot" }, foot));
    tipEl.classList.add("on");
    const w = tipEl.offsetWidth, hh = tipEl.offsetHeight;
    const left = Math.min(Math.max(8, x + 16), window.innerWidth - w - 8);
    const top = y - hh - 14 < 8 ? y + 18 : y - hh - 14;
    tipEl.style.left = `${left}px`;
    tipEl.style.top = `${top}px`;
  },
  hide() { tipEl.classList.remove("on"); },
};

/** Redesenha `draw(width)` sempre que o contêiner muda de largura. */
export function mount(container, draw) {
  let last = 0;
  const run = () => {
    const w = Math.max(280, Math.round(container.clientWidth));
    if (w === last) return;
    last = w;
    clear(container);
    container.append(draw(w));
  };
  run();
  const ro = new ResizeObserver(() => run());
  ro.observe(container);
  return () => ro.disconnect();
}

const V = (name) => `var(--${name})`;
const roundedTop = (x, y, w, hgt, r = 4) => {
  const rr = Math.min(r, w / 2, Math.max(hgt, 0));
  if (hgt <= 0) return `M${x},${y}h${w}`;
  return `M${x},${y + hgt}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + hgt}Z`;
};

function yAxis(g, ticks, y, left, right, fmt = moneyShort) {
  for (const t of ticks) {
    g.append(svg("g", { class: t === 0 ? "axis" : "grid" }, svg("line", { x1: left, x2: right, y1: y(t), y2: y(t), class: t === 0 ? "base" : "" })));
    g.append(svg("text", { x: left - 10, y: y(t) + 4, "text-anchor": "end" }, fmt(t)));
  }
}

/* ---------- barras agrupadas: real x previsto (+ média de 3 meses) por conta ---------- */
export function barsChart(container, groups, { selected, onSelect, hasActual }) {
  return mount(container, (W) => {
    const H = 310, m = { t: 14, r: 10, b: 50, l: 52 };
    const max = Math.max(1, ...groups.flatMap((g) => [g.predicted, g.actual ?? 0, g.baseline ?? 0]));
    const { top, ticks } = niceTicks(max * 1.05);
    const y = scale(0, top, H - m.b, m.t);
    const band = (W - m.l - m.r) / groups.length;
    const bw = Math.max(8, Math.min(38, band * (hasActual ? 0.27 : 0.42)));
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Valor previsto e valor real por conta" });
    yAxis(root, ticks, y, m.l, W - m.r);
    groups.forEach((g, i) => {
      const cx = m.l + band * (i + 0.5);
      const gw = hasActual ? bw * 2 + 2 : bw;
      const x0 = cx - gw / 2;
      const on = g.id === selected;
      const hit = svg("rect", {
        x: m.l + band * i + 2, y: m.t, width: band - 4, height: H - m.b - m.t + 30, rx: 8, class: `hit${on ? " on" : ""}`,
        tabindex: 0, role: "button", "aria-label": `Conta ${g.id}: previsto ${num(g.predicted)}${g.actual != null ? `, real ${num(g.actual)}` : ""}`,
      });
      const rows = [{ label: "Previsto", value: money(g.predicted), color: "var(--series-1)" }];
      if (g.actual != null) rows.push({ label: "Real", value: money(g.actual), color: "var(--series-2)" });
      if (g.baseline != null) rows.push({ label: "Média de 3 meses", value: money(g.baseline), color: "var(--baseline)" });
      const foot = g.actual != null ? `Erro do modelo: ${signed(g.predicted - g.actual)} Kč` : "Ainda sem valor real";
      const show = (e) => tip.show(e.clientX, e.clientY, `Conta ${g.id}`, rows, foot);
      hit.addEventListener("pointermove", show);
      hit.addEventListener("pointerleave", () => tip.hide());
      hit.addEventListener("focus", () => { const r = hit.getBoundingClientRect(); tip.show(r.left + r.width / 2, r.top + 20, `Conta ${g.id}`, rows, foot); });
      hit.addEventListener("blur", () => tip.hide());
      hit.addEventListener("click", () => onSelect(g.id));
      hit.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(g.id); } });
      root.append(hit);
      root.append(svg("path", { d: roundedTop(x0, y(g.predicted), bw, y(0) - y(g.predicted)), class: "bar s-pred", style: { "--i": i } }));
      if (g.actual != null) root.append(svg("path", { d: roundedTop(x0 + bw + 2, y(g.actual), bw, y(0) - y(g.actual)), class: "bar s-real", style: { "--i": i } }));
      if (g.baseline != null) {
        root.append(svg("line", { x1: x0 - 5, x2: x0 + gw + 5, y1: y(g.baseline), y2: y(g.baseline), stroke: V("baseline"), "stroke-width": 3, "stroke-linecap": "round", "pointer-events": "none" }));
      }
      root.append(svg("text", { x: cx, y: H - m.b + 20, "text-anchor": "middle", class: on ? "lbl" : "" }, band < 62 ? String(g.id) : `Conta ${g.id}`));
    });
    return root;
  });
}

/* ---------- linha: histórico de saídas + previsto e real do mês seguinte ---------- */
export function lineChart(container, { points, target, predicted, actual }) {
  return mount(container, (W) => {
    const H = 290, m = { t: 22, r: 92, b: 34, l: 52 };
    const series = points.filter((p) => p.outflow != null);
    const max = Math.max(1, ...series.map((p) => p.outflow), predicted ?? 0, actual ?? 0);
    const { top, ticks } = niceTicks(max * 1.08);
    const n = points.length + 1;
    const x = (i) => m.l + ((W - m.l - m.r) * i) / (n - 1);
    const y = scale(0, top, H - m.b, m.t);
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Saídas mensais recentes e previsão do mês seguinte" });
    yAxis(root, ticks, y, m.l, W - m.r);
    // faixa do mês previsto
    root.append(svg("rect", { x: x(n - 1) - 20, y: m.t - 8, width: 40, height: H - m.b - m.t + 8, rx: 8, fill: V("tint-1"), opacity: 0.6 }));
    root.append(svg("text", { x: x(n - 1), y: m.t - 12, "text-anchor": "middle", class: "lbl-soft" }, "previsto"));
    const step = Math.ceil(n / 7);
    points.forEach((p, i) => { if ((points.length - i) % step === 0) root.append(svg("text", { x: x(i), y: H - m.b + 20, "text-anchor": "middle" }, monthShort(p.month))); });
    root.append(svg("text", { x: x(n - 1), y: H - m.b + 20, "text-anchor": "middle", class: "lbl" }, monthShort(target)));
    const path = series.map((p, k) => `${k ? "L" : "M"}${x(points.indexOf(p))},${y(p.outflow)}`).join("");
    root.append(svg("path", { d: path, fill: "none", stroke: V("ink-2"), "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const last = series[series.length - 1];
    if (last && predicted != null) {
      root.append(svg("line", { x1: x(points.indexOf(last)), y1: y(last.outflow), x2: x(n - 1), y2: y(predicted), stroke: V("series-1"), "stroke-width": 2, "stroke-dasharray": "5 5", opacity: 0.8 }));
    }
    for (const p of series) root.append(svg("circle", { cx: x(points.indexOf(p)), cy: y(p.outflow), r: 3.2, fill: V("ink-2"), stroke: V("surface"), "stroke-width": 2 }));
    // real (cheio, laranja) por baixo e previsto (anel azul) por cima: continuam visíveis mesmo quando coincidem
    const labels = [];
    if (actual != null) labels.push({ v: actual, name: "Real", color: V("ink") });
    if (predicted != null) labels.push({ v: predicted, name: "Previsto", color: V("series-1") });
    if (actual != null) root.append(svg("circle", { cx: x(n - 1), cy: y(actual), r: 5.5, class: "s-real", stroke: V("surface"), "stroke-width": 2 }));
    if (predicted != null) root.append(svg("circle", { cx: x(n - 1), cy: y(predicted), r: 9, fill: "none", stroke: V("series-1"), "stroke-width": 3 }));
    labels.sort((a, b) => b.v - a.v);
    labels.forEach((l, k) => {
      const above = labels.length === 1 || k === 0;
      root.append(svg("text", { x: x(n - 1) + 18, y: y(l.v) + (above ? -3 : 13), class: "lbl", style: { fill: l.color } }, `${l.name} ${num(l.v)}`));
    });
    // cruzeta com tooltip
    const guide = svg("line", { y1: m.t, y2: H - m.b, stroke: V("ink-3"), "stroke-width": 1, opacity: 0 });
    root.append(guide);
    const hit = svg("rect", { x: m.l - 8, y: m.t - 8, width: W - m.l - m.r + 16 + 40, height: H - m.t - m.b + 16, fill: "transparent", tabindex: 0, role: "img", "aria-label": "Passe o mouse para ver cada mês" });
    const near = (clientX) => {
      const r = root.getBoundingClientRect();
      const px = ((clientX - r.left) / r.width) * W;
      return Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / (W - m.l - m.r)) * (n - 1))));
    };
    hit.addEventListener("pointermove", (e) => {
      const i = near(e.clientX);
      guide.setAttribute("x1", x(i)); guide.setAttribute("x2", x(i)); guide.setAttribute("opacity", 0.5);
      if (i === n - 1) {
        const rows = [];
        if (predicted != null) rows.push({ label: "Previsto", value: money(predicted), color: "var(--series-1)" });
        if (actual != null) rows.push({ label: "Real", value: money(actual), color: "var(--series-2)" });
        tip.show(e.clientX, e.clientY, monthLabel(target), rows, "Mês previsto");
      } else {
        const p = points[i];
        tip.show(e.clientX, e.clientY, monthLabel(p.month), [
          { label: "Saídas", value: money(p.outflow), color: "var(--ink-2)" },
          { label: "Entradas", value: money(p.inflow) },
          { label: "Saldo final", value: money(p.closing_balance) },
        ]);
      }
    });
    hit.addEventListener("pointerleave", () => { guide.setAttribute("opacity", 0); tip.hide(); });
    root.append(hit);
    return root;
  });
}

/* ---------- barras horizontais: erro médio por modelo ---------- */
export function hbarChart(container, rows) {
  return mount(container, (W) => {
    const rowH = 38, m = { t: 4, r: 78, b: 4, l: Math.min(160, W * 0.36) };
    const H = rows.length * rowH + m.t + m.b;
    const max = Math.max(...rows.map((r) => r.value));
    const x = scale(0, max, 0, W - m.l - m.r);
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Erro médio no teste por modelo" });
    rows.forEach((r, i) => {
      const cy = m.t + i * rowH + rowH / 2;
      const cls = r.champion ? "s-pred" : r.kind === "baseline" ? "s-base" : "s-gray";
      root.append(svg("text", { x: m.l - 12, y: cy + 4, "text-anchor": "end", class: r.champion ? "lbl" : "" }, r.label));
      root.append(svg("rect", { x: m.l, y: cy - 8, width: Math.max(2, x(r.value)), height: 16, rx: 4, class: `hbar ${cls}`, style: { "--i": i } }));
      root.append(svg("text", { x: m.l + x(r.value) + 8, y: cy + 4, class: r.champion ? "lbl" : "lbl-soft" }, num(r.value)));
    });
    return root;
  });
}

/* ---------- dispersão: previsto x real no teste inteiro ---------- */
export function scatterChart(container, { points, key, axisMax, onCount }) {
  return mount(container, (W) => {
    const size = Math.min(W, 560), H = size + 4, m = { t: 12, r: 14, b: 46, l: 58 };
    const { top, ticks } = niceTicks(axisMax, 4);
    const x = scale(0, top, m.l, size - m.r), y = scale(0, top, H - m.b, m.t);
    const root = svg("svg", { viewBox: `0 0 ${size} ${H}`, role: "img", "aria-label": "Valor previsto contra valor real no conjunto de teste", style: { maxWidth: `${size}px`, margin: "0 auto" } });
    yAxis(root, ticks, y, m.l, size - m.r);
    for (const t of ticks) if (t) root.append(svg("text", { x: x(t), y: H - m.b + 18, "text-anchor": "middle" }, moneyShort(t)));
    root.append(svg("polygon", { points: `${x(0)},${y(0)} ${x(top)},${y(top * 0.8)} ${x(top)},${y(Math.min(top, top * 1.2))}`, fill: V("tint-1"), opacity: 0.55 }));
    root.append(svg("line", { class: "diag", x1: x(0), y1: y(0), x2: x(top), y2: y(top) }));
    root.append(svg("text", { x: (m.l + size - m.r) / 2, y: H - 6, "text-anchor": "middle" }, "Valor real do mês seguinte (Kč)"));
    root.append(svg("text", { transform: `translate(14 ${(m.t + H - m.b) / 2}) rotate(-90)`, "text-anchor": "middle" }, "Valor previsto (Kč)"));
    const inside = points.filter((p) => p.actual <= top && p[key] <= top);
    onCount?.(inside.length, points.length);
    const g = svg("g", { class: `dots-sc ${key === "predicted" ? "pred" : "base"}` });
    const circles = inside.map((p) => svg("circle", { cx: x(p.actual), cy: y(p[key]), r: 2.7 }));
    g.append(...circles);
    root.append(g);
    root.addEventListener("pointermove", (e) => {
      const r = root.getBoundingClientRect();
      const px = ((e.clientX - r.left) / r.width) * size, py = ((e.clientY - r.top) / r.height) * H;
      let best = -1, bd = 22 * 22;
      inside.forEach((p, i) => { const d = (x(p.actual) - px) ** 2 + (y(p[key]) - py) ** 2; if (d < bd) { bd = d; best = i; } });
      circles.forEach((c) => c.classList.remove("hot"));
      if (best < 0) return tip.hide();
      circles[best].classList.add("hot");
      const p = inside[best];
      tip.show(e.clientX, e.clientY, "Uma conta em um mês de teste", [
        { label: "Real", value: money(p.actual), color: "var(--series-2)" },
        { label: key === "predicted" ? "Previsto" : "Média de 3 meses", value: money(p[key]), color: key === "predicted" ? "var(--series-1)" : "var(--baseline)" },
      ], `Erro: ${signed(p[key] - p.actual)} Kč`);
    });
    root.addEventListener("pointerleave", () => { circles.forEach((c) => c.classList.remove("hot")); tip.hide(); });
    return root;
  });
}

/* ---------- barras por mês de teste: modelo x média de 3 meses ---------- */
export function monthBars(container, months) {
  return mount(container, (W) => {
    const H = 270, m = { t: 22, r: 10, b: 34, l: 52 };
    const max = Math.max(...months.flatMap((r) => [r.model_mae, r.baseline_mae]));
    const { top, ticks } = niceTicks(max * 1.05);
    const y = scale(0, top, H - m.b, m.t);
    const band = (W - m.l - m.r) / months.length;
    const bw = Math.max(10, Math.min(46, band * 0.3));
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Erro médio por mês de teste" });
    yAxis(root, ticks, y, m.l, W - m.r);
    months.forEach((r, i) => {
      const cx = m.l + band * (i + 0.5), x0 = cx - bw - 1;
      root.append(svg("path", { d: roundedTop(x0, y(r.model_mae), bw, y(0) - y(r.model_mae)), class: "bar s-pred", style: { "--i": i } }));
      root.append(svg("path", { d: roundedTop(x0 + bw + 2, y(r.baseline_mae), bw, y(0) - y(r.baseline_mae)), class: "bar s-base", style: { "--i": i } }));
      root.append(svg("text", { x: x0 + bw / 2, y: y(r.model_mae) - 6, "text-anchor": "middle", class: "lbl" }, num(r.model_mae)));
      root.append(svg("text", { x: x0 + bw * 1.5 + 2, y: y(r.baseline_mae) - 6, "text-anchor": "middle", class: "lbl-soft" }, num(r.baseline_mae)));
      root.append(svg("text", { x: cx, y: H - m.b + 20, "text-anchor": "middle" }, monthLabel(r.month)));
      const hit = svg("rect", { x: m.l + band * i + 2, y: m.t, width: band - 4, height: H - m.b - m.t, class: "hit", tabindex: 0, "aria-label": `${monthLabel(r.month)}: modelo ${num(r.model_mae)}, média de 3 meses ${num(r.baseline_mae)}` });
      const rows = [{ label: "Modelo", value: money(r.model_mae), color: "var(--series-1)" }, { label: "Média de 3 meses", value: money(r.baseline_mae), color: "var(--baseline)" }];
      const foot = `${pct(1 - r.model_mae / r.baseline_mae)} menos erro · ${num(r.n)} contas`;
      hit.addEventListener("pointermove", (e) => tip.show(e.clientX, e.clientY, monthLabel(r.month), rows, foot));
      hit.addEventListener("pointerleave", () => tip.hide());
      root.append(hit);
    });
    return root;
  });
}
