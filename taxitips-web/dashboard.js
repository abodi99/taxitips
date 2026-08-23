const companyName = document.getElementById("companyName");
const statusLine = document.getElementById("statusLine");
const planLine = document.getElementById("planLine");
const seatsInput = document.getElementById("seatsInput");
const deviceList = document.getElementById("deviceList");
const joinCodeBox = document.getElementById("joinCodeBox");
const joinHint = document.getElementById("joinHint");
const joinError = document.getElementById("joinError");
const transferResult = document.getElementById("transferResult");
const transferCodeBox = document.getElementById("transferCodeBox");
const paidNote = document.getElementById("paidNote");
const billingError = document.getElementById("billingError");
const orgLine = document.getElementById("orgLine");
const orgInput = document.getElementById("orgInput");
const orgHint = document.getElementById("orgHint");
const orgError = document.getElementById("orgError");
const ticketList = document.getElementById("ticketList");
const ticketOk = document.getElementById("ticketOk");
const ticketError = document.getElementById("ticketError");
const memberOk = document.getElementById("memberOk");
const memberError = document.getElementById("memberError");
const memberList = document.getElementById("memberList");
const adminLink = document.getElementById("adminLink");
const areaGrid = document.getElementById("areaGrid");
const areasOk = document.getElementById("areasOk");
const areasError = document.getElementById("areasError");
const areasSummary = document.getElementById("areasSummary");
const customArea = document.getElementById("customArea");

let areaCatalog = [];
let selectedAreas = new Set();
let currentJoinCode = "";

const STATUS_SV = {
  open: "Öppen",
  in_progress: "Pågår",
  waiting: "Väntar på er",
  resolved: "Löst",
  closed: "Stängd",
};

function statusBadge(access, company) {
  if (company.status === "owner" || access?.reason === "owner") {
    return `<span class="badge ok">Ägare — gratis</span>`;
  }
  if (access?.reason === "trial") {
    const end = access.trialEndsAt || company.trialEndsAt;
    const days = Math.max(0, Math.ceil((end - Date.now()) / 86400000));
    return `<span class="badge warn">Provperiod · ${days} dagar kvar</span>`;
  }
  if (access?.reason === "past_due_grace" || access?.grace) {
    const days = Math.max(0, Math.ceil(((access.graceUntil || 0) - Date.now()) / 86400000));
    return `<span class="badge warn">Betalning saknas · ${days} dagar grace</span>`;
  }
  if (access?.ok) return `<span class="badge ok">Aktiv</span>`;
  return `<span class="badge">Ej aktiv</span>`;
}

function renderGraceBanner(ent) {
  const el = document.getElementById("graceBanner");
  if (!el) return;
  if (!ent?.grace && ent?.reason !== "past_due_grace") {
    el.hidden = true;
    return;
  }
  const days = Math.max(0, Math.ceil(((ent.graceUntil || 0) - Date.now()) / 86400000));
  el.hidden = false;
  el.innerHTML = `Betalningen misslyckades. Ni har fortfarande tillgång i <strong>${days} dagar</strong>. <a href="#billing">Uppdatera betalmetod</a> via portalen.`;
}

function renderDevices(devices) {
  if (!devices.length) {
    deviceList.innerHTML = `<p class="muted">Inga förare ännu. Kopiera bolagskoden ovan och be dem öppna <a href="/join.html">join</a>.</p>`;
    return;
  }
  deviceList.innerHTML = devices
    .map((d) => {
      const push = d.hasPush ? " · push på" : "";
      const cities = (d.notifyPrefs?.cities || []).join(", ");
      return `
      <div class="device-row">
        <div>
          <strong>${escapeHtml(d.label)}</strong>
          <div class="muted">${d.kind === "shared" ? "Delad enhet" : "Förartelefon"}${push}${cities ? ` · ${escapeHtml(cities)}` : ""} · ${d.swapsRemainingThisMonth ?? 2} byte kvar i månaden</div>
        </div>
        <div class="row" style="gap:0.35rem;width:auto">
          <button class="btn btn-ghost" data-transfer="${d.id}" type="button" style="width:auto">Byt telefon</button>
          <button class="btn btn-danger" data-del="${d.id}" type="button" style="width:auto">Ta bort</button>
        </div>
      </div>`;
    })
    .join("");

  deviceList.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetch(`/api/devices/${btn.getAttribute("data-del")}`, { method: "DELETE" });
      load();
    });
  });
  deviceList.querySelectorAll("[data-transfer]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      joinError.hidden = true;
      const res = await fetch(`/api/devices/${btn.getAttribute("data-transfer")}/transfer-code`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        joinError.textContent = data.error || "Kunde inte skapa byteskod";
        joinError.hidden = false;
        return;
      }
      transferResult.hidden = false;
      transferCodeBox.textContent = data.code;
    });
  });
}

