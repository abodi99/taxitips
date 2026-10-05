import { resolve } from "node:path";
import { defineConfig } from "vite";

/**
 * Flera HTML-sidor: marknad, portal, admin m.fl.
 *
 * Vite bygger bara index.html som standard. Utan den här filen hade
 * portal.html funnits i utvecklingsservern men saknats i dist/ -- och felet
 * syns först i produktion, som en 404 på en sida som fungerade lokalt.
 *
 * server.host = 127.0.0.1: utan det lyssnar Vite bara på IPv6 (::1). Då
 * misslyckas http://127.0.0.1:5173/... och http://localhost:5173/... när
 * localhost löses till IPv4 först — symptomet är "sidan svarar inte".
 *
 * Lokalt: http://127.0.0.1:5173/portal.html (eller /portal).
 */
export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
  build: {
    rollupOptions: {
      input: {
        index: resolve(__dirname, "index.html"),
        portal: resolve(__dirname, "portal.html"),
        admin: resolve(__dirname, "admin.html"),
        bekraftad: resolve(__dirname, "bekraftad.html"),
        forare: resolve(__dirname, "forare.html"),
        registrera: resolve(__dirname, "registrera.html"),
        demo: resolve(__dirname, "demo.html"),
      },
    },
  },
});
