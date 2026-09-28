// Kasumi diagnostic report service (Cloudflare Worker).
//
// Kasumi uploads a report only when the player chooses "Send diagnostic
// report" and confirms. The report is kept for 30 days in Workers KV and read
// back with a short code the player shares (e.g. on a GitHub issue).
//
// Bindings (Worker settings in the Cloudflare dashboard):
//   REPORTS          KV namespace (required)
//   ADMIN_KEY        secret: long random string to read reports (required)
//   DISCORD_WEBHOOK  secret: Discord webhook URL for new-report pings (optional)
//
// Routes:
//   POST /report                       Kasumi uploads a report, gets {code}
//   GET  /report/CODE?key=ADMIN_KEY    read a report as text
//   GET  /report/CODE/dump?key=...     download its Luma crash dump, if any
//   GET  /reports?key=ADMIN_KEY        list recent reports

const KEEP_SECONDS = 30 * 24 * 3600;
const MAX_UPLOAD_BYTES = 1536 * 1024;
const MAX_REPORT_BYTES = 4 * 1024 * 1024; // uncompressed
const REPORTS_PER_HOUR = 6;               // per sender address
const CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"; // no 0/O, 1/I/L

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (request.method === "POST" && url.pathname === "/report") return await submit(request, env);
      if (request.method === "GET" && url.pathname === "/reports") return await list(url, env);
      // Codes are shown as "K7F-2QX"; accept them with or without the dash.
      const match = url.pathname.toUpperCase().match(/^\/REPORT\/([A-Z0-9]{3})-?([A-Z0-9]{3})(\/DUMP)?$/);
      if (request.method === "GET" && match) return await view(url, env, match[1] + match[2], !!match[3]);
      return text("Kasumi report service", 404);
    } catch (error) {
      return text("Error: " + (error && error.message ? error.message : error), 500);
    }
  },
};

