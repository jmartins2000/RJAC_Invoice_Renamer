// New interface: Preact + htm (no build step), talking to Python through pywebview's js_api.
import { h, render } from "./vendor/preact.mjs";
import { useEffect, useState } from "./vendor/hooks.mjs";
import htm from "./vendor/htm.mjs";

const html = htm.bind(h);

// ---------- Python bridge ----------
const ready = new Promise((resolve) => {
  if (window.pywebview && window.pywebview.api) resolve();
  else window.addEventListener("pywebviewready", () => resolve());
});
export const api = new Proxy({}, {
  get: (_, name) => async (...args) => { await ready; return window.pywebview.api[name](...args); },
});

// ---------- Icons (vector: crisp at any size) ----------
const paths = {
  folder: html`<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>`,
  chat: html`<path d="M5 5h14a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-8l-4 4v-4H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/>`,
  gear: html`<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>`,
};
export const Icon = ({ name, size = 16 }) =>
  html`<svg class="icon-svg" viewBox="0 0 24 24" style=${{ width: size, height: size }}>${paths[name]}</svg>`;

const money = (v) => Number(v || 0).toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const niceDate = (iso) => {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  const s = d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return d.getFullYear() === new Date().getFullYear() ? s : `${s} ${d.getFullYear()}`;
};

// ---------- Home: your clients ----------
function FolderRow({ p, first, onOpen }) {
  const [fresh, setFresh] = useState(null);
  useEffect(() => { if (p.exists) api.new_files(p.path).then(setFresh); }, [p.path]);
  let badge = null;
  if (fresh) badge = html`<span class="badge new">${fresh} new file${fresh !== 1 ? "s" : ""}</span>`;
  else if (p.to_check) badge = html`<span class="badge check">${p.to_check} to check</span>`;
  else if (fresh === 0) badge = html`<span class="badge done">All done</span>`;
  return html`
    <div class="row" onClick=${() => onOpen(p.path)}>
      <div class=${"tile" + (first ? " filled" : "")}><${Icon} name="folder" size=${22} /></div>
      <div class="name"><b>${p.name}</b><small class=${p.exists ? "" : "warn"}>${p.exists ? p.parent : "Folder not found (moved or deleted?)"}</small></div>
      <div class="stat w110"><b>${p.invoices}</b><small>invoices</small></div>
      <div class="stat w140"><b>${money(p.total)}</b><small>total</small></div>
      <div class="stat grow"><b>${p.last_run ? "Last run " + niceDate(p.last_run) : "No runs yet"}</b><small>${p.runs} run${p.runs !== 1 ? "s" : ""}</small></div>
      ${badge}
    </div>`;
}

function Home({ go }) {
  const [projects, setProjects] = useState(null);
  const load = () => api.projects().then(setProjects);
  useEffect(load, []);
  const add = async () => { const path = await api.add_folder(); if (path) go("folder", path); };
  return html`
    <div class="topbar">
      <div class="brand"><img src="logo.png" alt="" /><span>Invoice Renamer</span></div>
      <button class="btn icon" title="Send feedback"><${Icon} name="chat" /></button>
      <button class="btn"><${Icon} name="gear" /> Settings</button>
    </div>
    <div class="page">
      <div class="head">
        <div><h1>Your clients</h1><div class="sub">One folder per client: its invoices, runs and Excel by quarter or year.</div></div>
        <button class="btn primary" onClick=${add}>+ Add a client folder</button>
      </div>
      ${projects === null ? null : projects.length === 0 ? html`
        <div class="empty"><b>No clients yet</b><p>Add a client's folder of invoices (PDFs or photos).</p></div>` : html`
        <div class="list">${projects.map((p, i) => html`<${FolderRow} key=${p.path} p=${p} first=${i === 0} onOpen=${(path) => go("folder", path)} />`)}</div>`}
    </div>`;
}

// ---------- App shell ----------
function App() {
  const [route, setRoute] = useState({ name: "home" });
  const go = (name, arg) => setRoute({ name, arg });
  if (route.name === "home") return html`<${Home} go=${go} />`;
  return html`<div class="page"><h1>${route.name}</h1><p class="sub">${route.arg || ""}</p>
    <button class="btn" onClick=${() => go("home")}>Back</button></div>`;
}

render(html`<${App} />`, document.getElementById("app"));
