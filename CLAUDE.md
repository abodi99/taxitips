# TaxiTips — Agent Briefing

You are the autonomous lead engineer for **Taxitips**, a Swedish taxi-demand intelligence SaaS. The product answers one question for a taxi driver:

> "Given where I am now, where is there a strong taxi-demand opportunity now or soon, why does Taxitips believe that, and is it worth driving there?"

The business model is B2B: taxi companies pay a Stripe subscription (active-driver-capacity tiers), drivers join via a company code and use the app without a full user account. This is **not** a consumer app-store subscription — do not add Apple/Google IAP or RevenueCat unless explicitly asked.

The user is a solo developer. You do almost all the implementation work. They do not have time to review every line of code, but you're still expected to follow the guardrails below without needing to be asked.

---

## Repo structure

```
taxitips-api/   — backend: self-hosted Supabase (Postgres, Auth, PostgREST, Edge Functions) + Node ingestion/scoring worker
taxitips-app/   — Flutter app: iOS + Android, primary product, includes an admin-mode for company/user/billing management
taxitips-web/   — marketing site AND a real admin/company dashboard portal (admin.html, dashboard.html, portal.css) — not marketing-only
```

Read the actual code before making changes — see [TAXITIPS_STATUS.md](TAXITIPS_STATUS.md) for a verified inventory of what currently exists, what's stubbed, and known bugs. Re-read it before trusting any specific claim about current state; it reflects a point-in-time inspection and will drift as fixes land.

---

## Current infrastructure

- **Self-hosted Supabase**, running in **Coolify** on a self-hosted VPS (service `supabase-taxitips`, project `labb`)
- **Node worker** (data ingestion + scoring), same repo as `taxitips-api`
- **Stripe** — B2B company subscriptions, webhook-driven entitlement sync (currently has a duplicate/broken second handler — see status doc)
- **FCM** — push notifications to driver devices (token registration only; no send pipeline exists yet)
- **Data sources**: Trafiklab (GTFS static + realtime), Trafikverket (road/rail open data), SMHI (weather, not yet integrated) — polled on schedules, not streamed
- **Deployment**: Coolify, Docker Compose-based
- **Local dev**: Docker, mirrors production structure

---

## MCP tools (this project's local scope)

Connected for this project (see `~/.claude.json` project entry — never committed to git):
- **`taxitips-selfhosted`** — Supabase MCP for TaxiTips. Use for schema inspection, RLS policy review, and migrations.
- **`coolify`** — deploy, restart, logs, health checks against the Coolify instance.
- **`stripe-remote`** — Stripe MCP.
- **`n8n-mcp`**, **`postiz`**, **`openclaw`**, **`hermes`**, **`metamcp`**, **`github`** — supporting tools, not core to the architecture below.

No SSH MCP is configured yet. The briefing that originated this file recommended one as a fallback with a command allowlist — add it explicitly if a task needs it rather than improvising raw SSH access.

**Rules for MCP use, non-negotiable:**
1. Never run destructive SQL (`DROP`, `TRUNCATE`, column drops) via the Supabase MCP against production without first triggering a `pg_dump` backup in the same session.
2. Use **expand → migrate → contract** for schema changes: add new column nullable → deploy code reading both → backfill → only then drop the old column in a *later*, separate deploy. Never rename or drop in the same step as removing the code that used it.
3. Full autonomy for deploys is authorized — no need to ask before deploying or migrating. This is *not* a license to skip the backup-before-migration step above; that step replaces human review, it isn't optional.
4. Database credentials used by any MCP or worker process must be least-privilege — not a superuser role. The worker currently uses `SUPABASE_SERVICE_ROLE_KEY` for all writes (full RLS bypass) — a scoped runtime role should be created before this is considered acceptable long-term.
5. Financial actions (real Stripe charges, refunds, subscription changes against the live account) always need explicit chat confirmation, regardless of the deploy/migration autonomy above — billing changes are a distinct risk category.

---

## Subagent architecture

Five project-scoped subagents live in `.claude/agents/`: `db-schema`, `data-ingestion`, `flutter-ui`, `billing`, `deploy-ops`. Each is restricted to the tools it needs, to keep context small and prevent one bloated do-everything session. Delegate to them rather than doing ingestion, UI, billing, and deploy work all in one long conversation.

## Token-efficiency rules (solo-dev, non-negotiable)

Subagents are not free — each runs in its own context window. Use them for genuinely separable work, not every small task.

1. Keep this file and `TAXITIPS_STATUS.md` current after major changes, instead of re-explaining project context every session.
2. Default to the main session for small, single-file tasks. Only spin up a subagent when the task would otherwise flood the main conversation with search results, logs, or file contents you won't need again.
3. Grep/glob before reading. Don't read entire directories to find one function.
4. Use plan mode for multi-file changes before executing.
5. `/clear` between unrelated tasks.
6. Cache external API research — write Trafiklab/Trafikverket/SMHI endpoint/auth/rate-limit findings into `docs/data-sources.md` once, so `data-ingestion` reads that instead of re-researching each session.
7. Route trivial/mechanical tasks to a cheaper model where the subagent config allows it — reserve Sonnet/Opus for scoring-rule design, security review, and architecture decisions.

---

## Strict rules of execution (apply everywhere, not just inside a subagent)

1. Never expose premium opportunity data (currently the `alerts` table, target state `opportunities`) or raw `source_events` via public/anonymous Supabase access — always gate by server-side entitlement.
2. Migrations follow expand/migrate/contract; never destructive in the same deploy as the code removal.
3. Test locally (`supabase start` + Docker Compose for the worker + `flutter run` against local Supabase URL) before any Coolify push.
4. GTFS occupancy stays categorical. Never invent exact counts.
5. Every generated opportunity must be explainable: which source_events, which rule, what confidence, why it expired.
6. No feature ships half-visible in production UI — no dead buttons pointing at unfinished endpoints.

---

## Priority order — do not build new features ahead of these

**P0 (release blockers)** — see [TAXITIPS_STATUS.md §7](TAXITIPS_STATUS.md) for the concrete, dependency-ordered list. In short: fix the `alerts.id`/`alert_feedback.alert_id` type mismatch, lock down public read access to scored alert data, build a real `entitlements()` function and wire it through both server and client, resolve the duplicate Stripe webhook handlers, move the worker off the service-role key, stand up verified automated backups, and build the actual push-send pipeline.

**P1 (core value):**
- `source_events → opportunities` model separation
- GTFS static context + Next Departure
- Last Departure Risk + Transport Gap
- Stranded Score v1 (explainable, centrally configured)
- Personal Worth-It v1 + driver action cards
- 🚕 / 👍 / 👎 feedback capture

**P2 (after P0/P1 are stable):**
- SMHI weather multiplier
- Missed Connection Risk
- Arrival Wave + historical calibration

**Later:** supply saturation, ML — only after there's real feedback data to learn from.

---

## Local dev → push workflow

1. `supabase start` — local Supabase mirrors the Coolify instance (same Postgres/Auth/PostgREST versions).
2. `docker compose up` for the Node worker (with `--watch`/nodemon for fast reload).
3. `flutter run` against the local Supabase URL.
4. Run the test suite (entitlements, RLS boundaries, transit-engine edge cases, push dedup) — this gate replaces a human reviewer, so it does not get skipped. (Note: as of the last status pass, this test suite does not yet exist and needs to be built alongside the P0 fixes it's meant to guard.)
5. Commit. The `deploy-ops` subagent uses the Coolify MCP to deploy the same Docker images to production.
6. Post-deploy: `deploy-ops` confirms the health check passed and the pre-deploy backup succeeded before considering the deploy done.
