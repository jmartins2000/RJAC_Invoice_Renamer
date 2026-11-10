// Home (your clients), Welcome (API key) and Done (after renaming).
import { useEffect, useRef, useState } from "../vendor/hooks.mjs";
import { api, ctx, FeedbackButton, html, Icon, money, niceDate, plural, TopBar } from "../ui.js";

// ---------- Home ----------
function FolderRow({ p, first, onOpen }) {
  const [fresh, setFresh] = useState(null);
  useEffect(() => { if (p.exists) api.new_files(p.path).then(setFresh); }, [p.path]);
  let badge = null;
  if (fresh) badge = html`<span class="badge new">${plural(fresh, "new file")}</span>`;
  else if (p.to_check) badge = html`<span class="badge check">${p.to_check} to check</span>`;
  else if (fresh === 0) badge = html`<span class="badge done">All done</span>`;
  return html`
    <div class="row" onClick=${() => onOpen(p.path)}>
      <div class=${"tile" + (first ? " filled" : "")}><${Icon} name="folder" size=${22} /></div>
      <div class="name"><b>${p.name}</b><small class=${p.exists ? "" : "warn"}>${p.exists ? p.parent : "Folder not found (moved or deleted?)"}</small></div>
      <div class="stat w110"><b>${p.invoices}</b><small>invoices</small></div>
      <div class="stat w140"><b>${money(p.total)}</b><small>total</small></div>
      <div class="stat grow"><b>${p.last_run ? "Last run " + niceDate(p.last_run) : "No runs yet"}</b><small>${plural(p.runs, "run")}</small></div>
      ${badge}
    </div>`;
}

export function Home({ go, update, onUpdate }) {
  const [projects, setProjects] = useState(null);
  useEffect(() => { ctx.screen = "Home"; ctx.folder = null; api.projects().then(setProjects); }, []);
  const add = async () => { const path = await api.add_folder(); if (path) go("folder", path); };
  return html`
    <div class="topbar">
      <div class="brand"><img src="logo.png" alt="" /><span>Invoice Renamer</span></div>
      ${update && html`<button class="pill-update" onClick=${onUpdate}>Version ${update.version} is ready · Update</button>`}
      <${FeedbackButton} />
      <button class="btn" onClick=${() => go("settings")}><${Icon} name="gear" /> Settings</button>
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

// ---------- Welcome (first launch, or no key) ----------
export function Welcome({ onDone }) {
  const [key, setKey] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const input = useRef();
  useEffect(() => { ctx.screen = "Welcome"; setTimeout(() => input.current && input.current.focus(), 100); }, []);
  const check = async () => {
    setBusy(true); setErr("");
    const e = await api.check_key(key);
    setBusy(false);
    if (e) setErr(e); else onDone();
  };
  return html`
    <div class="center-page">
      <div class="center-col">
        <img src="logo.png" class="logo-big" alt="" />
        <h1 class="display">Welcome</h1>
        <p class="lead">One thing before we start: paste your Gemini API key. It's what lets the app read your invoices, and it stays on this computer.</p>
        <label class="field-label">Gemini API key</label>
        <input ref=${input} class="input mono" type="password" placeholder="AIza…" value=${key}
          onInput=${(e) => setKey(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && check()} />
        <button class="link" onClick=${() => api.open_url("https://aistudio.google.com/apikey")}>Don't have one? Get a key at aistudio.google.com ↗</button>
        ${err && html`<p class="error">${err}</p>`}
        <div class="submit"><button class="btn primary" disabled=${busy} onClick=${check}>${busy ? "Checking…" : "Check key and continue"}</button></div>
      </div>
    </div>`;
}

// ---------- Done ----------
export function Done({ result, go }) {
  const [exported, setExported] = useState(null);
  useEffect(() => { ctx.screen = "Done"; }, []);
  const r = result;
  let detail = `Saved in ${r.dest_name}.`;
  if (r.skipped) detail += ` ${r.skipped} file${r.skipped > 1 ? "s were" : " was"} skipped and left untouched.`;
  if (r.failed.length) detail += ` ${r.failed.length} could not be copied: ${r.failed.slice(0, 5).join(", ")}${r.failed.length > 5 ? "…" : ""}.`;
  const exp = async () => { const ok = await api.done_export(); if (ok !== null) setExported(ok); };
  return html`
    <div class="topbar">
      <button class="btn" onClick=${() => go("folder", r.folder)}><${Icon} name="back" /> Back to ${r.folder_name}</button>
      <div class="spacer"></div>
      <${FeedbackButton} />
    </div>
    <div class="center-page">
      <div class="center-col">
        <div class="big-check"><${Icon} name="check" size=${30} stroke=${2.6} /></div>
        <h1 class="display">${plural(r.renamed, "invoice")} renamed</h1>
        <p class="lead">${detail}</p>
        <div class="btn-row">
          <button class="btn primary" onClick=${() => api.open(r.dest)}>Open folder</button>
          <button class="btn big" onClick=${exp}>${exported === true ? "✓ Exported" : exported === false ? "Export failed" : "Export to Excel"}</button>
        </div>
        <div class="divider"></div>
        <div class="stats">
          <div><b>${r.renamed}</b><small>renamed</small></div>
          <div><b>${r.corrected}</b><small>corrected by you</small></div>
          <div><b>${r.skipped}</b><small>skipped</small></div>
          <div><b>€${r.cost_eur.toFixed(2)}</b><small>Gemini cost</small></div>
        </div>
      </div>
    </div>`;
}
