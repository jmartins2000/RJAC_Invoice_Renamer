// New interface: Preact + htm (no build step), talking to Python through pywebview's js_api.
import { render } from "./vendor/preact.mjs";
import { useEffect, useState } from "./vendor/hooks.mjs";
import { api, GlobalLayers, html, toast, usePy } from "./ui.js";
import { Done, Home, Welcome } from "./screens/home.js";
import { Folder } from "./screens/folder.js";
import { Review } from "./screens/review.js";
import { Fields, Settings } from "./screens/settings.js";
import { Feedback, UpdateDialog } from "./screens/feedback.js";
import { Efatura } from "./screens/efatura.js";

const dark = window.matchMedia("(prefers-color-scheme: dark)");
function applyTheme(mode) {
  const isDark = mode === "dark" || (mode === "system" && dark.matches);
  document.documentElement.dataset.theme = isDark ? "dark" : "light";
}

function App() {
  const [info, setInfo] = useState(null);
  const [route, setRoute] = useState(null);
  const [appearance, setAppearanceState] = useState("system");
  const [update, setUpdate] = useState(null);
  const [showUpdate, setShowUpdate] = useState(false);
  const [feedback, setFeedback] = useState(false);
  const go = (name, arg) => { window.scrollTo(0, 0); setRoute({ name, arg }); };

  useEffect(() => {
    api.app_info().then((i) => {
      setInfo(i); setAppearanceState(i.appearance); applyTheme(i.appearance); setUpdate(i.update);
      document.documentElement.dataset.platform = i.platform;
      setRoute(i.has_key ? { name: "home" } : { name: "welcome" });
      api.start_background();
    });
    // Never fail silently: if anything goes wrong behind a button, say so.
    window.addEventListener("error", (e) => {
      api.log_ui(`page error: ${e.message} at ${e.filename}:${e.lineno}:${e.colno}`).catch(() => {});
    });
    window.addEventListener("unhandledrejection", (e) => {
      api.log_ui(`unhandled: ${(e.reason && (e.reason.stack || e.reason.message)) || e.reason}`).catch(() => {});
      const msg = String((e.reason && (e.reason.message || e.reason)) || "unknown error").trim().split("\n").pop() || "unknown error";
      toast(`Something went wrong: ${msg}. Please send feedback (speech bubble, top right).`, "warn");
    });
    const open = () => setFeedback(true);
    window.addEventListener("open-feedback", open);
    return () => window.removeEventListener("open-feedback", open);
  }, []);
  useEffect(() => {
    const f = () => applyTheme(appearance);
    dark.addEventListener("change", f);
    return () => dark.removeEventListener("change", f);
  }, [appearance]);
  usePy("update", (u) => setUpdate(u), []);

  const setAppearance = (mode) => { setAppearanceState(mode); applyTheme(mode); api.set_appearance(mode); };
  const updateFound = (u, show) => { setUpdate(u); if (show) setShowUpdate(true); };

  if (!route) return null;
  const { name, arg } = route;
  let screen;
  if (name === "welcome") screen = html`<${Welcome} onDone=${() => go(...((arg && arg.then) || ["home"]))} />`;
  else if (name === "home") screen = html`<${Home} go=${go} update=${update} onUpdate=${() => setShowUpdate(true)} />`;
  else if (name === "folder") screen = html`<${Folder} key=${arg} path=${arg} go=${go} />`;
  else if (name === "review") screen = html`<${Review} key=${arg} path=${arg} go=${go} onDone=${(r) => go("done", r)} />`;
  else if (name === "done") screen = html`<${Done} result=${arg} go=${go} />`;
  else if (name === "settings") screen = html`<${Settings} go=${go} appearance=${appearance} setAppearance=${setAppearance} onUpdateFound=${updateFound} />`;
  else if (name === "fields") screen = html`<${Fields} go=${go} back=${(arg && arg.back) || ["settings"]} />`;
  else if (name === "efatura") screen = html`<${Efatura} key=${arg} path=${arg} go=${go} />`;
  return html`
    ${screen}
    ${feedback && html`<${Feedback} onClose=${() => setFeedback(false)} />`}
    ${showUpdate && update && html`<${UpdateDialog} info=${update} onClose=${() => setShowUpdate(false)} />`}
    <${GlobalLayers} />`;
}

render(html`<${App} />`, document.getElementById("app"));
window.__rjacStarted = true;  // the safety net in index.html stops waiting
try { sessionStorage.removeItem("rjacReloads"); } catch (e) { /* storage unavailable */ }
