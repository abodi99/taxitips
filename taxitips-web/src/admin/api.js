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
  pairingCode: (id, licenseId, label = "Support") =>
    request(`/api/admin/companies/${id}/pairing-code`, {
      method: "POST",
      body: { license_id: licenseId, label },
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
  events: ({ q = "", hidden = false, days = 14, source = "" } = {}) => {
    const params = new URLSearchParams({ days: String(days) });
    if (q) params.set("q", q);
    if (hidden) params.set("hidden", "1");
    if (source) params.set("source", source);
    return request(`/api/admin/events?${params}`);
  },
  createEvent: (body) => request("/api/admin/events/new", { method: "POST", body }),
  importEvents: (filename, content, dryRun) =>
    request("/api/admin/events/import", { method: "POST", body: { filename, content, dryRun } }),
  deleteEvent: (id) => request(`/api/admin/events/${id}/delete`, { method: "POST", body: {} }),
  venues: (q) => request(`/api/admin/events/venues?q=${encodeURIComponent(q)}`),

  /* --- Bilar (fleet/admin_vehicles.py) --- */
  changeVehicle: (licenseId, plate, mode = "permanent") =>
    request(`/api/admin/licenses/${licenseId}/vehicle`, { method: "POST", body: { plate, mode } }),
  setTrialCounties: (licenseId, base, extras) =>
    request(`/api/admin/licenses/${licenseId}/counties`, { method: "POST", body: { base, extras } }),
  removeLicense: (licenseId, reason) =>
    request(`/api/admin/licenses/${licenseId}/remove`, { method: "POST", body: { reason } }),

  /* --- Konton och spärrar (fleet/admin_accounts.py) --- */
  accounts: (q) => request(`/api/admin/accounts?q=${encodeURIComponent(q)}`),
  blocks: () => request("/api/admin/blocks"),
  block: (kind, value, reason) =>
    request("/api/admin/blocks/new", { method: "POST", body: { kind, value, reason } }),
  liftBlock: (id, note) => request(`/api/admin/blocks/${id}/lift`, { method: "POST", body: { note } }),
  setMember: (companyId, userId, body) =>
    request(`/api/admin/companies/${companyId}/members/${userId}`, { method: "POST", body }),
  verifyCompany: (companyId, status, note) =>
    request(`/api/admin/companies/${companyId}/verification`, { method: "POST", body: { status, note } }),
  staff: () => request("/api/admin/staff"),
  setStaff: (email, role) => request("/api/admin/staff/set", { method: "POST", body: { email, role } }),
  setEventVisibility: (id, hidden, reason = "") =>
    request(`/api/admin/events/${id}/visibility`, {
      method: "POST",
      body: { hidden, reason },
    }),
  reviews: (status = "open") => request(`/api/admin/reviews?status=${status}`),

  /* --- Säljflödet (fleet/admin_sales.py) --- */
  salesConfig: () => request("/api/admin/sales/config"),
  lookup: (orgNumber) =>
    request(`/api/admin/sales/lookup?orgNumber=${encodeURIComponent(orgNumber)}`),
  createCompany: (body) => request("/api/admin/companies/new", { method: "POST", body }),
  updateProfile: (id, body) =>
    request(`/api/admin/companies/${id}/profile`, { method: "POST", body }),
  quote: (id, change) =>
    request(`/api/admin/companies/${id}/quote`, { method: "POST", body: change }),
  order: (id, body) => request(`/api/admin/companies/${id}/orders`, { method: "POST", body }),
  startTrial: (id, vehicles) =>
    request(`/api/admin/companies/${id}/trial`, { method: "POST", body: { vehicles } }),
  redeemCoupon: (id, code, vehicles) =>
    request(`/api/admin/companies/${id}/coupon`, { method: "POST", body: { code, vehicles } }),
  cancelSubscription: (id, reason, immediate = false) =>
    request(`/api/admin/companies/${id}/cancel`, {
      method: "POST",
      body: { reason, immediate },
    }),
  undoCancel: (id) => request(`/api/admin/companies/${id}/undo-cancel`, { method: "POST", body: {} }),
  inviteOwner: (id, email) =>
    request(`/api/admin/companies/${id}/owner-invite`, { method: "POST", body: { email } }),
  paymentLink: (orderId, payment, daysUntilDue = 14) =>
    request(`/api/admin/orders/${orderId}/payment-link`, {
      method: "POST",
      body: { payment, daysUntilDue },
    }),
  refreshOrder: (orderId) =>
    request(`/api/admin/orders/${orderId}/refresh`, { method: "POST", body: {} }),
  markPaid: (orderId, note) =>
    request(`/api/admin/orders/${orderId}/mark-paid`, { method: "POST", body: { note } }),
  cancelOrder: (orderId, reason) =>
    request(`/api/admin/orders/${orderId}/cancel`, { method: "POST", body: { reason } }),
  coupons: () => request("/api/admin/coupons"),
  createCoupon: (body) => request("/api/admin/coupons/new", { method: "POST", body }),
  deactivateCoupon: (id) =>
    request(`/api/admin/coupons/${id}/deactivate`, { method: "POST", body: {} }),
  resolveReview: (id, approved, note) =>
    request(`/api/admin/reviews/${id}/resolve`, {
      method: "POST",
      body: { approved, note },
    }),
};
