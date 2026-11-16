// Emails you when someone sends feedback from the RJAC app.
// Lives in your Google account (script.google.com), deployed as a Web app; the feedback Worker
// calls it with a shared secret (Cloudflare secret NOTIFY_SECRET; the same value goes below).
const SECRET = "PASTE_THE_SECRET_HERE";

function doPost(e) {
  let d;
  try { d = JSON.parse(e.postData.contents); } catch (err) { return ContentService.createTextOutput("bad"); }
  if (!d || d.secret !== SECRET) return ContentService.createTextOutput("no");
  const kind = d.kind === "idea" ? "ideia" : "problema";
  const subject = `RJAC: novo feedback (${kind}) · v${d.version}${d.folder ? " · " + d.folder : ""}`;
  const body = [
    d.message || "(sem mensagem)",
    "",
    `Ecrã: ${d.screen || "-"}   ·   Sistema: ${d.os || "-"}   ·   Anexos: ${d.mb} MB`,
    `ID: ${d.id}`,
    "",
    "Para descarregar:  python tools/feedback.py get new",
  ].join("\n");
  MailApp.sendEmail(Session.getEffectiveUser().getEmail(), subject, body);
  return ContentService.createTextOutput("ok");
}

// Run this once from the editor (▶ Run) to grant permission and get a test email.
function test() {
  doPost({ postData: { contents: JSON.stringify({ secret: SECRET, id: "teste", kind: "bug", version: "test",
    os: "-", screen: "-", folder: "", message: "Isto é um teste: se recebeu este email, está a funcionar.", mb: 0 }) } });
}
