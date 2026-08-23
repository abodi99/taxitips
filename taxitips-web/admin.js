const countsLine = document.getElementById("countsLine");
const billingHint = document.getElementById("billingHint");
const pollLine = document.getElementById("pollLine");
const envLine = document.getElementById("envLine");
const debugBox = document.getElementById("debugBox");
const ticketList = document.getElementById("ticketList");
const companyList = document.getElementById("companyList");
const companyError = document.getElementById("companyError");
const adminLayout = document.getElementById("adminLayout");
const detailPanel = document.getElementById("detailPanel");

const STATUS_SV = {
  open: "Öppen",
  in_progress: "Pågår",
  waiting: "Väntar på kund",
  resolved: "Löst",
  closed: "Stängd",
};

const COMPANY_STATUS_SV = {
  owner: "Ägare",
  trial: "Provperiod",
  active: "Aktiv",
  past_due: "Förfallen",
  suspended: "Pausad",
  canceled: "Avslutad",
};

let adminStatuses = ["trial", "active", "past_due", "suspended", "canceled"];
let allCompanies = [];
let selectedId = null;
let areaCatalog = [];
let selectedAreas = new Set();
let detailCompany = null;

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmtTime(ts) {
  if (!ts) return "—";
  return new Date(ts).toLocaleString("sv-SE");
}

function showCompanyError(msg) {
  if (!companyError) return;
  companyError.textContent = msg || "";
  companyError.hidden = !msg;
}

function filteredCompanies() {
  const q = (document.getElementById("companyQ")?.value || "").trim().toLowerCase();
  const status = document.getElementById("companyStatusFilter")?.value || "";
  return allCompanies.filter((c) => {
    if (status && c.status !== status) return false;
    if (!q) return true;
    const hay = `${c.name || ""} ${c.email || ""} ${c.orgNumber || ""}`.toLowerCase();
    return hay.includes(q);
  });
}

function renderCompanyList() {
  const companies = filteredCompanies();
  if (!companies.length) {
    companyList.innerHTML = `<p class="muted">Inga bolag matchar.</p>`;
    return;
  }
  companyList.innerHTML = companies
    .map((c) => {
      const seats = `${c.seatsUsed ?? c.deviceCount ?? 0}/${c.seats || 1}`;
      const push = `${c.pushReady || 0} push`;
      const accessOk = c.access?.ok ? "tillgång" : "blockerad";
      const chainOk = c.chain?.ready ? "kedja ok" : "kedja ofullständig";
      return `<div class="company-row ${c.id === selectedId ? "active" : ""}" data-open="${escapeHtml(c.id)}">
        <div class="row" style="justify-content:space-between;gap:0.5rem;align-items:center">
          <strong>${escapeHtml(c.name)}</strong>
          <span class="status-pill ${escapeHtml(c.status || "")}">${COMPANY_STATUS_SV[c.status] || c.status}</span>
        </div>
        <div class="muted">${escapeHtml(c.email)} · ${seats} platser · ${push} · ${accessOk}</div>
        <div class="muted">${escapeHtml(c.orgNumber || "inget org.nr")} · ${chainOk} · ${fmtTime(c.createdAt)}</div>
      </div>`;
    })
    .join("");

  companyList.querySelectorAll("[data-open]").forEach((el) => {
    el.addEventListener("click", () => openDetail(el.getAttribute("data-open")));
  });
}

