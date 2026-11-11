// Shared pieces for every screen: Python bridge, icons, top bar, dialogs, formatting.
import { h } from "./vendor/preact.mjs";
import { useEffect, useRef, useState } from "./vendor/hooks.mjs";
import htm from "./vendor/htm.mjs";
import { getLang, t } from "./i18n.js";

export { t };

export const html = htm.bind(h);

// ---------- Python bridge ----------
// pywebview first creates `window.pywebview.api` as an EMPTY object and only adds the Python
// functions later (then fires "pywebviewready"). Checking that `api` exists is not enough: if the
// page runs in between, the first call isn't a function yet and the app stays blank. So wait until
// a real function is there — via the event, with polling as a fallback in case the event was missed.
const bridgeReady = () => !!(window.pywebview && window.pywebview.api && typeof window.pywebview.api.app_info === "function");
const ready = new Promise((resolve) => {
  if (bridgeReady()) return resolve();
  const done = () => { if (bridgeReady()) { clearInterval(poll); window.removeEventListener("pywebviewready", done); resolve(); } };
  const poll = setInterval(done, 50);
  window.addEventListener("pywebviewready", done);
});
export const api = new Proxy({}, {
  get: (_, name) => async (...args) => { await ready; return window.pywebview.api[name](...args); },
});

/** For calls that are safe to repeat (reading the client list, app info): if the answer doesn't come
 * back in time (on macOS a call is very occasionally lost), ask again instead of leaving the screen empty. */
export async function ask(name, ...args) {
  for (let attempt = 1; ; attempt++) {
    const timeout = new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 6000 * attempt));
    try {
      return await Promise.race([api[name](...args), timeout]);
    } catch (e) {
      if (String(e.message) !== "timeout" || attempt >= 3) throw e;
      api.log_ui(`${name}() didn't answer in ${6 * attempt}s; asking again`).catch(() => {});
    }
  }
}

/** Subscribe to a push from Python (api._emit). */
export function usePy(event, fn, deps = []) {
  useEffect(() => {
    const handler = (e) => { if (e.detail && e.detail.event === event) fn(e.detail.data); };
    window.addEventListener("py", handler);
    return () => window.removeEventListener("py", handler);
  }, deps);
}

// What the user is looking at (offered in feedback).
export const ctx = { screen: "Home", folder: null };

// ---------- Icons (vector: crisp at any size) ----------
const paths = {
  folder: html`<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>`,
  chat: html`<path d="M5 5h14a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-8l-4 4v-4H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/>`,
  gear: html`<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>`,
  back: html`<path d="M19 12H5M11 18l-6-6 6-6"/>`,
  left: html`<path d="M15 18l-6-6 6-6"/>`,
  right: html`<path d="M9 18l6-6-6-6"/>`,
  down: html`<path d="M6 9l6 6 6-6"/>`,
  up: html`<path d="M18 15l-6-6-6 6"/>`,
  check: html`<path d="M20 6L9 17l-5-5"/>`,
  plus: html`<path d="M12 5v14M5 12h14"/>`,
  minus: html`<path d="M5 12h14"/>`,
  external: html`<path d="M7 17L17 7M9 7h8v8"/>`,
  file: html`<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M12 11v6M9 14h6"/>`,
  copy: html`<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>`,
  camera: html`<path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/>`,
  x: html`<path d="M18 6L6 18M6 6l12 12"/>`,
  fit: html`<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>`,
};
export const Icon = ({ name, size = 16, stroke }) =>
  html`<svg class="icon-svg" viewBox="0 0 24 24" style=${{ width: size, height: size, strokeWidth: stroke }}>${paths[name]}</svg>`;

/** File status in the review list: filled tick, outline circle, amber "!", red "×", dashed while reading. */
export function StatusDot({ state }) {
  if (state === "confirmed" || state === "renamed")
    return html`<span class="dot ok"><${Icon} name="check" size=${11} stroke=${3} /></span>`;
  if (state === "warning") return html`<span class="dot warn">!</span>`;
  if (state === "error") return html`<span class="dot err">×</span>`;
  if (state === "duplicate") return html`<span class="dot dup">=</span>`;
  if (state === "reading") return html`<span class="dot reading"></span>`;
  return html`<span class="dot ready"></span>`;
}

// ---------- Formatting ----------
/** 1.234,56 in Portuguese (as accountants write it), 1,234.56 in English. */
export const money = (v) => {
  if (v === null || v === undefined || v === "" || isNaN(Number(v))) return v ?? "";
  const en = Number(v).toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return getLang() === "pt" ? en.replace(/,/g, "X").replace(/\./g, ",").replace(/X/g, ".") : en;
};
export const plain2 = (v) => (v === null || v === undefined || v === "" || isNaN(Number(v))) ? (v ?? "") : Number(v).toFixed(2);
const MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
export const niceDate = (iso, alwaysYear = false) => {
  if (!iso) return "";
  const d = new Date(String(iso).slice(0, 10) + "T00:00:00");
  if (isNaN(d)) return iso;
  const s = `${d.getDate()} ${(getLang() === "pt" ? MONTHS_PT : MONTHS_EN)[d.getMonth()]}`;
  return !alwaysYear && d.getFullYear() === new Date().getFullYear() ? s : `${s} ${d.getFullYear()}`;
};
/** tn(3, "{n} file renamed", "{n} files renamed") → "3 ficheiros renomeados" (one/many sentence, translated). */
export const tn = (n, one, many, vars = {}) =>
  t(n === 1 ? one : many, { ...vars, n: Number(n).toLocaleString(getLang() === "pt" ? "pt-PT" : "en") });
