import { COUNTIES, countyName, date, dateTime, money, offerableCountyEntries } from "./api.js";
import { notifyCard } from "../notify_editor.js";

/**
 * Portalens fem vyer, som rena funktioner från data till HTML.
 *
 * Ingen vy räknar ut ett belopp. Allt som ser ut som pengar kommer från
 * backendens uträkning (fleet/pricing.py) -- en andra prismotor i webbläsaren
 * hade kunnat visa rätt när fakturan blev fel, vilket är värre än att inte
 * visa något alls.
 */

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

function statusPill(status) {
  const map = {
    active: ["pill-ok", "Aktiv"],
    trialing: ["pill-warn", "Provperiod"],
    trial: ["pill-warn", "Provplats"],
    past_due: ["pill-danger", "Förfallen"],
    canceled: ["pill-danger", "Avslutad"],
    pending_cancel: ["pill-warn", "Avslutas"],
    none: ["", "Inget abonnemang"],
  };
  const [cls, label] = map[status] ?? ["", status ?? "—"];
  return `<span class="pill ${cls}">${esc(label)}</span>`;
}

/* --- Översikt ---------------------------------------------------------- */

/**
 * "Fortsätt med provet": dit mejlen före och efter provslut länkar
 * (portal#fortsatt). Under pågående prov: spara kort för auto-förnyelse.
 * Efter prov utan kort: vanlig beställning (betala nu).
 */
/**
 * Var kunden står i fortsättningen efter provet. Översiktens kort och
 * medlemskapet under Abonnemang läser samma svar, så att de aldrig visar två
 * olika steg för samma bolag.
 *
 *   card_on_file -- kortet är sparat; första dragningen vid provets slut
 *   finish_card  -- medlemskapen är bekräftade men kortet inte sparat hos Stripe
 *   commit       -- pågående prov; bekräfta medlemskap och spara kort
 *   pay          -- provet är slut utan kort; vanlig beställning
 */
export function continueState(data) {
  const cars = data.continueVehicles ?? [];
  const canBuy = (data.permissions ?? []).includes("purchase");
  if (!cars.length || !canBuy) return null;
  const trial = data.trial;
  const activeTrial = trial && ["pending", "active"].includes(trial.status);
  if (activeTrial && trial.cardOnFile === true) return { kind: "card_on_file", cars, trial };
  if (activeTrial && trial.committed === true && trial.paymentUrl) {
    return { kind: "finish_card", cars, trial };
  }
  if (activeTrial) return { kind: "commit", cars, trial };
  return { kind: "pay", cars, trial };
}

/**
 * Guided väg för nya kunder: uppgifter → medlemskap → konton → betala.
 * Visas bara medan något steg saknas; när allt är klart tystnar den.
 */
export function setupSteps(data) {
  const company = data.company ?? {};
  const details = company.details ?? {};
  const licenses = data.licenses ?? [];
  const hasMemberships = licenses.length > 0;
  const hasAccounts = licenses.some(
    (row) => row.assigned || row.assigneeEmail || row.assigneeUserId,
  );
  const contactOk = Boolean(details.contactName && details.contactPhone);
  const companyOk =
    contactOk ||
    company.verificationStatus === "verified" ||
    company.verificationStatus === "pending_review";
  const sub = data.subscription ?? {};
  const trial = data.trial;
  const cs = continueState(data);
  const payOk =
    ["active", "trialing", "past_due"].includes(sub.status) ||
    cs?.kind === "card_on_file" ||
    (trial && trial.cardOnFile === true);

  return [
    {
      id: "company",
      title: "Uppgifter om företaget",
      hint: "Kontaktperson så vi når er om något krånglar.",
      done: companyOk,
      goto: "foretag",
      cta: "Fyll i uppgifter",
    },
    {
      id: "memberships",
      title: "Skaffa medlemskap",
      hint: "En licens = en plats för ett konto, inte en bil.",
      done: hasMemberships,
      goto: "abonnemang",
      cta: "Skaffa medlemskap",
    },
    {
      id: "accounts",
      title: "Bjud in konton",
      hint: "Tilldela varje medlemskap ett konto med e-post.",
      done: hasAccounts,
      goto: "medlemskap",
      cta: "Bjud in konto",
      blocked: !hasMemberships,
    },
    payStep({ payOk, hasMemberships, cs, trial }),
  ];
}

function payStep({ payOk, hasMemberships, cs, trial }) {
  const pay = {
    id: "pay",
    title: "Fortsätt med medlemskap",
    hint: "Kort sparas hos Stripe. Inget dras under ett pågående prov.",
    done: payOk,
    goto: "abonnemang",
    cta: "Till abonnemang",
    blocked: !hasMemberships,
    action: null,
    href: null,
  };
  if (payOk || !hasMemberships) return pay;
  if (cs?.kind === "commit") {
    pay.cta = "Bekräfta medlemskap och spara kort";
    pay.action = "continue-trial";
    pay.hint = "Nästa steg: spara kortet. Första dragningen när provet tar slut.";
  } else if (cs?.kind === "finish_card") {
    pay.cta = "Öppna betalsidan";
    pay.href = trial?.paymentUrl || null;
    pay.hint = "Ni är nästan klara — spara kortet hos Stripe.";
  } else if (cs?.kind === "pay") {
    pay.cta = "Visa pris och betala";
    pay.action = "continue-trial";
    pay.hint = "Provet är slut. Betala för att behålla åtkomsten.";
  } else if (trial && ["pending", "active"].includes(trial.status)) {
    pay.cta = "Se medlemskap";
    pay.hint = "När medlemskap och konton är på plats: fortsätt efter provet här.";
  }
  return pay;
}

function journeyStepAction(step, isNext) {
  if (step.done || step.blocked) return "";
  const cls = `btn ${isNext ? "btn-primary" : "btn-quiet"} btn-sm`;
  if (step.href) {
    return `<a class="${cls}" href="${esc(step.href)}" target="_blank" rel="noopener">${esc(step.cta)}</a>`;
  }
  if (step.action) {
    return `<button type="button" class="${cls}" data-action="${esc(step.action)}">${esc(step.cta)}</button>`;
  }
  return `<button type="button" class="${cls}" data-goto="${esc(step.goto)}">${esc(step.cta)}</button>`;
}