function renderMembers(members) {
  const el = document.getElementById("memberList");
  if (!el) return;
  if (!members.length) {
    el.innerHTML = `<p class="muted">Inga medlemmar ännu.</p>`;
    return;
  }
  const ROLE_SV = { company_owner: "Ägare", company_admin: "Admin", driver: "Förare" };
  el.innerHTML = members
    .map(
      (m) => `
      <div class="device-row">
        <div>
          <strong>${escapeHtml(m.name || m.email)}</strong>
          <div class="muted">${escapeHtml(m.email)}${m.emailVerified ? "" : " · e-post ej verifierad"}</div>
        </div>
        <div class="row" style="gap:0.35rem;width:auto">
          <span class="badge ${m.role === "company_owner" ? "ok" : ""}">${ROLE_SV[m.role] || m.role}</span>
          ${
            m.role !== "company_owner"
              ? `
            <select class="member-role" data-role="${m.userId}" title="Ändra roll" style="width:auto;min-height:auto;padding:0.3rem 0.4rem">
              <option value="company_admin" ${m.role === "company_admin" ? "selected" : ""}>Admin</option>
              <option value="driver" ${m.role === "driver" ? "selected" : ""}>Förare</option>
            </select>
            <button class="btn btn-danger" data-remove="${m.userId}" type="button" style="width:auto">Ta bort</button>`
              : ""
          }
        </div>
      </div>`
    )
    .join("");

  el.querySelectorAll("[data-role]").forEach((sel) => {
    sel.addEventListener("change", async () => {
      const userId = sel.getAttribute("data-role");
      const role = sel.value;
      const res = await fetch(`/api/company/members/${userId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        memberError.textContent = d.error || "Kunde inte ändra roll";
        memberError.hidden = false;
      }
      load();
    });
  });
  el.querySelectorAll("[data-remove]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const userId = btn.getAttribute("data-remove");
      if (!confirm("Ta bort medlemmen från kontot?")) return;
      await fetch(`/api/company/members/${userId}`, { method: "DELETE" });
      load();
    });
  });
}

function renderTickets(list) {
  if (!list.length) {
    ticketList.innerHTML = `<p class="muted">Inga ärenden ännu.</p>`;
    return;
  }
  ticketList.innerHTML = list
    .map((t) => {
      const last = t.messages?.[t.messages.length - 1];
      return `<div class="device-row" style="align-items:flex-start;flex-direction:column;gap:0.5rem">
        <div style="display:flex;justify-content:space-between;width:100%;gap:1rem;flex-wrap:wrap">
          <div>
            <strong>${escapeHtml(t.subject)}</strong>
            <div class="muted">${STATUS_SV[t.status] || t.status} · ${escapeHtml(t.category)} · ${new Date(t.updatedAt).toLocaleString("sv-SE")}</div>
          </div>
          <span class="badge">${escapeHtml(t.id)}</span>
        </div>
        ${last ? `<div class="muted" style="white-space:pre-wrap">${escapeHtml(last.role)}: ${escapeHtml(last.body)}</div>` : ""}
        ${
          t.status !== "closed" && t.status !== "resolved"
            ? `<div class="row" style="width:100%">
                <input data-reply="${t.id}" placeholder="Svara…" style="flex:1" />
                <button class="btn btn-ghost" type="button" data-send="${t.id}">Skicka</button>
              </div>`
            : ""
        }
      </div>`;
    })
    .join("");

  ticketList.querySelectorAll("[data-send]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-send");
      const input = ticketList.querySelector(`[data-reply="${id}"]`);
      const body = input?.value?.trim();
      if (!body) return;
      await fetch(`/api/tickets/${id}/reply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
      });
      loadTickets();
    });
  });
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderOrg(company) {
  orgInput.value = company.orgNumber || "";
  if (company.orgNumber) {
    const info = company.companyInfo;
    orgLine.textContent = `Org.nr ${company.orgNumber}${
      info?.legalForm ? " · " + info.legalForm : ""
    }${info?.found === false ? " · uppslag ej kopplat än" : ""}`;
    if (info?.address) {
      orgHint.textContent = [info.address.street, info.address.zip, info.address.city]
        .filter(Boolean)
        .join(", ");
    } else {
      orgHint.textContent = info?.message || "";
    }
  } else {
    orgLine.textContent = "Org.nr saknas — fyll i för faktura och support";
    orgHint.textContent = "";
  }
}