export const plural = (n, word, many) => `${Number(n).toLocaleString(getLang() === "pt" ? "pt-PT" : "en")} ${t(n === 1 ? word : (many || word + "s"))}`;

// ---------- Top bar ----------
export function TopBar({ onBack, title, sub, children, progress }) {
  return html`
    <div class="topbar">
      ${onBack && html`<button class="btn icon" title=${t("Back")} onClick=${onBack}><${Icon} name="back" /></button>`}
      <div class="bar-title">
        <b>${title}</b>
        ${progress != null && html`<div class="progress-row"><div class="bar"><div style=${{ width: `${Math.round(progress * 100)}%` }}></div></div><small>${sub}</small></div>`}
        ${progress == null && sub && html`<small>${sub}</small>`}
      </div>
      ${children}
    </div>`;
}

export const FeedbackButton = () =>
  html`<button class="btn icon" title=${t("Send feedback")} onClick=${() => window.dispatchEvent(new Event("open-feedback"))}><${Icon} name="chat" /></button>`;

// ---------- Dialogs ----------
export function Modal({ children, onClose, width = 480 }) {
  useEffect(() => {
    const key = (e) => { if (e.key === "Escape" && onClose) onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
  return html`
    <div class="overlay" onMouseDown=${(e) => { if (e.target === e.currentTarget && onClose) onClose(); }}>
      <div class="modal" style=${{ width }}>${children}</div>
    </div>`;
}

let confirmSetter = null;
/** await confirmBox({title, text, ok, danger}) → true/false */
export function confirmBox(opts) {
  return new Promise((resolve) => confirmSetter && confirmSetter({ ...opts, resolve }));
}
let toastSetter = null;
export function toast(text, kind = "info") { toastSetter && toastSetter({ text, kind, id: Math.random() }); }

export function GlobalLayers() {
  const [c, setC] = useState(null);
  const [t, setT] = useState(null);
  confirmSetter = setC;
  toastSetter = setT;
  useEffect(() => {
    if (!t) return;
    api.log_ui(`popup (${t.kind}): ${JSON.stringify(t.text)} on ${ctx.screen}`).catch(() => {});
    const id = setTimeout(() => setT(null), 4200); return () => clearTimeout(id);
  }, [t]);
  const close = (v) => { c.resolve(v); setC(null); };
  return html`
    ${c && html`<${Modal} onClose=${() => close(false)} width=${440}>
      <h2>${c.title}</h2>
      ${c.text && html`<p class="muted pre">${c.text}</p>`}
      <div class="actions">
        ${c.cancel !== false && html`<button class="btn" onClick=${() => close(false)}>${c.cancel || t("Cancel")}</button>`}
        <button class=${"btn solid" + (c.danger ? " danger" : "")} onClick=${() => close(true)} autofocus>${c.ok || t("OK")}</button>
      </div>
    <//>`}
    ${t && html`<div key=${t.id} class=${"toast " + t.kind}>${t.text}</div>`}`;
}

/** A dropdown menu (custom, so it looks the same on Mac and Windows). */
export function Menu({ value, options, onChange, width = 230, label }) {
  const [open, setOpen] = useState(false);
  const ref = useRef();
  useEffect(() => {
    if (!open) return;
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    window.addEventListener("mousedown", away);
    return () => window.removeEventListener("mousedown", away);
  }, [open]);
  const current = options.find((o) => o.value === value);
  return html`
    <div class="menu" ref=${ref} style=${{ width }}>
      <button class="menu-btn" onClick=${() => setOpen(!open)}>
        <span>${label || (current ? current.label : "")}</span><${Icon} name="down" size=${14} />
      </button>
      ${open && html`<div class="menu-list">
        ${options.map((o) => html`<div class=${"menu-item" + (o.value === value ? " on" : "") + (o.sep ? " sep" : "")}
            onClick=${() => { setOpen(false); onChange(o.value); }}>${o.label}</div>`)}
      </div>`}
    </div>`;
}

export const Toggle = ({ on, onChange, disabled }) =>
  html`<button class=${"toggle" + (on ? " on" : "")} disabled=${disabled} onClick=${() => onChange(!on)}><span></span></button>`;

export const Check = ({ on, onChange, children }) =>
  html`<label class="check"><input type="checkbox" checked=${on} onChange=${(e) => onChange(e.target.checked)} /><span class="box"><${Icon} name="check" size=${12} stroke=${3} /></span>${children}</label>`;

export const Spinner = () => html`<span class="spinner"></span>`;