function journeyCard(data) {
  const steps = setupSteps(data);
  const remaining = steps.filter((s) => !s.done);
  if (!remaining.length) {
    return `<div class="card journey-done">
      <h2>Ni är igång</h2>
      <p class="muted">Medlemskap, konton och betalning är på plats. Titta tillbaka
        hit om något behöver åtgärdas.</p>
    </div>`;
  }
  const next = remaining.find((s) => !s.blocked) ?? remaining[0];
  const doneCount = steps.filter((s) => s.done).length;
  return `<div class="card journey" aria-labelledby="journeyTitle">
    <h2 id="journeyTitle">Kom igång</h2>
    <p class="muted">Steg ${esc(doneCount + 1)} av ${esc(steps.length)}:
      <b>${esc(next.title)}</b></p>
    <ol class="journey-steps">
      ${steps
        .map((s) => {
          const state = s.done ? "done" : s.id === next.id ? "current" : s.blocked ? "blocked" : "todo";
          return `<li class="journey-step is-${state}">
            <span class="journey-mark" aria-hidden="true"></span>
            <div class="journey-body">
              <b>${esc(s.title)}</b>
              <span class="muted">${esc(s.hint)}</span>
              ${journeyStepAction(s, s.id === next.id)}
            </div>
          </li>`;
        })
        .join("")}
    </ol>
  </div>`;
}

/** Synlig räknare under provet. CTA här bara när Fortsätt-kortet inte redan syns. */
function trialBanner(data) {
  const trial = data.trial;
  if (!trial || !["pending", "active"].includes(trial.status)) return "";
  if (trial.cardOnFile === true) return "";
  const cs = continueState(data);
  const hasContinueCta = cs && ["commit", "finish_card", "pay"].includes(cs.kind);
  const ends = trial.endsAt ? new Date(trial.endsAt) : null;
  const daysLeft =
    ends && !Number.isNaN(ends.getTime())
      ? Math.max(0, Math.ceil((ends.getTime() - Date.now()) / 86_400_000))
      : null;
  const dayText =
    daysLeft == null
      ? "Provet startar när den första telefonen ansluts."
      : daysLeft === 0
        ? "Provet tar slut i dag."
        : daysLeft === 1
          ? "1 dag kvar av provet."
          : `${daysLeft} dagar kvar av provet.`;

  const cta = hasContinueCta
    ? ""
    : `<div class="btn-row"><button type="button" class="btn btn-primary" data-goto="abonnemang">Se hur ni fortsätter</button></div>`;

  return `<div class="trial-banner" role="region" aria-label="Provperiod">
    <div class="trial-banner-text">
      <b>Provperiod</b>
      <span>${esc(dayText)} ${esc(trial.vehiclesUsed ?? 0)} av ${esc(trial.vehicleLimit ?? 0)} provplatser.</span>
    </div>
    ${cta}
  </div>`;
}

function continueCard(data) {
  const state = continueState(data);
  if (!state) return "";
  const { cars, trial } = state;
  const n = cars.length;

  if (state.kind === "card_on_file") {
    return `<div class="card continue-card" id="fortsatt">
      <h2>Auto-förnyelse är klar</h2>
      <p>${cars.map((c) => `<b>${esc(c.plate)}</b>`).join(", ")}</p>
      <p class="muted">Kortet är sparat. Första dragningen sker
        ${esc(date(trial.firstChargeAt || trial.endsAt))} när provet tar slut,
        sedan varje månad tills ni säger upp.</p>
      <div class="btn-row">
        <button class="btn btn-quiet" data-action="cancel-trial-commit">Avbryt auto-förnyelse</button>
      </div>
    </div>`;
  }

  if (state.kind === "finish_card") {
    return `<div class="card continue-card" id="fortsatt">
      <h2>Spara kortet för att fortsätta</h2>
      <p>${cars.map((c) => `<b>${esc(c.plate)}</b>`).join(", ")}</p>
      <p class="muted">Ni har bekräftat medlemskapen. Öppna Stripes sida och spara
        kortet — ingen dragning sker förrän provet tar slut
        (${esc(date(trial.endsAt))}).</p>
      <div class="btn-row">
        <a class="btn btn-primary btn-lg" href="${esc(trial.paymentUrl)}" target="_blank" rel="noopener">Öppna betalsidan</a>
        <button class="btn btn-quiet" data-action="cancel-trial-commit">Avbryt</button>
      </div>
    </div>`;
  }

  if (state.kind === "commit") {
    return `<div class="card continue-card" id="fortsatt">
      <h2>Fortsätt med medlemskap</h2>
      <p>${cars.map((c) => `<b>${esc(c.plate)}</b>`).join(", ")} ·
        provet slutar ${esc(date(trial.endsAt))}</p>
      <p class="muted">Bekräfta medlemskapen och spara kortet hos Stripe. Inget dras
        under provet — första dragningen sker när det tar slut, sedan varje månad.</p>
      <div class="btn-row"><button class="btn btn-primary btn-lg" data-action="continue-trial">Bekräfta medlemskap och spara kort</button></div>
    </div>`;
  }

  // Prov slut utan kort: betala nu (gamla flödet).
  return `<div class="card continue-card" id="fortsatt">
      <h2>Fortsätt med medlemskap</h2>
      <p>${cars.map((c) => `<b>${esc(c.plate)}</b>`).join(", ")}</p>
      <p class="muted">Provet är slut. Du ser priset innan du godkänner.
        Betalningen sker på Stripes betalsida.</p>
      <div class="btn-row"><button class="btn btn-primary btn-lg" data-action="continue-trial">Visa pris och betala</button></div>
    </div>`;
}

export function oversikt(data) {
  const sub = data.subscription ?? {};
  const reviews = (data.reviews ?? []).filter((r) => r.status === "open");
  const steps = setupSteps(data);
  const setupDone = steps.every((s) => s.done);

  const notices = [];
  if (sub.cancelAtPeriodEnd) {
    notices.push(`<div class="notice notice-danger">
      <b>Abonnemanget är uppsagt.</b> Allt fungerar som vanligt till
      ${esc(date(sub.accessUntil))}. Du kan ångra uppsägningen fram till dess.
      <div class="btn-row"><button class="btn btn-quiet" data-action="undo-cancel">Ångra uppsägningen</button></div>
    </div>`);
  }
  if (sub.status === "past_due") {
    notices.push(`<div class="notice notice-danger">
      <b>Betalningen har inte gått igenom.</b>
      ${sub.graceUntil ? `Åtkomsten gäller till ${esc(dateTime(sub.graceUntil))}.` : "Ingen betalningsfrist gäller för den här betalningen."}
      Öppna Stripe och uppdatera kortet för att behålla åtkomsten.
      <div class="btn-row"><button class="btn btn-primary" data-action="billing-portal">Uppdatera betalmetod</button></div>
    </div>`);
  }
  if (sub.renewalStopped) {
    notices.push(`<div class="notice notice-danger">
      <b>Förnyelsen är stoppad.</b> Inga nya månadsavgifter tillkommer.
      En obetald faktura hanteras separat -- kontakta oss så reder vi ut den.
    </div>`);
  }
  for (const review of reviews) {
    notices.push(
      `<div class="notice"><b>Under granskning.</b> ${esc(review.message)}</div>`,
    );
  }
  if (data.company?.legacyAccessUntil) {
    notices.push(`<div class="notice">
      <b>Övergång pågår.</b> Era telefoner fungerar som förut till
      ${esc(date(data.company.legacyAccessUntil))}. Lägg upp medlemskapen och bjud
      in konton under <em>Medlemskap</em> före dess.
    </div>`);
  }

  return `
    ${trialBanner(data)}
    ${continueCard(data)}
    ${notices.join("")}
    ${journeyCard(data)}

    ${
      setupDone
        ? `<div class="status-strip" aria-label="Läge just nu">
            <div><span class="muted">Abonnemang</span><b>${statusPill(sub.status)}</b></div>
            <div><span class="muted">Medlemskap</span><b>${esc(data.licenseCount ?? 0)}</b></div>
            <div><span class="muted">Nästa betalning</span><b>${esc(date(sub.currentPeriodEnd) || "—")}</b></div>
          </div>`
        : ""
    }

    ${
      setupDone && (data.licenses ?? []).length
        ? `<div class="card">
             <h2>Medlemskap just nu</h2>
             ${membershipList(data)}
             <div class="btn-row"><button type="button" class="btn btn-quiet" data-goto="medlemskap">Hantera medlemskap</button></div>
           </div>`
        : ""
    }

    ${vantandeAndringar(data)}
  `;
}

