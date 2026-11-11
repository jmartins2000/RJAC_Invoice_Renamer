// Settings (key, model, fields, appearance, updates) and Fields & filename.
import { useEffect, useRef, useState } from "../vendor/hooks.mjs";
import { api, Check, confirmBox, ctx, FeedbackButton, html, Icon, Menu, Modal, niceDate, Toggle, TopBar, usePy } from "../ui.js";

/** Install any published version, e.g. go back to an earlier one if a new version causes trouble. */
function VersionsDialog({ onClose }) {
  const [list, setList] = useState(null);
  const [state, setState] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [msg, setMsg] = useState(null);
  usePy("update_progress", setProgress, []);
  useEffect(() => { api.releases().then(setList); }, []);
  const install = async (r) => {
    const older = !r.newer;
    if (!(await confirmBox({ title: `Install version ${r.version}?`, ok: `Install ${r.version}`,
      text: older ? "Your clients, history and settings are kept. Features added after this version won't be there, " +
        "and the app will offer the newest version again when you open it (you can ignore it)." : "Your clients, history and settings are kept." }))) return;
    setState("downloading"); setProgress(0); setMsg(null);
    const res = await api.install_version(r.version);
    if (res.error) { setState("idle"); setMsg({ err: true, text: res.error }); }
    else { setState("done"); setMsg({ text: res.message }); }
  };
  return html`<${Modal} onClose=${state === "downloading" ? null : onClose} width=${560}>
    <h2>Install another version</h2>
    <p class="muted">If a new version gives you trouble, you can go back to an earlier one here.</p>
    ${list === null ? html`<p class="muted">Loading versions…</p>` : list.length === 0 ? html`<p class="error small">Couldn't load the versions (no internet?).</p>` : html`
      <div class="versions">${list.map((r) => html`<div class="version-row">
        <div class="grow"><b>${r.version}</b> <span class="muted small">· ${niceDate(r.date, true)}</span>
          ${r.notes && html`<small class="muted block ellipsis">${r.notes}</small>`}</div>
        ${r.current ? html`<span class="muted small">Installed</span>` :
          html`<button class="btn small" disabled=${state === "downloading"} onClick=${() => install(r)}>${r.newer ? "Update" : "Install"}</button>`}
      </div>`)}</div>`}
    ${state === "downloading" && html`<div class="bar mt"><div style=${{ width: `${Math.round(progress * 100)}%` }}></div></div>`}
    ${msg && html`<p class=${msg.err ? "error small" : "muted small"}>${msg.text}</p>`}
    <div class="actions"><button class="btn" disabled=${state === "downloading"} onClick=${onClose}>Close</button></div>
  <//>`;
}