async function openDetail(id) {
  selectedId = id;
  showCompanyError("");
  renderCompanyList();
  detailPanel.hidden = false;
  adminLayout.classList.add("has-detail");
  document.getElementById("detailName").textContent = "Laddar…";

  const res = await fetch(`/api/admin/companies/${id}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showCompanyError(data.error || "Kunde inte hämta kund");
    return;
  }

  detailCompany = data.company;
  areaCatalog = data.areaCatalog || areaCatalog;
  selectedAreas = new Set(data.company.watchedAreas || []);
  fillDetail(data);
}

function fillDetail(data) {
  const c = data.company;
  const isOwner = c.status === "owner";
  document.getElementById("detailName").textContent = c.name || "—";
  document.getElementById("detailMeta").textContent = `${c.email || "—"} · ${c.orgNumber || "inget org.nr"} · skapad ${fmtTime(c.createdAt)} · access: ${
    data.access?.ok ? "ok" : data.access?.reason || "nej"
  }`;

  const statusSel = document.getElementById("detailStatus");
  statusSel.innerHTML = isOwner
    ? `<option value="owner">Ägare</option>`
    : adminStatuses
        .map(
          (s) =>
            `<option value="${s}" ${s === c.status ? "selected" : ""}>${COMPANY_STATUS_SV[s] || s}</option>`
        )
        .join("");
  statusSel.disabled = isOwner;
  document.getElementById("detailSeats").value = c.seats || 1;
  document.getElementById("detailSeats").disabled = isOwner;
  document.getElementById("detailSave").disabled = isOwner;
  document.getElementById("detailActivate").disabled = isOwner;
  document.getElementById("detailCheckout").disabled = isOwner;
  document.getElementById("detailRegenCode").disabled = isOwner;
  document.getElementById("detailSaveAreas").disabled = isOwner;

  const b = data.billing || {};
  const sub = b.subscription;
  document.getElementById("detailBilling").textContent = [
    `Stripe kund: ${c.stripeCustomerId || "—"}`,
    sub ? `sub ${sub.plan || "?"} / ${sub.status || "?"} · qty ${sub.quantity || 1}` : "ingen speglad subscription",
    b.portalAvailable ? "portal tillgänglig" : "portal ej tillgänglig",
  ].join(" · ");
  document.getElementById("detailPortal").disabled = !c.stripeCustomerId;

  document.getElementById("detailJoinCode").textContent = c.joinCode || "(saknas)";
  document.getElementById("detailNotes").value = c.adminNotes || "";

  renderChain(data.chain);
  renderAreas();
  renderDetailDevices(data.devices || []);
  renderDetailTickets(data.tickets || []);
}

function renderChain(chain) {
  const el = document.getElementById("detailChain");
  if (!el) return;
  if (!chain?.steps?.length) {
    el.textContent = "—";
    return;
  }
  el.innerHTML = chain.steps
    .map(
      (s) => `<div class="chain-step">
        <span class="chain-dot ${s.ok ? "ok" : ""}" aria-hidden="true"></span>
        <div><strong>${escapeHtml(s.label)}</strong>
        <div class="muted">${escapeHtml(s.detail || "")}</div></div>
      </div>`
    )
    .join("");
}

function renderAreas() {
  const el = document.getElementById("detailAreas");
  if (!areaCatalog.length) {
    el.innerHTML = `<span class="muted">Ingen katalog</span>`;
    return;
  }
  el.innerHTML = areaCatalog
    .map((name) => {
      const on = selectedAreas.has(name) ? "on" : "";
      return `<button type="button" class="area-chip ${on}" data-area="${escapeHtml(name)}">${escapeHtml(name)}</button>`;
    })
    .join("");
  el.querySelectorAll("[data-area]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (detailCompany?.status === "owner") return;
      const name = btn.getAttribute("data-area");
      if (selectedAreas.has(name)) selectedAreas.delete(name);
      else selectedAreas.add(name);
      renderAreas();
    });
  });
}

function renderDetailDevices(devices) {
  const el = document.getElementById("detailDevices");
  if (!devices.length) {
    el.innerHTML = `<p class="muted">Inga förare ännu. Dela bolagskoden så de registrerar telefonen.</p>`;
    return;
  }
  el.innerHTML = devices
    .map((d) => {
      const cities = (d.notifyPrefs?.cities || []).join(", ") || "inga stadsfilter";
      const push = d.hasPush ? `push · ${escapeHtml(d.platform || "?")}` : "ingen push";
      return `<div class="device-item">
        <div>
          <strong>${escapeHtml(d.label || "Förare")}</strong>
          <div class="muted">${push} · filter: ${escapeHtml(cities)}</div>
          <div class="muted">sedd ${fmtTime(d.lastSeenAt)} · byten kvar ${d.swapsRemainingThisMonth ?? "—"}</div>
        </div>
        <div class="row" style="gap:0.35rem;width:auto">
          <button class="btn btn-ghost" type="button" data-push="${escapeHtml(d.id)}" style="width:auto" ${d.hasPush ? "" : "disabled"}>Test-push</button>
          <button class="btn btn-ghost" type="button" data-transfer="${escapeHtml(d.id)}" style="width:auto">Byteskod</button>
          <button class="btn btn-ghost" type="button" data-del="${escapeHtml(d.id)}" style="width:auto">Ta bort</button>
        </div>
      </div>`;
    })
    .join("");

  el.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!selectedId || !confirm("Ta bort föraren?")) return;
      const res = await fetch(`/api/admin/companies/${selectedId}/devices/${btn.getAttribute("data-del")}`, {
        method: "DELETE",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return showCompanyError(data.error || "Kunde inte ta bort");
      openDetail(selectedId);
      loadOverview(false);
    });
  });

  el.querySelectorAll("[data-transfer]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!selectedId) return;
      const res = await fetch(
        `/api/admin/companies/${selectedId}/devices/${btn.getAttribute("data-transfer")}/transfer-code`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return showCompanyError(data.error || "Kunde inte skapa byteskod");
      const code = data.code || data.transferCode || data.token;
      alert(code ? `Byteskod: ${code}` : JSON.stringify(data));
    });
  });

  el.querySelectorAll("[data-push]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const res = await fetch("/api/admin/test-push", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deviceId: btn.getAttribute("data-push") }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return showCompanyError(data.error || "Push misslyckades");
      alert(data.ok === false ? data.error || "Push misslyckades" : "Test-push skickad (eller simulerad)");
    });
  });
}

function renderDetailTickets(list) {
  const el = document.getElementById("detailTickets");
  if (!list.length) {
    el.innerHTML = `<p class="muted">Inga ärenden.</p>`;
    return;
  }
  el.innerHTML = list
    .map(
      (t) =>
        `<div class="muted" style="margin-bottom:0.35rem"><strong>${escapeHtml(t.subject)}</strong> · ${STATUS_SV[t.status] || t.status} · ${fmtTime(t.updatedAt)}</div>`
    )
    .join("");
}

async function patchSelected(body) {
  if (!selectedId) return;
  showCompanyError("");
  const res = await fetch(`/api/admin/companies/${selectedId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showCompanyError(data.error || "Kunde inte spara");
    return false;
  }
  await loadOverview(false);
  await openDetail(selectedId);
  return true;
}

function renderTickets(list) {
  if (!list?.length) {
    ticketList.innerHTML = `<p class="muted">Inga ärenden.</p>`;
    return;
  }
  ticketList.innerHTML = list
    .map((t) => {
      const thread = (t.messages || [])
        .map(
          (m) =>
            `<div class="muted" style="margin-top:0.35rem;white-space:pre-wrap"><strong>${escapeHtml(m.role)}</strong> ${fmtTime(m.at)}: ${escapeHtml(m.body)}</div>`
        )
        .join("");
      return `<div class="device-row" style="flex-direction:column;align-items:stretch;gap:0.5rem">
        <div style="display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap">
          <div>
            <strong>${escapeHtml(t.subject)}</strong>
            <div class="muted">${escapeHtml(t.companyName || "—")} · ${escapeHtml(t.category)} · ${STATUS_SV[t.status] || t.status}</div>
            <div class="muted">${escapeHtml(t.id)} · uppdaterad ${fmtTime(t.updatedAt)}</div>
          </div>
          <select data-tstatus="${t.id}" style="width:auto;min-height:40px">
            ${["open", "in_progress", "waiting", "resolved", "closed"]
              .map(
                (s) =>
                  `<option value="${s}" ${s === t.status ? "selected" : ""}>${STATUS_SV[s]}</option>`
              )
              .join("")}
          </select>
        </div>
        ${thread}
        <div class="row">
          <input data-reply="${t.id}" placeholder="Svara som support…" style="flex:1" />
          <button class="btn btn-primary" type="button" data-send="${t.id}" style="width:auto">Svara</button>
        </div>
      </div>`;
    })
    .join("");

  ticketList.querySelectorAll("[data-tstatus]").forEach((sel) => {
    sel.addEventListener("change", async () => {
      await fetch(`/api/admin/tickets/${sel.getAttribute("data-tstatus")}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: sel.value }),
      });
      loadTickets();
    });
  });

  ticketList.querySelectorAll("[data-send]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-send");
      const input = ticketList.querySelector(`[data-reply="${id}"]`);
      const body = input?.value?.trim();
      if (!body) return;
      await fetch(`/api/admin/tickets/${id}/reply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body, status: "waiting" }),
      });
      loadTickets();
    });
  });
}

