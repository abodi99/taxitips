import { setupConsent } from "./consent.js";
import { trackEvent } from "./analytics.js";
import { setupForms } from "./forms.js";
import { initChatwoot } from "./chatwoot.js";
import { loadRuntimeConfig } from "./config.js";

// Confirms JS is running before CSS hides anything behind [data-reveal] —
// no-JS visitors get the full page instantly, no broken hidden content.
document.documentElement.classList.add("js");

const prefersReducedMotion = window.matchMedia(
  "(prefers-reduced-motion: reduce)"
).matches;

setupForms();

loadRuntimeConfig().finally(() => {
  setupConsent();
  initChatwoot();
});

const footerYear = document.getElementById("footerYear");
if (footerYear) footerYear.textContent = String(new Date().getFullYear());

// ---------- CTA click tracking ----------

document.querySelectorAll("[data-track]").forEach((el) => {
  el.addEventListener("click", () => trackEvent(el.dataset.track));
});

// ---------- FAQ accordion ----------

document.querySelectorAll(".faq-question").forEach((button) => {
  button.addEventListener("click", () => {
    const item = button.closest(".faq-item");
    const isOpen = item.classList.toggle("is-open");
    button.setAttribute("aria-expanded", String(isOpen));
  });
});

// ---------- Scroll reveal ----------
// Low threshold so tall elements (the sticky phone, long lists) on a short
// phone screen still trigger; the -8% bottom margin keeps it from firing
// for things that only just peek in.

const revealTargets = document.querySelectorAll("[data-reveal]");

if (revealTargets.length) {
  const revealObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          revealObserver.unobserve(entry.target);
        }
      }
    },
    { threshold: 0.15, rootMargin: "0px 0px -8% 0px" }
  );
  revealTargets.forEach((el) => revealObserver.observe(el));
}

// ---------- Mobile menu: one button, closes on link tap, Esc or outside tap ----------

const navToggle = document.querySelector(".nav-toggle");
const siteNav = document.getElementById("siteNav");

if (navToggle && siteNav) {
  const setOpen = (open) => {
    siteNav.classList.toggle("is-open", open);
    navToggle.setAttribute("aria-expanded", String(open));
    navToggle.setAttribute("aria-label", open ? "Stäng menyn" : "Öppna menyn");
  };
  navToggle.addEventListener("click", () => setOpen(!siteNav.classList.contains("is-open")));
  siteNav.querySelectorAll(".nav-links a").forEach((a) => a.addEventListener("click", () => setOpen(false)));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && siteNav.classList.contains("is-open")) {
      setOpen(false);
      navToggle.focus();
    }
  });
  document.addEventListener("click", (e) => {
    if (siteNav.classList.contains("is-open") && !siteNav.contains(e.target)) setOpen(false);
  });
}

// ---------- Nav: border + shadow once the page has scrolled ----------

const nav = document.getElementById("siteNav");
if (nav) {
  const onScroll = () => nav.classList.toggle("is-scrolled", window.scrollY > 8);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });
}

// ---------- Sticky mobile CTA: appears once the hero is behind you,
// hides again at the contact form (which is where it points) ----------

const stickyCta = document.getElementById("stickyCta");
const hero = document.querySelector(".hero");
const contact = document.getElementById("kontakt");

if (stickyCta && hero && contact) {
  let heroVisible = true;
  let contactVisible = false;
  const update = () =>
    stickyCta.classList.toggle("is-visible", !heroVisible && !contactVisible);

  new IntersectionObserver((entries) => {
    heroVisible = entries[0].isIntersecting;
    update();
  }).observe(hero);

  new IntersectionObserver(
    (entries) => {
      contactVisible = entries[0].isIntersecting;
      update();
    },
    { threshold: 0.1 }
  ).observe(contact);
}

// ---------- Hero lock screen: a new notification lands every few seconds ----------
// Purely illustrative (captioned "Exempel"). One card at a time slides in on
// top and the oldest fades out at the bottom, like a real lock screen.

const stack = document.getElementById("notifStack");

