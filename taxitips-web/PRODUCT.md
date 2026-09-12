# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Plain static HTML/CSS/JS built and served via Vite (no framework). User's explicit choice: "det behöver inte vara react, men något du är stark på och kan uppnå bra design snabbt" — speed and full design control over framework overhead, for a single page.

## Users

Primary: a taxi company owner/decision-maker in Skåne, Sweden, deciding whether to pay for a per-driver-phone subscription tool for their fleet. Secondary: a solo owner-operator driver paying for themselves (treated as "a company of one" — same product, one seat).

Drivers themselves are not the buyer and do not use this landing page to sign up — they join an existing company's account via a code, inside the native app, given to them by their company.

## Product Purpose

Taxi Tips tells a taxi driver where there is a strong demand opportunity right now or soon, and why — using live public transit disruption and road-traffic signals (not internal ride-history or dispatch data). Goal: fewer empty, guessed drives; more driving toward a place that's actually about to need a taxi.

## Positioning

Not a dispatch/ride-hailing platform and not a generic navigation app. The mechanism is specific: it correlates live, publicly-sourced transit and road disruption data (train cancellations, delays, road incidents/closures) into a ranked, explainable "drive here" signal, categorical rather than exact-count based (never fabricates precise passenger counts from GTFS occupancy data). A competitor without a live transit/road data pipeline could not truthfully copy this claim.

## Operating Context

- Company owner discovers/evaluates via this landing page, then manages their account, billing (Stripe subscription, ~199 kr per driver phone/month, 14-day free trial), and driver phone connections entirely inside the Taxitips native app (iOS/Android) — not on the web anymore.
- No web signup, login, or checkout exists as of this rebuild. The only thing the web does is market the product and capture interest — real contact channel: hej@taxitips.se (used consistently as the company's contact address in prior site content and legal copy).
- No App Store / Google Play listing is live yet (verified: no real store URLs exist anywhere in the codebase). Do not imply the app can be downloaded from a store today.

## Capabilities and Constraints

- Confirmed pricing fact (real, not fabricated, previously live on the site): from 199 kr per driver phone per month, 14 days free trial, cancel anytime. Safe to state as a positioning signal; no live checkout to link to.
- Data sources are real and already integrated per the engineering docs: Trafiklab (GTFS static + realtime, trains/buses), Trafikverket (road/traffic incidents). SMHI weather is planned, not yet live — do not claim weather as a current signal.
- Market is Skåne specifically (prior copy: "Tips när taxi behövs — Skåne"), not all of Sweden.
- Brand name: "Taxi Tips" / stylized lockup "taxitips" in the logo.

## Brand Commitments

- Five-color palette only, fixed: midnatt (navy #14213d), guld (gold #fca311), vit (white), ljusgrå (light gray #f5f7fa), skiffer (slate #526078). Documented in `src/brand.css`.
- Typography: Montserrat for display/headings, Inter for body — both already used site-wide, not open for change.
- Existing logo asset family in `public/brand/` (on-light, on-dark, mono variants, stacked lockup) — reuse, do not redraw.
- Existing custom single-color stroke icon set in `public/brand/icons/` (taxi, train, bus, route, filter, hotspot, map-pin, clock, notification, office, drivers, traffic-alert, check, download, smartphone) — reuse/extend this icon language rather than introducing a different one (e.g. an icon font or emoji).
- Voice: plain, efficient, concrete Swedish B2B copy — not hype-driven. Prior copy avoided marketing clichés in favor of specific mechanism claims.

## Evidence on Hand

- No testimonials, customer logos, press mentions, or case studies exist. Do not fabricate any — state the mechanism and data sources as the proof instead.
- Real contact address: hej@taxitips.se. Real company/entity line used in prior footer: "A2M Tech · Malmö".
- A native iOS and Android app exists (confirmed 2026-09-12) and is where the whole product experience lives (account, billing, driver phones, everything). It is not yet published on the App Store or Google Play — no real store URLs exist. The landing page should announce/pre-announce the app (platform badges, "launching soon" framing) without linking to a store listing that doesn't exist yet. Revisit once real store URLs are confirmed.

## Product Principles

0. Never name specific data-provider names (Trafiklab, Trafikverket, etc.) in public-facing copy — competitive/positioning choice, confirmed by the user. Keep the categories visible (train disruptions, road incidents, events) without naming the APIs behind them.
1. The mechanism is the pitch: lead with what specifically makes the signal trustworthy (real transit/road data, explainable, categorical not fabricated-precise) rather than generic "smart AI" framing.
2. One clear buyer, one clear action: the company owner is the primary audience and the page should not dilute focus trying to also fully onboard drivers.
3. Never claim something not yet true: no store download links, no live weather signal, no fabricated social proof.
4. Brand restraint: five colors, two fonts, one icon language — consistency over novelty.
- The web's only job now is to earn a conversation (email) or make the case for the app the company will actually use — not to replicate app functionality.
- Interest capture: early-access / newsletter via Listmonk (`Taxi Tips — lanseringslista`), contact form → `/api/lead` (Listmonk private leads + optional Twenty CRM at taxitips.tw.a2m-tech.com), live chat via Chatwoot when website token is configured. Analytics: Firebase GA4 + Umami after consent; errors via GlitchTip when DSN is set.

## Accessibility & Inclusion

No product-specific requirement beyond standard WCAG AA (contrast, keyboard focus, semantic headings) — carried over as a general quality bar, not a stated user need.
