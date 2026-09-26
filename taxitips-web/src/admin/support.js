import { admin } from "./api.js";
import { esc } from "./sales.js";

/**
 * Supportchatten i adminwebben: användarnas frågor från appen, och svaren.
 *
 * Resten av adminwebben ritar om hela vyn vid varje åtgärd. Här går det inte:
 * listan och konversationen hämtas om medan man skriver, och en omritning hade
 * tömt svaret mitt i en mening. Modulen äger därför sin del av sidan -- skalet
 * ritas en gång, sedan byts bara listan och meddelandena ut.
 *
 * Egna attribut (`data-sup`, `data-sup-thread`) i stället för `data-action`
 * och `data-company`: main.js lyssnar på hela vyn, och en rad med
 * `data-company` hade öppnat kundsidan i stället för konversationen.
 */

const LIST_EVERY_MS = 10_000;
const THREAD_EVERY_MS = 4_000;

let active = null;

/** Stoppar hämtningen när man lämnar sidan. Anropas av main.js vid varje byte. */
export function stop() {
  active?.stop();
  active = null;
}

const KIND = { member: "Konto", device: "Förartelefon" };

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date();
  const hm = d.toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return hm;
  return `${d.toLocaleDateString("sv-SE", { day: "numeric", month: "short" })} ${hm}`;
}

function threadItem(t, selected) {
  return `
    <li><button class="sup-thread${t.id === selected ? " is-selected" : ""}${t.waiting ? " is-waiting" : ""}"
        data-sup-thread="${esc(t.id)}">
      <span class="sup-thread-top">
        <b>${esc(t.companyName || t.requesterLabel || "Okänd")}</b>
        <span class="muted">${esc(when(t.lastMessageAt))}</span>
      </span>
      <span class="sup-thread-who muted">${esc(KIND[t.requesterKind] ?? "")} · ${esc(t.requesterLabel)}</span>
      <span class="sup-thread-preview">${t.waiting ? '<span class="sup-dot" aria-label="Väntar på svar"></span>' : ""}${esc(t.preview)}</span>
    </button></li>`;
}

function messageItem(m) {
  const mine = m.sender === "staff";
  return `
    <li class="sup-msg ${mine ? "sup-msg-staff" : "sup-msg-user"}">
      <div class="sup-bubble">${esc(m.body).replace(/\n/g, "<br>")}</div>
      <div class="sup-meta muted">${mine ? "Support · " : ""}${esc(when(m.createdAt))}</div>
    </li>`;
}

/**
 * Ritar sidan och startar hämtningen.
 *
 * @param {HTMLElement} container  vyn (#view)
 * @param {object} opts
 *   threadId      konversationen att öppna direkt (t.ex. från kundsidan)
 *   canReply      personalen får svara (ADMIN_SUPPORT)
 *   onOpenCompany kundsidan för ett bolag
 *   onError       adminwebbens gemensamma felvisning
 *   onWaiting     antalet som väntar på svar, för menyns räknare
 */