function membershipList(data) {
  const rows = data.licenses ?? [];
  if (!rows.length) {
    return `<p class="muted">Inga medlemskap upplagda än.</p>`;
  }
  return `<ul class="car-list">${rows
    .map((row) => {
      const who = row.assigneeEmail
        ? esc(row.assigneeEmail)
        : row.assigneeUserId
          ? "ett konto"
          : "inte tilldelat";
      const counties = (row.counties ?? []).map((c) => countyName(c)).join(", ") || "—";
      return `<li>
        <div>
          <b>${esc(membershipLabel(row))}</b>
          <span class="muted">${esc(counties)}</span>
        </div>
        <div class="car-list-meta">
          ${membershipStatusPill(row.status)}
          <span class="muted">${who}</span>
        </div>
      </li>`;
    })
    .join("")}</ul>`;
}

function vantandeAndringar(data) {
  const pending = data.pendingChanges ?? [];
  if (!pending.length) return "";
  const label = {
    reduce_licenses: "Medlemskap avslutas",
    remove_county: "Extra län tas bort",
    change_base_county: "Baslänet byts",
    cancel_subscription: "Abonnemanget avslutas",
  };
  return `<div class="card">
    <h2>Väntande ändringar</h2>
    <p class="muted">Träder i kraft vid nästa förnyelse. Fram till dess gäller
    det du har nu.</p>
    <ul class="simple-list">${pending
      .map(
        (p) =>
          `<li><b>${esc(label[p.kind] ?? p.kind)}</b>
             <span class="muted">från ${esc(date(p.effectiveAt))}</span></li>`,
      )
      .join("")}</ul>
  </div>`;
}

/* --- Medlemskap ---------------------------------------------------------- */

/**
 * Status per medlemskap. Provplatsen får en egen pjäs så att provet syns
 * bredvid de betalda platserna; annars återanvänds den gemensamma statusen.
 */
function membershipStatusPill(status) {
  if (status === "trial") return '<span class="pill pill-warn">Provplats</span>';
  return statusPill(status);
}

/** Namnet på ett medlemskap i listor: baslänet identifierar platsen. */
function membershipLabel(row) {
  const county = row.baseCounty ? countyName(row.baseCounty) : "utan län";
  return `Medlemskap · ${county}`;
}

/** Baslänet som text, även innan provplatsen fått ett län. */
function baseCountyText(row) {
  return row.baseCounty ? countyName(row.baseCounty) : "inte valt";
}

/** Vem som håller platsen, som en kort text. */
function assigneeText(row, userId) {
  if (row.assigneeEmail) return `väntar på ${row.assigneeEmail}`;
  if (row.assigneeUserId) {
    return userId && String(row.assigneeUserId) === String(userId) ? "ditt konto" : "ett konto";
  }
  return "ingen än";
}

/**
 * Översikten: hur många medlemskap, prov eller betalda, och vilket som ligger
 * på ditt eget konto. Portalen hanterar hela företaget -- den här raden visar
 * bara vad som är vad.
 */
function membershipOverview(data, rows, userId) {
  const trialCount = rows.filter((r) => r.status === "trial").length;
  const paidCount = rows.length - trialCount;
  const mine = rows.find((r) => userId && String(r.assigneeUserId) === String(userId));
  return `<div class="card membership-overview" aria-labelledby="membershipOverviewTitle">
    <h2 id="membershipOverviewTitle">Medlemskap</h2>
    <p class="muted">En plats gäller ett <b>konto</b> i ett län, inte en bil.
      Alla län kostar lika mycket. Den som håller platsen loggar in i appen och
      tar den där.</p>
    <dl class="membership-facts">
      <div><dt>Totalt</dt><dd>${esc(String(rows.length))}</dd></div>
      <div><dt>Betalda</dt><dd>${esc(String(paidCount))}</dd></div>
      <div><dt>Provplatser</dt><dd>${esc(String(trialCount))}</dd></div>
    </dl>
    <p class="membership-managed">${
      mine
        ? `Du hanterar medlemskapet med ${esc(baseCountyText(mine))}.`
        : "Inget medlemskap ligger på ditt konto just nu."
    }</p>
  </div>`;
}

/** Bjud in ett konto: välj vilket medlemskap som ska tilldelas adressen. */
function inviteAccountsCard(rows, canAssign) {
  if (!canAssign || !rows.length) return "";
  const unassigned = rows.filter((r) => !r.assigned);
  const pool = unassigned.length ? unassigned : rows;
  const options = pool
    .map(
      (r) =>
        `<option value="${esc(r.licenseId)}">${esc(membershipLabel(r))} — ${esc(assigneeText(r))}</option>`,
    )
    .join("");
  return `<div class="card invite-primary">
    <h2>Bjud in ett konto</h2>
    <p class="muted">Personen får platsen på sin e-postadress. När hen loggar
      in i appen binds kontot och platsen är redo att tas.</p>
    <form id="membershipInviteForm">
      <label for="membership-invite-for">Medlemskap</label>
      <select id="membership-invite-for" name="licenseId" required>${options}</select>
      <label for="membership-invite-email">E-post</label>
      <input id="membership-invite-email" name="email" type="email" required
        autocomplete="off" inputmode="email" placeholder="namn@exempel.se" />
      <div class="btn-row">
        <button class="btn btn-primary" type="submit">Bjud in konto</button>
      </div>
    </form>
  </div>`;
}

/**
 * Länkontroller per medlemskap. Provet byter direkt och kostnadsfritt; en
 * betald plats byter via en beställning, så att fakturan stämmer.
 */
