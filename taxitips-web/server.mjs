/**
 * Tiny production server for the static Vite build.
 * Serves dist/ and exposes:
 *   POST /api/subscribe  → Listmonk public subscription (CORS-safe)
 *   POST /api/lead       → Listmonk private leads + optional Django CRM (native)
 *
 * Coolify env (optional for CRM/leads):
 *   LISTMONK_URL=https://lm.a2m-tech.com
 *   LISTMONK_USER=...
 *   LISTMONK_TOKEN=...
 *   LISTMONK_LEADS_LIST_ID=7
 *   CRM_LEAD_BACKEND_URL=https://backend.taxitips.se
 *   CRM_LEAD_INGEST_SECRET=...   (samma som på taxitips-backend)
 */

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DIST = path.join(__dirname, "dist");
const PORT = Number(process.env.PORT || 80);

const LISTMONK_URL = (process.env.LISTMONK_URL || "https://lm.a2m-tech.com").replace(/\/$/, "");
const LISTMONK_USER = process.env.LISTMONK_USER || "";
const LISTMONK_TOKEN = process.env.LISTMONK_TOKEN || "";
const LISTMONK_LEADS_LIST_ID = Number(process.env.LISTMONK_LEADS_LIST_ID || 7);
const PUBLIC_LIST_UUID =
  process.env.LISTMONK_PUBLIC_LIST_UUID || "e2f8a9bc-674d-47a0-8dd8-77d1272cbfa5";

const CRM_LEAD_BACKEND_URL = (process.env.CRM_LEAD_BACKEND_URL || "").replace(/\/$/, "");
const CRM_LEAD_INGEST_SECRET = process.env.CRM_LEAD_INGEST_SECRET || "";
const CHATWOOT_WEBSITE_TOKEN = process.env.CHATWOOT_WEBSITE_TOKEN || "";
const GLITCHTIP_DSN = process.env.GLITCHTIP_DSN || "";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".json": "application/json",
  ".webmanifest": "application/manifest+json",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml; charset=utf-8",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
};

/** Filändelser som aldrig får falla tillbaka till index.html (SEO/crawlers). */
const NO_HTML_FALLBACK = new Set([".txt", ".xml", ".json", ".webmanifest", ".mp4", ".webm"]);

function cors(res, origin) {
  const allowed =
    !origin ||
    origin === "https://taxitips.se" ||
    origin === "https://www.taxitips.se" ||
    /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  if (allowed && origin) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Accept");
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (c) => {
      size += c.length;
      if (size > 32_000) {
        reject(new Error("body_too_large"));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on("end", () => {
      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        reject(new Error("invalid_json"));
      }
    });
    req.on("error", reject);
  });
}

function json(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

function isEmail(v) {
  return typeof v === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v) && v.length <= 254;
}

async function listmonkPublicSubscribe({ email, name, listUuids }) {
  const res = await fetch(`${LISTMONK_URL}/api/public/subscription`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      email,
      name: name || "",
      list_uuids: listUuids?.length ? listUuids : [PUBLIC_LIST_UUID],
    }),
  });
  const text = await res.text();
  if (!res.ok) {
    const err = new Error(`listmonk_public_${res.status}`);
    err.detail = text;
    throw err;
  }
  return text ? JSON.parse(text) : { ok: true };
}

async function listmonkPrivateLead({ email, name, attribs }) {
  if (!LISTMONK_USER || !LISTMONK_TOKEN) {
    return { skipped: true, reason: "listmonk_auth_missing" };
  }
  const auth = `token ${LISTMONK_USER}:${LISTMONK_TOKEN}`;
  const res = await fetch(`${LISTMONK_URL}/api/subscribers`, {
    method: "POST",
    headers: {
      Authorization: auth,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      email,
      name: name || "",
      status: "enabled",
      lists: [LISTMONK_LEADS_LIST_ID],
      attribs: attribs || {},
      preconfirm_subscriptions: true,
    }),
  });
  if (res.ok || res.status === 409) {
    return { ok: true, status: res.status };
  }
  return { ok: false, status: res.status, body: await res.text() };
}

