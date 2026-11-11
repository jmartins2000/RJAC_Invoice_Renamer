// Feedback window (message, snipped screenshot, optional folder data) and the update dialog.
import { useEffect, useRef, useState } from "../vendor/hooks.mjs";
import { domToPng } from "../vendor/modern-screenshot.mjs";
import { api, Check, ctx, html, Icon, Modal, t, tn, usePy } from "../ui.js";

/** Covers the window with a faded picture of the page; drag to choose the part to send. */
function Snip({ shot, onDone }) {
  const [sel, setSel] = useState(null);
  const start = useRef(null);
  useEffect(() => {
    const key = (e) => { if (e.key === "Escape") onDone(null); if (e.key === "Enter") onDone(shot.src); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  const pos = (e) => [e.clientX, e.clientY];
  const down = (e) => { start.current = pos(e); setSel(null); };
  const move = (e) => {
    if (!start.current) return;
    const [x0, y0] = start.current, [x1, y1] = pos(e);
    setSel({ l: Math.min(x0, x1), t: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) });
  };
  const up = () => {
    start.current = null;
    if (!sel || sel.w < 12 || sel.h < 12) { setSel(null); return; }
    const img = new Image();
    img.onload = () => {
      const sx = img.width / window.innerWidth, sy = img.height / window.innerHeight;
      const c = document.createElement("canvas");
      c.width = Math.round(sel.w * sx); c.height = Math.round(sel.h * sy);
      c.getContext("2d").drawImage(img, sel.l * sx, sel.t * sy, c.width, c.height, 0, 0, c.width, c.height);
      onDone(c.toDataURL("image/png"));
    };
    img.src = shot.src;
  };
  return html`
    <div class="snip" onMouseDown=${down} onMouseMove=${move} onMouseUp=${up}>
      <img src=${shot.src} class="snip-faded" draggable="false" />
      ${sel && html`<div class="snip-sel" style=${{ left: sel.l, top: sel.t, width: sel.w, height: sel.h,
        backgroundImage: `url(${shot.src})`, backgroundSize: `${window.innerWidth}px ${window.innerHeight}px`,
        backgroundPosition: `${-sel.l}px ${-sel.t}px` }}></div>`}
      <div class="snip-hint">${t("Drag to select the part to send · Enter: whole page · Esc: cancel")}</div>
    </div>`;
}

export function Feedback({ onClose }) {
  const [kind, setKind] = useState("bug");
  const [message, setMessage] = useState("");
  const [shot, setShot] = useState(null);
  const [snipping, setSnipping] = useState(null);
  const [folder, setFolder] = useState(null);
  const [include, setInclude] = useState(true);
  const [status, setStatus] = useState(null);
  const [state, setState] = useState("idle");  // idle | sending | sent | saved
  const screen = ctx.screen, folderPath = ctx.folder;
  useEffect(() => { if (folderPath) api.feedback_folder(folderPath).then(setFolder); }, []);
  usePy("feedback_status", (t) => setStatus({ text: t }), []);

  const take = async () => {
    setSnipping("capturing");
    await new Promise((r) => setTimeout(r, 60));  // let the dialog disappear first
    try {
      const src = await domToPng(document.getElementById("app"), { scale: window.devicePixelRatio || 1,
        backgroundColor: getComputedStyle(document.body).backgroundColor });
      setSnipping({ src });
    } catch (e) {
      setSnipping(null);
      setStatus({ err: true, text: t("Couldn't take a screenshot:") + " " + e });
    }
  };
  const send = async () => {
    if (!message.trim()) { setStatus({ err: true, text: t("Please write a few words about it first.") }); return; }
    setState("sending"); setStatus({ text: t("Preparing…") });
    const r = await api.feedback_send(kind, message, shot, folderPath, folder ? include : false, screen);
    if (r.ok) { setState("sent"); setStatus({ ok: true, text: t("Thank you! Your feedback was sent.") }); }
    else if (r.saved) { setState("saved"); setStatus({ err: true, text: t("Couldn't send it (no internet?). It was saved to your Desktop as \"{file}\" — please email it to João.", { file: r.saved.split(/[\\/]/).pop() }) }); }
    else { setState("idle"); setStatus({ err: true, text: r.error }); }
  };

  if (snipping === "capturing") return null;
  if (snipping) return html`<${Snip} shot=${snipping} onDone=${(img) => { setSnipping(null); if (img) setShot(img); }} />`;
  const busy = state === "sending";
  return html`<${Modal} onClose=${busy ? null : onClose} width=${620}>
    <h2>${t("Send feedback")}</h2>
    <p class="muted small">${t("Goes privately to João, with what's needed to look into it.")}</p>
    <div class="seg mt">${[["bug", "Report a problem"], ["idea", "Suggest an idea"]].map(([k, l]) =>
      html`<button class=${kind === k ? "on" : ""} onClick=${() => setKind(k)}>${t(l)}</button>`)}</div>
    <label class="field-label">${t("What happened, or what would help?")}</label>
    <textarea class="input" rows="4" value=${message} onInput=${(e) => setMessage(e.target.value)} autofocus></textarea>
    <div class="shot-head"><span class="field-label inline">${t("Screenshot (optional)")}</span>
      <span>
        <button class="link" onClick=${take}><${Icon} name="camera" size=${14} /> ${t("Take screenshot")}</button>
        <button class="link" onClick=${async () => { const s = await api.choose_image(); if (s) setShot(s); }}>${t("Choose image…")}</button>
      </span></div>
    ${shot && html`<div class="shot"><img src=${shot} /><button class="btn icon small" title=${t("Remove")} onClick=${() => setShot(null)}><${Icon} name="x" size=${14} /></button></div>`}
    ${folder && html`<div class="toggle-row"><${Check} on=${include} onChange=${setInclude} />
      <div><b>${t("Include this folder's invoices and data")}</b><small class="muted">"${folder.name}" · ${tn(folder.files, "{n} file", "{n} files")}, ${folder.mb} MB${folder.efatura ? " · " + t("plus its e-Fatura data") : ""} · ${t("never the API key")}</small></div></div>`}
    ${status && html`<p class=${status.err ? "error small" : status.ok ? "green small" : "muted small"}>${status.text}</p>`}
    <div class="actions">
      <button class="btn" disabled=${busy} onClick=${onClose}>${state === "sent" || state === "saved" ? t("Close") : t("Cancel")}</button>
      ${state !== "sent" && state !== "saved" && html`<button class="btn solid" disabled=${busy} onClick=${send}>${busy ? t("Sending…") : t("Send")}</button>`}
    </div>
  <//>`;
}

export function UpdateDialog({ info, onClose }) {
  const [state, setState] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [msg, setMsg] = useState(null);
  usePy("update_progress", setProgress, []);
  const go = async () => {
    setState("downloading");
    const r = await api.update_install();
    if (r.error) { setState("idle"); setMsg({ err: true, text: r.error }); }
    else { setState("done"); setMsg({ text: r.message }); }
  };
  return html`<${Modal} onClose=${state === "downloading" ? null : onClose} width=${480}>
    <h2>${t("Version {v} is ready", { v: info.version })}</h2>
    <div class="notes">${info.notes}</div>
    ${state === "downloading" && html`<div class="bar mt"><div style=${{ width: `${Math.round(progress * 100)}%` }}></div></div>`}
    ${msg && html`<p class=${msg.err ? "error small" : "muted small"}>${msg.text}</p>`}
    <div class="actions">
      <button class="btn" disabled=${state === "downloading"} onClick=${onClose}>${state === "done" ? t("Close") : t("Later")}</button>
      ${state !== "done" && html`<button class="btn solid" disabled=${state === "downloading"} onClick=${go}>${state === "downloading" ? t("Downloading…") : msg ? t("Try again") : t("Update now")}</button>`}
    </div>
  <//>`;
}

// Used by the automated UI test (tools/ui_smoke.py) to save pictures of each screen.
window.__rjacShot = async () => domToPng(document.getElementById("app"), { scale: window.devicePixelRatio || 1,
  backgroundColor: getComputedStyle(document.body).backgroundColor });