if (stack && !prefersReducedMotion) {
  const pool = [
    { title: "Färja på väg in · Visby", body: "Lägger till 21:35.", lvl: "Medel" },
    { title: "Tåg försenat · Norrköping C", body: "40 min sen, sista tåget mot Linköping.", lvl: "Stark" },
    { title: "Olycka · E4 vid Sundsvall", body: "Trafiken står still norrut.", lvl: "Medel" },
    { title: "Match slutar · Ullevi", body: "Publiken går hem cirka 21:50.", lvl: "Stark" },
    { title: "Ersättningsbuss · Karlstad C", body: "Inga tåg mot Kil i kväll.", lvl: "Stark" },
    { title: "Sista planet · Arlanda", body: "Landar 00:20, sedan tomt till morgonen.", lvl: "Medel" },
  ];
  const template = stack.querySelector(".notif");
  const MAX = 3;
  let next = 0;
  let timer = null;

  function push() {
    stack.classList.add("settled");
    const item = pool[next++ % pool.length];
    const card = template.cloneNode(true);
    card.classList.remove("is-leaving");
    card.classList.add("is-new");
    card.querySelector(".notif-meta span:last-child").textContent = "nu";
    card.querySelector(".notif-title").textContent = item.title;
    const body = card.querySelector(".notif-body");
    body.textContent = `${item.body} `;
    const lvl = document.createElement("b");
    lvl.className = `lvl ${item.lvl === "Stark" ? "lvl-hi" : "lvl-mid"}`;
    lvl.textContent = item.lvl;
    body.append(lvl);

    // Older cards age by one step: "nu" → "2 min" → "6 min".
    stack.querySelectorAll(".notif:not(.is-leaving)").forEach((el, i) => {
      el.querySelector(".notif-meta span:last-child").textContent =
        ["2 min", "6 min", "9 min"][i] ?? "";
    });

    stack.prepend(card);

    const live = stack.querySelectorAll(".notif:not(.is-leaving)");
    if (live.length > MAX) {
      const old = live[live.length - 1];
      old.classList.add("is-leaving");
      old.addEventListener("animationend", () => old.remove(), { once: true });
    }
  }

  const start = () => { if (!timer) timer = window.setInterval(push, 3800); };
  const stop = () => { window.clearInterval(timer); timer = null; };

  // Only animate while the hero is on screen and the tab is visible —
  // no work for a phone that has scrolled on or switched apps.
  let onScreen = true;
  new IntersectionObserver((entries) => {
    onScreen = entries[0].isIntersecting;
    onScreen && !document.hidden ? start() : stop();
  }).observe(stack);
  document.addEventListener("visibilitychange", () => {
    onScreen && !document.hidden ? start() : stop();
  });

  // First push after the opening sequence has finished.
  window.setTimeout(() => { if (onScreen && !document.hidden) start(); }, 2600);
}

// ---------- Tip anatomy: list item ↔ numbered pin on the screenshot ----------

const tipShot = document.querySelector(".tip-shot");
const tipItems = document.querySelectorAll("[data-pin-target]");

if (tipShot && tipItems.length) {
  const pins = tipShot.querySelectorAll(".pin");
  const setActive = (n) => {
    tipItems.forEach((li) => li.classList.toggle("is-active", li.dataset.pinTarget === n));
    pins.forEach((p) => p.classList.toggle("is-active", p.dataset.pin === n));
  };

  const lastPin = pins[pins.length - 1];
  if (prefersReducedMotion || !lastPin) {
    tipShot.classList.add("pins-done");
  } else {
    lastPin.addEventListener("animationend", () => tipShot.classList.add("pins-done"), { once: true });
  }

  // Pointer/keyboard: hovering or focusing a row lights its pin.
  tipItems.forEach((li) => {
    li.addEventListener("pointerenter", () => setActive(li.dataset.pinTarget));
    li.addEventListener("focusin", () => setActive(li.dataset.pinTarget));
  });

  // Scrolling: the row crossing the middle of the screen is the active one.
  // On desktop the screenshot is sticky beside the list, so the pins follow.
  const middle = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) setActive(entry.target.dataset.pinTarget);
      }
    },
    { rootMargin: "-45% 0px -45% 0px" }
  );
  tipItems.forEach((li) => middle.observe(li));
}

// ---------- Tip card: the countdown keeps itself current ----------
// Speeded up (a "minute" every few seconds) so a visitor sees the point:
// the card never shows a stale "om 7 tim" like a frozen timestamp would.

const countdowns = document.querySelectorAll("[data-countdown]");

if (tipShot && countdowns.length && !prefersReducedMotion) {
  const start = [...countdowns].map((el) => Number(el.dataset.countdown));
  let elapsed = 0;
  const fmt = (m) => {
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60);
    return m % 60 ? `${h} tim ${m % 60} min` : `${h} tim`;
  };
  const chip = tipShot.querySelector(".ac-live");

  window.setInterval(() => {
    if (document.hidden || !tipShot.classList.contains("is-visible")) return;
    elapsed = elapsed >= 9 ? 0 : elapsed + 1;
    countdowns.forEach((el, i) => { el.textContent = fmt(start[i] - elapsed); });
    chip?.classList.remove("tick");
    void chip?.offsetWidth; // restart the flash animation
    chip?.classList.add("tick");
  }, 3000);
}
