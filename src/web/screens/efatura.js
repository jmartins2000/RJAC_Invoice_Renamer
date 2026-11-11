// e-Fatura reconciliation: the client's receipts vs. the AT's list, one case at a time.
import { useEffect, useRef, useState } from "../vendor/hooks.mjs";
import { api, confirmBox, ctx, FeedbackButton, html, Icon, Menu, Modal, money, niceDate, plain2, t, tn, toast, TopBar, usePy } from "../ui.js";
import { PeriodMenu } from "./folder.js";
import { Preview } from "./review.js";

const KIND = {
  differ: { chip: "≠ Differs", title: "≠ Values differ", cls: "red" },
  missing: { chip: "No receipt", title: "No receipt", cls: "amber" },
  not_in_ef: { chip: "Not in e-Fat.", title: "Not in e-Fatura", cls: "amber" },
  matched: { chip: "Matched", title: "✓ Matched", cls: "green" },
  cancelled: { chip: "Cancelled", title: "Cancelled by the supplier", cls: "grey" },
};
const DECIDED = { not_needed: "Marked as not needed", kept: "Kept the receipt's values", registered: "Marked as registered in e-Fatura" };
const n0 = (v) => Number(v).toLocaleString();
const FILTERS = [["attention", "Needs attention"], ["missing", "No receipt"], ["not_in_ef", "Not in e-Fatura"], ["differ", "Differs"],
  ["cancelled", "Cancelled"], ["all", "All"]];

// Open = still needs a decision: no code chosen (e-Fatura documents) or no decision (receipts not in e-Fatura).
const open = (i) => i.kind !== "matched" && i.kind !== "cancelled" && !i.resolution && !(i.code && !i.code_auto);

/** The accountant's code for an e-Fatura document: small coloured square with the number. */
export function CodeBadge({ item, codes }) {
  const c = item.code && codes.find((x) => x.code === item.code);
  if (!c) return html`<span class="code-badge none"></span>`;
  return html`<span class=${"code-badge" + (item.code_auto ? " auto" : "")} title=${c.label + (item.code_auto ? " " + t("(automatic: matched)") : "")}
    style=${c.color ? { background: "#" + c.color, color: "#" + c.text, borderColor: "#" + c.color } : {}}>${c.code}</span>`;
}

function CodePicker({ item, codes, onPick, busy }) {
  const c = item.code && codes.find((x) => x.code === item.code);
  const dot = (x) => html`<span class="code-dot" style=${x.color ? { background: "#" + x.color, borderColor: "#" + x.color } : {}}></span>`;
  const options = codes.map((x) => ({ value: x.code, label: html`${dot(x)}${x.code} · ${x.label}` }));
  if (item.code && !item.code_auto) options.push({ value: 0, label: t("Remove the code"), sep: true });
  return html`<div class="code-row">
    <b>${t("Code")}</b>
    <${Menu} width=${320} value=${item.code} options=${options} onChange=${(v) => !busy && onPick(v || null)}
      label=${c ? html`${dot(c)}${c.code} · ${c.label}` : t("Choose a code…")} />
    ${item.code_auto && html`<small class="muted">${t("Set automatically because the receipt matches. Change it if needed.")}</small>`}
  </div>`;
}
const main = (i) => i.ef || i.receipt;

