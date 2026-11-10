// Review: file list · preview (zoom, QR outline) · fields. Values come from history, filename, QR or Gemini.
import { useEffect, useRef, useState } from "../vendor/hooks.mjs";
import { api, ctx, FeedbackButton, html, Icon, Modal, plural, StatusDot, Toggle, TopBar, usePy, Spinner } from "../ui.js";

export function Preview({ pages, qr, loading, compact = false }) {
  const [zoom, setZoom] = useState(1);
  const box = useRef();
  useEffect(() => setZoom(1), [pages]);
  useEffect(() => {
    const el = box.current;
    if (!el || compact) return;
    const wheel = (e) => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); setZoom((z) => Math.min(4, Math.max(0.5, z * (e.deltaY < 0 ? 1.1 : 0.9)))); } };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [compact]);
  return html`
    <div class="preview" ref=${box}>
      ${loading ? html`<div class="preview-msg">Loading preview…</div>` : !pages || !pages.length ? html`<div class="preview-msg">No preview for this file.</div>` : html`
        <div class="pages" style=${{ width: compact ? "100%" : `calc(min(100% - 48px, 720px) * ${zoom})` }}>
          ${pages.map((p, i) => html`<div class="page-img">
            <img src=${p.src} draggable="false" />
            ${qr && qr.page === i && html`<div class="qr-box" title="Official AT QR code" style=${{ left: `${qr.box[0] * 100}%`, top: `${qr.box[1] * 100}%`, width: `${(qr.box[2] - qr.box[0]) * 100}%`, height: `${(qr.box[3] - qr.box[1]) * 100}%` }}></div>`}
          </div>`)}
        </div>`}
      ${!compact && pages && pages.length > 0 && html`<div class="zoom">
        <button title="Zoom out" onClick=${() => setZoom(Math.max(0.5, zoom / 1.25))}><${Icon} name="minus" size=${14} /></button>
        <button class="zoom-pct" title="Fit" onClick=${() => setZoom(1)}>${Math.round(zoom * 100)}%</button>
        <button title="Zoom in" onClick=${() => setZoom(Math.min(4, zoom * 1.25))}><${Icon} name="plus" size=${14} /></button>
      </div>`}
    </div>`;
}