async function loadOverview(reloadDetail = true) {
  const res = await fetch("/api/admin/overview");
  if (res.status === 401) {
    location.href = "/login.html";
    return null;
  }
  if (res.status === 403) {
    countsLine.textContent = "Endast ägarkonto har tillgång till admin.";
    return null;
  }
  const data = await res.json();
  if (data.statuses?.length) adminStatuses = data.statuses;
  allCompanies = data.companies || [];
  countsLine.textContent = `${data.counts.taxiCompanies ?? data.counts.companies} taxibolag · ${data.counts.seatsUsed || 0}/${data.counts.seatsTotal || 0} platser · ${data.counts.pushReady || 0} push · ${data.counts.ticketsOpen} öppna ärenden · ${data.counts.chainReady || 0} kedjor klara`;
  if (billingHint) {
    billingHint.textContent = data.stripeConfigured
      ? data.priceIdsConfigured
        ? "Stripe: på · Price IDs satta"
        : "Stripe: på · Price IDs saknas (sätt STRIPE_PRICE_* i .env)"
      : "Stripe: av (dev autoaktiverar utan nyckel)";
  }
  const chainHint = document.getElementById("chainHint");
  if (chainHint) {
    chainHint.textContent =
      "Kedja: konto → betalning → bolagskod → förare → push → orter → ärenden. Öppna ett bolag för checklista.";
  }
  const seedRow = document.getElementById("seedRow");
  if (seedRow) seedRow.hidden = !data.canSeed;
  const p = data.poll || {};
  pollLine.textContent = `Poll: ${p.source || "—"} · aktivt rått ${p.activeCount ?? "—"} · uppdaterad ${fmtTime(p.at)}${p.error ? " · fel: " + p.error : ""}`;
  envLine.textContent = `Bolagsuppslag: ${data.companyLookupReady ? "nycklar finns" : "saknas"} · billing: ${data.billingMode}`;
  renderCompanyList();
  if (reloadDetail && selectedId) openDetail(selectedId);
  return data;
}