function renderAreas() {
  const extras = [...selectedAreas].filter(
    (a) => !areaCatalog.some((c) => c.toLowerCase() === a.toLowerCase())
  );
  const names = [...areaCatalog, ...extras];
  areaGrid.innerHTML = names
    .map((name) => {
      const checked = [...selectedAreas].some((a) => a.toLowerCase() === name.toLowerCase());
      return `<label><input type="checkbox" value="${escapeHtml(name)}" ${checked ? "checked" : ""}/> ${escapeHtml(name)}</label>`;
    })
    .join("");

  areaGrid.querySelectorAll("input[type=checkbox]").forEach((box) => {
    box.addEventListener("change", () => {
      if (box.checked) selectedAreas.add(box.value);
      else {
        selectedAreas = new Set(
          [...selectedAreas].filter((a) => a.toLowerCase() !== box.value.toLowerCase())
        );
      }
      updateAreasSummary();
    });
  });
  updateAreasSummary();
}

function updateAreasSummary() {
  if (!selectedAreas.size) {
    areasSummary.textContent = "Inga områden valda — visar allt.";
  } else {
    areasSummary.textContent = `Följer: ${[...selectedAreas].join(", ")}`;
  }
}

async function loadAreas() {
  const res = await fetch("/api/company/areas");
  if (!res.ok) return;
  const data = await res.json();
  areaCatalog = data.catalog || [];
  selectedAreas = new Set(data.watchedAreas || []);
  renderAreas();
}

async function loadTickets() {
  const res = await fetch("/api/tickets");
  if (!res.ok) return;
  const data = await res.json();
  renderTickets(data.tickets || []);
}