function membershipCountyControls(row, opts) {
  const trial = row.status === "trial";
  const options = offerableCountyEntries()
    .map(([code, name]) => `<option value="${esc(code)}">${esc(name)}</option>`)
    .join("");
  if (trial) {
    return `<details class="advanced county-panel">
      <summary>Län för det här medlemskapet</summary>
      <p>Baslän: <b>${esc(baseCountyText(row))}</b></p>
      ${countyChangesLeft(row)}
      ${
        opts.canCounties
          ? `<div class="btn-row county-actions">
               <label class="visually-hidden" for="county-${esc(row.licenseId)}">Län</label>
               <select id="county-${esc(row.licenseId)}" data-county-for="${esc(row.licenseId)}">${options}</select>
               <button class="btn btn-primary" data-action="change-base" data-license="${esc(row.licenseId)}" data-status="trial">Byt baslän</button>
             </div>`
          : '<p class="muted">Bara ägaren eller fordonsadministratören kan byta län.</p>'
      }
      <p class="muted">Provet byter län direkt och utan kostnad. Högst två byten per månad.</p>
    </details>`;
  }
  return `<details class="advanced county-panel">
    <summary>Län för det här medlemskapet</summary>
    <p>Baslän: <b>${esc(baseCountyText(row))}</b>${
      row.scheduledBaseCounty
        ? ` <span class="pill pill-warn">Byts till ${esc(countyName(row.scheduledBaseCounty))}</span>`
        : ""
    }</p>
    <p class="muted">Extra län: ${esc((row.extraCounties ?? []).map((c) => countyName(c)).join(", ") || "inga")}</p>
    ${countyChangesLeft(row)}
    ${
      opts.canBuy
        ? `<div class="btn-row county-actions">
             <label class="visually-hidden" for="county-${esc(row.licenseId)}">Län</label>
             <select id="county-${esc(row.licenseId)}" data-county-for="${esc(row.licenseId)}">${options}</select>
             <button class="btn btn-primary" data-action="add-county" data-license="${esc(row.licenseId)}">Köp extra län</button>
             ${
               row.countyChanges && row.countyChanges.remaining <= 0
                 ? ""
                 : `<button class="btn btn-quiet" data-action="change-base" data-license="${esc(row.licenseId)}" data-status="${esc(row.status)}">Byt baslän</button>`
             }
           </div>`
        : '<p class="muted">Ägaren eller ekonomiansvarig köper extra län eller byter baslän.</p>'
    }
    <p class="muted">Extra län är för <b>samma konto</b> -- en person som vill ha
      två län. Det börjar gälla när tilläggsbetalningen lyckats. Baslänsbyte
      gäller vid nästa förnyelse. Högst två byten per månad.</p>
  </details>`;
}

/** Ett medlemskapskort: plats, konto och län. Provet får egen layout. */
function membershipSlotCard(row, opts, userId) {
  const canAssign = opts.canAssign;
  const assigned = row.assigned === true;
  const who = assigneeText(row, userId);
  return `<div class="card membership-card${row.status === "trial" ? " is-trial" : ""}">
    <div class="membership-head">
      <div>
        <h2>${esc(membershipLabel(row))}</h2>
        <p class="muted">${esc(
          who === "ingen än" ? "Platsen är inte tilldelad än." : `Platsen ligger på ${who}.`,
        )}</p>
      </div>
      ${membershipStatusPill(row.status)}
    </div>

    <dl class="membership-facts">
      <div><dt>Baslän</dt><dd>${esc(baseCountyText(row))}${
        row.scheduledBaseCounty
          ? ` <span class="pill pill-warn">Byts till ${esc(countyName(row.scheduledBaseCounty))}</span>`
          : ""
      }</dd></div>
      <div><dt>Extra län</dt><dd>${esc(
        (row.extraCounties ?? []).map((c) => countyName(c)).join(", ") || "inga",
      )}</dd></div>
    </dl>

    ${
      canAssign
        ? `<div class="btn-row">
             <button class="btn btn-quiet" type="button" data-action="assign-membership-self" data-license="${esc(row.licenseId)}">Tilldela mig</button>
             ${assigned ? `<button class="btn btn-quiet" type="button" data-action="unassign-membership" data-license="${esc(row.licenseId)}">Ta bort tilldelning</button>` : ""}
           </div>`
        : ""
    }

    ${membershipCountyControls(row, opts)}
  </div>`;
}

/** Länbyten kvar den här månaden (fleet/county_changes.py). Två per medlemskap
 * och kalendermånad, plus ett extra om support gett det. Servern räknar; vyn
 * visar bara svaret. */
export function countyChangesLeft(row) {
  const c = row.countyChanges;
  if (!c) return "";
  const total = (c.limit ?? 2) + (c.extra ?? 0);
  return c.remaining > 0
    ? `<p class="muted">Länbyten kvar den här månaden: <b>${esc(c.remaining)} av ${esc(total)}</b></p>`
    : `<p class="muted">Länbyten kvar den här månaden: <b>0 av ${esc(total)}</b>.
       Du kan byta igen nästa månad, eller kontakta support om det inte kan vänta.</p>`;
}

export function medlemskap(data, userId = null, notify = null) {
  const perms = data.permissions ?? [];
  const rows = data.licenses ?? [];
  const opts = {
    canAssign: perms.includes("manage_devices"),
    canCounties: perms.includes("manage_vehicles"),
    canBuy: perms.includes("purchase"),
  };
  return `
    ${membershipOverview(data, rows, userId)}
    ${inviteAccountsCard(rows, opts.canAssign)}
    ${
      rows.length
        ? rows.map((row) => membershipSlotCard(row, opts, userId)).join("")
        : `<div class="card"><h2>Inga medlemskap än</h2>
             <p class="muted">Köp dem under Abonnemang. Ett medlemskap är en plats
             för ett konto -- den som håller platsen loggar in i appen.</p>
             <div class="btn-row"><button type="button" class="btn btn-primary"
               data-goto="abonnemang">Köp medlemskap</button></div>
           </div>`
    }
    ${
      notify
        ? `<details class="advanced notify-wrap">
             <summary>Mer: notiser för förarna</summary>
             <div class="advanced-body">${notifyCard(notify, { countyNames: COUNTIES })}</div>
           </details>`
        : ""
    }
  `;
}

/** Äldre bokmärken och tester: "bilar" och "lan" går till Medlemskap. */
export function bilar(data, userId = null, notify = null) {
  return medlemskap(data, userId, notify);
}

export function lan(data, userId = null, notify = null) {
  return medlemskap(data, userId, notify);
}

/* --- Abonnemang och fakturor -------------------------------------------- */

/**
 * Kategorierna i appen. Nycklarna är fleet/features.py:ALL_CATEGORIES;
 * texterna är desamma som i mejlen om provet
 * (fleet/notifications.py:_TRIAL_SCOPE), så att portalen inte lovar något
 * mejlet inte säger.
 */
const CATEGORY_TEXT = {
  transit: ["Tåg och buss", "Inställda tåg, sista avgången och ersättningstrafik"],
  flight: ["Flyg", "Ankomster till flygplatserna"],
  ferry: ["Färjor", ""],
  events: ["Evenemang", "När publiken går hem"],
  road: ["Trafikolyckor", ""],
};
const ALL_CATEGORIES = ["transit", "flight", "ferry", "events", "road"];
const TRIAL_CATEGORIES = ["transit"];

