// e-Fatura reconciliation: the client's receipts vs. the AT's list, one case at a time.
import { useEffect, useState } from "../vendor/hooks.mjs";
import { api, ctx, FeedbackButton, html, Icon, niceDate, plain2, toast, TopBar } from "../ui.js";
import { PeriodMenu } from "./folder.js";
import { Preview } from "./review.js";

const KIND = {
  differ: { chip: "≠ Differs", title: "≠ Values differ", cls: "red" },
  missing: { chip: "No receipt", title: "No receipt", cls: "amber" },
  not_in_ef: { chip: "Not in e-Fat.", title: "Not in e-Fatura", cls: "amber" },
  matched: { chip: "Matched", title: "✓ Matched", cls: "green" },
};
const DECIDED = { not_needed: "Marked as not needed", kept: "Kept the receipt's values", registered: "Marked as registered in e-Fatura" };
const FILTERS = [["attention", "Needs attention"], ["missing", "No receipt"], ["not_in_ef", "Not in e-Fatura"], ["differ", "Differs"], ["all", "All"]];

const open = (i) => i.kind !== "matched" && !i.resolution;
const main = (i) => i.ef || i.receipt;

function Detail({ item, path, reload }) {
  const [thumb, setThumb] = useState(null);
  const [busy, setBusy] = useState(false);
  const rc = item.receipt, ef = item.ef;
  useEffect(() => { setThumb(null); if (rc) api.efatura_thumb(rc.path).then(setThumb); }, [item.id]);
  const act = async (fn) => { setBusy(true); try { await fn(); } finally { setBusy(false); } await reload(); };
  const resolve = (r) => act(() => api.efatura_resolve(path, item.id, r));
  const copy = async () => {
    const d = main(item);
    const text = [`Supplier: ${d.supplier}`, `NIF: ${d.nif}`, `Document: ${d.number}`, `Date: ${d.date}`, `Total: ${plain2(d.total)}`,
      ef && ef.atcud ? `ATCUD: ${ef.atcud}` : ""].filter(Boolean).join("\n");
    if (await api.copy_text(text)) toast("Details copied.");
  };
  const k = KIND[item.kind];
  const diffDate = rc && ef && rc.date && ef.date && rc.date !== ef.date;
  const diffTotal = rc && ef && rc.total != null && Math.abs(Number(rc.total) - Number(ef.total)) >= 0.01;
  const rows = [["Supplier", rc && rc.supplier, ef && ef.supplier, false], ["NIF", rc && rc.nif, ef && ef.nif, false],
    ["Document", rc && rc.number, ef && ef.number, false], ["Date", rc && rc.date, ef && ef.date, diffDate],
    ["Total", rc && plain2(rc.total), ef && plain2(ef.total), diffTotal]];
  const how = item.kind === "matched" ? (item.how === "probable" ? "Probable match: same supplier, date and total" : "Matched by NIF + document number")
    : item.kind === "differ" ? "Matched by NIF + document number"
    : item.kind === "missing" ? "In e-Fatura, but no file in this folder" : "In the folder, but the AT doesn't have it";
  let text, actions;
  if (item.kind === "differ") {
    const parts = [];
    if (diffTotal) parts.push(html`${parts.length ? "the" : "The"} receipt says <b>${plain2(rc.total)}</b>, the AT has <b>${plain2(ef.total)}</b>`);
    if (diffDate) parts.push(html`${parts.length ? "the" : "The"} receipt is dated <b>${rc.date}</b>, the AT has <b>${ef.date}</b>`);
    text = html`${parts.map((p, i) => html`${i ? "; " : ""}${p}`)}. Check the receipt: if the AT is right, use its values (the filename is updated too).`;
    actions = html`<button class="btn solid" disabled=${busy} onClick=${() => act(async () => { const r = await api.efatura_use_values(path, item.id); if (r.error) toast(r.error, "warn"); })}>Use e-Fatura values</button>
      <button class="btn" disabled=${busy} onClick=${() => resolve("kept")}>Keep receipt values</button>`;
  } else if (item.kind === "missing") {
    text = "The AT has this invoice for the client, but there's no receipt for it in the folder. Find it (it will be read and matched), or mark it as not needed.";
    actions = html`<button class="btn solid" disabled=${busy} onClick=${() => act(async () => { const r = await api.efatura_find_receipt(path, item.id); if (r && r.error) toast(r.error, "warn"); else if (r) toast(`Added "${r.file}" to the folder.`); })}>${busy ? "Reading…" : "Find the receipt…"}</button>
      <button class="btn" disabled=${busy} onClick=${() => resolve("not_needed")}>Not needed</button>`;
  } else if (item.kind === "not_in_ef") {
    text = "The AT has no record of this receipt for the client: usually the client's NIF wasn't on it, or the supplier didn't report it. If it should count, register it in e-Fatura (Adquirente › Registar faturas) with these details.";
    actions = html`<button class="btn solid" disabled=${busy} onClick=${() => resolve("registered")}>Registered</button>
      <button class="btn" disabled=${busy} onClick=${() => resolve("not_needed")}>Not needed</button>`;
  } else {
    text = "Receipt and e-Fatura agree. Nothing to do.";
  }
  const d = main(item);
  return html`
    <div class="ef-detail">
      <div class="ef-chiprow"><span class=${"chip " + k.cls}>${k.title}</span><small class="muted">${how}</small></div>
      <h2 class="ef-title">${d.supplier || d.nif || "Unknown supplier"} · ${d.number || "no number"}</h2>
      <table class="cmp">
        <thead><tr><th>Field</th><th>Receipt (app)</th><th>e-Fatura (AT)</th></tr></thead>
        <tbody>${rows.map(([label, a, b, bad]) => html`<tr class=${bad ? "bad" : ""}><td>${label}</td><td>${rc ? (a || "—") : "—"}</td><td>${ef ? (b || "—") : "—"}</td></tr>`)}</tbody>
      </table>
      <div class="ef-bottom">
        <div class="ef-thumb">${rc ? html`<${Preview} pages=${thumb && thumb.pages} qr=${thumb && thumb.qr} loading=${!thumb} compact=${true} />`
          : html`<div class="no-receipt"><${Icon} name="file" size=${20} /><small>No receipt</small></div>`}</div>
        <div class="ef-text">
          ${item.resolution && item.resolution !== "matched" ? html`
            <div class="decided"><${Icon} name="check" size=${14} stroke=${2.5} /> ${DECIDED[item.resolution] || "Resolved"}
              <button class="link" onClick=${() => resolve(null)}>Undo</button></div>` : html`
            <p class="muted">${text}</p>
            ${actions && html`<div class="btn-row">${actions}</div>`}`}
          <div class="links">
            ${rc && html`<button class="link" onClick=${() => api.open(rc.path)}>Open receipt <${Icon} name="external" size=${13} /></button>`}
            ${item.kind !== "matched" && html`<button class="link" onClick=${copy}>Copy details</button>`}
          </div>
        </div>
      </div>
    </div>`;
}

