// Review: file list · preview (zoom, QR outline) · fields. Values come from history, filename, QR or Gemini.
import { useEffect, useRef, useState } from "../vendor/hooks.mjs";
import { api, Calendar, ctx, FeedbackButton, html, Icon, Modal, money, niceDate, plural, StatusDot, t, tn, Toggle, TopBar, usePy, Spinner } from "../ui.js";

export function Preview({ pages, qr, qrs = [], focus = null, loading, compact = false }) {
  const [zoom, setZoom] = useState(1);
  const box = useRef();
  useEffect(() => setZoom(1), [pages]);
  useEffect(() => {  // a row of the invoices table was clicked: bring its QR code into view
    if (focus == null || !box.current) return;
    const el = box.current.querySelector(`.qr-box[data-n="${focus}"]`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focus]);
  useEffect(() => {
    const el = box.current;
    if (!el || compact) return;
    const wheel = (e) => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); setZoom((z) => Math.min(4, Math.max(0.5, z * (e.deltaY < 0 ? 1.1 : 0.9)))); } };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [compact]);
  return html`
    <div class="preview" ref=${box}>
      ${loading ? html`<div class="preview-msg">${t("Loading preview…")}</div>` : !pages || !pages.length ? html`<div class="preview-msg">${t("No preview for this file.")}</div>` : html`
        <div class="pages" style=${{ width: compact ? "100%" : `calc(min(100% - 48px, 720px) * ${zoom})` }}>
          ${pages.map((p, i) => html`<div class="page-img">
            <img src=${p.src} draggable="false" />
            ${qr && qr.page === i && html`<div class="qr-box" title=${t("Official AT QR code")} style=${{ left: `${qr.box[0] * 100}%`, top: `${qr.box[1] * 100}%`, width: `${(qr.box[2] - qr.box[0]) * 100}%`, height: `${(qr.box[3] - qr.box[1]) * 100}%` }}></div>`}
            ${qrs.filter((q) => q.page === i).map((q) => html`<div class=${"qr-box numbered" + (focus === q.n ? " focus" : "")} data-n=${q.n}
              title=${t("Invoice {n}: official AT QR code", { n: q.n })}
              style=${{ left: `${q.box[0] * 100}%`, top: `${q.box[1] * 100}%`, width: `${(q.box[2] - q.box[0]) * 100}%`, height: `${(q.box[3] - q.box[1]) * 100}%` }}>
              <span class="qr-n">${q.n}</span></div>`)}
          </div>`)}
        </div>`}
      ${!compact && pages && pages.length > 0 && html`<div class="zoom">
        <button title=${t("Zoom out")} onClick=${() => setZoom((z) => Math.max(0.5, z / 1.25))}><${Icon} name="minus" size=${14} /></button>
        <button class="zoom-pct" title=${t("Fit")} onClick=${() => setZoom(1)}>${Math.round(zoom * 100)}%</button>
        <button title=${t("Zoom in")} onClick=${() => setZoom((z) => Math.min(4, z * 1.25))}><${Icon} name="plus" size=${14} /></button>
      </div>`}
    </div>`;
}

function RenameDialog({ info, onCancel, onGo }) {
  const [dest, setDest] = useState(info.dest);
  const [del, setDel] = useState(info.delete);
  const [split, setSplit] = useState(info.split);
  const [busy, setBusy] = useState(false);
  const notes = [];
  if (info.done) notes.push(t("{n} already renamed or duplicates (left as they are)", { n: info.done }));
  if (info.skipped) notes.push(t("{n} without values (skipped, left untouched)", { n: info.skipped }));
  return html`<${Modal} onClose=${busy ? null : onCancel} width=${520}>
    <h2>${tn(info.todo, "Rename {n} file", "Rename {n} files")}</h2>
    ${notes.length > 0 && html`<p class="muted small">${notes.join(" · ")}</p>`}
    <div class="eyebrow mt">${t("Save to")}</div>
    <div class="dest-box"><span class="ellipsis">${dest}</span><button class="link" onClick=${async () => { const d = await api.review_choose_dest(dest); if (d) setDest(d); }}>${t("Change")}</button></div>
    <div class="toggle-row"><${Toggle} on=${del} onChange=${setDel} />
      <div><b>${t("Delete the originals")}</b><small class="muted">${t("Only after each renamed copy is saved")}</small></div></div>
    ${info.multi > 0 && html`<div class="multi-choice">
      <b>${tn(info.multi, "{n} PDF has several invoices", "{n} PDFs have several invoices")}</b>
      <div class="seg wide mt-s">
        <button class=${split ? "on" : ""} onClick=${() => setSplit(true)}>${t("One copy per invoice")}</button>
        <button class=${!split ? "on" : ""} onClick=${() => setSplit(false)}>${t("A single file")}</button>
      </div>
      <small class="muted">${split ? t("The same PDF is saved once per invoice, each copy named after its invoice.") : t("The PDF is renamed once, after the document itself.")} ${t("Your choice is remembered.")}</small>
    </div>`}
    <div class="actions"><button class="btn" disabled=${busy} onClick=${onCancel}>${t("Cancel")}</button>
      <button class="btn solid" disabled=${busy} onClick=${() => { setBusy(true); onGo(dest, del, info.multi > 0 ? split : null); }}>${busy ? t("Renaming…") : t("Rename")}</button></div>
  <//>`;
}

