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
  // Dashboarden: ledning, sälj, support, uppföljning, drift, användning (fleet/admin_dashboard.py).
  dashboard: () => request("/api/admin/dashboard"),
  // Varje koppling, grön/gul/röd (fleet/admin_status.py). `fresh` kör om
  // kontrollerna; annars ett svar som är högst 30 s gammalt.
  status: (fresh = false) => request(`/api/admin/status${fresh ? "?fresh=1" : ""}`),
  // Minsta och rekommenderade appversion (core/app_version.py). Ändra kräver ADMIN_MANAGE.
  appVersion: () => request("/api/admin/app-version"),
  setAppVersion: (body) => request("/api/admin/app-version", { method: "POST", body }),
  companies: (q = "", archived = false) => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (archived) params.set("archived", "1");
    const qs = params.toString();
    return request(`/api/admin/companies${qs ? `?${qs}` : ""}`);
  },
  archiveCompany: (id, archived = true) =>
    request(`/api/admin/companies/${id}/archive`, { method: "POST", body: { archived } }),
  deleteCompany: (id, confirmName) =>
    request(`/api/admin/companies/${id}/delete`, { method: "POST", body: { confirmName } }),
  company: (id) => request(`/api/admin/companies/${id}`),
  crmStatus: () => request("/api/admin/crm/status"),
  /** f: { stage, q, tags[], city, form, phone, email, sort, limit } — filter AND:as på servern. */
  crmPipeline: (f = {}) => {
    const params = new URLSearchParams();
    if (f.stage) params.set("stage", f.stage);
    if (f.q) params.set("q", f.q);
    for (const t of f.tags ?? []) if (t) params.append("tag", t);
    if (f.city) params.set("city", f.city);
    if (f.form) params.set("form", f.form);
    if (f.phone) params.set("phone", "1");
    if (f.email) params.set("email", "1");
    if (f.sort) params.set("sort", f.sort);
    if (f.limit) params.set("limit", String(f.limit));
    const qs = params.toString();
    return request(`/api/admin/crm/pipeline${qs ? `?${qs}` : ""}`);
  },
  crmDeal: (id) => request(`/api/admin/crm/deals/${id}`),
  crmNoteUpdate: (id, body) =>
    request(`/api/admin/crm/notes/${id}/update`, { method: "POST", body }),
  crmPeopleSearch: (q, excludeAccount = "") => {
    const params = new URLSearchParams({ q });
    if (excludeAccount) params.set("excludeAccount", excludeAccount);
    return request(`/api/admin/crm/people?${params}`);
  },
  crmContactAdd: (dealId, body) =>
    request(`/api/admin/crm/deals/${dealId}/contacts`, { method: "POST", body }),
  crmContactAction: (dealId, personId, action) =>
    request(`/api/admin/crm/deals/${dealId}/contacts/${personId}/${action}`, { method: "POST", body: {} }),
  crmPersonUpdate: (id, body) =>
    request(`/api/admin/crm/people/${id}/update`, { method: "POST", body }),
  /** f: { assignee: "me"|"all"|"none"|userId, status: "open"|"todo"|"doing"|"done" } */
  crmTasks: (f = {}) => {
    const params = new URLSearchParams();
    if (f.assignee) params.set("assignee", f.assignee);
    if (f.status) params.set("status", f.status);
    return request(`/api/admin/crm/tasks?${params}`);
  },
  crmTaskCreate: (body) => request("/api/admin/crm/tasks/create", { method: "POST", body }),
  crmTaskUpdate: (id, body) =>
    request(`/api/admin/crm/tasks/${id}/update`, { method: "POST", body }),
  crmTaskDelete: (id) =>
    request(`/api/admin/crm/tasks/${id}/delete`, { method: "POST", body: {} }),
  crmCreateLead: (body) => request("/api/admin/crm/deals", { method: "POST", body }),
  crmUpdateLead: (id, body) =>
    request(`/api/admin/crm/deals/${id}/update`, { method: "POST", body }),
  crmLinkLeadCompany: (id, body) =>
    request(`/api/admin/crm/deals/${id}/link-company`, { method: "POST", body }),
  crmDealNote: (id, body) =>
    request(`/api/admin/crm/deals/${id}/notes`, { method: "POST", body }),
  companyCrm: (id) => request(`/api/admin/companies/${id}/crm`),
  crmNote: (id, body) =>
    request(`/api/admin/companies/${id}/crm/notes`, { method: "POST", body }),
  /* --- Uppföljning av prov (fleet/admin_followup.py) --- */
  followUps: () => request("/api/admin/followups"),
  updateFollowUp: (companyId, body) =>
    request(`/api/admin/followups/${companyId}`, { method: "POST", body }),
  setSubscription: (id, body) =>
    request(`/api/admin/companies/${id}/subscription`, { method: "POST", body }),
  pairingCode: (id, licenseId, label = "Support") =>
    request(`/api/admin/companies/${id}/pairing-code`, {
      method: "POST",
      body: { license_id: licenseId, label },
    }),
  testPush: (id) =>
    request(`/api/admin/companies/${id}/test-push`, { method: "POST", body: {} }),
  // Notiserna för kundens telefoner (fleet/admin_notify.py). Ändra kräver ADMIN_SELL och loggas.
  setDeviceNotify: (companyId, deviceId, body) =>
    request(`/api/admin/companies/${companyId}/devices/${deviceId}/notify-prefs`, { method: "POST", body }),
  setNotifyDefault: (companyId, body) =>
    request(`/api/admin/companies/${companyId}/notify-default`, { method: "POST", body }),
  blockPhone: (approvalId, reason) =>
    request(`/api/admin/approvals/${approvalId}/block`, {
      method: "POST",
      body: { reason },
    }),
  renamePhone: (approvalId, label) =>
    request(`/api/admin/approvals/${approvalId}/label`, { method: "POST", body: { label } }),
  releaseCar: (licenseId, reason) =>
    request(`/api/admin/licenses/${licenseId}/release`, { method: "POST", body: { reason } }),
  inviteDriver: (id, licenseId, email, label) =>
    request(`/api/admin/companies/${id}/driver-invites`, {
      method: "POST",
      body: { licenseId, email, label },
    }),
  resendDriverInvite: (inviteId) =>
    request(`/api/admin/driver-invites/${inviteId}/resend`, { method: "POST", body: {} }),
  revokeDriverInvite: (inviteId) =>
    request(`/api/admin/driver-invites/${inviteId}/revoke`, { method: "POST", body: {} }),
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

  /* --- Bolagsverket (fleet/admin_sales.py:refresh_registry) --- */
  refreshRegistry: (companyId, overwriteAddress = false) =>
    request(`/api/admin/companies/${companyId}/registry`, { method: "POST", body: { overwriteAddress } }),

  /* --- Supportchatten (fleet/admin_support.py) --- */
  supportSummary: () => request("/api/admin/support/summary"),
  supportThreads: (status = "open", q = "") => {
    const params = new URLSearchParams({ status });
    if (q) params.set("q", q);
    return request(`/api/admin/support/threads?${params}`);
  },
  // markRead bara för den som kan svara; servern kontrollerar det också.
  supportThread: (id, markRead = false) =>
    request(`/api/admin/support/threads/${id}${markRead ? "?markRead=1" : ""}`),
  supportReply: (id, body) =>
    request(`/api/admin/support/threads/${id}/messages`, { method: "POST", body: { body } }),
  supportStatus: (id, status) =>
    request(`/api/admin/support/threads/${id}/status`, { method: "POST", body: { status } }),
  supportStart: (companyId) =>
    request(`/api/admin/companies/${companyId}/support`, { method: "POST", body: {} }),

  /* --- Bilar (fleet/admin_vehicles.py) --- */
  changeVehicle: (licenseId, plate, mode = "permanent") =>
    request(`/api/admin/licenses/${licenseId}/vehicle`, { method: "POST", body: { plate, mode } }),
  setTrialCounties: (licenseId, base, extras) =>
    request(`/api/admin/licenses/${licenseId}/counties`, { method: "POST", body: { base, extras } }),
  removeLicense: (licenseId, reason) =>
    request(`/api/admin/licenses/${licenseId}/remove`, { method: "POST", body: { reason } }),
  setBaseCountyNow: (licenseId, county, reason) =>
    request(`/api/admin/licenses/${licenseId}/base-county`, { method: "POST", body: { county, reason } }),
  setCompanyBaseCounty: (companyId, county, reason) =>
    request(`/api/admin/companies/${companyId}/base-county`, { method: "POST", body: { county, reason } }),
  undoPendingChange: (changeId, reason) =>
    request(`/api/admin/pending-changes/${changeId}/undo`, { method: "POST", body: { reason } }),

  /* --- Konton och spärrar (fleet/admin_accounts.py) --- */
  accounts: (q = "") => request(`/api/admin/accounts?q=${encodeURIComponent(q)}`),
  account: (userId) => request(`/api/admin/accounts/${userId}`),
  accountRecovery: (userId, redirectTo) =>
    request(`/api/admin/accounts/${userId}/recovery`, {
      method: "POST",
      body: redirectTo ? { redirectTo } : {},
    }),
  deleteAccount: (userId, confirmEmail) =>
    request(`/api/admin/accounts/${userId}/delete`, {
      method: "POST",
      body: { confirmEmail },
    }),
  accountTestPush: (userId) =>
    request(`/api/admin/accounts/${userId}/test-push`, { method: "POST", body: {} }),
  allowCountyChange: (licenseId, note = "") =>
    request(`/api/admin/licenses/${licenseId}/allow-county-change`, {
      method: "POST",
      body: { note },
    }),
  allowDeviceSwap: (userId, note = "") =>
    request(`/api/admin/accounts/${userId}/allow-device-swap`, {
      method: "POST",
      body: { note },
    }),
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

  /* --- Tipprapporter (fleet/admin_tip_reports.py) --- */
  tipReportsSummary: () => request("/api/admin/tip-reports/summary"),
  tipReports: (status = "open") =>
    request(`/api/admin/tip-reports?status=${encodeURIComponent(status)}`),
  tipReport: (id) => request(`/api/admin/tip-reports/${id}`),
  resolveTipReport: (id, body) =>
    request(`/api/admin/tip-reports/${id}/resolve`, { method: "POST", body }),

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
  startTrial: (id, vehicles, days) =>
    request(`/api/admin/companies/${id}/trial`, {
      method: "POST",
      body: { vehicles, ...(days != null ? { days } : {}) },
    }),
  extendTrial: (id, days, reason) =>
    request(`/api/admin/companies/${id}/trial/extend`, {
      method: "POST",
      body: { days, reason },
    }),
  // Fler bilar i provet: alltid ett manuellt beslut med skäl (fleet/trials.set_vehicle_limit).
  setTrialVehicleLimit: (id, vehicleLimit, reason) =>
    request(`/api/admin/companies/${id}/trial/vehicles`, {
      method: "POST",
      body: { vehicleLimit, reason },
    }),
  setDiscount: (id, body) =>
    request(`/api/admin/companies/${id}/discount`, { method: "POST", body }),
  clearDiscount: (id, reason) =>
    request(`/api/admin/companies/${id}/discount/clear`, { method: "POST", body: { reason } }),
  redeemCoupon: (id, code, vehicles) =>
    request(`/api/admin/companies/${id}/coupon`, { method: "POST", body: { code, vehicles } }),
  cancelSubscription: (id, reason, immediate = false) =>
    request(`/api/admin/companies/${id}/cancel`, {
      method: "POST",
      body: { reason, immediate },
    }),
  undoCancel: (id) => request(`/api/admin/companies/${id}/undo-cancel`, { method: "POST", body: {} }),
  inviteOwner: (id, email, role = "company_owner") =>
    request(`/api/admin/companies/${id}/owner-invite`, { method: "POST", body: { email, role } }),
  paymentLink: (orderId, payment, daysUntilDue = 14) =>
    request(`/api/admin/orders/${orderId}/payment-link`, {
      method: "POST",
      body: { payment, daysUntilDue },
    }),
  refreshOrder: (orderId) =>
    request(`/api/admin/orders/${orderId}/refresh`, { method: "POST", body: {} }),
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