async function loadDebug() {
  const res = await fetch("/api/admin/debug");
  if (!res.ok) return;
  const data = await res.json();
  debugBox.textContent = JSON.stringify(data, null, 2);
}

async function loadTickets() {
  const q = document.getElementById("ticketQ").value.trim();
  const status = document.getElementById("ticketStatus").value;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (status) params.set("status", status);
  const res = await fetch(`/api/admin/tickets?${params}`);
  if (!res.ok) return;
  const data = await res.json();
  renderTickets(data.tickets);
}

async function loadMetrics() {
  const res = await fetch("/api/admin/saas/metrics");
  if (!res.ok) return;
  const m = await res.json();
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };
  set("mCompanies", m.companies);
  set("mSeats", m.seats);
  set("mRevenue", m.revenueMonthDisplay);
  set("mDevices", m.devices);
  set("mPush", m.pushReady);
  set("mTrials", m.trialsActive);
  set("mTrialsSoon", m.trialsEndingSoon);
  set("mTickets", m.openTickets);
}

async function load() {
  const overview = await loadOverview(false);
  if (!overview) return;
  await Promise.all([loadTickets(), loadDebug(), loadMetrics()]);
}

document.getElementById("refreshBtn").addEventListener("click", load);
document.getElementById("ticketFilterBtn").addEventListener("click", loadTickets);
document.getElementById("companyQ")?.addEventListener("input", renderCompanyList);
document.getElementById("companyStatusFilter")?.addEventListener("change", renderCompanyList);
document.getElementById("closeDetail")?.addEventListener("click", () => {
  selectedId = null;
  detailPanel.hidden = true;
  adminLayout.classList.remove("has-detail");
  renderCompanyList();
});