export function Efatura({ path, go }) {
  const [info, setInfo] = useState(null);
  const [period, setPeriod] = useState(null);
  const [view, setView] = useState(null);
  const [filter, setFilter] = useState("attention");
  const [sel, setSel] = useState(null);
  const [exported, setExported] = useState(null);
  useEffect(() => {
    ctx.screen = "e-Fatura"; ctx.folder = path;
    api.folder(path).then((f) => { setInfo(f); setPeriod(f.periods.find((p) => p.label !== f.custom)); });
  }, [path]);
  const load = async () => { if (period) setView(await api.efatura_view(path, period.start, period.end)); };
  useEffect(() => { setView(null); load(); }, [period]);
  const importFiles = async () => {
    const r = await api.efatura_import(path);
    if (!r) return;
    if (r.error) toast(r.error, "warn"); else toast(r.message);
    const f = await api.folder(path); setInfo(f); load();
  };
  const exp = async () => { const ok = await api.efatura_export(path, period.start, period.end, period.short); if (ok !== null) setExported(ok); };

  const items = view ? view.items : [];
  const count = (f) => items.filter((i) => f === "all" ? true : f === "attention" ? open(i) : i.kind === f).length;
  const shown = items.filter((i) => filter === "all" ? true : filter === "attention" ? open(i) : i.kind === filter);
  const selected = shown.find((i) => i.id === sel) || shown[0];
  const resolved = items.filter((i) => !open(i)).length;
  const attention = count("attention");
  const name = info ? info.name : "";
  return html`
    <${TopBar} onBack=${() => go("folder", path)} title=${`e-Fatura · ${name}`}
        sub=${view && view.stored ? `${resolved} of ${items.length} resolved · ${attention} need${attention === 1 ? "s" : ""} attention` : ""}
        progress=${view && view.stored ? (items.length ? resolved / items.length : 1) : null}>
      <${FeedbackButton} />
      ${info && period && html`<${PeriodMenu} periods=${info.periods} custom=${info.custom} value=${period} onChange=${setPeriod} />`}
      <button class="btn" onClick=${importFiles}>Import export files…</button>
      <button class="btn solid" disabled=${!items.length} onClick=${exp}>${exported === true ? "✓ Exported" : exported === false ? "Export failed" : "Export to Excel"}</button>
    <//>
    ${view && !view.stored ? html`
      <div class="center-page"><div class="center-col">
        <h1>No e-Fatura data for this client yet</h1>
        <p class="lead">In the Portal das Finanças: e-Fatura › Faturação › Adquirente › choose the period › Pesquisar › "Obter dados para Excel". You can import one file per month or quarter.</p>
        <div><button class="btn primary" onClick=${importFiles}>Import export files…</button></div>
      </div></div>` : html`
      <div class="ef">
        <div class="ef-list">
          <div class="chips">${FILTERS.map(([k, l]) => html`<button class=${"fchip" + (filter === k ? " on" : "")} onClick=${() => { setFilter(k); setSel(null); }}>${l} · ${count(k)}</button>`)}</div>
          <div class="ef-items">
            ${view && shown.length === 0 && html`<p class="muted pad">${filter === "attention" ? (items.length ? "All resolved for this period. 🎉" : "No invoices in this period.") : "None."}</p>`}
            ${shown.map((i) => { const d = main(i); return html`
              <div class=${"ef-item" + (selected && selected.id === i.id ? " on" : "")} onClick=${() => setSel(i.id)}>
                <span class=${"chip small " + KIND[i.kind].cls + (open(i) || i.kind === "matched" ? "" : " faded")}>${i.resolution && i.kind !== "matched" ? "✓ Done" : KIND[i.kind].chip}</span>
                <div class="ef-item-text"><b>${d.supplier || d.nif}</b><small class="muted">${niceDate(d.date, true)} · ${d.number}</small></div>
                <span class=${"ef-total" + (i.kind === "differ" ? " strong" : "")}>${plain2(d.total)}</span>
              </div>`; })}
          </div>
        </div>
        <div class="ef-right">${selected ? html`<${Detail} key=${selected.id} item=${selected} path=${path} reload=${load} />` : view && html`<p class="muted pad">Nothing selected.</p>`}</div>
      </div>`}`;
}
