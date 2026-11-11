// Languages: Portuguese (Portugal) and English. Texts are written in English in the code and
// translated here; anything without a translation shows in English (never breaks).
import PT from "./i18n/pt.js";

let lang = "pt";

export function setLang(l) {
  lang = l === "en" ? "en" : "pt";
  document.documentElement.lang = lang === "pt" ? "pt-PT" : "en";
}
export const getLang = () => lang;

/** t("Rename {n} files", {n: 3}) → "Renomear 3 ficheiros" (in Portuguese) */
export function t(text, vars) {
  let out = lang === "pt" && PT[text] != null ? PT[text] : text;
  if (vars) out = out.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? ""));
  return out;
}