function esc(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function text(body, status = 200, type = "text/plain; charset=utf-8") {
  return new Response(body, { status, headers: { "content-type": type } });
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function authorised(url, env) {
  const key = url.searchParams.get("key") || "";
  return env.ADMIN_KEY && key.length >= 16 && key === env.ADMIN_KEY;
}

function base64ToBytes(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function gunzip(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  const buffer = await new Response(stream).arrayBuffer();
  if (buffer.byteLength > MAX_REPORT_BYTES) throw new Error("report too large");
  return new TextDecoder().decode(buffer);
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function newCode() {
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  return [...bytes].map((b) => CODE_ALPHABET[b % CODE_ALPHABET.length]).join("");
}

async function submit(request, env) {
  const length = Number(request.headers.get("content-length") || 0);
  if (length > MAX_UPLOAD_BYTES) return json({ error: "too large" }, 413);

  // Light rate limit per sender. Only a hash of the address is stored, and
  // only for the hour it counts.
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  const hour = Math.floor(Date.now() / 3600000);
  const limitKey = "rl:" + (await sha256Hex(ip + ":" + hour)).slice(0, 32);
  const sent = Number((await env.REPORTS.get(limitKey)) || 0);
  if (sent >= REPORTS_PER_HOUR) return json({ error: "too many reports, try again later" }, 429);

  const body = await request.text();
  if (body.length > MAX_UPLOAD_BYTES) return json({ error: "too large" }, 413);
  let upload;
  try {
    upload = JSON.parse(body);
  } catch {
    return json({ error: "bad request" }, 400);
  }
  if (upload.format !== "kasumi-report-1" || typeof upload.payload !== "string")
    return json({ error: "not a Kasumi report" }, 400);

  // Check it really is a Kasumi report before storing it.
  const gz = base64ToBytes(upload.payload);
  const report = JSON.parse(await gunzip(gz));
  if (report.app !== "Kasumi" || typeof report.version !== "string")
    return json({ error: "not a Kasumi report" }, 400);

  let code = newCode();
  for (let i = 0; i < 4 && (await env.REPORTS.get("r:" + code)); i++) code = newCode();

  const meta = {
    version: String(report.version).slice(0, 32),
    build: String(report.build || "").slice(0, 8),
    at: new Date().toISOString(),
    size: gz.length,
    dump: !!(report.dump && report.dump.data),
    trigger: String(report.trigger || "manual").slice(0, 24),
    install: String(report.install || "").slice(0, 20),
  };
  await env.REPORTS.put("r:" + code, gz, { expirationTtl: KEEP_SECONDS, metadata: meta });
  await env.REPORTS.put(limitKey, String(sent + 1), { expirationTtl: 3700 });

  if (env.DISCORD_WEBHOOK) {
    const note = `New Kasumi report **${code}** (${meta.trigger}): ${meta.version} (build ${meta.build})` +
      (meta.dump ? ", with a crash dump" : "");
    await fetch(env.DISCORD_WEBHOOK, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ content: note }),
    }).catch(() => {});
  }
  return json({ code });
}

async function load(env, code) {
  const gz = await env.REPORTS.get("r:" + code, { type: "arrayBuffer" });
  return gz ? JSON.parse(await gunzip(new Uint8Array(gz))) : null;
}

async function view(url, env, code, wantDump) {
  if (!authorised(url, env)) return text("Not authorised", 401);
  const report = await load(env, code);
  if (!report) return text("No report " + code + " (reports are kept 30 days)", 404);

  if (wantDump) {
    if (!report.dump || !report.dump.data) return text("This report has no crash dump", 404);
    return new Response(base64ToBytes(report.dump.data), {
      headers: {
        "content-type": "application/octet-stream",
        "content-disposition": `attachment; filename="${code}-${report.dump.name || "crash_dump.dmp"}"`,
      },
    });
  }

  const lines = [
    `Kasumi report ${code}`,
    `Version: ${report.version} (build ${report.build})`,
    `Sent: ${report.sent_at || "?"}`,
    `Why: ${report.trigger || "manual"}`,
    `Console: ${report.install || "?"} (anonymous install id)`,
    report.dump && report.dump.data
      ? `Crash dump: ${report.dump.name} -> ${url.origin}/report/${code}/dump?key=...`
      : "Crash dump: none",
    "",
    "===== settings.json =====",
    report.settings || "(none)",
    "",
    "===== current log (this run) =====",
    report.log || "(empty)",
    "",
    "===== previous log (the run before) =====",
    report.previous_log || "(none)",
  ];
  return text(lines.join("\n"));
}

async function list(url, env) {
  if (!authorised(url, env)) return text("Not authorised", 401);
  const result = await env.REPORTS.list({ prefix: "r:", limit: 1000 });
  const rows = result.keys
    .map((k) => ({ code: k.name.slice(2), ...(k.metadata || {}) }))
    .sort((a, b) => String(b.at).localeCompare(String(a.at)));
  const key = encodeURIComponent(url.searchParams.get("key"));
  const html = [
    "<!doctype html><meta charset=utf-8><title>Kasumi reports</title>",
    "<style>body{font:14px system-ui;margin:24px;background:#111;color:#ddd}a{color:#7EBEA5}td,th{padding:4px 12px;text-align:left}</style>",
    `<h1>Kasumi reports (${rows.length})</h1><table><tr><th>Code</th><th>Sent</th><th>Why</th><th>Version</th><th>Build</th><th>Console</th><th>Dump</th></tr>`,
    ...rows.map((r) =>
      `<tr><td><a href="/report/${r.code}?key=${key}">${r.code}</a></td><td>${r.at || ""}</td>` +
      `<td>${esc(r.trigger || "manual")}</td><td>${esc(r.version || "")}</td><td>${esc(r.build || "")}</td>` +
      `<td>${esc(r.install || "")}</td><td>${r.dump ? "yes" : ""}</td></tr>`),
    "</table>",
  ];
  return text(html.join(""), 200, "text/html; charset=utf-8");
}
