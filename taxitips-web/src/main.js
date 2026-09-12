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
    { threshold: 0.3, rootMargin: "0px 0px -10% 0px" }
  );
  revealTargets.forEach((el) => revealObserver.observe(el));
}

// ---------- Nav: solid once the hero has scrolled past ----------

const nav = document.getElementById("siteNav");
if (nav) {
  const onScroll = () => nav.classList.toggle("is-scrolled", window.scrollY > 24);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });
}

// ---------- Sticky mobile CTA: appears once the hero is behind you,
// hides once the app section (which has its own big CTA) is reached ----------

const stickyCta = document.getElementById("stickyCta");
const hero = document.querySelector(".hero");
const appSection = document.getElementById("app");

if (stickyCta && hero && appSection) {
  let appInView = false;

  const heroObserver = new IntersectionObserver(
    (entries) => {
      const heroVisible = entries[0].isIntersecting;
      stickyCta.classList.toggle("is-visible", !heroVisible && !appInView);
    },
    { threshold: 0 }
  );

  const appObserver = new IntersectionObserver(
    (entries) => {
      appInView = entries[0].isIntersecting;
      if (appInView) stickyCta.classList.remove("is-visible");
    },
    { threshold: 0.2 }
  );

  heroObserver.observe(hero);
  appObserver.observe(appSection);
}

// ---------- Signal board live-cycle ----------
// Purely illustrative (the board is labeled "Exempel") — this proves what a
// live board would feel like, one row updates at a time, like a real
// departure board flapping over a single line rather than refreshing at once.

const board = document.querySelector(".board");
const boardRows = document.querySelectorAll(".board-row");

if (board && boardRows.length && !prefersReducedMotion) {
  const pool = [
    { time: "20:02", place: "Kristianstad", strength: "MEDEL", reason: "Tåg försenat 20 min", hot: false },
    { time: "20:18", place: "Malmö Live", strength: "HÖG", reason: "Konsert slutar", hot: true },
    { time: "20:35", place: "Landskrona", strength: "LÅG", reason: "Färja försenad", hot: false },
    { time: "20:51", place: "Lund Arena", strength: "HÖG", reason: "Match slutar", hot: true },
    { time: "21:07", place: "Malmö C", strength: "MEDEL", reason: "Ersättningsbuss", hot: false },
    { time: "21:22", place: "Helsingborg C", strength: "HÖG", reason: "Tåg inställt", hot: true },
  ];

  let poolIndex = 0;
  let rowIndex = 0;
  let timer = null;

  function updateOneRow() {
    const row = boardRows[rowIndex % boardRows.length];
    const next = pool[poolIndex % pool.length];
    rowIndex++;
    poolIndex++;

    row.classList.add("row-updating");
    window.setTimeout(() => {
      row.querySelector(".col-time").textContent = next.time;
      row.querySelector(".col-place").textContent = next.place;
      row.querySelector(".col-strength").textContent = next.strength;
      row.querySelector(".col-reason").textContent = next.reason;
      row.classList.toggle("board-row-hot", next.hot);
      row.classList.remove("row-updating");
      row.classList.add("row-updated");
      window.setTimeout(() => row.classList.remove("row-updated"), 900);
    }, 220);
  }

  function start() {
    if (timer) return;
    timer = window.setInterval(updateOneRow, 4200);
  }

  function stop() {
    window.clearInterval(timer);
    timer = null;
  }

  start();
  board.addEventListener("mouseenter", stop);
  board.addEventListener("mouseleave", start);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
    else start();
  });
}

// ---------- Phone mockup: subtle mouse-parallax tilt ----------
// Desktop/mouse only — touch has no hover, and a finger resting on the
// screen isn't "aiming" at the phone the way a cursor is.

const phoneMockup = document.getElementById("phoneMockup");
const tiltLayer = phoneMockup?.querySelector(".phone-mockup-tilt");
const canHover = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

if (phoneMockup && tiltLayer && canHover && !prefersReducedMotion) {
  const MAX_TILT = 8;

  phoneMockup.addEventListener("mousemove", (e) => {
    const rect = phoneMockup.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width - 0.5;
    const py = (e.clientY - rect.top) / rect.height - 0.5;
    tiltLayer.style.setProperty("--tilt-x", `${(px * MAX_TILT * 2).toFixed(2)}deg`);
    tiltLayer.style.setProperty("--tilt-y", `${(-py * MAX_TILT * 2).toFixed(2)}deg`);
  });

  phoneMockup.addEventListener("mouseleave", () => {
    tiltLayer.style.setProperty("--tilt-x", "0deg");
    tiltLayer.style.setProperty("--tilt-y", "0deg");
  });
}