function Detail({ item, path, reload, codes }) {
  const [thumb, setThumb] = useState(null);
  const [busy, setBusy] = useState(false);
  const rc = item.receipt, ef = item.ef;
  useEffect(() => { setThumb(null); if (rc) api.efatura_thumb(rc.path).then(setThumb); }, [item.id]);
  const act = async (fn) => { setBusy(true); try { await fn(); } finally { setBusy(false); } await reload(); };
  const resolve = (r) => act(() => api.efatura_resolve(path, item.id, r));
  const setCode = (c) => act(() => api.efatura_set_code(path, item.id, c));
  const copy = async () => {
    const d = main(item);
    const text = [`${t("Supplier")}: ${d.supplier}`, `NIF: ${d.nif}`, `${t("Document")}: ${d.number}`, `${t("Date")}: ${d.date}`, `${t("Total")}: ${money(d.total)}`,
      ef && ef.atcud ? `ATCUD: ${ef.atcud}` : ""].filter(Boolean).join("\n");
    if (await api.copy_text(text)) toast(t("Details copied."));
  };
  const k = KIND[item.kind];
  const diffDate = rc && ef && rc.date && ef.date && rc.date !== ef.date;
  const diffTotal = rc && ef && rc.total != null && Math.abs(Number(rc.total) - Number(ef.total)) >= 0.01;
  const rows = [[t("Supplier"), rc && rc.supplier, ef && ef.supplier, false], ["NIF", rc && rc.nif, ef && ef.nif, false],
    [t("Document"), rc && rc.number, ef && ef.number, false], [t("Date"), rc && rc.date, ef && ef.date, diffDate],
    [t("Total"), rc && money(rc.total), ef && money(ef.total), diffTotal]];
  const how = t(item.kind === "matched" ? (item.how === "probable" ? "Probable match: same supplier, date and total" : "Matched by NIF + document number")
    : item.kind === "differ" ? "Matched by NIF + document number"
    : item.kind === "missing" ? "In e-Fatura, but no file in this folder"
    : item.kind === "cancelled" ? (ef && ef.status) || "Cancelled" : "In the folder, but the AT doesn't have it");
  let text, actions;
  if (item.kind === "differ") {
    const parts = [];
    if (diffTotal) parts.push(html`${t("The receipt says")} <b>${money(rc.total)}</b>, ${t("the AT has")} <b>${money(ef.total)}</b>`);
    if (diffDate) parts.push(html`${t("The receipt is dated")} <b>${rc.date}</b>, ${t("the AT has")} <b>${ef.date}</b>`);
    text = html`${parts.map((p, i) => html`${i ? "; " : ""}${p}`)}. ${t("Check the receipt: if the AT is right, use its values (the filename is updated too).")}`;
    actions = html`<button class="btn solid" disabled=${busy} onClick=${() => act(async () => { const r = await api.efatura_use_values(path, item.id); if (r.error) toast(r.error, "warn"); })}>${t("Use e-Fatura values")}</button>
      <button class="btn" disabled=${busy} onClick=${() => resolve("kept")}>${t("Keep receipt values")}</button>`;
  } else if (item.kind === "missing") {
    text = t("The AT has this invoice for the client, but there's no receipt for it in the folder. Find it (it will be read and matched), or give it a code.");
    actions = html`<button class="btn solid" disabled=${busy} onClick=${() => act(async () => { const r = await api.efatura_find_receipt(path, item.id); if (r && r.error) toast(r.error, "warn"); else if (r) toast(t("Added \"{file}\" to the folder.", { file: r.file })); })}>${busy ? t("Reading…") : t("Find the receipt…")}</button>`;
  } else if (item.kind === "cancelled") {
    text = t("The supplier cancelled this document in e-Fatura, so no receipt is expected. It still appears in the Excel export.");
  } else if (item.kind === "not_in_ef") {
    text = t("The AT has no record of this receipt for the client: usually the client's NIF wasn't on it, or the supplier didn't report it. If it should count, register it in e-Fatura (Adquirente › Registar faturas) with these details.");
    actions = html`<button class="btn solid" disabled=${busy} onClick=${() => resolve("registered")}>${t("Registered")}</button>
      <button class="btn" disabled=${busy} onClick=${() => resolve("not_needed")}>${t("Not needed")}</button>`;
  } else {
    text = t("Receipt and e-Fatura agree. Nothing to do.");
  }
  const d = main(item);
  return html`
    <div class="ef-detail">
      <div class="ef-chiprow"><span class=${"chip " + k.cls}>${t(k.title)}</span><small class="muted">${how}</small></div>
      <h2 class="ef-title">${d.supplier || d.nif || t("Unknown supplier")} · ${d.number || t("no number")}</h2>
      <table class="cmp">
        <thead><tr><th>${t("Field")}</th><th>${t("Receipt (app)")}</th><th>${t("e-Fatura (AT)")}</th></tr></thead>
        <tbody>${rows.map(([label, a, b, bad]) => html`<tr class=${bad ? "bad" : ""}><td>${label}</td><td>${rc ? (a || "—") : "—"}</td><td>${ef ? (b || "—") : "—"}</td></tr>`)}</tbody>
      </table>
      <div class="ef-bottom">
        <div class="ef-thumb">${rc ? html`<${Preview} pages=${thumb && thumb.pages} qr=${thumb && thumb.qr} loading=${!thumb} compact=${true} />`
          : html`<div class="no-receipt"><${Icon} name="file" size=${20} /><small>${t("No receipt")}</small></div>`}</div>
        <div class="ef-text">
          ${item.ef_key && html`<${CodePicker} item=${item} codes=${codes} onPick=${setCode} busy=${busy} />`}
          ${item.resolution && item.resolution !== "matched" && item.resolution !== "cancelled" ? html`
            <div class="decided"><${Icon} name="check" size=${14} stroke=${2.5} /> ${t(DECIDED[item.resolution] || "Resolved")}
              <button class="link" onClick=${() => resolve(null)}>${t("Undo")}</button></div>` : html`
            <p class="muted">${text}</p>
            ${actions && html`<div class="btn-row">${actions}</div>`}`}
          <div class="links">
            ${rc && html`<button class="link" onClick=${() => api.open(rc.path)}>${t("Open receipt")} <${Icon} name="external" size=${13} /></button>`}
            ${item.kind !== "matched" && html`<button class="link" onClick=${copy}>${t("Copy details")}</button>`}
          </div>
        </div>
      </div>
    </div>`;
}

