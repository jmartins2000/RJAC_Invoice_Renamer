// One client's folder: invoices by period, runs, filename, destination, e-Fatura.
import { useEffect, useRef, useState } from "../vendor/hooks.mjs";
import { api, Calendar, confirmBox, ctx, DateButton, FeedbackButton, html, Menu, Modal, money, niceDate, plural, t, tn, toast, TopBar } from "../ui.js";

/** Period dropdown shared with the e-Fatura screen. Handles "Custom dates…". */
export function PeriodMenu({ periods, custom, value, onChange, withCustom = true }) {
  const [asking, setAsking] = useState(false);
  const [extra, setExtra] = useState(null);
  const list = [...(extra ? [extra] : []), ...periods.filter((p) => withCustom || p.label !== custom)];
  const options = list.map((p) => ({ value: p.label, label: p.label }));
  return html`
    <${Menu} value=${value.label} options=${options} onChange=${(label) => {
      if (label === custom) { setAsking(true); return; }
      onChange(list.find((p) => p.label === label));
    }} />
    ${asking && html`<${CustomDates} onCancel=${() => setAsking(false)}
        onDone=${(p) => { setAsking(false); setExtra(p); onChange(p); }} />`}`;
}

function CustomDates({ onDone, onCancel }) {
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [which, setWhich] = useState("a");  // the calendar shown: for "a" (from), "b" (to) or none
  const [err, setErr] = useState(false);
  const ok = async () => {
    const p = await api.parse_dates(a, b);
    if (!p) setErr(true); else onDone(p);
  };
  const pick = (iso) => {
    setErr(false);
    if (which === "a") { setA(iso); if (b && iso > b) setB(""); setWhich("b"); }
    else { setB(iso); setWhich(null); }
  };
  return html`<${Modal} onClose=${onCancel} width=${440}>
    <h2>${t("Invoices dated between")}</h2>
    <div class="date-row">
      <div class="date-field"><span>${t("From")}</span>
        <${DateButton} value=${a} active=${which === "a"} onClick=${() => setWhich(which === "a" ? null : "a")} /></div>
      <span class="muted">–</span>
      <div class="date-field"><span>${t("To")}</span>
        <${DateButton} value=${b} active=${which === "b"} onClick=${() => setWhich(which === "b" ? null : "b")} /></div>
    </div>
    ${which && html`<div class="cal-inline"><${Calendar} key=${which} value=${which === "a" ? a : b}
      min=${which === "b" ? a || null : null} onPick=${pick} /></div>`}
    <p class=${err ? "error small" : "muted small"}>${err ? t("Please choose both dates.") : t("Both dates are included.")}</p>
    <div class="actions"><button class="btn" onClick=${onCancel}>${t("Cancel")}</button>
      <button class="btn solid" disabled=${!a || !b} onClick=${ok}>${t("Show")}</button></div>
  <//>`;
}

// Column widths: what the user dragged (saved for every client) or a sensible default by type.
const DEFAULT_WIDTH = { date: 112, number: 108, text: 210, _file: 260, _status: 124 };

export function InvoiceTable({ columns, rows, pending = [], folder = "", widths = {}, onWidth }) {
  const [sort, setSort] = useState([null, false]);
  const [live, setLive] = useState({});  // widths while dragging
  const dragged = useRef(false);
  const by = (key) => { if (dragged.current) { dragged.current = false; return; } setSort([key, sort[0] === key ? !sort[1] : false]); };
  let shown = rows;
  if (sort[0]) {
    const val = (r) => sort[0] === "_file" ? r.file : sort[0] === "_status" ? r.status_label : r.sort[sort[0]];
    shown = [...rows].sort((x, y) => {
      const a = val(x), b = val(y);
      const empty = (v) => v === null || v === undefined || v === "";
      if (empty(a) !== empty(b)) return empty(a) ? 1 : -1;
      const c = typeof a === "number" && typeof b === "number" ? a - b : String(a).toLowerCase().localeCompare(String(b).toLowerCase());
      return sort[1] ? -c : c;
    });
  }
  const arrow = (k) => sort[0] === k ? (sort[1] ? " ↓" : " ↑") : "";
  const cols = [...columns.map((c) => ({ key: c.key, label: c.label, type: c.type })),
    { key: "_file", label: t("File"), type: "_file" }, { key: "_status", label: t("Status"), type: "_status" }];
  const widthOf = (c) => live[c.key] ?? widths[c.key] ?? DEFAULT_WIDTH[c.type] ?? 160;
  const total = cols.reduce((s, c) => s + widthOf(c), 0);
  const startDrag = (e, c) => {
    e.preventDefault(); e.stopPropagation();
    const x0 = e.clientX, w0 = widthOf(c);
    let w = w0;
    const move = (ev) => { w = Math.max(50, Math.min(900, w0 + ev.clientX - x0)); setLive((l) => ({ ...l, [c.key]: w })); };
    const up = () => {
      window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up);
      dragged.current = w !== w0;
      if (w !== w0 && onWidth) onWidth(c.key, w);
      setTimeout(() => { dragged.current = false; }, 0);
    };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };
  const reset = (e, c) => { e.stopPropagation(); setLive((l) => { const n = { ...l }; delete n[c.key]; return n; }); if (onWidth) onWidth(c.key, null); };
  const numeric = (c) => c.type === "number";
  return html`
    <div class="table-wrap">
      <table class="table resizable" style=${{ width: `max(100%, ${total}px)` }}>
        <colgroup>${cols.map((c) => html`<col style=${{ width: `${widthOf(c)}px` }} />`)}</colgroup>
        <thead><tr>
          ${cols.map((c) => html`<th class=${numeric(c) ? "num" : ""} onClick=${() => by(c.key)}>${c.label}${arrow(c.key)}
            <span class="col-resize" title=${t("Drag to change the width · double-click: automatic")}
              onMouseDown=${(e) => startDrag(e, c)} onClick=${(e) => e.stopPropagation()} onDblClick=${(e) => reset(e, c)}></span></th>`)}
        </tr></thead>
        <tbody>
          ${pending.map((name) => html`<tr class="row-new" title=${t("Not read yet: use the button at the top to read it")}
              onDblClick=${async () => { if (!(await api.open(folder + "/" + name))) toast(t("This file is no longer there."), "warn"); }}>
            ${columns.map((c) => html`<td class=${numeric(c) ? "num" : ""}>—</td>`)}
            <td title=${name}>${name}</td>
            <td class="status-new">${t("Not read yet")}</td>
          </tr>`)}
          ${shown.map((r) => html`<tr onDblClick=${async () => { if (!(await api.open(r.path))) toast(t("This file is no longer there."), "warn"); }}>
            ${columns.map((c) => html`<td class=${numeric(c) ? "num" : ""} title=${r.cells[c.key]}>${r.cells[c.key]}</td>`)}
            <td title=${r.file}>${r.file}</td>
            <td class=${"status-" + r.status}>${r.status_label}</td>
          </tr>`)}
        </tbody>
      </table>
    </div>`;
}