export function mount(container, { threadId = null, canReply = false, onOpenCompany, onError, onWaiting }) {
  stop();
  const st = { status: "open", q: "", selected: threadId, threads: [], detail: null, timers: [], stopped: false };

  container.innerHTML = `
    <div class="page-head">
      <div><h1>Support</h1>
        <p class="muted">Frågor från appen. Nya meddelanden hämtas automatiskt; användaren får en notis när du svarar.</p></div>
    </div>
    <div class="support">
      <aside class="card support-list" aria-label="Konversationer">
        <div class="support-filter">
          <select id="supStatus" aria-label="Visa">
            <option value="open">Öppna</option>
            <option value="closed">Avslutade</option>
            <option value="all">Alla</option>
          </select>
          <input id="supQ" type="search" placeholder="Sök bolag eller e-post" aria-label="Sök" />
        </div>
        <ul id="supThreads" class="sup-threads"><li class="muted">Laddar …</li></ul>
      </aside>
      <section class="card support-chat" id="supChat" aria-live="polite">
        <p class="muted">Välj en konversation.</p>
      </section>
    </div>`;

  const $ = (id) => container.querySelector(`#${id}`);

  function renderList() {
    const list = $("supThreads");
    if (!list) return;
    list.innerHTML = st.threads.length
      ? st.threads.map((t) => threadItem(t, st.selected)).join("")
      : `<li class="muted sup-empty">${st.status === "open" ? "Inga öppna frågor. 🎉" : "Inget här."}</li>`;
  }

  function renderChatShell() {
    const chat = $("supChat");
    const d = st.detail;
    if (!chat) return;
    if (!d) {
      chat.innerHTML = '<p class="muted">Välj en konversation.</p>';
      return;
    }
    const t = d.thread;
    const closed = t.status === "closed";
    chat.innerHTML = `
      <header class="sup-head">
        <div>
          <h2>${esc(t.companyName || t.requesterLabel || "Okänd")}</h2>
          <p class="muted">${esc(KIND[t.requesterKind] ?? "")} · ${esc(t.requesterLabel)}
            ${closed ? ' · <span class="pill">Avslutad</span>' : ""}</p>
        </div>
        <div class="btn-row">
          ${t.companyId ? `<button class="btn btn-quiet btn-small" data-sup="company">Kundsidan</button>` : ""}
          ${canReply ? `<button class="btn btn-quiet btn-small" data-sup="${closed ? "reopen" : "close"}">
            ${closed ? "Öppna igen" : "Avsluta"}</button>` : ""}
        </div>
      </header>
      <ol id="supMessages" class="sup-messages"></ol>
      ${canReply ? `
      <form id="supForm" class="sup-form">
        <textarea id="supBody" rows="3" maxlength="2000" placeholder="Skriv ett svar … (Ctrl+Enter skickar)" required></textarea>
        <button class="btn btn-primary" type="submit">Skicka</button>
      </form>` : '<p class="muted">Din roll kan läsa men inte svara.</p>'}`;
    renderMessages(true);
  }

  function renderMessages(forceBottom = false) {
    const box = $("supMessages");
    if (!box || !st.detail) return;
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    const messages = st.detail.messages ?? [];
    box.innerHTML = messages.length
      ? messages.map(messageItem).join("")
      : '<li class="muted sup-empty">Inga meddelanden än. Skriv det första.</li>';
    if (forceBottom || nearBottom) box.scrollTop = box.scrollHeight;
  }

  async function loadList() {
    const res = await admin.supportThreads(st.status, st.q);
    if (st.stopped) return;
    st.threads = res.threads ?? [];
    onWaiting?.(res.waiting ?? 0);
    renderList();
  }

  async function loadThread({ shell = false } = {}) {
    if (!st.selected) return;
    const before = st.detail?.messages?.length ?? -1;
    const previousStatus = st.detail?.thread?.status;
    const res = await admin.supportThread(st.selected, canReply);
    if (st.stopped) return;
    st.detail = res;
    if (shell || res.thread.status !== previousStatus) renderChatShell();
    else if ((res.messages?.length ?? 0) !== before) renderMessages();
  }

  function guard(fn) {
    return async (...args) => {
      try {
        await fn(...args);
      } catch (error) {
        if (!st.stopped) onError?.(error);
      }
    };
  }

  const tick = (fn, ms) => {
    const id = setInterval(() => {
      if (!document.hidden) guard(fn)();
    }, ms);
    st.timers.push(id);
  };

  async function select(id) {
    st.selected = id;
    renderList();
    st.detail = null;
    $("supChat").innerHTML = '<p class="muted">Laddar …</p>';
    await loadThread({ shell: true });
    // Öppnad = läst: listans prick ska försvinna direkt, inte vid nästa hämtning.
    await loadList();
    $("supBody")?.focus();
  }

  async function send() {
    const input = $("supBody");
    const body = input?.value.trim();
    if (!body) return;
    const button = container.querySelector("#supForm button[type=submit]");
    button.disabled = true;
    try {
      st.detail = await admin.supportReply(st.selected, body);
      input.value = "";
      renderMessages(true);
      await loadList();
    } finally {
      button.disabled = false;
      input.focus();
    }
  }

  async function setStatus(status) {
    st.detail = await admin.supportStatus(st.selected, status);
    renderChatShell();
    await loadList();
  }

  // --- händelser: bara inom den här sidan ---
  const onClick = guard(async (event) => {
    const item = event.target.closest("[data-sup-thread]");
    if (item) return select(item.dataset.supThread);
    const button = event.target.closest("[data-sup]");
    if (!button) return;
    const what = button.dataset.sup;
    if (what === "company" && st.detail?.thread?.companyId) return onOpenCompany?.(st.detail.thread.companyId);
    if (what === "close") return setStatus("closed");
    if (what === "reopen") return setStatus("open");
  });
  const onSubmit = guard(async (event) => {
    if (event.target.id !== "supForm") return;
    event.preventDefault();
    await send();
  });
  const onKey = guard(async (event) => {
    if (event.target.id === "supBody" && event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      await send();
    }
  });
  const onChange = guard(async (event) => {
    if (event.target.id !== "supStatus") return;
    st.status = event.target.value;
    await loadList();
  });
  let searchTimer = null;
  const onInput = (event) => {
    if (event.target.id !== "supQ") return;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(guard(async () => {
      st.q = event.target.value.trim();
      await loadList();
    }), 300);
  };

  container.addEventListener("click", onClick);
  container.addEventListener("submit", onSubmit);
  container.addEventListener("keydown", onKey);
  container.addEventListener("change", onChange);
  container.addEventListener("input", onInput);

  active = {
    stop() {
      st.stopped = true;
      st.timers.forEach(clearInterval);
      clearTimeout(searchTimer);
      container.removeEventListener("click", onClick);
      container.removeEventListener("submit", onSubmit);
      container.removeEventListener("keydown", onKey);
      container.removeEventListener("change", onChange);
      container.removeEventListener("input", onInput);
    },
  };

  guard(async () => {
    await loadList();
    if (st.selected) await select(st.selected);
  })();
  tick(loadList, LIST_EVERY_MS);
  tick(() => loadThread(), THREAD_EVERY_MS);
}

