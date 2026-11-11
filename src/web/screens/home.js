// Home (your clients), Welcome (API key) and Done (after renaming).
import { useEffect, useRef, useState } from "../vendor/hooks.mjs";
import { api, ask, ctx, FeedbackButton, html, Icon, Modal, money, niceDate, plural, t, tn, TopBar } from "../ui.js";

// ---------- Home ----------
function FolderRow({ p, first, onOpen, tick }) {
  const [fresh, setFresh] = useState(null);
  useEffect(() => { if (p.exists) api.new_files(p.path).then(setFresh); }, [p.path, tick]);
  let badge = null;
  if (fresh) badge = html`<span class="badge new">${tn(fresh, "{n} new file", "{n} new files")}</span>`;
  else if (p.to_check) badge = html`<span class="badge check">${t("{n} to check", { n: p.to_check })}</span>`;
  else if (fresh === 0) badge = html`<span class="badge done">${t("All done")}</span>`;
  return html`
    <div class="row" onClick=${() => onOpen(p.path)}>
      <div class=${"tile" + (first ? " filled" : "")}><${Icon} name="folder" size=${22} /></div>
      <div class="name"><b>${p.name}</b><small class=${p.exists ? "" : "warn"}>${p.exists ? p.parent : t("Folder not found (moved or deleted?)")}</small></div>
      <div class="stat w110"><b>${p.invoices}</b><small>${t("invoices")}</small></div>
      <div class="stat w140"><b>${money(p.total)}</b><small>${t("total")}</small></div>
      <div class="stat grow"><b>${p.last_run ? t("Last run {date}", { date: niceDate(p.last_run) }) : t("No runs yet")}</b><small>${tn(p.runs, "{n} run", "{n} runs")}</small></div>
      ${badge}
    </div>`;
}

function NewClient({ onClose, onCreated }) {
  const [name, setName] = useState("");
  const [nif, setNif] = useState("");
  const [folder, setFolder] = useState(null);
  const [elsewhere, setElsewhere] = useState(false);
  const [dest, setDest] = useState(null);
  const [err, setErr] = useState("");
  const pick = async (set, start) => { const f = await api.choose_folder(start); if (f) set(f); };
  const badNif = nif && nif.replace(/\D/g, "").length !== 9;
  const ready = name.trim() && folder && !badNif && (!elsewhere || dest);
  const create = async () => {
    const r = await api.create_client(name, nif, folder, elsewhere ? dest : null);
    if (r.error) setErr(r.error); else onCreated(r.path);
  };
  const short = (p) => p ? p.split(/[\\/]/).slice(-2).join(" › ") : "";
  return html`<${Modal} onClose=${onClose} width=${520}>
    <h2>${t("New client")}</h2>
    <label class="field-label">${t("Name")}</label>
    <input class="input" value=${name} autofocus placeholder=${t("e.g. INLS Solutions, Lda")} onInput=${(e) => setName(e.target.value)} />
    <label class="field-label">${t("NIF (optional)")}</label>
    <input class="input mono" value=${nif} placeholder="500000000" inputmode="numeric" onInput=${(e) => setNif(e.target.value)} />
    ${badNif && html`<small class="warn">${t("A NIF has 9 digits.")}</small>`}
    <label class="field-label">${t("Folder with this client's receipts")}</label>
    <div class="dest-box"><span class="ellipsis">${folder ? short(folder) : html`<span class="muted">${t("Not chosen yet")}</span>`}</span>
      <button class="link" onClick=${() => pick(setFolder)}>${folder ? t("Change") : t("Choose…")}</button></div>
    <label class="field-label">${t("Renamed copies go to")}</label>
    <div class="seg wide">
      <button class=${!elsewhere ? "on" : ""} onClick=${() => setElsewhere(false)}>${t("The same folder")}</button>
      <button class=${elsewhere ? "on" : ""} onClick=${() => setElsewhere(true)}>${t("Another folder")}</button>
    </div>
    ${elsewhere && html`<div class="dest-box mt-s"><span class="ellipsis">${dest ? short(dest) : html`<span class="muted">${t("Not chosen yet")}</span>`}</span>
      <button class="link" onClick=${() => pick(setDest, folder)}>${dest ? t("Change") : t("Choose…")}</button></div>`}
    ${err && html`<p class="error small">${err}</p>`}
    <div class="actions"><button class="btn" onClick=${onClose}>${t("Cancel")}</button>
      <button class="btn solid" disabled=${!ready} onClick=${create}>${t("Create client")}</button></div>
  <//>`;
}