export function Settings({ go, appearance, setAppearance, onUpdateFound }) {
  const [info, setInfo] = useState(null);
  const [editing, setEditing] = useState(false);
  const [key, setKey] = useState("");
  const [keyMsg, setKeyMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [models, setModels] = useState(null);
  const [modelMsg, setModelMsg] = useState(null);
  const [upd, setUpd] = useState(null);
  const [versions, setVersions] = useState(false);
  const input = useRef();
  useEffect(() => {
    ctx.screen = "Settings"; ctx.folder = null;
    api.settings_info().then(setInfo);
    api.models_list().then(setModels);
  }, []);
  useEffect(() => { if (editing && input.current) input.current.focus(); }, [editing]);
  if (!info) return html`<${TopBar} onBack=${() => go("home")} title="Settings" />`;

  const saveKey = async () => {
    if (!editing) { setEditing(true); setKey(""); setKeyMsg(null); return; }
    if (!key.trim()) { setEditing(false); return; }
    setBusy(true);
    const err = await api.check_key(key);
    setBusy(false);
    if (err) { setKeyMsg({ err: true, text: err }); return; }
    setKeyMsg({ err: false, text: "Saved." }); setEditing(false);
    api.settings_info().then(setInfo); api.models_list().then(setModels);
  };
  const chooseModel = async (id) => {
    if (id === models.current) return;
    const m = models.models.find((x) => x.id === id);
    setModelMsg({ err: false, text: `Checking that ${m.label} works with your key…` });
    const err = await api.choose_model(id);
    if (err) setModelMsg({ err: true, text: err });
    else { setModelMsg(null); setModels({ ...models, current: id }); }
  };
  const checkUpdates = async () => {
    setUpd("checking");
    const u = await api.check_update();
    setUpd(u ? "found" : "latest");
    if (u) onUpdateFound(u, true);
  };
  const current = models && models.models.find((m) => m.id === models.current);
  const opt = (m) => `${m.label}${m.tag ? " · " + m.tag : ""} · ${m.price}`;
  return html`
    <${TopBar} onBack=${() => go("home")} title="Settings"><${FeedbackButton} /><//>
    <div class="page narrow">
      <section>
        <div class="sec-head"><h3>Gemini API key</h3>
          <span class=${"pill " + (info.has_key ? "ok" : "bad")}>● ${info.has_key ? "Working" : "Missing"}</span></div>
        <p class="muted">Used to read your invoices. It's saved on this computer for your user only, and is only ever sent to Google.</p>
        <div class="key-row">
          ${editing ? html`<input ref=${input} class="input mono grow" type="password" placeholder="AIza…" value=${key}
              onInput=${(e) => setKey(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && saveKey()} />`
            : html`<input class="input mono grow" disabled value=${info.key || "Not set"} />`}
          <button class="btn big" disabled=${busy} onClick=${saveKey}>${busy ? "Checking…" : editing ? "Save" : info.has_key ? "Replace" : "Add key"}</button>
        </div>
        ${keyMsg && html`<p class=${keyMsg.err ? "error" : "green"}>${keyMsg.text}</p>`}
        <button class="link" onClick=${() => api.open_url("https://aistudio.google.com/apikey")}>Get a key at aistudio.google.com ↗</button>
      </section>
      <section>
        <div class="sec-head"><h3>AI model</h3><span class="muted">${info.usage}</span></div>
        ${!models ? html`<div class="menu-btn disabled">Loading models…</div>` : html`
          <${Menu} width="100%" value=${models.current} label=${current ? opt(current) : models.current}
            options=${models.models.map((m) => ({ value: m.id, label: opt(m) }))} onChange=${chooseModel} />`}
        <p class=${modelMsg && modelMsg.err ? "error small" : "muted small"}>${modelMsg ? modelMsg.text : models && models.error ? models.error : current ? current.detail : ""}</p>
      </section>
      <section class="row-sec">
        <div><h3>Fields & filename</h3><p class="muted">${info.fields}</p></div>
        <button class="btn" onClick=${() => go("fields", { back: ["settings"] })}>Edit fields</button>
      </section>
      <section class="row-sec">
        <div><h3>Appearance</h3><p class="muted">Day or night colours</p></div>
        <div class="seg">${[["system", "Follow system"], ["light", "Day"], ["dark", "Night"]].map(([k, l]) =>
          html`<button class=${appearance === k ? "on" : ""} onClick=${() => setAppearance(k)}>${l}</button>`)}</div>
      </section>
      <section class="row-sec">
        <div><h3>Updates</h3><p class="muted">Version ${info.version}${upd === "latest" ? " · you have the latest version" : upd === "found" ? " · a new version is available" : ""}</p></div>
        <div class="btn-col">
          <button class="btn" disabled=${upd === "checking"} onClick=${checkUpdates}>${upd === "checking" ? "Checking…" : "Check now"}</button>
          <button class="link small" onClick=${() => setVersions(true)}>Other versions…</button>
        </div>
      </section>
    </div>
    ${versions && html`<${VersionsDialog} onClose=${() => setVersions(false)} />`}`;
}

const TYPES = [["text", "Text"], ["number", "Number"], ["date", "Date"]];

function FieldDialog({ field, onClose, onSaved }) {
  const [label, setLabel] = useState(field ? field.label : "");
  const [type, setType] = useState(field ? field.type : "text");
  const [instr, setInstr] = useState(field ? field.instructions : "");
  const [err, setErr] = useState("");
  const save = async () => {
    const r = await api.field_save(field ? field.key : null, label, type, instr);
    if (r.problem) setErr(r.problem); else { onSaved(r); onClose(); }
  };
  return html`<${Modal} onClose=${onClose} width=${540}>
    <h2>${field ? "Edit field" : "Add a field"}</h2>
    <label class="field-label">Name</label>
    <input class="input" placeholder="e.g. Supplier NIF" value=${label} onInput=${(e) => setLabel(e.target.value)} autofocus />
    <label class="field-label">Type</label>
    <div class="seg">${TYPES.map(([k, l]) => html`<button class=${type === k ? "on" : ""} disabled=${field && field.builtin} onClick=${() => setType(k)}>${l}</button>`)}</div>
    <label class="field-label">What should be read from the invoice?</label>
    <textarea class="input" rows="5" value=${instr} onInput=${(e) => setInstr(e.target.value)}></textarea>
    <p class="muted small">Describe it like you would to a person: what it's called on the invoice and what to avoid.</p>
    ${err && html`<p class="error small">${err}</p>`}
    <div class="actions"><button class="btn" onClick=${onClose}>Cancel</button><button class="btn solid" onClick=${save}>Save</button></div>
  <//>`;
}

export function Fields({ go, back }) {
  const [info, setInfo] = useState(null);
  const [sep, setSep] = useState("");
  const [problem, setProblem] = useState(null);
  const [dialog, setDialog] = useState(null);
  useEffect(() => { ctx.screen = "Fields & filename"; api.fields_info().then((i) => { setInfo(i); setSep(i.separator); }); }, []);
  if (!info) return html`<${TopBar} onBack=${() => go(...back)} title="Fields & filename" />`;
  const apply = (r) => { if (r.problem) setProblem(r.problem); else { setProblem(null); setInfo(r); } };
  const changeSep = async (v) => { setSep(v); apply(await api.set_separator(v)); };
  const del = async (f) => {
    if (await confirmBox({ title: "Delete field", ok: "Delete", danger: true, text: `Delete the field "${f.label}"?\n\nValues already read stay in the history.` }))
      setInfo(await api.field_delete(f.key));
  };
  return html`
    <${TopBar} onBack=${() => go(...back)} title="Fields & filename">
      <${FeedbackButton} />
      <button class="btn solid" onClick=${() => setDialog({ field: null })}>+ Add a field</button>
    <//>
    <div class="page narrow wide">
      <div class="sep-card">
        <div class="sep-top">
          <div><h3>Separator between fields</h3><p class="muted small">Type what goes between the values in the filename. Spaces count.</p></div>
          <input class=${"input mono sep-input" + (problem ? " bad" : "")} value=${sep} onInput=${(e) => changeSep(e.target.value)} />
          <button class="link" onClick=${() => changeSep(info.default_separator)}>Reset</button>
        </div>
        <p class=${"mono " + (problem ? "error" : "green")}>${problem || `Example:  ${info.example}`}</p>
        <div class="sep-extra">
          <${Check} on=${info.original} onChange=${async (v) => setInfo(await api.set_original(v))}>Add the original filename at the end<//>
          <span class="muted">Also in the Excel:</span>
          ${info.file_columns.map((c) => html`<${Check} on=${c.on} onChange=${async (v) => setInfo(await api.set_excel_column(c.key, v))}>${c.label}<//>`)}
        </div>
      </div>
      <p class="muted mt">What is read from each invoice. Switch a field off to stop reading it; choose whether it goes into the filename and the Excel. The order here is the order in the filename.</p>
      <div class="field-list">
        ${info.fields.map((f, i) => html`<div class="field-row">
          <${Toggle} on=${f.enabled} onChange=${async (v) => setInfo(await api.field_set(f.key, "enabled", v))} />
          <div class="field-text">
            <div><b class=${f.enabled ? "" : "muted"}>${f.label}</b> <small class="muted">${f.type_label}</small></div>
            <small class="muted clamp">${f.instructions}</small>
          </div>
          <div class="field-actions">
            ${f.enabled && html`
              <${Check} on=${f.in_filename} onChange=${async (v) => setInfo(await api.field_set(f.key, "in_filename", v))}>Filename<//>
              <${Check} on=${f.in_excel} onChange=${async (v) => setInfo(await api.field_set(f.key, "in_excel", v))}>Excel<//>`}
            <button class="btn icon small" disabled=${i === 0} title="Move up" onClick=${async () => setInfo(await api.field_move(f.key, -1))}><${Icon} name="up" size=${14} /></button>
            <button class="btn icon small" disabled=${i === info.fields.length - 1} title="Move down" onClick=${async () => setInfo(await api.field_move(f.key, 1))}><${Icon} name="down" size=${14} /></button>
            <button class="link" onClick=${() => setDialog({ field: f })}>Edit</button>
            ${!f.builtin && html`<button class="link red" onClick=${() => del(f)}>Delete</button>`}
          </div>
        </div>`)}
      </div>
    </div>
    ${dialog && html`<${FieldDialog} field=${dialog.field} onClose=${() => setDialog(null)} onSaved=${setInfo} />`}`;
}