function RenameDialog({ info, onCancel, onGo }) {
  const [dest, setDest] = useState(info.dest);
  const [del, setDel] = useState(info.delete);
  const [busy, setBusy] = useState(false);
  const notes = [];
  if (info.done) notes.push(`${info.done} already renamed or duplicates (left as they are)`);
  if (info.skipped) notes.push(`${info.skipped} without values (skipped, left untouched)`);
  return html`<${Modal} onClose=${busy ? null : onCancel} width=${520}>
    <h2>Rename ${plural(info.todo, "file")}</h2>
    ${notes.length > 0 && html`<p class="muted small">${notes.join(" · ")}</p>`}
    <div class="eyebrow mt">Save to</div>
    <div class="dest-box"><span class="ellipsis">${dest}</span><button class="link" onClick=${async () => { const d = await api.review_choose_dest(dest); if (d) setDest(d); }}>Change</button></div>
    <div class="toggle-row"><${Toggle} on=${del} onChange=${setDel} />
      <div><b>Delete the originals</b><small class="muted">Only after each renamed copy is saved</small></div></div>
    <div class="actions"><button class="btn" disabled=${busy} onClick=${onCancel}>Cancel</button>
      <button class="btn solid" disabled=${busy} onClick=${() => { setBusy(true); onGo(dest, del); }}>${busy ? "Renaming…" : "Rename"}</button></div>
  <//>`;
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
  const curRef = useRef(0);
  const filesRef = useRef([]);
  const dirty = useRef(false);

  useEffect(() => {
    ctx.screen = "Review"; ctx.folder = path;
    api.review_start(path).then((s) => {
      if (s.error === "no_key") { go("welcome", { then: ["folder", path] }); return; }
      setSession(s); setFiles(s.files); filesRef.current = s.files;
      if (s.files.length) show(0);
      api.review_summary().then(setSummary);
    });
  }, [path]);

  const loadDetail = async (name) => {
    const d = await api.review_file(name);
    if (!d || filesRef.current[curRef.current]?.name !== name) return;
    dirty.current = false;
    setDetail(d); setForm(d.form); setResult(d.result || "");
  };
  const show = (i) => {
    curRef.current = i; setCur(i);
    const name = filesRef.current[i].name;
    setDetail(null); setPreview(null);
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
  const doRename = async (dest, del) => { const r = await api.review_rename(dest, del); setRenaming(null); onDone(r); };
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

  if (!session) return html`<${TopBar} onBack=${() => go("folder", path)} title="Starting…" />`;
  const n = files.length;
  const reading = files.filter((f) => f.state === "reading").length;
  const attention = files.filter((f) => f.state === "warning" || f.state === "error").length;
  let sub = reading ? `${n - reading} of ${n} read` : `All ${n} read`;
  if (attention) sub += ` · ${attention} need${attention === 1 ? "s" : ""} attention`;
  const todo = summary ? summary.todo : 0;
  const file = files[cur];
  const last = cur === n - 1;

  return html`
    <${TopBar} onBack=${back} title=${session.name} sub=${sub} progress=${n ? (n - reading) / n : 1}>
      <${FeedbackButton} />
      <button class="btn" onClick=${exp}>${exported === true ? "✓ Exported" : exported === false ? "Export failed" : "Export to Excel"}</button>
      <button class="btn solid" disabled=${!todo || reading > 0} onClick=${openRename}>${todo ? `Rename ${plural(todo, "file")}` : "Nothing to rename"}</button>
    <//>
    ${n === 0 ? html`<div class="center-page"><div class="center-col"><h1>No invoices here</h1><p class="lead">This folder has no PDFs or photos of invoices.</p></div></div>` : html`
    <div class="review">
      <div class="files">
        <div class="eyebrow pad">Invoices</div>
        <div class="file-list">
          ${files.map((f, i) => html`<div class=${"file-row" + (i === cur ? " on" : "") + (f.state === "reading" ? " dim" : "")} onClick=${() => goto(i)}>
            <${StatusDot} state=${f.state} /><span class="ellipsis">${f.name}</span></div>`)}
        </div>
      </div>
      <${Preview} pages=${preview && preview.pages} qr=${preview && preview.qr} loading=${!preview} />
      <div class="panel">
        <small class="muted">Invoice ${cur + 1} of ${n}</small>
        <h3 class="file-title">${file.name}</h3>
        <div class="panel-scroll">
          ${!detail || detail.state === "reading" ? html`<div class="reading"><div class="indeterminate"><div></div></div><p class="muted">Reading this invoice…</p></div>` : html`
            ${detail.notice && html`<div class=${"notice " + detail.notice.kind}>
              <p>${detail.notice.text}</p>
              ${detail.notice.retry && html`<button class="btn small" onClick=${retry}>Read again with Gemini</button>`}
            </div>`}
            <div class="form">
              ${session.fields.map((f) => html`<label class=${"fld" + (f.type === "text" ? " full" : "")}>
                <span>${f.label}</span>
                <input class="input" value=${form[f.key] || ""} placeholder=${f.type === "date" ? "YYYY.MM.DD" : f.type === "number" ? "0.00" : ""}
                  onInput=${(e) => edit(f.key, e.target.value)} />
              </label>`)}
            </div>
            <div class="result"><div class="eyebrow">Will be saved as</div><p class="mono">${result || "…"}</p></div>`}
        </div>
        <div class="nav">
          <button class="btn icon big" disabled=${cur === 0} onClick=${prev}><${Icon} name="left" /></button>
          <button class="btn primary grow" onClick=${next}>${last ? "Looks right" : "Looks right · Next"} <${Icon} name="right" /></button>
        </div>
      </div>
    </div>`}
    ${renaming && html`<${RenameDialog} info=${renaming} onCancel=${() => setRenaming(null)} onGo=${doRename} />`}`;
}
