// RJAC feedback inbox.
//
// App (no secret needed, can only add):
//   PUT  /upload/<id>/<n>      body = part n of the zip (<= 20 MB), n = 0..19
//   POST /upload/<id>/done     body = JSON metadata (kind, message, parts, bytes, app version, ...)
// Owner (Authorization: Bearer <ADMIN_TOKEN>):
//   GET    /admin/list          -> [{id, meta}]
//   GET    /admin/<id>/<n>      -> part n
//   DELETE /admin/<id>          -> removes the submission
const MAX_PART = 20 * 1024 * 1024;
const MAX_PARTS = 20;
const ID = /^[0-9]{8}-[0-9]{6}-[a-z0-9]{6,12}$/; // e.g. 20261109-023512-k3j9x2
const APP_HEADER = "x-rjac-app";

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const parts = url.pathname.split("/").filter(Boolean);

    // ---- app uploads ----
    if (parts[0] === "upload") {
      if (!request.headers.get(APP_HEADER)) return json({ error: "not allowed" }, 403);
      const [, id, what] = parts;
      if (!ID.test(id || "")) return json({ error: "bad id" }, 400);
      if (request.method === "PUT" && /^\d+$/.test(what || "")) {
        const n = Number(what);
        if (n >= MAX_PARTS) return json({ error: "too many parts" }, 400);
        const body = await request.arrayBuffer();
        if (body.byteLength === 0 || body.byteLength > MAX_PART) return json({ error: "bad size" }, 413);
        if (await env.FEEDBACK.get(`fb:${id}:meta`)) return json({ error: "already submitted" }, 409);
        await env.FEEDBACK.put(`fb:${id}:part:${n}`, body, { expirationTtl: 60 * 60 * 24 * 180 });
        return json({ ok: true });
      }
      if (request.method === "POST" && what === "done") {
        const text = await request.text();
        if (text.length > 100_000) return json({ error: "meta too large" }, 413);
        let meta;
        try { meta = JSON.parse(text); } catch { return json({ error: "bad json" }, 400); }
        const n = Number(meta.parts || 0);
        for (let i = 0; i < n; i++) {
          if (!(await env.FEEDBACK.get(`fb:${id}:part:${i}`, { type: "stream" }))) {
            return json({ error: `missing part ${i}` }, 400);
          }
        }
        meta.received_at = new Date().toISOString();
        await env.FEEDBACK.put(`fb:${id}:meta`, JSON.stringify(meta), { expirationTtl: 60 * 60 * 24 * 180 });
        return json({ ok: true, id });
      }
      return json({ error: "not found" }, 404);
    }

    // ---- owner ----
    if (parts[0] === "admin") {
      const auth = request.headers.get("authorization") || "";
      if (!env.ADMIN_TOKEN || auth !== `Bearer ${env.ADMIN_TOKEN}`) return json({ error: "not allowed" }, 403);
      if (parts[1] === "list" && request.method === "GET") {
        const out = [];
        let cursor;
        do {
          const page = await env.FEEDBACK.list({ prefix: "fb:", cursor });
          for (const k of page.keys) {
            if (k.name.endsWith(":meta")) {
              const id = k.name.split(":")[1];
              out.push({ id, meta: JSON.parse((await env.FEEDBACK.get(k.name)) || "{}") });
            }
          }
          cursor = page.list_complete ? null : page.cursor;
        } while (cursor);
        return json(out.sort((a, b) => (a.id < b.id ? 1 : -1)));
      }
      const id = parts[1];
      if (!ID.test(id || "")) return json({ error: "bad id" }, 400);
      if (request.method === "GET" && /^\d+$/.test(parts[2] || "")) {
        const data = await env.FEEDBACK.get(`fb:${id}:part:${parts[2]}`, { type: "arrayBuffer" });
        return data ? new Response(data, { headers: { "content-type": "application/zip" } }) : json({ error: "not found" }, 404);
      }
      if (request.method === "DELETE") {
        const page = await env.FEEDBACK.list({ prefix: `fb:${id}:` });
        await Promise.all(page.keys.map((k) => env.FEEDBACK.delete(k.name)));
        return json({ ok: true, deleted: page.keys.length });
      }
    }
    return new Response("RJAC feedback inbox", { status: 404 });
  },
};
