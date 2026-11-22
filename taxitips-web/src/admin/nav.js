/**
 * Adminwebbens meny: EN lista över alla vyer, grupperad efter vad man ska
 * göra. Menyn, snabbsökningen (⌘K) och raden ovanför rubriken läser härifrån,
 * så att en vy aldrig heter en sak i menyn och en annan i sökningen.
 *
 * Grupperna följer arbetet, inte tekniken: kunderna och deras konton, sälj,
 * support, det förarna ser i appen, siffror och drift. Allt syns hela tiden --
 * inget ligger under ett hopfällt "Mer".
 */

/** Ikoner i samma stil som /brand/icons: 24×24, 1.8 i linjebredd, rundade. */
const ICONS = {
  home: "M3 11l9-8 9 8M5.5 9v12h4.5v-6h4v6h4.5V9",
  office: "M4 22V3h16v19M2 22h20M9 22v-5h6v5M8 7h1m6 0h1M8 11h1m6 0h1",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  shield: "M12 3l8 3v6c0 4.8-3.4 8-8 9-4.6-1-8-4.2-8-9V6l8-3zM9 12l2 2 4-4",
  funnel: "M3 4h18l-7 8.5V19l-4 2v-8.5L3 4z",
  ticket: "M3 7h18v3.2a1.8 1.8 0 0 0 0 3.6V17H3v-3.2a1.8 1.8 0 0 0 0-3.6V7zM14.5 7v2m0 2.5v1m0 2.5v2",
  chat: "M20.5 12a8.5 8.5 0 0 1-12.4 7.5L3.5 20.5l1-4.4A8.5 8.5 0 1 1 20.5 12zM8.5 12h.01M12 12h.01M15.5 12h.01",
  flag: "M5 21V4m0 0h12l-2.5 4.5L17 13H5",
  calendar: "M4 6h16v15H4zM4 10.5h16M8.5 3v5M15.5 3v5",
  bell: "M6 16.5V11a6 6 0 1 1 12 0v5.5l1.8 1.5H4.2L6 16.5zM10 21h4",
  chart: "M4 3v17h17M8 16v-4.5M12 16V7.5M16 16v-6.5M20 16v-3",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3.5 9h17M3.5 15h17M12 3c2.3 2.4 3.4 5.4 3.4 9s-1.1 6.6-3.4 9c-2.3-2.4-3.4-5.4-3.4-9S9.7 5.4 12 3z",
  pulse: "M3 12h4l2.5-6 5 12 2.5-6h4",
  phoneAlert: "M7 2.5h10v19H7zM11 18.5h2M12 7.5v4.5m0 2.5v.01",
  team: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20.5a6.5 6.5 0 0 1 13 0M16 4.3a3.5 3.5 0 0 1 0 6.4M18.2 14.2a6.5 6.5 0 0 1 3.3 6.3",
  search: "M10.5 18a7.5 7.5 0 1 0 0-15 7.5 7.5 0 0 0 0 15zM21 21l-5.2-5.2",
  plus: "M12 5v14M5 12h14",
  menu: "M4 7h16M4 12h16M4 17h16",
  close: "M6 6l12 12M18 6L6 18",
  key: "M14.5 14a5 5 0 1 0-4.6-3L3 18v3h3v-2h2v-2h2l1.9-1.9a5 5 0 0 0 2.6.9zM16.5 7.5h.01",
  logout: "M14 4h5v16h-5M10 8l-4 4 4 4M6 12h11",
  arrow: "M5 12h14m-5-5l5 5-5 5",
};

