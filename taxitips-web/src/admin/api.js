import { request } from "../portal/api.js";

/**
 * Adminwebbens anrop. Samma inloggning och felhantering som kundportalen
 * (src/portal/api.js) -- en andra kopia hade kunnat skicka token på ett annat
 * sätt och tyst sluta fungera.
 *
 * Behörigheten avgörs av servern (fleet/admin_api.py, StaffRole). Den här
 * filen vet ingenting om vem som får vad.
 */
export const admin = {
  overview: () => request("/api/admin/overview"),
  companies: (q = "") =>
    request(`/api/admin/companies${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  company: (id) => request(`/api/admin/companies/${id}`),
  setSubscription: (id, body) =>
    request(`/api/admin/companies/${id}/subscription`, { method: "POST", body }),
  pairingCode: (id, licenseId) =>
    request(`/api/admin/companies/${id}/pairing-code`, {
      method: "POST",
      body: { license_id: licenseId, label: "Support" },
    }),
  testPush: (id) =>
    request(`/api/admin/companies/${id}/test-push`, { method: "POST", body: {} }),
  blockPhone: (approvalId, reason) =>
    request(`/api/admin/approvals/${approvalId}/block`, {
      method: "POST",
      body: { reason },
    }),
  notifications: (status = "") =>
    request(`/api/admin/notifications${status ? `?status=${status}` : ""}`),
  events: (q = "", hidden = false, days = 14) => {
    const params = new URLSearchParams({ days: String(days) });
    if (q) params.set("q", q);
    if (hidden) params.set("hidden", "1");
    return request(`/api/admin/events?${params}`);
  },
  setEventVisibility: (id, hidden, reason = "") =>
    request(`/api/admin/events/${id}/visibility`, {
      method: "POST",
      body: { hidden, reason },
    }),
  reviews: (status = "open") => request(`/api/admin/reviews?status=${status}`),
  resolveReview: (id, approved, note) =>
    request(`/api/admin/reviews/${id}/resolve`, {
      method: "POST",
      body: { approved, note },
    }),
};