function ClientDialog({ info, onClose, onSaved }) {
  const [name, setName] = useState(info.custom_name ? info.name : "");
  const [nif, setNif] = useState(info.nif || "");
  const [busy, setBusy] = useState(false);
  const save = async () => { setBusy(true); onSaved(await api.rename_client(info.path, name, nif)); };
  const badNif = nif && nif.replace(/\D/g, "").length !== 9;
  return html`<${Modal} onClose=${onClose} width=${460}>
    <h2>${t("Client details")}</h2>
    <label class="field-label">${t("Name")}</label>
    <input class="input" value=${name} placeholder=${info.folder_name} autofocus
      onInput=${(e) => setName(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && !badNif && save()} />
    <small class="muted">${t("Shown in the app and used in Excel file names. Leave empty to use the folder's name ({name}).", { name: info.folder_name })}</small>
    <label class="field-label">${t("NIF (optional)")}</label>
    <input class="input mono" value=${nif} placeholder="500000000" inputmode="numeric"
      onInput=${(e) => setNif(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && !badNif && save()} />
    ${badNif && html`<small class="warn">${t("A NIF has 9 digits.")}</small>`}
    <div class="actions"><button class="btn" onClick=${onClose}>${t("Cancel")}</button>
      <button class="btn solid" disabled=${busy || badNif} onClick=${save}>${t("Save")}</button></div>
  <//>`;
}

