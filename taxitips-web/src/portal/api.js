import { createClient } from "@supabase/supabase-js";

import { portal } from "../config.js";

/**
 * Portalens väg mot TaxiTips-backenden.
 *
 * **Varför allt går via backenden och inte via PostgREST.** Bilar, licenser,
 * län och beställningar ligger i Djangos tabeller, som inte är åtkomliga för
 * någon klientroll (fleet/migrations/0003_revoke_postgrest_access.py).
 * Behörigheten kontrolleras i Python, per anrop, med den inloggades roll --
 * inte av en policy som en framtida tabell kan råka sakna.
 *
 * Supabase används bara till inloggningen. Sessionens access token följer med
 * som `Authorization: Bearer`, och backenden verifierar signaturen själv
 * (core/entitlement.verify_supabase_jwt).
 */

let client = null;

export function supabase() {
  if (client) return client;
  if (!portal.supabaseAnonKey) {
    throw new Error(
      "VITE_SUPABASE_ANON_KEY saknas. Portalen kan inte logga in utan den.",
    );
  }
  client = createClient(portal.supabaseUrl, portal.supabaseAnonKey, {
    auth: { persistSession: true, autoRefreshToken: true },
  });
  return client;
}

export async function accessToken() {
  const { data } = await supabase().auth.getSession();
  return data?.session?.access_token ?? null;
}

/** Fel från backenden bär ett maskinläsbart skäl vid sidan av texten. */
export class ApiError extends Error {
  constructor(status, message, reason, detail) {
    super(message);
    this.status = status;
    this.reason = reason;
    this.detail = detail;
  }
}

export async function request(path, { method = "GET", body } = {}) {
  const token = await accessToken();
  if (!token) throw new ApiError(401, "Du är inte inloggad.", "login_required");

  const res = await fetch(`${portal.apiBaseUrl}${path}`, {
    method,
    headers: {
      Accept: "application/json",
      ...(body ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${token}`,
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  let data = {};
  try {
    data = await res.json();
  } catch {
    throw new ApiError(res.status, `Servern svarade ${res.status}.`);
  }
  if (!res.ok || data.ok === false) {
    throw new ApiError(
      res.status,
      data.message || data.error || `Servern svarade ${res.status}.`,
      data.reason,
      data.detail,
    );
  }
  return data;
}

export const api = {
  company: () => request("/api/fleet/company"),
  claimInvite: () => request("/api/fleet/claim-invite", { method: "POST", body: {} }),
  orders: () => request("/api/fleet/orders/list"),
  createVehicle: (plate, label) =>
    request("/api/fleet/vehicles", { method: "POST", body: { plate, label } }),
  pairingCode: (licenseId, vehicleId, label) =>
    request("/api/fleet/pairing-codes", {
      method: "POST",
      body: { license_id: licenseId, vehicle_id: vehicleId, label },
    }),
  blockPhone: (approvalId, reason) =>
    request(`/api/fleet/approvals/${approvalId}/block`, {
      method: "POST",
      body: { reason },
    }),
  changeVehicle: (licenseId, payload) =>
    request(`/api/fleet/licenses/${licenseId}/vehicle`, {
      method: "POST",
      body: payload,
    }),
  quote: (change) => request("/api/fleet/quote", { method: "POST", body: change }),
  order: (change) =>
    request("/api/fleet/orders", { method: "POST", body: { ...change, accepted: true } }),
  cancel: (reason) =>
    request("/api/fleet/subscription/cancel", { method: "POST", body: { reason } }),
  undoCancel: () =>
    request("/api/fleet/subscription/undo-cancel", { method: "POST", body: {} }),
  closeAccount: () => request("/api/fleet/company/close", { method: "POST", body: {} }),
  transferOwnership: (toUserId) =>
    request("/api/fleet/ownership/transfer", {
      method: "POST",
      body: { to_user_id: toUserId },
    }),
};

/** Ören -> "799,00 kr". Backenden räknar; portalen visar bara. */
export function money(ore, currency = "SEK") {
  return new Intl.NumberFormat("sv-SE", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format((ore ?? 0) / 100);
}

export function date(iso) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("sv-SE", {
    dateStyle: "medium",
  }).format(new Date(iso));
}

export function dateTime(iso) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("sv-SE", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

/** SCB:s länskoder. Samma lista som backendens core/areas.py. */
export const COUNTIES = {
  "01": "Stockholms län",
  "03": "Uppsala län",
  "04": "Södermanlands län",
  "05": "Östergötlands län",
  "06": "Jönköpings län",
  "07": "Kronobergs län",
  "08": "Kalmar län",
  "09": "Gotlands län",
  10: "Blekinge län",
  12: "Skåne län",
  13: "Hallands län",
  14: "Västra Götalands län",
  17: "Värmlands län",
  18: "Örebro län",
  19: "Västmanlands län",
  20: "Dalarnas län",
  21: "Gävleborgs län",
  22: "Västernorrlands län",
  23: "Jämtlands län",
  24: "Västerbottens län",
  25: "Norrbottens län",
};

export function countyName(code) {
  return COUNTIES[String(code)] ?? `Län ${code}`;
}