const inTrial = (trial) => Boolean(trial && ["pending", "active"].includes(trial.status));

/**
 * Vad bolaget ser i appen just nu. Servern avgör (fleet/features.py). Skickar
 * GET /api/fleet/company med `features` används det rakt av; annars läses det
 * ur provets läge med samma regel: ett pågående prov utan sparat kort ser tåg
 * och buss, allt annat ser allt.
 */
function membershipPlan(data) {
  const f = data.features;
  if (f && Array.isArray(f.categories)) {
    const on = ALL_CATEGORIES.filter((c) => f.categories.includes(c));
    return { plan: f.plan, on, locked: ALL_CATEGORIES.filter((c) => !on.includes(c)) };
  }
  const t = data.trial;
  if (inTrial(t) && !(t.committed && t.cardOnFile)) {
    return {
      plan: "trial",
      on: TRIAL_CATEGORIES,
      locked: ALL_CATEGORIES.filter((c) => !TRIAL_CATEGORIES.includes(c)),
    };
  }
  return { plan: "full", on: ALL_CATEGORIES, locked: [] };
}

/** Var bolaget står: prov, prov med sparat kort, medlem, prov slut, eller inget. */
function membershipStage(data) {
  const sub = data.subscription ?? {};
  const t = data.trial;
  if (inTrial(t)) return t.committed && t.cardOnFile ? "trial_committed" : "trial";
  if ((data.licenseCount ?? 0) > 0 || ["active", "trialing", "past_due"].includes(sub.status)) {
    return "member";
  }
  if ((data.continueVehicles ?? []).length) return "trial_ended";
  return "none";
}

function featureItem(key, state) {
  const [label, detail] = CATEGORY_TEXT[key] ?? [key, ""];
  return `<li class="feature is-${state}">
      <span class="feature-icon" aria-hidden="true"></span>
      <span class="feature-text"><b>${esc(label)}</b>${detail ? `<span>${esc(detail)}</span>` : ""}
        <span class="visually-hidden">${state === "on" ? "(ingår)" : "(låst)"}</span></span>
    </li>`;
}

function featuresSection(data, stage) {
  const { plan, on, locked } = membershipPlan(data);
  if (plan === "trial" && locked.length) {
    return `<div class="member-features">
      <div class="feature-col">
        <h3>Ingår i provet</h3>
        <ul class="feature-list">${on.map((k) => featureItem(k, "on")).join("")}</ul>
      </div>
      <div class="feature-col feature-col-plus">
        <h3>Låses upp med medlemskap</h3>
        <ul class="feature-list">${locked.map((k) => featureItem(k, "locked")).join("")}</ul>
      </div>
    </div>`;
  }
  const heading = {
    trial_committed: "Allt är upplåst redan nu",
    member: "Det här ingår",
  }[stage] ?? "Det här ingår i medlemskapet";
  return `<div class="member-features">
      <div class="feature-col feature-col-wide">
        <h3>${esc(heading)}</h3>
        <ul class="feature-list feature-list-grid">${on.map((k) => featureItem(k, "on")).join("")}</ul>
      </div>
    </div>`;
}

const findLine = (quote, prefix) =>
  (quote?.lines ?? []).find((line) => String(line.key ?? "").startsWith(prefix)) ?? null;

/**
 * Vad det kostar, ur serverns offert (POST /api/fleet/quote, som inte ändrar
 * något). Portalen räknar inget själv: styckpriset, anteckningen och summan
 * är serverns rader. `pricing.quote` är fortsättningen med bolagets egna
 * medlemskap (eller nuläget), `pricing.probe` ett medlemskap med ett extra
 * län -- den enda vägen till länspriset utan en prislista i klienten.
 */
function priceSection(stage, pricing) {
  if (!pricing || pricing.loading) {
    return `<div class="member-price" aria-busy="true">
      <h3>Vad det kostar</h3>
      <p class="muted">Hämtar priset …</p>
    </div>`;
  }
  const plan = pricing.quote?.nextPeriod ?? null;
  const probe = pricing.probe?.nextPeriod ?? null;
  const ownLicenses = findLine(plan, "licenses_");
  const licenseLine = ownLicenses ?? findLine(probe, "licenses_");
  const countyLine = findLine(plan, "extra_counties") ?? findLine(probe, "extra_counties");
  const discount = findLine(plan, "company_discount");
  const currency = plan?.currency ?? probe?.currency ?? "SEK";
  const vatBp = plan?.vatRateBp ?? probe?.vatRateBp;

  if (!licenseLine && !countyLine) {
    return `<div class="member-price">
      <h3>Vad det kostar</h3>
      <p class="muted">Du ser hela priset och godkänner det innan något köps.</p>
    </div>`;
  }

  const row = (label, line) =>
    line
      ? `<div class="price-row">
          <dt>${esc(label)}</dt>
          <dd>${esc(money(line.unit_price_ore, currency))}</dd>
          ${line.note ? `<p class="price-note">${esc(line.note)}</p>` : ""}
        </div>`
      : "";

  let total = "";
  if (ownLicenses && plan) {
    const n = ownLicenses.quantity;
    const who = `${n} medlemskap`;
    const label = stage === "member" ? `Nästa period (${who})` : `Efter provet (${who})`;
    total = `<div class="price-total">
        <span>${esc(label)}</span>
        <b>${esc(money(plan.amountOre, currency))}</b>
        <span class="price-total-vat">${esc(money(plan.totalOre, currency))} inkl. moms</span>
      </div>`;
  }

  return `<div class="member-price">
      <h3>Vad det kostar</h3>
      <dl class="price-rows">
        ${row("Per medlemskap och månad", licenseLine)}
        ${row("Extra län, per medlemskap och månad", countyLine)}
        ${
          discount
            ? `<div class="price-row"><dt>${esc(discount.label)}</dt>
                <dd>${esc(money(discount.amount_ore, currency))}</dd>
                ${discount.note ? `<p class="price-note">${esc(discount.note)}</p>` : ""}</div>`
            : ""
        }
      </dl>
      ${total}
      <p class="price-fine">Priserna är exklusive moms${
        vatBp != null ? ` (${esc((vatBp / 100).toLocaleString("sv-SE"))} %)` : ""
      }. Du ser hela beloppet och godkänner det innan något köps.</p>
    </div>`;
}

/** "flyg, färjor och evenemang" */
function joinSv(words) {
  if (words.length < 2) return words.join("");
  return `${words.slice(0, -1).join(", ")} och ${words.at(-1)}`;
}