/** A button that opens a short list of actions. */
function ActionMenu({ label, solid, options, disabled }) {
  const [openM, setOpen] = useState(false);
  const ref = useRef();
  useEffect(() => {
    if (!openM) return;
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    window.addEventListener("mousedown", away);
    return () => window.removeEventListener("mousedown", away);
  }, [openM]);
  return html`<div class="menu action-menu" ref=${ref}>
    <button class=${"btn" + (solid ? " solid" : "")} disabled=${disabled} onClick=${() => setOpen(!openM)}>${label} <${Icon} name="down" size=${14} /></button>
    ${openM && html`<div class="menu-list right">${options.filter(Boolean).map((o) => html`
      <div class="menu-item" onClick=${() => { setOpen(false); o.run(); }}><b>${o.label}</b>${o.hint && html`<small class="muted block">${o.hint}</small>`}</div>`)}</div>`}
  </div>`;
}

// ---------- Mapping a workbook by hand: header row + what each column is ----------
const emptyLayout = () => ({ header_row: null, cols: {}, code_col: null, year: null });

function toColumns(layout) {  // layout → {columnIndex: fieldKey}
  const m = {};
  if (!layout) return m;
  Object.entries(layout.cols || {}).forEach(([k, i]) => { m[i] = k; });
  if (layout.code_col != null) m[layout.code_col] = "code";
  return m;
}
function fromColumns(header_row, colmap, year, sample) {  // {columnIndex: fieldKey} → layout
  const cols = {};
  let code_col = null;
  Object.entries(colmap).forEach(([i, k]) => { if (!k) return; if (k === "code") code_col = Number(i); else cols[k] = Number(i); });
  const numHeader = header_row && sample[header_row - 1] && cols.number != null ? String(sample[header_row - 1][cols.number] || "") : "";
  return { header_row, cols, code_col, year: year ? Number(year) : null, number_has_atcud: /atcud/i.test(numHeader) && cols.atcud == null };
}
const usable = (lay) => lay && lay.header_row && lay.cols.total != null && (lay.cols.supplier != null || lay.cols.supplier_nif != null);