export function Folder({ path, go }) {
  const [info, setInfo] = useState(null);
  const [period, setPeriod] = useState(null);
  const [data, setData] = useState(null);
  const [button, setButton] = useState({ label: t("Checking for new files…"), enabled: false });
  const [exported, setExported] = useState(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    ctx.screen = "Folder"; ctx.folder = path;
    api.folder(path).then((f) => { setInfo(f); setPeriod(f.periods[0]); });
    api.read_button(path).then(setButton);
  }, [path]);
  useEffect(() => { if (period) { setData(null); api.folder_rows(path, period.start, period.end).then(setData); } }, [period]);
  // Files may be added to the folder while this screen is open (e.g. in Finder / Explorer):
  // look again whenever the app window comes back to the front.
  useEffect(() => {
    const again = () => {
      api.read_button(path).then(setButton);
      if (period) api.folder_rows(path, period.start, period.end).then(setData);
    };
    window.addEventListener("focus", again);
    const vis = () => { if (!document.hidden) again(); };
    document.addEventListener("visibilitychange", vis);
    return () => { window.removeEventListener("focus", again); document.removeEventListener("visibilitychange", vis); };
  }, [path, period]);
  if (!info || !period) return html`<${TopBar} onBack=${() => go("home")} title="…" />`;

  const exp = async () => {
    const ok = await api.export_folder(path, period.start, period.end, period.short);
    if (ok !== null) setExported(ok);
  };
  const changeDest = async () => {
    const r = await api.change_dest(path);
    if (r) setInfo({ ...info, ...r });
  };
  const changeFolder = async () => {
    if (!(await confirmBox({ title: t("Change the receipts folder"), ok: t("Choose folder…"),
      text: t("Use this when the client's receipts moved to another folder, or should come from another folder from now on.\n\nEverything the app knows about this client (invoices read, runs, e-Fatura data and codes) stays with the client. No files are moved.") }))) return;
    const r = await api.change_client_folder(path);
    if (!r) return;
    if (r.error) toast(r.error, "warn"); else { toast(t("Receipts folder changed.")); go("folder", r.path); }
  };
  const remove = async () => {
    if (await confirmBox({ title: t("Delete {name}?", { name: info.name }), ok: t("Delete client"), danger: true,
      text: t("This removes the client from the app with everything the app keeps about it: invoices as read, runs, imported e-Fatura data and codes.\n\nThe files in the folder are NOT deleted or changed.\n\nIf you add the folder again, its invoices are read again (Gemini cost).") })) {
      await api.delete_client(path); toast(t("{name} deleted.", { name: info.name })); go("home");
    }
  };
  const rows = data ? data.rows : [];
  return html`
    <${TopBar} onBack=${() => go("home")} title=${info.name} sub=${info.nif ? `NIF ${info.nif}` : ""}>
      <${FeedbackButton} />
      <button class="btn" disabled=${!rows.length} onClick=${exp}>${exported === true ? t("✓ Exported") : exported === false ? t("Export failed") : t("Export to Excel")}</button>
      <button class="btn solid" disabled=${!button.enabled} onClick=${() => go("review", path)}>${button.label}</button>
    <//>
    <div class="folder-body">
      <div class="folder-main">
        <div class="table-head">
          <${PeriodMenu} periods=${info.periods} custom=${info.custom} value=${period} onChange=${setPeriod} />
          <span class="muted">${data ? `${tn(rows.length, "{n} invoice", "{n} invoices")} · ${t("total")} ${money(data.total)}` : ""}</span>
        </div>
        ${button.new > 0 && html`<div class="new-files">
          <span><b>${tn(button.new, "{n} file not read yet", "{n} files not read yet")}</b> ${t("in this folder (in red below).")}</span>
          <button class="btn solid small" onClick=${() => go("review", path)}>${t("Read now")}${button.cost ? ` · ${button.cost}` : ""}</button>
        </div>`}
        ${data && rows.length === 0 && !(button.files || []).length ? html`<div class="table-empty">${period.start ? t("No invoices dated in this period.") : t("No invoices read in this folder yet.")}</div>`
          : html`<${InvoiceTable} columns=${info.columns} rows=${rows} pending=${button.files || []} folder=${path}
              widths=${info.column_widths || {}} onWidth=${async (k, w) => { const cw = await api.set_column_width(k, w); setInfo((i) => ({ ...i, column_widths: cw })); }} />`}
        <small class="muted hint">${t("Double-click a row to open the file.")}</small>
      </div>
      <aside class="side">
        <div class="eyebrow">${t("Client")}</div>
        <p class="client-name"><b>${info.name}</b>${info.nif && html`<span class="muted"> · NIF ${info.nif}</span>`}</p>
        <button class="link" onClick=${() => setEditing(true)}>${t("Edit name and NIF")}</button>
        <div class="divider"></div>
        <div class="eyebrow">${t("Receipts folder")}</div>
        <p class="break">${info.where}</p>
        <button class="link" onClick=${changeFolder}>${t("Change")}</button>
        <div class="divider"></div>
        <div class="eyebrow">${t("Runs")}</div>
        ${info.runs.length === 0 && html`<p class="muted">${t("None yet")}</p>`}
        ${info.runs.slice(0, 6).map((r) => html`<div class="run"><span>${niceDate(r.date, true)}</span><span class="muted">${t("{n} read", { n: r.reads })} · €${r.eur.toFixed(2)}${r.renamed ? ` · ${t("{n} renamed", { n: r.renamed })}` : ""}</span></div>`)}
        ${info.runs.length > 6 && html`<p class="muted small">${t("+ {n} earlier", { n: info.runs.length - 6 })}</p>`}
        <div class="divider"></div>
        <div class="eyebrow">${t("Filename & fields")}</div>
        <p class="mono green">${info.example}</p>
        <button class="link" onClick=${() => go("fields", { back: ["folder", path] })}>${t("Customize")}</button>
        <div class="divider"></div>
        <div class="eyebrow">${t("Renamed files go to")}</div>
        <p class="break">${info.dest_label}</p>
        <button class="link" onClick=${changeDest}>${t("Change")}</button>
        <div class="divider"></div>
        <div class="eyebrow">e-Fatura</div>
        <p class="muted">${info.efatura ? tn(info.efatura, "{n} invoice imported from the portal", "{n} invoices imported from the portal") : t("Compare with the AT's list to find missing receipts.")}</p>
        <button class="link" onClick=${() => go("efatura", path)}>${t("Compare with e-Fatura")}</button>
        <button class="btn-quiet" onClick=${remove}>${t("Delete client…")}</button>
      </aside>
    </div>
    ${editing && html`<${ClientDialog} info=${info} onClose=${() => setEditing(false)}
      onSaved=${(f) => { setEditing(false); setInfo({ ...info, ...f }); toast(t("Saved.")); }} />`}`;
}