/** A date in the review form: typed as 2026.10.06 (quick to correct a digit), or picked on the calendar. */
function DateInput({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const iso = /^(\d{4})[.\-\/](\d{2})[.\-\/](\d{2})$/.test(value) ? value.replace(/[.\/]/g, "-") : "";
  return html`<div class="date-input">
    <div class="date-input-row">
      <input class="input" value=${value} placeholder="YYYY.MM.DD" onInput=${(e) => onChange(e.target.value)} />
      <button class=${"cal-in" + (open ? " on" : "")} type="button" title=${t("Choose on a calendar")} onClick=${() => setOpen(!open)}><${Icon} name="calendar" size=${15} /></button>
    </div>
    ${open && html`<div class="cal-inline"><${Calendar} value=${iso} onPick=${(d) => { setOpen(false); onChange(d.replace(/-/g, ".")); }} /></div>`}
  </div>`;
}

/** A PDF with several invoices (Via Verde, EDP…): each one, from its QR code, and how its copy will be named. */
function InvoicesInside({ inv, focus, onFocus }) {
  return html`<div class="inside">
    <div class="eyebrow">${tn(inv.items.length, "This PDF has {n} invoice", "This PDF has {n} invoices")}</div>
    <div class="inside-list">${inv.items.map((x, i) => html`
      <div class=${"inside-item" + (focus === i + 1 ? " on" : "")} onClick=${() => onFocus(i + 1)}
          title=${inv.names && inv.names[i] ? t("Copy: {name}", { name: inv.names[i] }) : ""}>
        <span class="n">${i + 1}</span>
        <div class="body">
          <div class="line1"><b class="ellipsis">${x.supplier || x.nif || "—"}</b>
            <span class="amt" title=${x.credit ? t("Credit note: subtracts") : ""}>${x.credit ? "−" : ""}${money(x.total)}</span></div>
          <div class="line2"><span class="ellipsis">${x.number}</span><span class="d">${niceDate(x.date, true)}</span>
            ${x.qr && html`<span class="qr-ok" title=${t("From its official AT QR code")}>QR</span>`}</div>
        </div>
      </div>`)}</div>
    <small class=${inv.sum_ok ? "green" : "muted"}>${inv.sum_ok ? t("✓ The invoices add up to the document's total ({sum})", { sum: money(inv.sum) })
      : t("The invoices add up to {sum}; the document's total is {total}", { sum: money(inv.sum), total: inv.total == null ? "—" : money(inv.total) })}</small>
    ${inv.clone != null && html`<small class="muted block">${t("This file is the copy for invoice {n}.", { n: inv.clone + 1 })}</small>`}
  </div>`;
}

const PANEL_DEFAULT = 340;
const FILES_DEFAULT = 248;

/** "✓ no documento" / "?" next to a value: whether it is really printed in the PDF's text. */
const InText = ({ ok }) => ok == null ? null : ok
  ? html`<span class="in-text ok" title=${t("Found in the PDF's text")}>✓ ${t("in the document")}</span>`
  : html`<span class="in-text no" title=${t("Not found in the PDF's text: check it on the preview")}>? ${t("not found in the text")}</span>`;

/** Documento | 1 | 2 | 3 | 4 — which values the fields show. */
function InvoiceTabs({ n, tab, onTab }) {
  return html`<div class="inv-tabs">
    <button class=${tab == null ? "on" : ""} onClick=${() => onTab(null)}>${t("Document")}</button>
    ${Array.from({ length: n }, (_, i) => html`<button class=${tab === i ? "on" : ""} title=${t("Invoice {n}", { n: i + 1 })} onClick=${() => onTab(i)}>${i + 1}</button>`)}
  </div>`;
}

/** One invoice inside the PDF, every value read for it (read-only: they come from its official QR code). */
function InvoiceValues({ x, i, n }) {
  const row = (label, value, extra) => html`<div class="iv-field"><span>${label}</span><div class="iv-value">${value || "—"} ${extra || ""}</div></div>`;
  const amount = (v) => (v == null || v === "") ? "" : `${x.credit ? "−" : ""}${money(v)} €`;
  return html`<div class="iv">
    <div class="iv-head"><b>${t("Invoice {a} of {n}", { a: i + 1, n })}</b>
      ${x.qr ? html`<span class="qr-ok">QR</span> <small class="muted">${t("values from its official AT QR code")}</small>`
        : html`<small class="muted">${t("values read by Gemini (no QR code)")}</small>`}</div>
    <div class="iv-grid">
      ${row(t("Date"), niceDate(x.date, true))}
      ${row(t("Total"), amount(x.total), x.credit ? html`<small class="muted">${t("credit note")}</small>` : "")}
      ${row(t("Invoice no."), x.number, html`<${InText} ok=${x.number_ok} />`)}
      ${row(t("Type"), x.doc_type)}
      ${row(t("Supplier"), x.supplier, html`<${InText} ok=${x.name_ok} />`)}
      ${row("NIF", x.nif)}
      ${row(t("VAT"), amount(x.vat))}
    </div>
  </div>`;
}

export function Review({ path, go, onDone }) {
  const [session, setSession] = useState(null);
  const [files, setFiles] = useState([]);
  const [cur, setCur] = useState(0);
  const [detail, setDetail] = useState(null);
  const [form, setForm] = useState({});
  const [result, setResult] = useState("");
  const [preview, setPreview] = useState(null);
  const [summary, setSummary] = useState(null);
  const [renaming, setRenaming] = useState(null);
  const [exported, setExported] = useState(null);
  const [focusQr, setFocusQr] = useState(null);
  const tab = focusQr == null ? null : focusQr - 1;  // which invoice the fields show (null = the document)
  const setTab = (i) => setFocusQr(i == null ? null : i + 1);
  const [filesW, setFilesW] = useState(FILES_DEFAULT);
  const startFilesDrag = (e) => {
    e.preventDefault();
    const x0 = e.clientX, w0 = filesW;
    let w = w0;
    const move = (ev) => { w = Math.max(180, Math.min(520, w0 + (ev.clientX - x0))); setFilesW(w); };
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); document.body.classList.remove("resizing"); if (w !== w0) api.set_panel_width(w, "files"); };
    document.body.classList.add("resizing");
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };
  const [panelW, setPanelW] = useState(PANEL_DEFAULT);
  const startPanelDrag = (e) => {
    e.preventDefault();
    const x0 = e.clientX, w0 = panelW;
    let w = w0;
    const move = (ev) => { w = Math.max(300, Math.min(760, w0 - (ev.clientX - x0))); setPanelW(w); };
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); document.body.classList.remove("resizing"); if (w !== w0) api.set_panel_width(w); };
    document.body.classList.add("resizing");
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };
  const curRef = useRef(0);
  const filesRef = useRef([]);
  const dirty = useRef(false);

  useEffect(() => {
    ctx.screen = "Review"; ctx.folder = path;
    api.review_start(path).then((s) => {
      if (s.error === "no_key") { go("welcome", { then: ["folder", path] }); return; }
      setSession(s); setFiles(s.files); filesRef.current = s.files;
      if (s.panel_width) setPanelW(s.panel_width);
      if (s.files_width) setFilesW(s.files_width);
      if (s.files.length) show(0);
      api.review_summary().then(setSummary);
    });
  }, [path]);

  const loadDetail = async (name) => {
    const d = await api.review_file(name);
    if (!d || filesRef.current[curRef.current]?.name !== name) return;
    dirty.current = false;
    setDetail(d); setForm(d.form); setResult(d.result || "");
    if (d.invoices && d.invoices.clone != null) setFocusQr(d.invoices.clone + 1);  // a copy: its own invoice
  };
  const show = (i) => {
    curRef.current = i; setCur(i);
    const name = filesRef.current[i].name;
    setDetail(null); setPreview(null); setFocusQr(null);
    loadDetail(name);
    api.review_preview(name).then((p) => { if (filesRef.current[curRef.current]?.name === name) setPreview(p); });
  };

  let pending = useRef(null);
  usePy("file", (f) => {
    const list = filesRef.current.map((x) => x.name === f.name ? f : x);
    const before = filesRef.current.find((x) => x.name === f.name);
    filesRef.current = list; setFiles(list);
    const current = list[curRef.current];
    if (current && current.name === f.name && (!dirty.current || (before && before.state === "reading"))) loadDetail(f.name);
    clearTimeout(pending.current);
    pending.current = setTimeout(() => api.review_summary().then(setSummary), 150);
  }, []);

  const save = async () => {
    const name = filesRef.current[curRef.current]?.name;
    if (!name || !detail || detail.state === "reading") return;
    const f = await api.review_confirm(name, form);
    if (f) { const list = filesRef.current.map((x) => x.name === f.name ? f : x); filesRef.current = list; setFiles(list); }
    api.review_summary().then(setSummary);
  };
  const goto = async (i) => { await save(); show(i); };
  const next = async () => { await save(); if (cur < files.length - 1) show(cur + 1); };
  const prev = async () => { await save(); if (cur > 0) show(cur - 1); };
  const edit = (key, v) => {
    dirty.current = true;
    const f = { ...form, [key]: v };
    setForm(f);
    api.review_filename(files[cur].name, f).then(setResult);
  };
  const retry = async () => {
    const name = files[cur].name;
    await api.review_retry(name);
    dirty.current = false;
    loadDetail(name);
  };
  const back = async () => { await save(); await api.review_close(); go("folder", path); };
  const openRename = async () => { await save(); setRenaming(await api.review_rename_info()); };
  const doRename = async (dest, del, split) => { const r = await api.review_rename(dest, del, split); setRenaming(null); onDone(r); };
  const exp = async () => { await save(); const ok = await api.review_export(); if (ok !== null) setExported(ok); };

  useEffect(() => {
    const key = (e) => {
      if (e.key !== "Enter" || renaming || document.querySelector(".overlay")) return;
      if (e.target && (e.target.tagName === "BUTTON" || e.target.tagName === "TEXTAREA")) return;
      e.preventDefault(); next();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  if (!session) return html`<${TopBar} onBack=${() => go("folder", path)} title=${t("Starting…")} />`;
  const n = files.length;
  const reading = files.filter((f) => f.state === "reading").length;
  const attention = files.filter((f) => f.state === "warning" || f.state === "error").length;
  let sub = reading ? t("{a} of {n} read", { a: n - reading, n }) : t("All {n} read", { n });
  if (attention) sub += " · " + tn(attention, "{n} needs attention", "{n} need attention");
  const todo = summary ? summary.todo : 0;
  const file = files[cur];
  const last = cur === n - 1;

  return html`
    <${TopBar} onBack=${back} title=${session.name} sub=${sub} progress=${n ? (n - reading) / n : 1}>
      <${FeedbackButton} />
      <button class="btn" onClick=${exp}>${exported === true ? t("✓ Exported") : exported === false ? t("Export failed") : t("Export to Excel")}</button>
      <button class="btn solid" disabled=${!todo || reading > 0} onClick=${openRename}>${todo ? tn(todo, "Rename {n} file", "Rename {n} files") : t("Nothing to rename")}</button>
    <//>
    ${n === 0 ? html`<div class="center-page"><div class="center-col"><h1>${t("No invoices here")}</h1><p class="lead">${t("This folder has no PDFs or photos of invoices.")}</p></div></div>` : html`
    <div class="review">
      <div class="files" style=${{ width: `${filesW}px` }}>
        <div class="files-resize" title=${t("Drag to change the width · double-click: automatic")}
          onMouseDown=${startFilesDrag} onDblClick=${() => { setFilesW(FILES_DEFAULT); api.set_panel_width(null, "files"); }}></div>
        <div class="eyebrow pad">${t("Invoices")}</div>
        <div class="file-list">
          ${files.map((f, i) => html`<div class=${"file-row" + (i === cur ? " on" : "") + (f.state === "reading" ? " dim" : "")} onClick=${() => goto(i)}>
            <${StatusDot} state=${f.state} /><span class="ellipsis">${f.name}</span>
            ${f.parts > 1 && html`<span class="parts-tag" title=${t("This PDF has {n} invoices", { n: f.parts })}>${tn(f.parts, "{n} invoice", "{n} invoices")}</span>`}</div>`)}
        </div>
      </div>
      <${Preview} pages=${preview && preview.pages} qr=${preview && preview.qr} qrs=${(preview && preview.qrs) || []} focus=${focusQr} loading=${!preview} />
      <div class="panel" style=${{ width: `${panelW}px` }}>
        <div class="panel-resize" title=${t("Drag to change the width · double-click: automatic")}
          onMouseDown=${startPanelDrag} onDblClick=${() => { setPanelW(PANEL_DEFAULT); api.set_panel_width(null); }}></div>
        <small class="muted">${t("Invoice {a} of {n}", { a: cur + 1, n })}</small>
        <h3 class="file-title">${file.name}</h3>
        <div class="panel-scroll">
          ${!detail || detail.state === "reading" ? html`<div class="reading"><div class="indeterminate"><div></div></div><p class="muted">${t("Reading this invoice…")}</p></div>` : html`
            ${detail.notice && html`<div class=${"notice " + detail.notice.kind}>
              <p>${detail.notice.text}</p>
              ${detail.notice.retry && html`<button class="btn small" onClick=${retry}>${t("Read again with Gemini")}</button>`}
            </div>`}
            ${detail.invoices && html`<${InvoiceTabs} n=${detail.invoices.items.length} tab=${tab} onTab=${setTab} />`}
            ${detail.invoices && tab != null && detail.invoices.items[tab] ? html`<${InvoiceValues} x=${detail.invoices.items[tab]} i=${tab} n=${detail.invoices.items.length} />` : html`
            <div class="form">
              ${session.fields.map((f) => html`<label class=${"fld" + (f.type === "text" ? " full" : "")}>
                <span>${t(f.label)}${detail.invoices && form[f.key] && (f.key === "invoice_number" || f.key === "supplier")
                  ? html` <${InText} ok=${f.key === "invoice_number" ? detail.invoices.doc_number_ok : detail.invoices.doc_supplier_ok} />` : ""}</span>
                ${f.type === "date" ? html`<${DateInput} value=${form[f.key] || ""} onChange=${(v) => edit(f.key, v)} />` : html`
                <input class="input" value=${form[f.key] || ""} placeholder=${f.type === "number" ? "0.00" : ""}
                  onInput=${(e) => edit(f.key, e.target.value)} />`}
              </label>`)}
            </div>
            `}
            ${detail.invoices && html`<${InvoicesInside} inv=${detail.invoices} focus=${focusQr} onFocus=${setFocusQr} />`}
            <div class="result"><div class="eyebrow">${t("Will be saved as")}</div>
              ${!detail.invoices ? html`<p class="mono">${result || "…"}</p>`
                : detail.invoices.clone != null ? html`<p class="mono">${file.name}</p><small class="muted">${t("This file is the copy for invoice {n}.", { n: detail.invoices.clone + 1 })}</small>`
                : detail.invoices.split ? (tab != null
                    ? html`<p class="mono">${detail.invoices.names[tab] || "…"}</p><small class="muted">${t("The copy for invoice {n} (one copy per invoice).", { n: tab + 1 })}</small>`
                    : html`<p>${tn(detail.invoices.items.length, "{n} file, one per invoice", "{n} files, one per invoice")}</p><small class="muted">${t("Choose an invoice above to see its file name. You can change this when renaming.")}</small>`)
                : (tab != null
                    ? html`<p class="mono">${result || "…"}</p><small class="muted">${t("“A single file” is chosen: the PDF keeps one name, the document's.")}</small>`
                    : html`<p class="mono">${result || "…"}</p>`)}
            </div>`}
        </div>
        <div class="nav">
          <button class="btn icon big" disabled=${cur === 0} onClick=${prev}><${Icon} name="left" /></button>
          <button class="btn primary grow" onClick=${next}>${last ? t("Looks right") : t("Looks right · Next")} <${Icon} name="right" /></button>
        </div>
      </div>
    </div>`}
    ${renaming && html`<${RenameDialog} info=${renaming} onCancel=${() => setRenaming(null)} onGo=${doRename} />`}`;
}
