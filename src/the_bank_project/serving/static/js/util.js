// Utilitários: construção segura de DOM (textContent, nunca innerHTML) e formatação pt-BR.

const SVG_NS = "http://www.w3.org/2000/svg";

/** Cria um elemento. `svg:tag` cria no namespace SVG. Textos entram como nós de texto (sem HTML). */
export function h(tag, props = {}, ...kids) {
  const el = tag.startsWith("svg:") ? document.createElementNS(SVG_NS, tag.slice(4)) : document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export const svg = (tag, props, ...kids) => h(`svg:${tag}`, props, ...kids);
export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
export const $ = (sel, root = document) => root.querySelector(sel);

const int = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const dec1 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const compact = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });

export const num = (v) => (v == null || Number.isNaN(v) ? "—" : int.format(v));
export const money = (v) => (v == null || Number.isNaN(v) ? "—" : `${int.format(v)} Kč`);
export const moneyShort = (v) => (v == null ? "—" : compact.format(v));
export const signed = (v) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${int.format(Math.abs(v))}`);
export const pct = (v, digits = 0) =>
  v == null || !Number.isFinite(v) ? "—" : `${new Intl.NumberFormat("pt-BR", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(v * 100)}%`;
export const signedPct = (v, digits = 0) =>
  v == null || !Number.isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${pct(Math.abs(v), digits)}`;
export const one = (v) => dec1.format(v);

const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const MONTHS_LONG = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
/** 'YYYY-MM-DD' -> partes, sem passar por Date (evita deslocamento de fuso). */
const parts = (iso) => { const [y, m] = iso.split("-").map(Number); return { y, m }; };
export const monthLabel = (iso) => { const { y, m } = parts(iso); return `${MONTHS[m - 1]}/${y}`; };
export const monthShort = (iso) => { const { y, m } = parts(iso); return `${MONTHS[m - 1]}/${String(y).slice(2)}`; };
export const monthLong = (iso) => { const { y, m } = parts(iso); return `${MONTHS_LONG[m - 1]} de ${y}`; };

/** Escala linear simples. */
export const scale = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);

/** Teto "bonito" e marcas de eixo a partir de um máximo. */
export function niceTicks(max, count = 4) {
  if (!(max > 0)) return { top: 1, ticks: [0, 1] };
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 1.5, 2, 2.5, 3, 4, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const top = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = 0; v <= top + step / 1e6; v += step) ticks.push(v);
  return { top, ticks };
}

export const GENDER = { F: "Titular feminina", M: "Titular masculino" };
export const FREQ = { MENSAL: "Extrato mensal", SEMANAL: "Extrato semanal", POR_TRANSACAO: "Extrato por transação" };