/** Nästa steg: starta medlemskapet, slutföra kortet, eller inget alls. */
function membershipAction(data, stage, plan) {
  const cs = continueState(data);
  const plates = cs ? cs.cars.map((c) => `<b>${esc(c.plate)}</b>`).join(", ") : "";
  const theMemberships = cs?.cars.length === 1 ? "medlemskapet" : "medlemskapen";
  const trial = data.trial;
  const unlocked = joinSv(plan.locked.map((k) => (CATEGORY_TEXT[k] ?? [k])[0].toLowerCase()));
  const unlockText = unlocked
    ? ` ${unlocked.charAt(0).toUpperCase()}${unlocked.slice(1)} öppnas när kortet är sparat.`
    : "";

  switch (cs?.kind) {
    case "commit":
      return `<div class="member-cta">
          <div class="member-cta-text">
            <h3>Fortsätt efter provet</h3>
            <p>Bekräfta ${theMemberships} (${plates}) och spara kortet hos Stripe. Inget
              dras under provet. Första dragningen sker ${esc(date(trial?.endsAt))},
              sedan en gång i månaden.${esc(unlockText)}</p>
          </div>
          <div class="member-cta-act">
            <button class="btn btn-primary btn-lg" data-action="continue-trial">Fortsätt efter provet</button>
            <p class="member-fine">Du ser beloppet och godkänner det innan kortet sparas.</p>
          </div>
        </div>`;
    case "finish_card":
      return `<div class="member-cta">
          <div class="member-cta-text">
            <h3>Spara kortet</h3>
            <p>Ni har bekräftat ${theMemberships} (${plates}). Spara kortet på Stripes
              sida, så fortsätter appen efter provet. Inget dras förrän
              ${esc(date(trial?.endsAt))}.</p>
          </div>
          <div class="member-cta-act">
            <a class="btn btn-primary btn-lg" href="${esc(trial.paymentUrl)}" target="_blank" rel="noopener">Spara kortet hos Stripe</a>
            <button class="btn btn-quiet" data-action="cancel-trial-commit">Avbryt</button>
          </div>
        </div>`;
    case "card_on_file":
      return `<div class="member-cta is-done">
          <div class="member-cta-text">
            <h3>Klart. Medlemskapet tar vid efter provet.</h3>
            <p>Kortet är sparat för ${plates}. Första dragningen sker
              ${esc(date(trial?.firstChargeAt || trial?.endsAt))}, sedan varje
              månad tills ni säger upp.</p>
          </div>
          <div class="member-cta-act">
            <button class="btn btn-quiet" data-action="cancel-trial-commit">Avbryt auto-förnyelse</button>
          </div>
        </div>`;
    case "pay":
      return `<div class="member-cta">
          <div class="member-cta-text">
            <h3>Fortsätt med ${theMemberships}</h3>
            <p>Provet är slut för ${plates}. Du ser priset och godkänner det,
              sedan betalar du på Stripes betalsida. Appen öppnas när
              betalningen har gått igenom.</p>
          </div>
          <div class="member-cta-act">
            <button class="btn btn-primary btn-lg" data-action="continue-trial">Visa pris och betala</button>
          </div>
        </div>`;
    default:
      break;
  }

  if (stage === "trial" || stage === "trial_ended") {
    const canBuy = (data.permissions ?? []).includes("purchase");
    const text = !canBuy
      ? "Ägaren eller ekonomiansvarig startar medlemskapet här."
      : "Skaffa medlemskap och bjud in konton under <em>Medlemskap</em>. Sedan kan ni fortsätta efter provet här.";
    return `<div class="member-cta is-quiet"><div class="member-cta-text"><p>${text}</p></div></div>`;
  }
  return "";
}

