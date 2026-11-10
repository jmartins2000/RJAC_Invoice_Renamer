// One client's folder: invoices by period, runs, filename, destination, e-Fatura.
import { useEffect, useState } from "../vendor/hooks.mjs";
import { api, confirmBox, ctx, FeedbackButton, html, Menu, Modal, money, niceDate, plural, toast, TopBar } from "../ui.js";

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
  const [err, setErr] = useState(false);
  const ok = async () => {
    const p = await api.parse_dates(a, b);
    if (!p) setErr(true); else onDone(p);
  };
  const key = (e) => e.key === "Enter" && ok();
  return html`<${Modal} onClose=${onCancel} width=${440}>
    <h2>Invoices dated between</h2>
    <div class="date-row">
      <input class="input" placeholder="From, e.g. 01/02/2026" value=${a} onInput=${(e) => setA(e.target.value)} onKeyDown=${key} autofocus />
      <span class="muted">–</span>
      <input class="input" placeholder="To, e.g. 30/04/2026" value=${b} onInput=${(e) => setB(e.target.value)} onKeyDown=${key} />
    </div>
    <p class=${err ? "error small" : "muted small"}>${err ? "Please write both dates, e.g. 01/02/2026." : "Both dates are included."}</p>
    <div class="actions"><button class="btn" onClick=${onCancel}>Cancel</button><button class="btn solid" onClick=${ok}>Show</button></div>
  <//>`;
}

export function InvoiceTable({ columns, rows }) {
  const [sort, setSort] = useState([null, false]);
  const by = (key) => setSort([key, sort[0] === key ? !sort[1] : false]);
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
  return html`
    <div class="table-wrap">
      <table class="table">
        <thead><tr>
          ${columns.map((c) => html`<th class=${c.type === "number" ? "num" : ""} onClick=${() => by(c.key)}>${c.label}${arrow(c.key)}</th>`)}
          <th class="grow" onClick=${() => by("_file")}>File${arrow("_file")}</th>
          <th onClick=${() => by("_status")}>Status${arrow("_status")}</th>
        </tr></thead>
        <tbody>
          ${shown.map((r) => html`<tr onDblClick=${async () => { if (!(await api.open(r.path))) toast("This file is no longer there.", "warn"); }} title="Double-click to open">
            ${columns.map((c) => html`<td class=${c.type === "number" ? "num" : ""}>${r.cells[c.key]}</td>`)}
            <td class="grow ellipsis" title=${r.file}>${r.file}</td>
            <td class=${"status-" + r.status}>${r.status_label}</td>
          </tr>`)}
        </tbody>
      </table>
    </div>`;
}

export function Folder({ path, go }) {
  const [info, setInfo] = useState(null);
  const [period, setPeriod] = useState(null);
  const [data, setData] = useState(null);
  const [button, setButton] = useState({ label: "Checking for new files…", enabled: false });
  const [exported, setExported] = useState(null);

  useEffect(() => {
    ctx.screen = "Folder"; ctx.folder = path;
    api.folder(path).then((f) => { setInfo(f); setPeriod(f.periods[0]); });
    api.read_button(path).then(setButton);
  }, [path]);
  useEffect(() => { if (period) { setData(null); api.folder_rows(path, period.start, period.end).then(setData); } }, [period]);
  if (!info || !period) return html`<${TopBar} onBack=${() => go("home")} title="…" />`;

  const exp = async () => {
    const ok = await api.export_folder(path, period.start, period.end, period.short);
    if (ok !== null) setExported(ok);
  };
  const changeDest = async () => {
    const r = await api.change_dest(path);
    if (r) setInfo({ ...info, ...r });
  };
  const remove = async () => {
    if (await confirmBox({ title: "Remove folder", ok: "Remove", danger: true,
      text: `Remove "${info.name}" from your folders?\n\nNo files are deleted, and invoices already read stay remembered (they won't be paid for again if you add the folder back).` })) {
      await api.remove_folder(path); go("home");
    }
  };
  const rows = data ? data.rows : [];
  return html`
    <${TopBar} onBack=${() => go("home")} title=${info.name} sub=${info.where}>
      <${FeedbackButton} />
      <button class="btn" disabled=${!rows.length} onClick=${exp}>${exported === true ? "✓ Exported" : exported === false ? "Export failed" : "Export to Excel"}</button>
      <button class="btn solid" disabled=${!button.enabled} onClick=${() => go("review", path)}>${button.label}</button>
    <//>
    <div class="folder-body">
      <div class="folder-main">
        <div class="table-head">
          <${PeriodMenu} periods=${info.periods} custom=${info.custom} value=${period} onChange=${setPeriod} />
          <span class="muted">${data ? `${plural(rows.length, "invoice")} · total ${money(data.total)}` : ""}</span>
        </div>
        ${data && rows.length === 0 ? html`<div class="table-empty">${period.start ? "No invoices dated in this period." : "No invoices read in this folder yet."}</div>`
          : html`<${InvoiceTable} columns=${info.columns} rows=${rows} />`}
        <small class="muted hint">Double-click a row to open the file.</small>
      </div>
      <aside class="side">
        <div class="eyebrow">Runs</div>
        ${info.runs.length === 0 && html`<p class="muted">None yet</p>`}
        ${info.runs.slice(0, 6).map((r) => html`<div class="run"><span>${niceDate(r.date, true)}</span><span class="muted">${r.reads} read · €${r.eur.toFixed(2)}${r.renamed ? ` · ${r.renamed} renamed` : ""}</span></div>`)}
        ${info.runs.length > 6 && html`<p class="muted small">+ ${info.runs.length - 6} earlier</p>`}
        <div class="divider"></div>
        <div class="eyebrow">Filename & fields</div>
        <p class="mono green">${info.example}</p>
        <button class="link" onClick=${() => go("fields", { back: ["folder", path] })}>Customize</button>
        <div class="divider"></div>
        <div class="eyebrow">Renamed files go to</div>
        <p class="break">${info.dest_label}</p>
        <button class="link" onClick=${changeDest}>Change</button>
        <div class="divider"></div>
        <div class="eyebrow">e-Fatura</div>
        <p class="muted">${info.efatura ? `${info.efatura} invoices imported from the portal` : "Compare with the AT's list to find missing receipts."}</p>
        <button class="link" onClick=${() => go("efatura", path)}>Compare with e-Fatura</button>
        <button class="btn-quiet" onClick=${remove}>Remove from the list</button>
      </aside>
    </div>`;
}
