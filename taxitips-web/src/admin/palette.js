/**
 * Snabbsökningen (⌘K / Ctrl+K): skriv vad som helst -- ett kundnamn, ett
 * org.nr, en e-postadress eller vad en sida handlar om -- och hoppa dit.
 *
 * Sidorna söks lokalt ur menyn (nav.js) med deras sökord, så att "stripe"
 * hittar Status och "rabatt" hittar Kuponger. Kunder och konton söks på
 * servern med samma anrop som listorna använder; servern avgör behörigheten.
 */
import { icon, navItems } from "./nav.js";

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[ch]);

const norm = (s) => String(s ?? "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

/** Genvägar som inte är en sida i menyn. */
const ACTIONS = [
  { kind: "view", view: "nykund", label: "Ny kund", icon: "plus",
    desc: "Lägg upp ett företag med prov.", keys: "skapa lägg till registrera ny kund bolag" },
];

/**
 * @param {object} opts
 * @param {(view: string) => void} opts.onView
 * @param {(id: string) => void} opts.onCompany
 * @param {(userId: string) => void} opts.onAccount
 * @param {(q: string) => Promise<object>} opts.searchCompanies
 * @param {(q: string) => Promise<object>} opts.searchAccounts
 */
export function setupPalette(opts) {
  const dialog = document.getElementById("palette");
  const input = document.getElementById("paletteInput");
  const list = document.getElementById("paletteList");
  if (!dialog || !input || !list) return { open() {} };

  let results = [];
  let active = 0;
  let seq = 0;
  let timer = null;
  let remote = { companies: [], accounts: [], loading: false };

  const pages = () => [...ACTIONS, ...navItems().map((n) => ({ ...n, kind: "view" }))];

  function matchPages(q) {
    if (!q) return pages().filter((p) => p.view !== "nykund").map((p) => ({ ...p }));
    const words = norm(q).split(/\s+/).filter(Boolean);
    return pages()
      .map((p) => {
        const label = norm(p.label);
        const hay = `${label} ${norm(p.group)} ${norm(p.desc)} ${norm(p.keys)}`;
        if (!words.every((w) => hay.includes(w))) return null;
        const score = label.startsWith(words[0]) ? 0 : label.includes(words[0]) ? 1 : 2;
        return { ...p, score };
      })
      .filter(Boolean)
      .sort((a, b) => a.score - b.score);
  }

  function row(r, i) {
    const id = `pal-${i}`;
    const sel = i === active;
    const lead = r.kind === "company" ? icon("office", "pal-icon")
      : r.kind === "account" ? icon("user", "pal-icon")
        : icon(r.icon, "pal-icon");
    const meta = r.kind === "view" ? (r.group || "") : r.kind === "company" ? "Kund" : "Konto";
    return `<li id="${id}" role="option" aria-selected="${sel}" class="pal-row${sel ? " is-active" : ""}" data-i="${i}">
      ${lead}
      <span class="pal-main"><b>${esc(r.label)}</b>${r.desc ? `<span class="muted">${esc(r.desc)}</span>` : ""}</span>
      ${meta ? `<span class="pal-meta">${esc(meta)}</span>` : ""}
    </li>`;
  }

  function section(title, rows, offset) {
    if (!rows.length) return "";
    return `<li class="pal-head" role="presentation">${esc(title)}</li>${rows.map((r, i) => row(r, offset + i)).join("")}`;
  }

  function paint() {
    const q = input.value.trim();
    const matched = matchPages(q);
    const companies = remote.companies.map((c) => ({
      kind: "company", id: c.id, label: c.name,
      desc: [c.orgNumber, c.trial ? "Prov" : "", ["active", "past_due"].includes(c.subscriptionStatus) ? "Betalande" : ""]
        .filter(Boolean).join(" · "),
    }));
    const accounts = remote.accounts.map((a) => ({
      kind: "account", id: a.userId, label: a.email || a.userId,
      desc: (a.memberships ?? []).map((m) => m.companyName).filter(Boolean).join(", "),
    }));
    // Med en sökning först kunderna (det man oftast letar efter), sedan sidorna.
    const groups = q
      ? [["Kunder", companies], ["Konton", accounts], ["Sidor", matched]]
      : [["Gå till", matched]];
    results = groups.flatMap(([, rows]) => rows);
    if (active >= results.length) active = Math.max(0, results.length - 1);
    let offset = 0;
    let html = "";
    for (const [title, rows] of groups) {
      html += section(title, rows, offset);
      offset += rows.length;
    }
    if (!results.length) {
      html = `<li class="pal-empty" role="presentation">${remote.loading ? "Söker …" : `Inget hittades för “${esc(q)}”.`}</li>`;
    } else if (remote.loading) {
      html += '<li class="pal-empty" role="presentation">Söker bland kunder och konton …</li>';
    }
    list.innerHTML = html;
    input.setAttribute("aria-activedescendant", results.length ? `pal-${active}` : "");
    list.querySelector(".is-active")?.scrollIntoView({ block: "nearest" });
  }

  function searchRemote(q) {
    clearTimeout(timer);
    const mine = ++seq;
    if (q.length < 2) {
      remote = { companies: [], accounts: [], loading: false };
      paint();
      return;
    }
    remote.loading = true;
    timer = setTimeout(async () => {
      // Konton söks bara när det ser ut som en e-postadress eller ett namn på
      // minst tre tecken -- annars blir listan bara brus.
      const [c, a] = await Promise.all([
        opts.searchCompanies(q).catch(() => null),
        q.length >= 3 ? opts.searchAccounts(q).catch(() => null) : null,
      ]);
      if (mine !== seq) return;
      remote = {
        companies: (c?.companies ?? []).slice(0, 6),
        accounts: (a?.accounts ?? []).slice(0, 4),
        loading: false,
      };
      paint();
    }, 220);
  }

  function choose(r) {
    if (!r) return;
    dialog.close();
    if (r.kind === "company") opts.onCompany(r.id);
    else if (r.kind === "account") opts.onAccount(r.id);
    else opts.onView(r.view);
  }

  input.addEventListener("input", () => {
    active = 0;
    searchRemote(input.value.trim());
    paint();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      active = Math.min(results.length - 1, active + 1);
      paint();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      active = Math.max(0, active - 1);
      paint();
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(results[active]);
    }
  });
  list.addEventListener("mousemove", (event) => {
    const li = event.target.closest(".pal-row");
    if (!li) return;
    const i = Number(li.dataset.i);
    if (i !== active) {
      active = i;
      for (const node of list.querySelectorAll(".pal-row")) {
        const on = Number(node.dataset.i) === active;
        node.classList.toggle("is-active", on);
        node.setAttribute("aria-selected", String(on));
      }
    }
  });
  list.addEventListener("click", (event) => {
    const li = event.target.closest(".pal-row");
    if (li) choose(results[Number(li.dataset.i)]);
  });
  // Klick utanför rutan (på bakgrunden) stänger.
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });

  function open(prefill = "") {
    if (dialog.open) return;
    input.value = prefill;
    active = 0;
    remote = { companies: [], accounts: [], loading: false };
    paint();
    dialog.showModal();
    input.focus();
    if (prefill) searchRemote(prefill);
  }

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      if (document.getElementById("app")?.hidden) return;
      event.preventDefault();
      if (dialog.open) dialog.close();
      else open();
    }
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-open-palette]")) open();
  });

  const key = document.getElementById("paletteKey");
  if (key && !/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)) key.textContent = "Ctrl K";

  return { open };
}
