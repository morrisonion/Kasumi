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
//   POST /stats                        anonymous session performance summary
//   GET  /stats?key=ADMIN_KEY          performance page (averages + recent)
//   GET  /api/stats?days=90            raw summaries as JSON (for dashboard.html)
//   GET  /api/reports                  report list as JSON
// Read routes take the key as ?key= or an "X-Admin-Key" header, and allow
// cross-origin reads so the local dashboard.html can use them.

const KEEP_SECONDS = 30 * 24 * 3600;
const MAX_UPLOAD_BYTES = 1536 * 1024;
const MAX_REPORT_BYTES = 4 * 1024 * 1024; // uncompressed
const REPORTS_PER_HOUR = 6;               // per sender address
const STATS_KEEP_SECONDS = 90 * 24 * 3600;
const STATS_PER_HOUR = 30;                // per sender address
const CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"; // no 0/O, 1/I/L

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    // A key sent as a header (the dashboard) counts like ?key=. This URL
    // object belongs to this request only.
    const headerKey = request.headers.get("x-admin-key");
    if (headerKey) url.searchParams.set("key", headerKey);
    try {
      if (request.method === "GET" && url.pathname === "/api/stats") return await apiStats(url, env);
      if (request.method === "GET" && url.pathname === "/api/reports") return await apiReports(url, env);
      if (request.method === "POST" && url.pathname === "/report") return await submit(request, env);
      if (request.method === "GET" && url.pathname === "/reports") return await list(url, env);
      if (request.method === "POST" && url.pathname === "/stats") return await submitStats(request, env);
      if (request.method === "GET" && url.pathname === "/stats") return await statsPage(url, env);
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

// Everything readable needs the admin key anyway, so any origin may ask.
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, x-admin-key",
  "access-control-max-age": "86400",
};

function text(body, status = 200, type = "text/plain; charset=utf-8") {
  return new Response(body, { status, headers: { "content-type": type, ...CORS } });
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...CORS } });
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
        ...CORS,
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
    `<h1>Kasumi reports (${rows.length})</h1><p><a href="/stats?key=${key}">Performance stats &rarr;</a></p><table><tr><th>Code</th><th>Sent</th><th>Why</th><th>Version</th><th>Build</th><th>Console</th><th>Dump</th></tr>`,
    ...rows.map((r) =>
      `<tr><td><a href="/report/${r.code}?key=${key}">${r.code}</a></td><td>${r.at || ""}</td>` +
      `<td>${esc(r.trigger || "manual")}</td><td>${esc(r.version || "")}</td><td>${esc(r.build || "")}</td>` +
      `<td>${esc(r.install || "")}</td><td>${r.dump ? "yes" : ""}</td></tr>`),
    "</table>",
  ];
  return text(html.join(""), 200, "text/html; charset=utf-8");
}

// ---- Session performance summaries --------------------------------------
//
// Each summary is ~400 bytes of numbers (see source/perf_stats.c for the
// keys). It is stored as the metadata of a KV key, so one list call reads
// up to 1000 of them without fetching values.

const STAT_FIELDS = {
  v: "string", b: "string", i: "string", g: "string", r: "string", e: "string",
  m: "number", br: "number", d: "number", p: "number", pm: "number", w: "number",
  k: "number", kn: "number", kx: "number", f: "number", rp: "number", sk: "number",
  dr: "number", lo: "number", kf: "number", rs: "number", cc: "number", rc: "number",
  da: "number", dx: "number", sl: "number", lm: "number",
};

async function limited(env, request, prefix, perHour) {
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  const hour = Math.floor(Date.now() / 3600000);
  const key = prefix + (await sha256Hex(ip + ":" + hour)).slice(0, 32);
  const count = Number((await env.REPORTS.get(key)) || 0);
  if (count >= perHour) return true;
  await env.REPORTS.put(key, String(count + 1), { expirationTtl: 3700 });
  return false;
}