function SheetMapper({ sheet, fields, state, setState }) {
  const [result, setResult] = useState(null);
  const lay = fromColumns(state.header_row, state.colmap, state.year, sheet.rows);
  useEffect(() => {
    if (state.skip || !usable(lay)) { setResult(null); return; }
    const id = setTimeout(() => api.efatura_workbook_try(sheet.sheet, lay).then(setResult), 250);
    return () => clearTimeout(id);
  }, [JSON.stringify(lay), state.skip]);
  const width = sheet.rows.reduce((w, r) => Math.max(w, r.length), 0);
  const setCol = (i, k) => {
    const colmap = { ...state.colmap };
    if (k) Object.keys(colmap).forEach((j) => { if (colmap[j] === k && k !== "") delete colmap[j]; });  // one column per field
    colmap[i] = k;
    setState({ ...state, colmap });
  };
  const yearNeeded = !sheet.year;
  return html`<div class="mapper">
    <div class="mapper-bar">
      <label class="check-inline"><input type="checkbox" checked=${state.skip} onChange=${(e) => setState({ ...state, skip: e.target.checked })} /> ${t("This sheet has no documents (skip it)")}</label>
      ${yearNeeded && !state.skip && html`<label class="year-in">${t("Year")} <input class="input small mono" value=${state.year || ""} placeholder="2026"
        onInput=${(e) => setState({ ...state, year: e.target.value.replace(/\D/g, "").slice(0, 4) })} /></label>`}
    </div>
    ${!state.skip && html`
      <p class="muted small">${t("1. Click the number of the header row (the row with the column names). 2. Above each column, choose what it is. Columns you leave empty are ignored.")}</p>
      <div class="map-table-wrap"><table class="map-table">
        <thead><tr><th class="rn"></th>${Array.from({ length: width }, (_, i) => html`<th>
          <select class=${state.colmap[i] ? "set" : ""} value=${state.colmap[i] || ""} onChange=${(e) => setCol(i, e.target.value)}>
            <option value="">—</option>${fields.map((f) => html`<option value=${f.key}>${t(f.label)}</option>`)}
          </select></th>`)}</tr></thead>
        <tbody>${sheet.rows.map((r, ri) => html`<tr class=${state.header_row === ri + 1 ? "hdr" : state.header_row && ri + 1 < state.header_row ? "above" : ""}>
          <td class="rn" title=${t("This is the header row")} onClick=${() => setState({ ...state, header_row: ri + 1 })}>${ri + 1}</td>
          ${Array.from({ length: width }, (_, i) => html`<td>${r[i] || ""}</td>`)}</tr>`)}</tbody>
      </table></div>
      <small class="muted">${t("Showing the first {a} of {n} rows.", { a: sheet.rows.length, n: sheet.total_rows })}</small>
      <div class="map-result">
        ${!usable(lay) ? html`<p class="muted small">${t("Still needed:")} ${[!state.header_row && t("the header row"), lay.cols.total == null && t("the Total column"),
            lay.cols.supplier == null && lay.cols.supplier_nif == null && t("the Supplier (or Supplier NIF) column")].filter(Boolean).join(", ")}.</p>`
          : !result ? html`<p class="muted small">${t("Checking…")}</p>` : html`
          <p><b>${tn(result.documents, "{n} document", "{n} documents")}</b> · ${t("{n} with a code", { n: n0(result.coded) })} · ${t("total")} ${money(result.total)}
            ${result.skipped ? html` · <span class="warn">${t("{n} rows without a total are left out", { n: result.skipped })}</span>` : ""}</p>
          ${result.examples.length > 0 && html`<table class="cmp small-cmp"><thead><tr><th>${t("Row")}</th><th>${t("Supplier")}</th><th>NIF</th><th>${t("Document")}</th><th>${t("Date")}</th><th>${t("Total")}</th><th>${t("Code")}</th></tr></thead>
            <tbody>${result.examples.map((d) => html`<tr><td>${d.row}</td><td>${d.supplier_name || "—"}</td><td>${d.supplier_nif || "—"}</td><td>${d.number || "—"}</td>
              <td>${d.date || "—"}</td><td>${money(d.total)}</td><td>${d.code || "—"}</td></tr>`)}</tbody></table>`}
          ${(result.notes || []).filter((n) => !n.includes("read correctly")).map((n) => html`<small class="muted block">· ${n}</small>`)}`}
      </div>`}
  </div>`;
}