async function djangoCrmLead({ name, email, company, message, source, page }) {
  if (!CRM_LEAD_BACKEND_URL || !CRM_LEAD_INGEST_SECRET) {
    return { skipped: true, reason: "crm_backend_not_configured" };
  }
  const res = await fetch(`${CRM_LEAD_BACKEND_URL}/api/crm/lead`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Crm-Lead-Secret": CRM_LEAD_INGEST_SECRET,
    },
    body: JSON.stringify({ name, email, company, message, source, page }),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    return { ok: false, status: res.status, body: payload };
  }
  return { ok: true, leadId: payload.leadId };
}

// Adminwebben har en egen värd. På den värden är `/` adminsidan, inte
// marknadssidan -- annars landar den som skriver admin.taxitips.se på
// "Hitta fler kunder. Tjäna mer." och tror att något är trasigt.
// Behörigheten avgörs ändå av backenden (StaffRole), inte av värdnamnet.
const ADMIN_HOSTS = new Set(
  (process.env.ADMIN_HOSTS || "admin.taxitips.se")
    .split(",")
    .map((h) => h.trim().toLowerCase())
    .filter(Boolean),
);

function requestHost(req) {
  return String(req.headers["x-forwarded-host"] || req.headers.host || "")
    .split(",")[0]
    .split(":")[0]
    .trim()
    .toLowerCase();
}

function isAdminHost(req) {
  return ADMIN_HOSTS.has(requestHost(req));
}

// Kundportalen har också en egen värd: portal.taxitips.se. Där är `/`
// portalen. Registreringen ligger på samma värd, eftersom Supabase sparar
// inloggningen per värd -- ett konto som skapas på taxitips.se vore annars
// utloggat på portal.taxitips.se direkt efteråt.
const PORTAL_ORIGIN = (process.env.PORTAL_ORIGIN || "https://portal.taxitips.se").replace(/\/$/, "");
const PORTAL_HOST = (() => {
  try {
    return new URL(PORTAL_ORIGIN).hostname.toLowerCase();
  } catch {
    return "";
  }
})();
// Sökvägar på marknadsvärden som hör till portalen och skickas dit.
const PORTAL_PATHS = new Map([
  ["/portal", "/"],
  ["/portal.html", "/"],
  ["/registrera", "/registrera"],
  ["/registrera.html", "/registrera"],
]);

function isPortalHost(req) {
  return Boolean(PORTAL_HOST) && requestHost(req) === PORTAL_HOST;
}

/** Lokalt (localhost, 127.0.0.1) skickas ingen vidare: där finns ingen portalvärd. */
function isLocalHost(req) {
  const host = requestHost(req);
  return host === "localhost" || host === "127.0.0.1" || host === "";
}

function serveStatic(req, res) {
  let urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
  const query = (req.url || "").includes("?") ? (req.url || "").slice((req.url || "").indexOf("?")) : "";
  if (PORTAL_HOST && !isPortalHost(req) && !isLocalHost(req) && PORTAL_PATHS.has(urlPath)) {
    // 302, inte 301: en flytt av portalen ska inte fastna i webbläsarnas cache.
    // Hash (#access_token från e-postlänken) följer med av sig själv.
    res.writeHead(302, { Location: `${PORTAL_ORIGIN}${PORTAL_PATHS.get(urlPath)}${query}` });
    res.end();
    return;
  }
  if (urlPath === "/") {
    urlPath = isAdminHost(req) ? "/admin.html" : isPortalHost(req) ? "/portal.html" : "/index.html";
  }
  const filePath = path.normalize(path.join(DIST, urlPath));
  if (!filePath.startsWith(DIST)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }
  fs.readFile(filePath, (err, data) => {
    if (err) {
      // Snygga sökvägar utan ändelse: /portal -> portal.html. Samma regel som
      // nginx.conf:s `try_files $uri.html`. Utan den föll /portal igenom till
      // index.html-fallbacken nedan och visade marknadssidan i stället för
      // portalen -- en 200 med fel innehåll, vilket är svårare att upptäcka
      // än en 404.
      if (!path.extname(filePath)) {
        const asHtml = `${filePath}.html`;
        if (asHtml.startsWith(DIST) && fs.existsSync(asHtml)) {
          res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
          res.end(fs.readFileSync(asHtml));
          return;
        }
      }
      // robots.txt / sitemap.xml m.m. får aldrig bli HTML — Google tolkar det
      // som "saknas" och indexerar fel. Pretty paths utan ändelse → index.
      const missingExt = path.extname(filePath).toLowerCase();
      if (missingExt && NO_HTML_FALLBACK.has(missingExt)) {
        res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
        res.end("Not found");
        return;
      }
      const html = path.join(DIST, "index.html");
      fs.readFile(html, (err2, indexData) => {
        if (err2) {
          res.writeHead(404);
          res.end("Not found");
          return;
        }
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end(indexData);
      });
      return;
    }
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, {
      "Content-Type": MIME[ext] || "application/octet-stream",
      ...(ext.match(/\.(css|js|png|jpg|jpeg|gif|ico|svg|webp|woff2?)$/)
        ? { "Cache-Control": "public, max-age=604800" }
        : {}),
    });
    res.end(data);
  });
}