async function load() {
  const res = await fetch("/api/me");
  if (res.status === 401) {
    location.href = "/login.html";
    return;
  }
  const data = await res.json();
  const { company, access, pricing, devices, stripeEnabled } = data;
  const ent = data.entitlements || access;

  companyName.textContent = company.name;
  statusLine.innerHTML = `${statusBadge(ent, company)} · ${company.email}`;
  renderGraceBanner(ent);
  seatsInput.value = company.seats;
  const priceLine = document.getElementById("priceLine");
  if (priceLine) {
    const unit = pricing?.unitPrice || 199;
    const total = (pricing?.monthlyTotal ?? unit * company.seats);
    priceLine.textContent = company.status === "owner"
      ? "Ägarkonto — 0 kr/mån"
      : `${company.seats} bil${company.seats === 1 ? "" : "ar"} med mobilen · ${unit} kr/enhet/mån · <strong>${total.toLocaleString("sv-SE")} kr/mån</strong>`;
  }
  const qtySyncBtn = document.getElementById("qtySyncBtn");
  if (qtySyncBtn) {
    qtySyncBtn.hidden = !(data.billing?.subscription || company.stripeSubscriptionId);
    qtySyncBtn.onclick = async () => {
      billingError.hidden = true;
      const seats = Number(seatsInput.value || 1);
      const res = await fetch("/api/billing/quantity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seats }),
      });
      const data2 = await res.json().catch(() => ({}));
      if (!res.ok) {
        billingError.textContent = data2.error || "Kunde inte uppdatera antal";
        billingError.hidden = false;
        return;
      }
      paidNote.hidden = false;
      paidNote.textContent = `Antal uppdaterat till ${data2.quantity}. Stripe justerar fakturan automatiskt${data2.synced ? "" : " (första betalningen sker vid checkout)"}.`;
      load();
    };
  }
  planLine.textContent = `${pricing.seats} enheter · status: ${company.status}${
    company.status === "owner" ? " (ägare, 0 kr)" : ""
  }${!stripeEnabled ? " · Stripe ej kopplat (dev auto-aktivering)" : ""}`;
  const portalBtn = document.getElementById("portalBtn");
  if (portalBtn) {
    portalBtn.hidden = !(data.billing?.portalAvailable || company.stripeCustomerId);
  }
  if (data.billing?.subscription) {
    const s = data.billing.subscription;
    planLine.textContent += ` · plan ${s.plan || "—"} (${s.status})`;
  }
  if (data.billing?.trialEndsAt || company.trialEndsAt) {
    const end = data.billing?.trialEndsAt || company.trialEndsAt;
    const days = Math.max(0, Math.ceil((end - Date.now()) / 86400000));
    if (company.status === "trial") planLine.textContent += ` · trial ${days} dagar kvar`;
  }

  currentJoinCode = company.joinCode || "";
  joinCodeBox.textContent = currentJoinCode || "—";
  const used = devices?.length || 0;
  const seats = company.seats || 1;
  const free = Math.max(0, seats - used);
  const seatUsageLine = document.getElementById("seatUsageLine");
  if (seatUsageLine) {
    seatUsageLine.innerHTML = `<strong>${used} av ${seats}</strong> använda betalda platser${
      free > 0 ? ` · ${free} lediga` : " · fullt — öka antalet i Medlemskap"
    }`;
  }
  joinHint.textContent =
    free > 0
      ? `${free} ledig plats. Föraren anger koden i appen under “Registrera telefon”.`
      : "Inga lediga platser — öka antalet under Medlemskap, eller använd “Byt telefon” på en befintlig enhet (max 2 byten/månad).";

  renderOrg(company);
  renderDevices(devices || []);
  renderMembers(data.members || []);
  adminLink.hidden = company.status !== "owner";
  selectedAreas = new Set(company.watchedAreas || []);
  const accountName = document.getElementById("accountName");
  const accountEmailLine = document.getElementById("accountEmailLine");
  if (accountName) accountName.value = company.name || "";
  if (accountEmailLine) accountEmailLine.textContent = company.email || "—";
  await loadAreas();

  if (new URLSearchParams(location.search).get("paid") === "1") {
    paidNote.hidden = false;
    paidNote.textContent = "Prenumerationen är uppdaterad.";
  }

  await loadTickets();
}

document.getElementById("checkoutBtn").addEventListener("click", async () => {
  billingError.hidden = true;
  const seats = Number(seatsInput.value || 1);
  const plan = document.getElementById("planSelect")?.value || "driver";
  const interval = document.getElementById("intervalSelect")?.value || "month";
  await fetch("/api/company/seats", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seats }),
  });
  const res = await fetch("/api/billing/checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seats, plan, interval }),
  });
  const data = await res.json();
  if (!res.ok) {
    billingError.textContent = data.error || "Kunde inte starta betalning";
    billingError.hidden = false;
    return;
  }
  if (data.url) location.href = data.url;
  else load();
});

document.getElementById("portalBtn")?.addEventListener("click", async () => {
  billingError.hidden = true;
  const res = await fetch("/api/billing/portal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const data = await res.json();
  if (!res.ok) {
    billingError.textContent = data.error || "Kunde inte öppna portalen";
    billingError.hidden = false;
    return;
  }
  if (data.url) location.href = data.url;
});

document.getElementById("copyJoinBtn").addEventListener("click", async () => {
  if (!currentJoinCode) return;
  try {
    await navigator.clipboard.writeText(currentJoinCode);
    joinHint.textContent = "Bolagskod kopierad.";
  } catch {
    joinHint.textContent = currentJoinCode;
  }
});

document.getElementById("regenJoinBtn").addEventListener("click", async () => {
  joinError.hidden = true;
  const res = await fetch("/api/company/join-code/regenerate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    joinError.textContent = data.error || "Kunde inte skapa ny kod";
    joinError.hidden = false;
    return;
  }
  currentJoinCode = data.joinCode || "";
  joinCodeBox.textContent = currentJoinCode;
  joinHint.textContent = "Ny bolagskod skapad. Ge den till förarna.";
});

document.getElementById("saveOrgBtn").addEventListener("click", async () => {
  orgError.hidden = true;
  const res = await fetch("/api/company/profile", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ orgNumber: orgInput.value.trim() }),
  });
  const data = await res.json();
  if (!res.ok) {
    orgError.textContent = data.error || "Kunde inte spara";
    orgError.hidden = false;
    return;
  }
  if (data.company?.companyInfo?.found && data.company.companyInfo.name) {
    orgHint.textContent = `Uppdaterat från ${data.company.companyInfo.source}: ${data.company.companyInfo.name}`;
  }
  load();
});

