import { listmonk, twenty, site } from "./config.js";
import { trackEvent } from "./analytics.js";

function setStatus(el, message, kind) {
  if (!el) return;
  el.textContent = message;
  el.dataset.kind = kind || "";
  el.hidden = !message;
}

async function postJson(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = new Error(data?.error || `http_${res.status}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export function setupForms() {
  const earlyForm = document.getElementById("earlyAccessForm");
  if (earlyForm) {
    const status = earlyForm.querySelector("[data-form-status]");
    earlyForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(earlyForm);
      const email = String(fd.get("email") || "").trim().toLowerCase();
      const company = String(fd.get("company") || "").trim();
      if (!email || !email.includes("@")) {
        setStatus(status, "Ange en giltig e-postadress.", "error");
        return;
      }

      const submitBtn = earlyForm.querySelector('[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;
      setStatus(status, "Skickar…", "pending");

      try {
        await postJson(listmonk.subscribePath, {
          email,
          name: company || "",
          list_uuids: [listmonk.listUuid],
        });
        trackEvent("early_access_subscribe", { company: company ? 1 : 0 });
        earlyForm.reset();
        setStatus(
          status,
          "Tack! Kolla mejlen och bekräfta prenumerationen — vi hör av oss när appen släpps.",
          "ok"
        );
      } catch (err) {
        console.warn("[subscribe]", err);
        setStatus(
          status,
          `Något gick fel. Mejla oss på ${site.contactEmail} så hjälper vi dig.`,
          "error"
        );
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  const contactForm = document.getElementById("contactForm");
  if (contactForm) {
    const status = contactForm.querySelector("[data-form-status]");
    contactForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(contactForm);
      const name = String(fd.get("name") || "").trim();
      const email = String(fd.get("email") || "").trim().toLowerCase();
      const company = String(fd.get("company") || "").trim();
      const message = String(fd.get("message") || "").trim();

      if (!name || !email || !email.includes("@") || message.length < 10) {
        setStatus(status, "Fyll i namn, e-post och ett kort meddelande.", "error");
        return;
      }

      const submitBtn = contactForm.querySelector('[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;
      setStatus(status, "Skickar…", "pending");

      try {
        // Prefer server lead endpoint (Twenty CRM + Listmonk leads list).
        // Falls back to public list subscribe if /api/lead is not configured.
        try {
          await postJson(twenty.leadPath, {
            name,
            email,
            company,
            message,
            source: "taxitips_web_contact",
            page: window.location.href,
          });
        } catch (leadErr) {
          if (leadErr.status === 404 || leadErr.status === 501) {
            await postJson(listmonk.subscribePath, {
              email,
              name: [name, company].filter(Boolean).join(" · "),
              list_uuids: [listmonk.listUuid],
            });
          } else {
            throw leadErr;
          }
        }

        trackEvent("contact_submit", { has_company: company ? 1 : 0 });
        contactForm.reset();
        setStatus(status, "Tack! Vi återkommer så snart vi kan.", "ok");
      } catch (err) {
        console.warn("[contact]", err);
        const subject = encodeURIComponent(`Taxi Tips — ${company || name}`);
        const body = encodeURIComponent(
          `Namn: ${name}\nBolag: ${company}\nE-post: ${email}\n\n${message}`
        );
        setStatus(
          status,
          `Kunde inte skicka via formuläret. Öppna mejl till ${site.contactEmail} i stället.`,
          "error"
        );
        window.location.href = `mailto:${site.contactEmail}?subject=${subject}&body=${body}`;
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }
}