const server = http.createServer(async (req, res) => {
  const origin = req.headers.origin || "";
  const url = (req.url || "").split("?")[0];

  if (url === "/api/config" && (req.method === "GET" || req.method === "HEAD")) {
    cors(res, origin);
    json(res, 200, {
      ok: true,
      chatwootWebsiteToken: CHATWOOT_WEBSITE_TOKEN || null,
      glitchtipDsn: GLITCHTIP_DSN || null,
      listmonkPublicList: PUBLIC_LIST_UUID,
    });
    return;
  }

  if (url === "/api/subscribe" || url === "/api/lead") {
    cors(res, origin);
    if (req.method === "OPTIONS") {
      res.writeHead(204);
      res.end();
      return;
    }
    if (req.method !== "POST") {
      json(res, 405, { ok: false, error: "method_not_allowed" });
      return;
    }

    try {
      const body = await readBody(req);

      if (url === "/api/subscribe") {
        const email = String(body.email || "").trim().toLowerCase();
        const name = String(body.name || "").trim().slice(0, 200);
        if (!isEmail(email)) {
          json(res, 422, { ok: false, error: "invalid_email" });
          return;
        }
        const result = await listmonkPublicSubscribe({
          email,
          name,
          listUuids: body.list_uuids,
        });
        json(res, 200, { ok: true, listmonk: result });
        return;
      }

      // /api/lead
      const name = String(body.name || "").trim().slice(0, 200);
      const email = String(body.email || "").trim().toLowerCase();
      const company = String(body.company || "").trim().slice(0, 200);
      const message = String(body.message || "").trim().slice(0, 5000);
      const source = String(body.source || "taxitips_web").slice(0, 100);
      const page = String(body.page || "").slice(0, 500);

      if (!name || !isEmail(email) || message.length < 10) {
        json(res, 422, { ok: false, error: "invalid_fields" });
        return;
      }

      const [listmonkResult, crmResult] = await Promise.all([
        listmonkPrivateLead({
          email,
          name: company ? `${name} · ${company}` : name,
          attribs: { source, company, message: message.slice(0, 1000), page },
        }),
        djangoCrmLead({ name, email, company, message, source, page }),
      ]);

      // Always also put them on the public launch list (double opt-in).
      let publicSub = null;
      try {
        publicSub = await listmonkPublicSubscribe({
          email,
          name: company || name,
        });
      } catch {
        publicSub = { ok: false };
      }

      json(res, 200, {
        ok: true,
        listmonk_leads: listmonkResult,
        listmonk_public: publicSub,
        crm: crmResult,
      });
    } catch (err) {
      console.error("[api]", err);
      json(res, 500, { ok: false, error: err.message || "server_error" });
    }
    return;
  }

  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405);
    res.end();
    return;
  }
  serveStatic(req, res);
});

server.listen(PORT, () => {
  console.log(`taxitips-web listening on :${PORT}`);
});
