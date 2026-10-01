import { admin } from "./api.js";
import { esc } from "./sales.js";

/**
 * Förares rapporter om felaktiga tips. Egen modul så att main.js och
 * followup/sales inte behöver röras mer än navigeringen.
 */

export async function mount(container, { onError, onOpenChange }) {
  container.innerHTML = `
    <div class="page-head">
      <div><h1>Tipprapporter</h1>
        <p class="muted">Förare som tror att ett tips är fel. Granska tipset och ta bort det ur flödet om det behövs.</p></div>
    </div>
    <div class="support">
      <aside class="card support-list" aria-label="Rapporter">
        <div class="support-filter">
          <select id="trStatus" aria-label="Visa">
            <option value="open">Öppna</option>
            <option value="resolved">Avslutade</option>
            <option value="all">Alla</option>
          </select>
        </div>
        <ul id="trList" class="sup-threads"><li class="muted">Laddar …</li></ul>
      </aside>
      <section class="card support-chat" id="trDetail" aria-live="polite">
        <p class="muted">Välj en rapport.</p>
      </section>
    </div>`;

  const st = { status: "open", selected: null, reports: [], detail: null };

  const $ = (id) => container.querySelector(`#${id}`);

  function renderList() {
    const list = $("trList");
    if (!st.reports.length) {
      list.innerHTML = '<li class="muted">Inga rapporter.</li>';
      return;
    }
    list.innerHTML = st.reports.map((r) => {
      const o = r.opportunity ?? {};
      return `
        <li><button class="sup-thread${r.id === st.selected ? " is-selected" : ""}"
            type="button" data-tr-id="${esc(r.id)}">
          <span class="sup-thread-top">
            <b>${esc(o.title || "Tips")}</b>
            <span class="muted">${esc(r.createdAt?.slice(0, 16)?.replace("T", " ") ?? "")}</span>
          </span>
          <span class="sup-thread-preview">${esc(r.reason || "Ingen förklaring")}</span>
        </button></li>`;
    }).join("");
  }

  function renderDetail() {
    const box = $("trDetail");
    const d = st.detail;
    if (!d?.report) {
      box.innerHTML = '<p class="muted">Välj en rapport.</p>';
      return;
    }
    const r = d.report;
    const o = r.opportunity ?? {};
    box.innerHTML = `
      <h2>${esc(o.title || "Tips")}</h2>
      <p class="muted">${esc(o.kind ?? "")} · poäng ${esc(o.demandScore ?? "—")} · ${esc(o.ruleId ?? "")}</p>
      <p>${esc(o.summary ?? "")}</p>
      <p><strong>Förarens rapport:</strong> ${esc(r.reason || "—")}</p>
      <p class="muted">Enhet ${esc(r.deviceToken)} · ${esc(r.createdAt?.slice(0, 16)?.replace("T", " ") ?? "")}</p>
      ${o.suppressedAt ? `<p class="ok">Tipset är borttaget (${esc(o.expiredReason ?? "")}).</p>` : ""}
      ${r.status === "open" ? `
        <label for="trNote">Anteckning (valfritt)</label>
        <textarea id="trNote" rows="2" class="wide"></textarea>
        <div class="btn-row">
          <button class="btn btn-danger" type="button" id="trSuppress">Ta bort tipset och avsluta</button>
          <button class="btn btn-quiet" type="button" id="trDismiss">Tipset var korrekt — avfärda</button>
        </div>` : `<p class="muted">Avslutad${r.resolutionNote ? `: ${esc(r.resolutionNote)}` : ""}</p>`}
      ${d.sourceEvents?.length ? `
        <details class="audit-detail"><summary>Källhändelse (rå)</summary>
          <pre>${esc(JSON.stringify(d.sourceEvents[0]?.raw ?? {}, null, 2))}</pre>
        </details>` : ""}`;
  }

  async function loadList() {
    const res = await admin.tipReports(st.status);
    st.reports = res.reports ?? [];
    onOpenChange?.(res.open ?? 0);
    renderList();
  }

  async function openReport(id) {
    st.selected = id;
    st.detail = await admin.tipReport(id);
    renderList();
    renderDetail();
  }

  container.querySelector("#trStatus").addEventListener("change", (e) => {
    st.status = e.target.value;
    st.selected = null;
    st.detail = null;
    loadList().catch(onError);
    renderDetail();
  });

  container.querySelector("#trList").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-tr-id]");
    if (!btn) return;
    openReport(btn.dataset.trId).catch(onError);
  });

  container.querySelector("#trDetail").addEventListener("click", async (e) => {
    if (!st.selected || !st.detail?.report || st.detail.report.status !== "open") return;
    const note = container.querySelector("#trNote")?.value?.trim() ?? "";
    try {
      if (e.target.id === "trSuppress") {
        await admin.resolveTipReport(st.selected, { suppressTip: true, note });
      } else if (e.target.id === "trDismiss") {
        await admin.resolveTipReport(st.selected, { suppressTip: false, note });
      } else return;
      await loadList();
      st.detail = await admin.tipReport(st.selected);
      renderDetail();
    } catch (err) {
      onError(err);
    }
  });

  await loadList();
}