export function Home({ go, update, onUpdate }) {
  const [projects, setProjects] = useState(null);
  const [adding, setAdding] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => { ctx.screen = "Home"; ctx.folder = null; ask("projects").then(setProjects); }, []);
  useEffect(() => {  // files may have been added to the folders meanwhile: look again when the window is back
    const again = () => { setTick((n) => n + 1); api.projects().then(setProjects); };
    window.addEventListener("focus", again);
    return () => window.removeEventListener("focus", again);
  }, []);
  const add = () => setAdding(true);
  return html`
    <div class="topbar">
      <div class="brand"><img src="logo.png" alt="" /><span>Invoice Renamer</span></div>
      ${update && html`<button class="pill-update" onClick=${onUpdate}>${t("Version {v} is ready · Update", { v: update.version })}</button>`}
      <${FeedbackButton} />
      <button class="btn" onClick=${() => go("settings")}><${Icon} name="gear" /> ${t("Settings")}</button>
    </div>
    <div class="page">
      <div class="head">
        <div><h1>${t("Your clients")}</h1><div class="sub">${t("Each client keeps its receipts, runs, e-Fatura data and Excel exports.")}</div></div>
        <button class="btn primary" onClick=${add}>${t("+ New client")}</button>
      </div>
      ${projects === null ? null : projects.length === 0 ? html`
        <div class="empty"><b>${t("No clients yet")}</b><p>${t("Create a client and choose the folder where its receipts arrive (PDFs or photos).")}</p></div>` : html`
        <div class="list">${projects.map((p, i) => html`<${FolderRow} key=${p.path} p=${p} first=${i === 0} tick=${tick} onOpen=${(path) => go("folder", path)} />`)}</div>`}
    </div>
    ${adding && html`<${NewClient} onClose=${() => setAdding(false)} onCreated=${(path) => { setAdding(false); go("folder", path); }} />`}`;
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
        <h1 class="display">${t("Welcome")}</h1>
        <p class="lead">${t("One thing before we start: paste your Gemini API key. It's what lets the app read your invoices, and it stays on this computer.")}</p>
        <label class="field-label">${t("Gemini API key")}</label>
        <input ref=${input} class="input mono" type="password" placeholder="AIza…" value=${key}
          onInput=${(e) => setKey(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && check()} />
        <button class="link" onClick=${() => api.open_url("https://aistudio.google.com/apikey")}>${t("Don't have one? Get a key at aistudio.google.com ↗")}</button>
        ${err && html`<p class="error">${err}</p>`}
        <div class="submit"><button class="btn primary" disabled=${busy} onClick=${check}>${busy ? t("Checking…") : t("Check key and continue")}</button></div>
      </div>
    </div>`;
}

// ---------- Done ----------
export function Done({ result, go }) {
  const [exported, setExported] = useState(null);
  useEffect(() => { ctx.screen = "Done"; }, []);
  const r = result;
  let detail = t("Saved in {place}.", { place: r.dest_name });
  if (r.skipped) detail += " " + tn(r.skipped, "{n} file was skipped and left untouched.", "{n} files were skipped and left untouched.");
  if (r.failed.length) detail += " " + t("{n} could not be copied: {files}.", { n: r.failed.length, files: r.failed.slice(0, 5).join(", ") + (r.failed.length > 5 ? "…" : "") });
  const exp = async () => { const ok = await api.done_export(); if (ok !== null) setExported(ok); };
  return html`
    <div class="topbar">
      <button class="btn" onClick=${() => go("folder", r.folder)}><${Icon} name="back" /> ${t("Back to {name}", { name: r.folder_name })}</button>
      <div class="spacer"></div>
      <${FeedbackButton} />
    </div>
    <div class="center-page">
      <div class="center-col">
        <div class="big-check"><${Icon} name="check" size=${30} stroke=${2.6} /></div>
        <h1 class="display">${tn(r.renamed, "{n} invoice renamed", "{n} invoices renamed")}</h1>
        <p class="lead">${detail}</p>
        <div class="btn-row">
          <button class="btn primary" onClick=${() => api.open(r.dest)}>${t("Open folder")}</button>
          <button class="btn big" onClick=${exp}>${exported === true ? t("✓ Exported") : exported === false ? t("Export failed") : t("Export to Excel")}</button>
        </div>
        <div class="divider"></div>
        <div class="stats">
          <div><b>${r.renamed}</b><small>${t("renamed")}</small></div>
          <div><b>${r.corrected}</b><small>${t("corrected by you")}</small></div>
          <div><b>${r.skipped}</b><small>${t("skipped")}</small></div>
          <div><b>€${r.cost_eur.toFixed(2)}</b><small>${t("Gemini cost")}</small></div>
        </div>
      </div>
    </div>`;
}