async function submitStats(request, env) {
  if (Number(request.headers.get("content-length") || 0) > 4096) return json({ error: "too large" }, 413);
  if (await limited(env, request, "rs:", STATS_PER_HOUR)) return json({ error: "rate limited" }, 429);
  let raw;
  try {
    raw = JSON.parse(await request.text());
  } catch {
    return json({ error: "bad request" }, 400);
  }
  if (!raw || raw.app !== "Kasumi") return json({ error: "not a Kasumi summary" }, 400);
  const stat = { t: Date.now() };
  for (const [name, type] of Object.entries(STAT_FIELDS)) {
    const value = raw[name];
    if (type === "number" && Number.isFinite(value)) stat[name] = Math.round(value);
    if (type === "string" && typeof value === "string") stat[name] = value.slice(0, 40);
  }
  if (!(stat.d > 0)) return json({ error: "empty" }, 400);
  // Keys sort newest first: reversed timestamp.
  const id = "s:" + String(9999999999999 - stat.t).padStart(13, "0") + ":" + newCode();
  await env.REPORTS.put(id, "", { expirationTtl: STATS_KEEP_SECONDS, metadata: stat });
  return json({ ok: true });
}

async function loadStats(env, max = 5000) {
  const rows = [];
  let cursor;
  do {
    const page = await env.REPORTS.list({ prefix: "s:", limit: 1000, cursor });
    for (const k of page.keys) if (k.metadata) rows.push(k.metadata);
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor && rows.length < max);
  return rows;
}

function summarise(rows) {
  const n = rows.length;
  if (!n) return null;
  const minutes = rows.reduce((a, r) => a + (r.d || 0), 0) / 60;
  const avg = (key, scale = 1) => {
    const values = rows.filter((r) => Number.isFinite(r[key]) && r[key] >= 0).map((r) => r[key] / scale);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : NaN;
  };
  const perMin = (key) => (minutes ? rows.reduce((a, r) => a + (r[key] || 0), 0) / minutes : NaN);
  return {
    sessions: n,
    consoles: new Set(rows.map((r) => r.i).filter(Boolean)).size,
    hours: minutes / 60,
    ping: avg("p"),
    pingMax: avg("pm"),
    kbps: avg("k"),
    fps: avg("f", 10),
    wifi: avg("w", 10),
    lost: perMin("lo"),
    repeated: perMin("rp"),
    keyframes: perMin("kf"),
    reconnects: perMin("rc") * 60,
    decode: avg("da") / 1000,
    errors: rows.filter((r) => r.e && r.e !== "user" && r.e !== "ended").length / n,
  };
}

function fmt(value, digits = 1) {
  return Number.isFinite(value) ? value.toFixed(digits) : "-";
}

function table(title, groups) {
  const head = "<tr><th></th><th>Sessions</th><th>Consoles</th><th>Hours</th><th>Ping ms</th><th>Worst ping</th>" +
    "<th>Mbps</th><th>FPS</th><th>Wi-Fi</th><th>Lost frames/min</th><th>Hitches/min</th><th>Keyframes/min</th>" +
    "<th>Reconnects/h</th><th>Decode ms</th><th>Ended in error</th></tr>";
  const body = groups
    .filter(([, s]) => s)
    .map(([name, s]) =>
      `<tr><td><b>${esc(name)}</b></td><td>${s.sessions}</td><td>${s.consoles}</td><td>${fmt(s.hours)}</td>` +
      `<td>${fmt(s.ping, 0)}</td><td>${fmt(s.pingMax, 0)}</td><td>${fmt(s.kbps / 1000, 2)}</td><td>${fmt(s.fps)}</td>` +
      `<td>${fmt(s.wifi)}</td><td>${fmt(s.lost, 2)}</td><td>${fmt(s.repeated, 2)}</td><td>${fmt(s.keyframes, 2)}</td>` +
      `<td>${fmt(s.reconnects, 2)}</td><td>${fmt(s.decode)}</td><td>${fmt(s.errors * 100, 0)}%</td></tr>`)
    .join("");
  return `<h2>${esc(title)}</h2><table>${head}${body}</table>`;
}