function membershipCard(data, pricing) {
  const sub = data.subscription ?? {};
  const t = data.trial;
  const stage = membershipStage(data);
  const plan = membershipPlan(data);

  const head = {
    trial: [
      "Ni provar Taxi Tips — fortsätt med medlemskap",
      t?.endsAt
        ? `Gratis till ${dateTime(t.endsAt)}. Spara kortet nu så tar medlemskapet vid automatiskt.`
        : "Provet startar när den första telefonen ansluts. Därefter kan ni spara kortet här.",
      '<span class="pill pill-warn">Provperiod</span>',
    ],
    trial_committed: [
      "Medlemskapet är klart",
      `Kortet är sparat och allt är upplåst. Medlemskapet tar vid ${date(t?.firstChargeAt || t?.endsAt)}.`,
      '<span class="pill pill-ok">Kort sparat</span>',
    ],
    member: [
      "Medlemskap",
      sub.cancelAtPeriodEnd
        ? `Uppsagt. Allt fungerar som vanligt till ${date(sub.accessUntil)}.`
        : "Allt ingår. Förnyas en gång i månaden tills ni säger upp.",
      statusPill(sub.status),
    ],
    trial_ended: [
      "Provet är slut",
      "Fortsätt med medlemskap, så öppnas appen igen för era medlemskap.",
      '<span class="pill pill-danger">Provet slut</span>',
    ],
    none: ["Medlemskap", "Skaffa ett medlemskap för att komma igång.", statusPill("none")],
  }[stage];

  const facts = {
    trial: t
      ? [
          ["Provet slutar", t.endsAt ? date(t.endsAt) : "Vid första inloggningen"],
          ["Provplatser", `${t.vehiclesUsed ?? 0} av ${t.vehicleLimit ?? 0}`],
          ["Under provet", "0 kr"],
        ]
      : [],
    trial_committed: t
      ? [
          ["Första dragningen", date(t.firstChargeAt || t.endsAt)],
          ["Provplatser", `${t.vehiclesUsed ?? 0} av ${t.vehicleLimit ?? 0}`],
          ["Under provet", "0 kr"],
        ]
      : [],
    member: [
      ["Medlemskap", String(data.licenseCount ?? 0)],
      ["Extra län", String(data.extraCountyCount ?? 0)],
      sub.cancelAtPeriodEnd
        ? ["Gäller till", date(sub.accessUntil)]
        : ["Nästa betalning", date(sub.currentPeriodEnd)],
    ],
  }[stage] ?? [];

  const cs = continueState(data);
  const isUrgent = cs?.kind === "pay";
  const ctaHtml = membershipAction(data, stage, plan);
  return `<section class="card member${isUrgent ? " is-urgent" : ""}" aria-labelledby="memberTitle">
      <div class="member-head">
        <div>
          <h2 id="memberTitle">${esc(head[0])}</h2>
          <p class="member-sub">${esc(head[1])}</p>
        </div>
        ${head[2]}
      </div>

      ${
        facts.length
          ? `<dl class="member-facts">${facts
              .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`)
              .join("")}</dl>`
          : ""
      }

      ${isUrgent ? ctaHtml : ""}

      <div class="member-body">
        <div class="member-left">
          ${featuresSection(data, stage)}
          <ul class="member-terms">
            <li>En licens per konto. Den som håller platsen loggar in i appen och byter telefon utan extra kostnad.</li>
            <li>Månadsvis. Säg upp när ni vill, allt fungerar perioden ut.</li>
          </ul>
        </div>
        ${priceSection(stage, pricing)}
      </div>

      ${isUrgent ? "" : ctaHtml}
    </section>`;
}

export function abonnemang(data, orders, pricing = null) {
  const sub = data.subscription ?? {};
  const canBuy = (data.permissions ?? []).includes("purchase");
  const canCancel = (data.permissions ?? []).includes("cancel_subscription");
  const rows = [
    ["Status", statusPill(sub.status)],
    sub.currentPeriodStart
      ? ["Innevarande period", `${esc(date(sub.currentPeriodStart))} – ${esc(date(sub.currentPeriodEnd))}`]
      : null,
    sub.currentPeriodEnd ? ["Nästa betalning", esc(date(sub.currentPeriodEnd))] : null,
    sub.introEndsAt ? ["Introduktionen slutar", esc(date(sub.introEndsAt))] : null,
    sub.graceUntil ? ["Betalningsfrist", esc(dateTime(sub.graceUntil))] : null,
  ].filter(Boolean);

  return `
    ${membershipCard(data, pricing)}

    <div class="card">
      <h2>Hantera abonnemanget</h2>
      <dl class="kv-list">
        ${rows.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join("")}
      </dl>
      ${
        canBuy
          ? `<div class="btn-row">
               ${sub.status === "past_due"
                 ? `<button class="btn btn-primary btn-lg" data-action="billing-portal">Uppdatera betalmetod</button>
                    <button class="btn btn-quiet" data-action="add-license">Lägg till medlemskap</button>`
                 : `<button class="btn btn-primary" data-action="add-license">Lägg till medlemskap</button>
                    <button class="btn btn-quiet" data-action="billing-portal">Uppdatera kort / fakturor</button>`}
             </div>`
          : ""
      }
    </div>

    <details class="advanced">
      <summary>Mer: beställningar och fakturor</summary>
      ${
        (orders ?? []).filter((o) => !["canceled", "failed", "draft"].includes(o.status)).length
          ? `<ul class="simple-list order-list">
             ${(orders ?? [])
               .filter((o) => !["canceled", "failed", "draft"].includes(o.status))
               .map(
                 (o) => `<li>
                   <div>
                     <b>${esc(orderKind(o.kind))}</b>
                     <span class="muted">${esc(date(o.createdAt))} · ${esc(orderStatus(o.status))}</span>
                   </div>
                   <div class="order-amounts">
                     <span>${esc(money(o.totalNowOre, o.currency))} nu</span>
                     <span class="muted">${esc(money(o.nextPeriodTotalOre, o.currency))} / period</span>
                     ${
                       o.status === "pending_payment" && o.paymentUrl
                         ? `<a class="btn btn-primary btn-sm" href="${esc(o.paymentUrl)}" target="_blank" rel="noopener">Betala</a>`
                         : ""
                     }
                   </div>
                 </li>`,
               )
               .join("")}
             </ul>
             <p class="muted">Beloppen är inklusive moms.</p>`
          : '<p class="muted">Inga beställningar än.</p>'
      }
    </details>

    ${
      canCancel
        ? `<details class="advanced">
             <summary>Mer: säga upp</summary>
             ${
               sub.cancelAtPeriodEnd
                 ? `<div class="btn-row"><button class="btn btn-quiet" data-action="undo-cancel">Ångra uppsägningen</button></div>`
                 : `<p class="muted">Uppsägningen stoppar nästa period. Du behåller
                    åtkomsten den betalda perioden ut, och kan ångra dig fram till slutdatumet.</p>
                    <div class="btn-row"><button class="btn btn-danger" data-action="cancel">Säg upp abonnemanget</button></div>`
             }
           </details>`
        : ""
    }
  `;
}

function orderKind(kind) {
  return (
    {
      initial: "Första beställningen",
      add_license: "Fler medlemskap",
      add_county: "Extra län",
      reduce: "Minskning",
      change_base_county: "Byte av baslän",
      renewal: "Förnyelse",
    }[kind] ?? kind
  );
}

function orderStatus(status) {
  return (
    {
      draft: "Utkast",
      pending_payment: "Väntar på betalning",
      paid: "Betald",
      applied: "Verkställd",
      failed: "Misslyckad",
      canceled: "Avbruten",
      scheduled: "Schemalagd",
    }[status] ?? status
  );
}

/* --- Företag och behörigheter ------------------------------------------- */

/**
 * Vem som kan logga in i portalen och appens adminläge. Ägaren bjuder in en
 * kollega med e-post; servern mejlar en inloggningslänk (fleet/sales.py).
 * En ny ägare bjuds inte in här -- det är ägarbytet nedan.
 */
function membersCard(m) {
  if (!m) return "";
  const roleText = {
    fleet_admin: "Fordonsadministratör – medlemskap, län och konton",
    finance: "Ekonomiansvarig – betalning och fakturor",
  };
  return `
    <div class="card" id="inloggningar">
      <h2>Inloggningar</h2>
      <p class="muted">De som kan logga in här och i appens adminläge. Förare loggar in i appen.</p>
      <table><tbody>${(m.members ?? []).map((p) => `
        <tr><td>${esc(p.email || "Okänd e-post")}${p.isMe ? ' <span class="muted">(du)</span>' : ""}</td>
          <td>${esc(roleName(p.role))}</td>
          <td>${m.canManage && !p.isMe ? `<button class="btn btn-quiet" data-action="member-remove"
            data-user="${esc(p.userId)}" data-email="${esc(p.email)}">Ta bort</button>` : ""}</td></tr>`).join("")}
        ${(m.invites ?? []).map((i) => `
        <tr><td>${esc(i.email)} <span class="muted">${i.expired ? "inbjudan har gått ut" : `inbjuden, gäller till ${esc(date(i.expiresAt))}`}</span></td>
          <td>${esc(roleName(i.role))}</td>
          <td>${m.canManage ? `<button class="btn btn-quiet" data-action="member-invite-revoke"
            data-invite="${esc(i.id)}" data-email="${esc(i.email)}">Återkalla</button>` : ""}</td></tr>`).join("")}
      </tbody></table>
      ${m.canManage ? `
      <h3>Bjud in en kollega</h3>
      <form id="memberInviteForm" novalidate>
        <label for="mEmail">E-post</label>
        <input id="mEmail" name="email" type="email" autocomplete="off" required placeholder="namn@bolaget.se" />
        <label for="mRole">Roll</label>
        <select id="mRole" name="role">${(m.roles ?? []).map((r) =>
          `<option value="${esc(r)}">${esc(roleText[r] ?? roleName(r))}</option>`).join("")}</select>
        <div class="btn-row"><button class="btn btn-primary" type="submit">Skicka inbjudan</button></div>
        <p class="muted">Kollegan får ett mejl med en inloggningslänk som gäller i 14 dagar.</p>
      </form>` : '<p class="muted">Bara företagsägaren kan bjuda in fler.</p>'}
    </div>`;
}

export function foretag(data, members = null) {
  const company = data.company ?? {};
  const twoFactor = data.twoFactor ?? {};
  return `
    <div class="card">
      <h2>Företaget</h2>
      <dl class="kv-list">
        <div><dt>Namn</dt><dd>${esc(company.name)}</dd></div>
        <div><dt>Organisationsnummer</dt><dd>${esc(company.orgNumber || "—")}</dd></div>
        <div><dt>Verifiering</dt><dd>${esc(verification(company.verificationStatus))}</dd></div>
        <div><dt>Din roll</dt><dd>${esc(roleName(data.role))}</dd></div>
      </dl>
    </div>

    ${detailsCards(data)}

    ${membersCard(members)}

    <details class="advanced">
      <summary>Mer: säkerhet och konto</summary>
      <h3>Tvåfaktorsautentisering</h3>
      <p>${
        twoFactor.enforced
          ? twoFactor.satisfied
            ? '<span class="ok">Din session är tvåfaktorsäkrad.</span>'
            : '<span class="error">Krävs för köp, uppsägning och ägarbyte. Logga in med tvåfaktor.</span>'
          : "Inte påslaget än. Vi meddelar i god tid innan det börjar krävas."
      }</p>
      <h3>Ägarroll</h3>
      <p class="muted">Ägarrollen överförs i två steg: du begär bytet med en
        ny inloggning, och mottagaren accepterar. Den sista ägaren går inte att
        ta bort medan ett aktivt abonnemang löper.</p>
      <h3>Avsluta företagskontot</h3>
      <p class="muted">Stoppar framtida förnyelse. Att ta bort förare eller
        avinstallera appen avslutar inte abonnemanget -- det här gör det.</p>
      ${
        (data.permissions ?? []).includes("close_account")
          ? '<div class="btn-row"><button class="btn btn-danger" data-action="close-account">Avsluta kontot</button></div>'
          : '<p class="muted">Bara företagsägaren kan avsluta kontot.</p>'
      }
    </details>
  `;
}

/**
 * Kontaktperson och fakturering, som kunden ändrar själv
 * (POST /api/fleet/company/details). Fälten är låsta för den som saknar
 * behörigheten -- servern prövar den ändå.
 */
function detailsCards(data) {
  const d = data.company?.details ?? {};
  const a = d.billingAddress ?? {};
  const perms = data.permissions ?? [];
  const canContact = perms.includes("manage_members");
  const canBilling = perms.includes("purchase");
  const lock = (ok) => (ok ? "" : "disabled");
  return `
    <div class="card">
      <h2>Kontaktperson</h2>
      <p class="muted">Vi ringer det här numret om något behöver fixas.</p>
      <form id="contactForm" novalidate>
        <label for="cName">Namn</label>
        <input id="cName" name="contactName" autocomplete="name" value="${esc(d.contactName)}" ${lock(canContact)} required />
        <label for="cPhone">Mobilnummer</label>
        <input id="cPhone" name="contactPhone" type="tel" inputmode="tel" autocomplete="tel" value="${esc(d.contactPhone)}" ${lock(canContact)} required />
        ${d.contactEmail ? `<p class="muted">Inloggning: ${esc(d.contactEmail)}</p>` : ""}
        ${
          canContact
            ? '<div class="btn-row"><button class="btn btn-primary" type="submit">Spara</button></div><p class="ok" data-saved hidden>Sparat.</p>'
            : '<p class="muted">Bara ägaren kan ändra kontaktpersonen.</p>'
        }
      </form>
    </div>

    <div class="card">
      <h2>Fakturering</h2>
      <p class="muted">Hit skickar vi fakturor och kvitton.</p>
      <form id="billingForm" novalidate>
        <label for="bEmail">E-post för fakturor</label>
        <input id="bEmail" name="billingEmail" type="email" inputmode="email" autocomplete="email" value="${esc(d.billingEmail)}" ${lock(canBilling)} required />
        <label for="bRef">Er referens (valfritt)</label>
        <input id="bRef" name="billingReference" value="${esc(d.billingReference)}" ${lock(canBilling)} />
        <label for="bLine1">Gatuadress</label>
        <input id="bLine1" name="line1" autocomplete="address-line1" value="${esc(a.line1)}" ${lock(canBilling)} required />
        <label for="bLine2">c/o eller våning (valfritt)</label>
        <input id="bLine2" name="line2" autocomplete="address-line2" value="${esc(a.line2)}" ${lock(canBilling)} />
        <div class="form-pair">
          <div>
            <label for="bPostal">Postnummer</label>
            <input id="bPostal" name="postalCode" inputmode="numeric" autocomplete="postal-code" value="${esc(a.postalCode)}" ${lock(canBilling)} />
          </div>
          <div>
            <label for="bCity">Ort</label>
            <input id="bCity" name="city" autocomplete="address-level2" value="${esc(a.city)}" ${lock(canBilling)} required />
          </div>
        </div>
        ${
          canBilling
            ? '<div class="btn-row"><button class="btn btn-primary" type="submit">Spara</button></div><p class="ok" data-saved hidden>Sparat.</p>'
            : '<p class="muted">Bara ägaren eller ekonomiansvarig kan ändra faktureringen.</p>'
        }
      </form>
    </div>
  `;
}

function verification(status) {
  return (
    {
      unverified: "Inte verifierad",
      pending_review: "Under granskning",
      verified: "Verifierad",
      rejected: "Avvisad",
    }[status] ?? status
  );
}

function roleName(role) {
  return (
    {
      company_owner: "Företagsägare",
      fleet_admin: "Fordonsadministratör",
      finance: "Ekonomiansvarig",
      driver: "Förare",
      // `??` och `||` får inte blandas utan parenteser -- det är ett syntaxfel,
      // inte en stilfråga.
    }[role] ?? (role || "—")
  );
}

/* --- Prisunderlaget kunden godkänner ------------------------------------ */

export function quoteHtml(quote) {
  const now = quote.now ?? {};
  const next = quote.nextPeriod ?? {};
  const lines = (now.lines ?? []).length ? now.lines : (next.lines ?? []);
  return `
    <div class="quote-lines">
      ${lines
        .map(
          (l) => `<div>${esc(l.label)} × ${esc(l.quantity)} —
            ${esc(money(l.amount_ore, now.currency))}
            ${l.note ? `<br /><span class="muted">${esc(l.note)}</span>` : ""}</div>`,
        )
        .join("")}
    </div>
    <div>Att betala nu (exkl. moms): ${esc(money(now.amountOre, now.currency))}</div>
    <div>Moms: ${esc(money(now.vatOre, now.currency))}</div>
    <div class="quote-total">Att betala nu: ${esc(money(now.totalOre, now.currency))}</div>
    <div class="muted">Nästa period (${esc(date(quote.nextPeriodStart))}):
      ${esc(money(next.totalOre, next.currency))} inkl. moms</div>
  `;
}