function WorkbookMapper({ m, path, onClose, onImported }) {
  const candidates = m.sheets.filter((s) => s.looks_like_data || s.layout);
  const [states, setStates] = useState(() => Object.fromEntries(candidates.map((s) => [s.sheet,
    { header_row: s.layout ? s.layout.header_row : null, colmap: toColumns(s.layout), year: s.year || (s.layout && s.layout.year) || null,
      skip: !!s.suggested_skip }])));
  const [cur, setCur] = useState((candidates.find((s) => !s.layout) || candidates[0] || {}).sheet);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const layoutOf = (s) => fromColumns(states[s.sheet].header_row, states[s.sheet].colmap, states[s.sheet].year, s.rows);
  const ready = (s) => states[s.sheet].skip || (usable(layoutOf(s)) && (s.year || states[s.sheet].year));
  const allReady = candidates.length > 0 && candidates.every(ready) && candidates.some((s) => !states[s.sheet].skip);
  const go = async () => {
    setBusy(true); setErr("");
    const layouts = {}, skip = [];
    candidates.forEach((s) => { if (states[s.sheet].skip) skip.push(s.sheet); else layouts[s.sheet] = layoutOf(s); });
    const r = await api.efatura_workbook_confirm(path, layouts, skip);
    setBusy(false);
    if (r.error) setErr(r.error); else onImported(r.imported);
  };
  const sheet = candidates.find((s) => s.sheet === cur);
  return html`<${Modal} onClose=${busy ? null : onClose} width=${1100}>
    <h2>${t("How should this workbook be read?")}</h2>
    ${m.agent && m.agent.found ? html`<div class="notice info"><p>${t("Gemini worked out the layout of the sheets the app didn't recognise (cost €{cost}). Check each sheet below: the result under the table shows what will be imported. Then press Import.", { cost: m.agent.cost_eur.toFixed(3) })}</p></div>`
      : html`<p class="muted">${t("{file}: the app couldn't tell on its own how some sheets are laid out.", { file: m.file })}
        ${m.agent && m.agent.error ? t("Gemini couldn't help either ({error}).", { error: m.agent.error }) + " " : ""}${t("Show it once and it's remembered for this client.")}</p>`}
    ${candidates.length === 0 ? html`<p class="error small">${t("No sheet in this workbook looks like a list of documents.")}</p>` : html`
      <div class="sheet-tabs">${candidates.map((s) => html`<button class=${"fchip" + (s.sheet === cur ? " on" : "")} onClick=${() => setCur(s.sheet)}>
        ${s.sheet} ${states[s.sheet].skip ? "· " + t("skipped") : !ready(s) ? "· " + t("needs you") : s.layout && s.layout.suggested ? "· " + t("suggested") : "✓"}</button>`)}</div>
      ${sheet && html`<${SheetMapper} key=${sheet.sheet} sheet=${sheet} fields=${m.fields} state=${states[sheet.sheet]}
        setState=${(st) => setStates({ ...states, [sheet.sheet]: st })} />`}`}
    ${err && html`<p class="error small">${err}</p>`}
    <div class="actions"><button class="btn" disabled=${busy} onClick=${onClose}>${t("Cancel")}</button>
      <button class="btn solid" disabled=${!allReady || busy} onClick=${go}>${busy ? t("Importing…") : t("Import")}</button></div>
  <//>
  ${busy && html`<${ImportProgress} title=${t("Importing the client's workbook")} />`}`;
}