document.getElementById("addAreaBtn").addEventListener("click", () => {
  const name = customArea.value.trim();
  if (!name) return;
  selectedAreas.add(name);
  customArea.value = "";
  renderAreas();
});

document.getElementById("saveAreasBtn").addEventListener("click", async () => {
  areasOk.hidden = true;
  areasError.hidden = true;
  const res = await fetch("/api/company/areas", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ watchedAreas: [...selectedAreas] }),
  });
  const data = await res.json();
  if (!res.ok) {
    areasError.textContent = data.error || "Kunde inte spara områden";
    areasError.hidden = false;
    return;
  }
  selectedAreas = new Set(data.watchedAreas || []);
  renderAreas();
  areasOk.hidden = false;
  areasOk.textContent = selectedAreas.size
    ? `Sparat: ${[...selectedAreas].join(", ")}`
    : "Sparat — visar hela Skåne";
});

document.getElementById("ticketBtn").addEventListener("click", async () => {
  ticketOk.hidden = true;
  ticketError.hidden = true;
  const res = await fetch("/api/tickets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      subject: document.getElementById("ticketSubject").value,
      category: document.getElementById("ticketCategory").value,
      body: document.getElementById("ticketBody").value,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    ticketError.textContent = data.error || "Kunde inte skapa ärende";
    ticketError.hidden = false;
    return;
  }
  ticketOk.hidden = false;
  ticketOk.textContent = `Ärende skapat: ${data.ticket.id}`;
  document.getElementById("ticketSubject").value = "";
  document.getElementById("ticketBody").value = "";
  loadTickets();
});

document.getElementById("addMemberBtn").addEventListener("click", async () => {
  memberOk.hidden = true;
  memberError.hidden = true;
  const email = document.getElementById("memberEmail").value.trim();
  const name = document.getElementById("memberName").value.trim();
  const role = document.getElementById("memberRole").value;
  const res = await fetch("/api/company/members", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, name, role }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    memberError.textContent = data.error || "Kunde inte lägga till medlem";
    memberError.hidden = false;
    return;
  }
  memberOk.hidden = false;
  memberOk.textContent = `${data.member?.email} tillagd (${data.member?.created ? "inbjudan skickad" : "medlemmen finns redan"})`;
  document.getElementById("memberEmail").value = "";
  document.getElementById("memberName").value = "";
  load();
});

document.getElementById("logoutBtn").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  location.href = "/";
});

function showAccountMsg(ok, text) {
  const accountOk = document.getElementById("accountOk");
  const accountError = document.getElementById("accountError");
  if (!accountOk || !accountError) return;
  accountOk.hidden = !ok;
  accountError.hidden = ok;
  if (ok) accountOk.textContent = text;
  else accountError.textContent = text;
}

document.getElementById("saveNameBtn")?.addEventListener("click", async () => {
  const name = document.getElementById("accountName")?.value?.trim();
  const res = await fetch("/api/company/profile", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return showAccountMsg(false, data.error || "Kunde inte spara namn");
  showAccountMsg(true, "Bolagsnamn sparat");
  load();
});

document.getElementById("saveEmailBtn")?.addEventListener("click", async () => {
  const res = await fetch("/api/account/email", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      newEmail: document.getElementById("accountNewEmail")?.value,
      currentPassword: document.getElementById("accountEmailPassword")?.value,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return showAccountMsg(false, data.error || "Kunde inte byta e-post");
  document.getElementById("accountNewEmail").value = "";
  document.getElementById("accountEmailPassword").value = "";
  showAccountMsg(true, "E-post uppdaterad");
  load();
});

document.getElementById("savePasswordBtn")?.addEventListener("click", async () => {
  const res = await fetch("/api/account/password", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      currentPassword: document.getElementById("accountCurrentPassword")?.value,
      newPassword: document.getElementById("accountNewPassword")?.value,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return showAccountMsg(false, data.error || "Kunde inte byta lösenord");
  document.getElementById("accountCurrentPassword").value = "";
  document.getElementById("accountNewPassword").value = "";
  showAccountMsg(true, "Lösenord bytt");
});

load();
