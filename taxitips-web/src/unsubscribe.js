import { portal } from "./config.js";

// Sidan taxitips.se/avregistrera. Token i adressen är signerad av servern och
// pekar ut en mottagare; den säger ingenting om vem det är.
const token = new URLSearchParams(window.location.search).get("t") || "";
const show = (id) => {
  for (const section of ["ask", "done", "invalid"]) {
    document.getElementById(section).hidden = section !== id;
  }
};

if (!token) show("invalid");

document.getElementById("confirm").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const error = document.getElementById("error");
  button.disabled = true;
  error.hidden = true;
  try {
    const base = String(portal.apiBaseUrl || "").replace(/\/$/, "");
    const res = await fetch(`${base}/api/crm/avregistrera/${encodeURIComponent(token)}`, {
      method: "POST",
    });
    if (res.ok) return show("done");
    if (res.status === 404) return show("invalid");
    throw new Error(String(res.status));
  } catch {
    error.textContent = "Det gick inte just nu. Försök igen om en stund, eller svara \"nej tack\" på mejlet.";
    error.hidden = false;
    button.disabled = false;
  }
});