/** While a workbook is being read: a bar and the steps as they happen. */
function ImportProgress({ title }) {
  const [steps, setSteps] = useState([]);
  const [fraction, setFraction] = useState(0);
  usePy("wb_progress", (p) => {
    setSteps((old) => (p.start ? [] : old).concat([p.text]).slice(-8));
    if (p.fraction != null) setFraction(p.fraction);
  }, []);
  return html`<${Modal} width=${520}>
    <h2>${title}</h2>
    <div class="bar mt"><div style=${{ width: `${Math.round(fraction * 100)}%` }}></div></div>
    <div class="steps">${steps.map((step, i) => html`<div class=${i === steps.length - 1 ? "now" : "done"}>
      ${i === steps.length - 1 ? html`<span class="spinner small"></span>` : html`<${Icon} name="check" size=${12} stroke=${3} />`} ${step}</div>`)}</div>
  <//>`;
}

function WorkbookReport({ r, path, onClose, onAdjust }) {
  const [applied, setApplied] = useState(false);
  const useDetails = async () => { await api.rename_client(path, r.client_name, r.client_nif); setApplied(true); };
  const allOk = r.report.every((s) => s.ok);
  return html`<${Modal} onClose=${onClose} width=${680}>
    <h2>${t("Workbook imported")}</h2>
    <p class="muted">${t("{file}: {n} documents from {s} year sheets ({new} new for this client).", { file: r.file, n: n0(r.documents), s: r.report.length, new: n0(r.new) })}
      ${!allOk ? t("Some sheets need a look (below).") : r.report.every((x) => x.checked) ? t("Every sheet adds up to the same totals as in Excel.") : ""}</p>
    ${r.offer_details && html`<div class="notice info">
      <p>${t("The workbook is for")} <b>${r.client_name}</b>${r.client_nif ? html` · NIF ${r.client_nif}` : ""}.</p>
      ${applied ? html`<p class="green">${t("✓ Saved as this client's name and NIF.")}</p>` : html`<button class="btn small" onClick=${useDetails}>${t("Use as this client's name and NIF")}</button>`}
    </div>`}
    <div class="wb-report">${r.report.map((s) => html`<div class="wb-sheet">
      <div class="wb-head"><b>${s.sheet}</b>
        <span class="muted">${tn(s.documents, "{n} document", "{n} documents")} · ${t("{n} with a code", { n: n0(s.coded) })}</span>
        <span class=${!s.ok ? "chip small amber" : s.checked ? "chip small green" : "chip small grey"}>${!s.ok ? t("Look at this") : s.checked ? t("✓ Totals match") : t("Not checked")}</span></div>
      ${s.notes.filter((n) => !n.includes("read correctly")).map((n) => html`<small class="muted block">· ${n}</small>`)}
    </div>`)}</div>
    <div class="actions"><button class="link" onClick=${onAdjust}>${t("Check how the columns were read…")}</button><span class="spacer"></span>
      <button class="btn solid" onClick=${onClose}>${t("Done")}</button></div>
  <//>`;
}