document.getElementById("detailSave")?.addEventListener("click", () => {
  patchSelected({
    status: document.getElementById("detailStatus").value,
    seats: Number(document.getElementById("detailSeats").value || 1),
  });
});

document.getElementById("detailSaveAreas")?.addEventListener("click", () => {
  patchSelected({ watchedAreas: [...selectedAreas] });
});

document.getElementById("detailSaveNotes")?.addEventListener("click", () => {
  patchSelected({ adminNotes: document.getElementById("detailNotes").value });
});

document.getElementById("detailActivate")?.addEventListener("click", async () => {
  if (!selectedId) return;
  const seats = Number(document.getElementById("detailSeats").value || 1);
  const res = await fetch(`/api/admin/companies/${selectedId}/activate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seats }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return showCompanyError(data.error || "Kunde inte aktivera");
  await loadOverview(false);
  openDetail(selectedId);
});

document.getElementById("detailRegenCode")?.addEventListener("click", async () => {
  if (!selectedId) return;
  const res = await fetch(`/api/admin/companies/${selectedId}/join-code`, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return showCompanyError(data.error || "Kunde inte regenerera");
  openDetail(selectedId);
});

document.getElementById("detailPortal")?.addEventListener("click", async () => {
  if (!selectedId) return;
  const res = await fetch(`/api/admin/companies/${selectedId}/portal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return showCompanyError(data.error || "Portal misslyckades");
  if (data.url) window.open(data.url, "_blank", "noopener");
});

document.getElementById("detailCheckout")?.addEventListener("click", async () => {
  if (!selectedId) return;
  const seats = Number(document.getElementById("detailSeats").value || 1);
  const plan = document.getElementById("detailPlan").value;
  const interval = document.getElementById("detailInterval").value;
  const res = await fetch(`/api/admin/companies/${selectedId}/checkout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seats, plan, interval }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return showCompanyError(data.error || "Checkout misslyckades");
  if (data.url) window.open(data.url, "_blank", "noopener");
  else if (data.warning) showCompanyError(data.warning);
});

document.getElementById("pollBtn").addEventListener("click", async () => {
  await fetch("/api/admin/poll", { method: "POST" });
  load();
});
document.getElementById("seedBtn")?.addEventListener("click", async () => {
  showCompanyError("");
  const ok = document.getElementById("seedOk");
  if (ok) ok.hidden = true;
  const res = await fetch("/api/admin/seed", { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showCompanyError(data.error || "Seed misslyckades");
    return;
  }
  if (ok) {
    const logins = data.summary?.logins || {};
    ok.textContent = `Testdata laddad. Demo: ${logins.demoActive || "demo-malmo@taxitips.local"} / ${logins.password || "TaxiTipsDemo1!"}`;
    ok.hidden = false;
  }
  await load();
});
document.getElementById("logoutBtn").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  location.href = "/";
});

load();
