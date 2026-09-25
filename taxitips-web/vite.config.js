import { resolve } from "node:path";
import { defineConfig } from "vite";

/**
 * Två sidor: marknadssajten och kundportalen.
 *
 * Vite bygger bara index.html som standard. Utan den här filen hade
 * portal.html funnits i utvecklingsservern men saknats i dist/ -- och felet
 * syns först i produktion, som en 404 på en sida som fungerade lokalt.
 */
export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        index: resolve(__dirname, "index.html"),
        portal: resolve(__dirname, "portal.html"),
        admin: resolve(__dirname, "admin.html"),
        bekraftad: resolve(__dirname, "bekraftad.html"),
      },
    },
  },
});