export function Efatura({ path, go }) {
  const [info, setInfo] = useState(null);
  const [period, setPeriod] = useState(null);
  const [view, setView] = useState(null);
  const [filter, setFilter] = useState("attention");
  const [sel, setSel] = useState(null);
  const [exported, setExported] = useState(null);
  const [report, setReport] = useState(null);
  const [mapping, setMapping] = useState(null);
  const [limit, setLimit] = useState(300);
  const [busy, setBusy] = useState("");
  const pickPeriod = (f) => {
    // lots of documents (a whole workbook): start on this year instead of everything
    const year = f.periods.find((p) => p.kind === "this_year");
    return f.efatura > 3000 && year ? year : f.periods.find((p) => p.kind !== "custom");
  };
  useEffect(() => {
    ctx.screen = "e-Fatura"; ctx.folder = path;
    api.folder(path).then((f) => { setInfo(f); setPeriod(pickPeriod(f)); });
  }, [path]);
  useEffect(() => setLimit(300), [period]);
  const load = async () => { if (period) setView(await api.efatura_view(path, period.start, period.end)); };
  useEffect(() => { setView(null); load(); }, [period]);
  const importFiles = async () => {
    const r = await api.efatura_import(path);
    if (!r) return;
    if (r.error) toast(r.error, "warn"); else toast(r.message);
    const f = await api.folder(path); setInfo(f); load();
  };
  const imported = async (r) => {
    setMapping(null); setReport(r);
    const f = await api.folder(path); setInfo(f);
    if (!view || !view.stored) setPeriod(pickPeriod(f)); else load();
  };
  const adjust = async () => {
    const r = await api.efatura_import_workbook(path, true);
    if (r && r.mapping) { setReport(null); setMapping(r.mapping); }
  };
  const importWorkbook = async () => {
    setBusy("reading");
    try {
      const r = await api.efatura_import_workbook(path);
      if (!r) return;
      if (r.error) { toast(r.error, "warn"); return; }
      if (r.mapping) { setMapping(r.mapping); return; }  // (Gemini may have pre-filled it)
      await imported(r.imported);
    } finally { setBusy(""); }
  };
  const exp = async () => { const ok = await api.efatura_export(path, period.start, period.end, period.short); if (ok !== null) setExported(ok); };
  const expWorkbook = async () => {
    setBusy("writing");
    try {
      const r = await api.efatura_export_workbook(path);
      if (!r) return;
      if (r.error) { toast(r.error, "warn"); return; }
      const bits = [tn(r.added, "{n} document added", "{n} documents added"), tn(r.codes_changed, "{n} code updated", "{n} codes updated")];
      if (r.new_sheets.length) bits.push(t("new sheet {s}", { s: r.new_sheets.join(", ") }));
      if (await confirmBox({ title: t("Workbook saved"), ok: t("Open it"), cancel: t("Close"),
        text: `${bits.join(" · ")}.\n\n${t("Saved as a new file next to the original:")}\n${r.path.split(/[\\/]/).pop()}` })) api.open(r.path);
    } finally { setBusy(""); }
  };
  const wb = view && view.workbook;
  const importOptions = [
    { label: t("Portal export files (CSV)…"), hint: "e-Fatura › Adquirente › Obter dados para Excel", run: importFiles },
    { label: t("The client's workbook (Excel)…"), hint: wb ? t("Imported {date}: {name}", { date: wb.imported, name: wb.name }) : t("His yearly “Conferência EF” file, with codes"), run: importWorkbook },
  ];
  const exportOptions = [
    wb && { label: t("Update the client's workbook…"), hint: t("A new copy of {name} with everything in the app", { name: wb.name }), run: expWorkbook },
    { label: t("New Excel for this period…"), hint: period ? period.label : "", run: exp },
  ];

  const items = view ? view.items : [];
  const codes = (view && view.codes) || [];
  const count = (f) => items.filter((i) => f === "all" ? true : f === "attention" ? open(i) : i.kind === f).length;
  const shown = items.filter((i) => filter === "all" ? true : filter === "attention" ? open(i) : i.kind === filter);
  const selected = shown.find((i) => i.id === sel) || shown[0];
  const resolved = items.filter((i) => !open(i)).length;
  const attention = count("attention");
  const name = info ? info.name : "";
  return html`
    <${TopBar} onBack=${() => go("folder", path)} title=${`e-Fatura · ${name}`}
        sub=${view && view.stored ? `${t("{a} of {n} resolved", { a: n0(resolved), n: n0(items.length) })} · ${tn(attention, "{n} needs attention", "{n} need attention")}` : ""}
        progress=${view && view.stored ? (items.length ? resolved / items.length : 1) : null}>
      <${FeedbackButton} />
      ${info && period && html`<${PeriodMenu} periods=${info.periods} custom=${info.custom} value=${period} onChange=${setPeriod} />`}
      ${busy ? html`<span class="muted small">${busy === "writing" ? t("Writing the workbook…") : t("Reading the workbook…")}</span>` : html`
        <${ActionMenu} label=${t("Import")} options=${importOptions} />
        <${ActionMenu} label=${exported === true ? t("✓ Exported") : exported === false ? t("Export failed") : t("Export")} solid=${true}
          disabled=${!(view && view.stored)} options=${exportOptions} />`}
    <//>
    ${view && !view.stored ? html`
      <div class="center-page"><div class="center-col">
        <h1>${t("No e-Fatura data for this client yet")}</h1>
        <p class="lead">${t("In the Portal das Finanças: e-Fatura › Faturação › Adquirente › choose the period › Pesquisar › \"Obter dados para Excel\". You can import one file per month or quarter.")}</p>
        <p class="lead">${t("Or start from the client's own yearly workbook (\"Conferência EF\"): its documents and codes come in, and the app can write new quarters back into it.")}</p>
        <div class="btn-row"><button class="btn primary" disabled=${!!busy} onClick=${importFiles}>${t("Import export files…")}</button>
          <button class="btn big" disabled=${!!busy} onClick=${importWorkbook}>${busy ? t("Reading the workbook…") : t("Import the client's workbook…")}</button></div>
      </div></div>` : html`
      <div class="ef">
        <div class="ef-list">
          <div class="chips">${FILTERS.map(([k, l]) => html`<button class=${"fchip" + (filter === k ? " on" : "")} onClick=${() => { setFilter(k); setSel(null); }}>${t(l)} · ${n0(count(k))}</button>`)}</div>
          <div class="ef-items">
            ${view && shown.length === 0 && html`<p class="muted pad">${filter === "attention" ? (items.length ? t("All resolved for this period.") : t("No invoices in this period.")) : t("None.")}</p>`}
            ${shown.slice(0, limit).map((i) => { const d = main(i); return html`
              <div class=${"ef-item" + (selected && selected.id === i.id ? " on" : "")} onClick=${() => setSel(i.id)}>
                <span class=${"chip small " + KIND[i.kind].cls + (open(i) || i.kind === "matched" || i.kind === "cancelled" ? "" : " faded")}>${!open(i) && i.kind !== "matched" && i.kind !== "cancelled" ? t("✓ Done") : t(KIND[i.kind].chip)}</span>
                <div class="ef-item-text"><b>${d.supplier || d.nif}</b><small class="muted">${niceDate(d.date, true)} · ${d.number}</small></div>
                <span class=${"ef-total" + (i.kind === "differ" ? " strong" : "")}>${money(d.total)}</span>
                <${CodeBadge} item=${i} codes=${codes} />
              </div>`; })}
            ${shown.length > limit && html`<button class="btn small more" onClick=${() => setLimit(limit + 500)}>${t("Show more ({n} more)", { n: n0(shown.length - limit) })}</button>`}
          </div>
        </div>
        <div class="ef-right">${selected ? html`<${Detail} key=${selected.id} item=${selected} path=${path} reload=${load} codes=${codes} />` : view && html`<p class="muted pad">${t("Nothing selected.")}</p>`}</div>
      </div>`}
    ${busy === "reading" && html`<${ImportProgress} title=${t("Importing the client's workbook")} />`}
    ${report && html`<${WorkbookReport} r=${report} path=${path} onAdjust=${adjust} onClose=${() => { setReport(null); load(); }} />`}
    ${mapping && html`<${WorkbookMapper} m=${mapping} path=${path} onClose=${() => setMapping(null)} onImported=${imported} />`}`;
}