export function icon(name, cls = "nav-icon") {
  const d = ICONS[name];
  if (!d) return "";
  return `<svg class="${cls}" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false"
    fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
}

/**
 * Alla vyer. `desc` visas i snabbsökningen, `keys` är extra sökord (det man
 * kan tänkas skriva när man inte vet vad vyn heter), `badge`/`dot` är id:n
 * som main.js fyller med räknare och statusprick.
 */
export const NAV = [
  {
    group: "",
    items: [
      { view: "oversikt", label: "Hem", icon: "home",
        desc: "Det som behöver göras nu, och nyckeltalen.", keys: "start översikt att göra" },
    ],
  },
  {
    group: "Kunder",
    items: [
      { view: "kunder", label: "Alla kunder", icon: "office",
        desc: "Företagen: prov, platser, betalning, inloggningar.",
        keys: "kunder bolag företag org.nr organisationsnummer prov betalande arkiverade avstängda platser förare" },
      { view: "konton", label: "Konton", icon: "user",
        desc: "Enskilda användare: telefoner, lösenordslänk, spärr, radering.",
        keys: "användare inloggning e-post lösenord spärra blockera telefon radera konto" },
      { view: "granskning", label: "Granskningar", icon: "shield", badge: "granskningCount",
        desc: "Riskärenden som spärrar kundens nästa ändring.", keys: "risk spärr godkänn" },
    ],
  },
  {
    group: "Sälj",
    items: [
      { view: "pipeline", label: "CRM", icon: "funnel",
        desc: "Affärer, uppgifter och uppföljning av kunderna.",
        keys: "pipeline affär affärer leads säljlista uppgifter uppföljning ring samtal möte offert" },
      { view: "kuponger", label: "Kuponger", icon: "ticket",
        desc: "Rabattkoder och gratisdagar.", keys: "rabatt kod gratis dagar erbjudande" },
    ],
  },
  {
    group: "Support",
    items: [
      { view: "support", label: "Supportfrågor", icon: "chat", badge: "supportCount",
        desc: "Chatten med kunder och förare i appen.", keys: "support chatt meddelanden svara" },
      { view: "tipprapporter", label: "Tipprapporter", icon: "flag", badge: "tipReportCount",
        desc: "Förare som rapporterat ett tips som fel.", keys: "rapport fel tips felaktigt" },
    ],
  },
  {
    group: "Appen",
    items: [
      { view: "evenemang", label: "Evenemang", icon: "calendar",
        desc: "Det förarna ser under Evenemang i appen.", keys: "konsert match arena importera evenemang" },
      { view: "notiser", label: "Notiser", icon: "bell",
        desc: "Pushnotiser som skickats till förarna.", keys: "push skickade misslyckade" },
    ],
  },
  {
    group: "Statistik",
    items: [
      { view: "dashboard", label: "Rapport", icon: "chart",
        desc: "Hela tjänsten i siffror: intäkt, sälj, användning.",
        keys: "dashboard mrr intäkt nyckeltal ledning kvalitet" },
      { view: "webbstatistik", label: "Webbstatistik", icon: "globe",
        desc: "Besök på webben och i appen.", keys: "besök ga4 analytics google" },
    ],
  },
  {
    group: "Drift",
    items: [
      { view: "status", label: "Status", icon: "pulse", dot: "statusDot",
        desc: "Backend, datakällor, Stripe, e-post och push.",
        keys: "drift källor stripe smtp firebase databas appversion" },
      { view: "aktivitet", label: "Appar och fel", icon: "phoneAlert",
        desc: "Krascher, misslyckade flöden och appversioner.", keys: "krasch fel loggar version" },
    ],
  },
];

/** Längst ner i menyn: sådant man sällan ändrar. */
export const NAV_FOOT = [
  { view: "personal", label: "Personal", icon: "team", group: "Inställningar",
    desc: "Vem i personalen som får göra vad.", keys: "roller behörighet säljare support administratör" },
];

/** Undervyer som hör till en menypunkt. */
const PARENT = { nykund: "kunder", uppfoljning: "pipeline" };

const ALL = [
  ...NAV.flatMap((g) => g.items.map((item) => ({ ...item, group: g.group }))),
  ...NAV_FOOT,
];

/** Menypunkten för en vy, eller undefined. */
export function navItem(view) {
  const key = PARENT[view] ?? view;
  return ALL.find((item) => item.view === key);
}

export function navItems() {
  return ALL;
}

function itemHtml(item) {
  return `<button class="tab" type="button" data-view="${item.view}">
      ${icon(item.icon)}<span class="tab-label">${item.label}</span>
      ${item.badge ? `<span id="${item.badge}" class="nav-count" hidden></span>` : ""}
      ${item.dot ? `<span id="${item.dot}" class="st-dot st-nav" aria-label="" hidden></span>` : ""}
    </button>`;
}

/** Ritar menyn. Körs en gång innan main.js letar upp `.tab`-knapparna. */
export function mountNav(container, foot) {
  if (container) {
    container.innerHTML = NAV.map((g) => `
      <div class="nav-group">
        ${g.group ? `<p class="nav-group-label">${g.group}</p>` : ""}
        ${g.items.map(itemHtml).join("")}
      </div>`).join("");
  }
  if (foot) foot.innerHTML = NAV_FOOT.map(itemHtml).join("");
}