function groupBy(rows, key, label = (x) => x) {
  const groups = new Map();
  for (const r of rows) {
    const name = label(r[key]);
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(r);
  }
  return [...groups.entries()].sort((a, b) => b[1].length - a[1].length).map(([name, list]) => [name, summarise(list)]);
}

async function statsPage(url, env) {
  if (!authorised(url, env)) return text("Not authorised", 401);
  const days = Math.min(90, Math.max(1, Number(url.searchParams.get("days")) || 30));
  const since = Date.now() - days * 86400000;
  const rows = (await loadStats(env)).filter((r) => r.t >= since);
  const key = encodeURIComponent(url.searchParams.get("key"));
  const bitrates = ["Adaptive", "Steady 1", "Steady 1.2", "Steady 1.5"];
  const recent = rows.slice(0, 50).map((r) =>
    `<tr><td>${new Date(r.t).toISOString().slice(0, 16).replace("T", " ")}</td><td>${esc(r.v || "")}</td>` +
    `<td>${esc(r.g || "")}</td><td>${esc(r.r || "")}</td><td>${r.m ? "Weak" : "Standard"}</td>` +
    `<td>${Math.round((r.d || 0) / 60)} min</td><td>${r.p ?? "-"}</td><td>${fmt((r.k || 0) / 1000, 2)}</td>` +
    `<td>${r.lo ?? 0}</td><td>${r.rp ?? 0}</td><td>${r.rc ?? 0}</td><td>${esc(r.e || "")}</td><td>${esc(r.i || "")}</td></tr>`
  ).join("");
  const html = [
    "<!doctype html><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\">",
    "<title>Kasumi performance</title>",
    "<style>body{font:14px system-ui;margin:24px;background:#111;color:#ddd}a{color:#7EBEA5}h1,h2{color:#7EBEA5;font-weight:600}",
    "table{border-collapse:collapse;margin-bottom:24px;display:block;overflow-x:auto}td,th{padding:4px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid #222}",
    "td:first-child,th:first-child{text-align:left}th{color:#999;font-weight:500}</style>",
    `<h1>Kasumi performance, last ${days} days</h1>`,
    `<p><a href="/reports?key=${key}">&larr; Reports</a> · ` +
      [7, 30, 90].map((d) => `<a href="/stats?key=${key}&days=${d}">${d} days</a>`).join(" · ") + "</p>",
    rows.length ? "" : "<p>No sessions yet.</p>",
    table("Overall", [["All sessions", summarise(rows)]]),
    table("By version", groupBy(rows, "v")),
    table("By connection type", groupBy(rows, "m", (m) => (m ? "Weak / hotspot" : "Standard"))),
    table("By bitrate", groupBy(rows, "br", (b) => bitrates[b] || "?")),
    table("By server", groupBy(rows, "r", (r) => r || "?")),
    "<h2>Recent sessions</h2><table><tr><th>When (UTC)</th><th>Version</th><th>Game</th><th>Server</th><th>Type</th>" +
      "<th>Length</th><th>Ping</th><th>Mbps</th><th>Lost</th><th>Hitches</th><th>Reconnects</th><th>End</th><th>Console</th></tr>" +
      recent + "</table>",
  ];
  return text(html.join(""), 200, "text/html; charset=utf-8");
}

// ---- JSON for dashboard.html ------------------------------------------------

async function apiStats(url, env) {
  if (!authorised(url, env)) return json({ error: "not authorised" }, 401);
  const days = Math.min(90, Math.max(1, Number(url.searchParams.get("days")) || 90));
  const since = Date.now() - days * 86400000;
  const rows = (await loadStats(env)).filter((r) => r.t >= since);
  return json({ days, rows });
}

async function apiReports(url, env) {
  if (!authorised(url, env)) return json({ error: "not authorised" }, 401);
  const result = await env.REPORTS.list({ prefix: "r:", limit: 1000 });
  const rows = result.keys
    .map((k) => ({ code: k.name.slice(2), ...(k.metadata || {}) }))
    .sort((a, b) => String(b.at).localeCompare(String(a.at)));
  return json({ rows });
}
