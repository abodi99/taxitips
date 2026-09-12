# Taxi Tips — web

The marketing landing page. That's the web's entire job now — company
account management, driver registration, and billing all live in the
Taxitips native app.

Plain HTML/CSS/JS on Vite. No framework, no backend calls, no forms.

## Local dev

```bash
npm install
npm run dev
```

Opens on http://localhost:5173 with hot reload.

## Build

```bash
npm run build
```

Outputs static files to `dist/`, served by the `Dockerfile`'s nginx stage.

## Structure

- `index.html` — the page
- `src/style.css` — styles
- `src/brand.css` — brand tokens (5 colors, 2 fonts) — source of truth, do not add colors
- `public/brand/` — logo, favicon, icon set

## Design system

Built with the `impeccable` skill against `PRODUCT.md` (product truth).
Direction: "Signaltavlan" — the real-time transit departure/status-board
visual language (navy board housing, gold as the live-signal color),
not a generic SaaS dashboard hero.
