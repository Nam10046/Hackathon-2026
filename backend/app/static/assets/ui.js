/* Shared UI helpers, no dependencies. Anything put into innerHTML goes through SC.esc. */
window.SC = window.SC || {};
(function (SC) {
  // One place to change when a physical load cell is connected (see grafana/make_tenant_pages.py too).
  SC.SOURCE = {
    weight: "No physical load cell is connected yet. Weights come from a simulated load cell on the ESP32, or from demo history.",
    legend: [["real", "Real", "recorded by the system: accounts, decisions, device connections"],
             ["est", "Estimated", "calculated with placeholder prices or factors"],
             ["sim", "Simulated", "not from physical hardware or a real operator"]],
  };
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  SC.esc = v => String(v ?? "").replace(/[&<>"']/g, c => ESC[c]);
  const missing = "–";
  const fmt = (v, o) => (v === null || v === undefined || Number.isNaN(v)) ? missing : Number(v).toLocaleString("en-GB", o);
  SC.num = (v, d = 0) => fmt(v, { maximumFractionDigits: d });
  SC.eur = v => fmt(v, { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
  SC.kg = v => v === null || v === undefined ? missing : `${SC.num(v)} kg`;
  SC.date = t => t ? new Date(t).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC" : missing;
  SC.tag = kind => { const k = SC.SOURCE.legend.find(l => l[0] === kind); return `<span class="tag tag--${kind}">${k[1]}</span>`; };
  SC.badge = (kind, text) => `<span class="badge badge--${kind}">${SC.esc(text)}</span>`;
  SC.legend = () => `<p class="small muted inline">${SC.SOURCE.legend.map(l => `${SC.tag(l[0])} ${SC.esc(l[2])}`).join(" &nbsp; ")}</p>`;

  SC.state = ({ title, body = "", action = "" }) => `<div class="state"><h2>${SC.esc(title)}</h2><p>${SC.esc(body)}</p>${action}</div>`;
  SC.skeleton = (kpis = 4, lines = 5) => `<div class="stack" aria-busy="true"><span class="sr">Loading</span>
    <div class="kpis">${'<span class="skeleton skeleton--kpi"></span>'.repeat(kpis)}</div>
    <div class="card">${'<span class="skeleton"></span>'.repeat(lines)}</div></div>`;

  /** Turns any failure into one clear message. Never shows data, never pretends it worked. */
  SC.errorState = (err, retryId = "retry") => {
    const texts = {
      network: ["Cannot reach the server", "Check that the backend is running and your connection works."],
      auth: ["Please sign in", "Your session has ended or you are not signed in."],
      forbidden: ["You do not have access", err.message || "This page is not available for your account."],
      notfound: ["Not found", err.message || "This item does not exist or is not yours."],
      server: ["The server had a problem", "Nothing was changed. Try again in a moment."],
    }[err.kind] || ["Something went wrong", err.message || "Try again in a moment."];
    const action = err.kind === "auth" ? `<a class="btn primary" href="${SC.esc(SC.link("/portal"))}">Go to sign in</a>`
      : err.kind === "forbidden" ? `<a class="btn" href="${SC.esc(SC.link("/portal"))}">Back to portal</a>`
      : `<button id="${SC.esc(retryId)}">Try again</button>`;
    return `<div class="card" role="alert">${SC.state({ title: texts[0], body: texts[1], action })}</div>`;
  };

  let toasts;
  SC.toast = (message, kind = "ok") => {
    if (!toasts) {
      toasts = document.createElement("div");
      toasts.className = "toasts";
      toasts.setAttribute("role", "status");
      toasts.setAttribute("aria-live", "polite");
      document.body.append(toasts);
    }
    const t = document.createElement("div");
    t.className = "toast" + (kind === "bad" ? " toast--bad" : "");
    t.textContent = message;
    toasts.append(t);
    setTimeout(() => t.remove(), kind === "bad" ? 8000 : 5000);
  };

  /** Resolves true or false. Native dialog: traps focus, Esc cancels, focus returns afterwards. */
  SC.confirm = ({ title, body = "", yes = "Confirm", danger = false }) => new Promise(resolve => {
    const d = document.createElement("dialog");
    d.setAttribute("aria-labelledby", "dlg-title");
    d.innerHTML = `<h2 id="dlg-title">${SC.esc(title)}</h2><p>${SC.esc(body)}</p>
      <div class="dialog-actions"><button value="no" autofocus>Cancel</button>
      <button value="yes" class="${danger ? "danger-solid" : "primary"}">${SC.esc(yes)}</button></div>`;
    let answer = false;
    d.addEventListener("click", e => { if (e.target.value) { answer = e.target.value === "yes"; d.close(); } });
    d.addEventListener("close", () => { d.remove(); resolve(answer); });
    document.body.append(d);
    d.showModal();
  });

  /** Disables a button while the work runs, and shows failures. Returns true only if it worked. */
  SC.busy = async (button, work) => {
    const before = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spin" aria-hidden="true"></span>${before}`;
    try {
      await work();
      return true;
    } catch (err) {
      SC.toast(err.message || "That did not work", "bad");
      return false;
    } finally {
      button.disabled = false;
      button.innerHTML = before;
    }
  };

  /** Checks a form with the browser's rules and shows the reason under each field. Returns true if valid. */
  SC.validate = form => {
    let first = null;
    form.querySelectorAll("input, select").forEach(input => {
      if (!input.id || input.type === "checkbox") return;
      const id = input.id + "-err";
      document.getElementById(id)?.remove();
      input.removeAttribute("aria-invalid");
      const hint = input.dataset.hint ? input.dataset.hint + " " : "";
      input.setAttribute("aria-describedby", hint.trim());
      if (input.checkValidity()) return;
      const p = document.createElement("p");
      p.className = "error";
      p.id = id;
      p.textContent = input.dataset.message || input.validationMessage;
      input.after(p);
      input.setAttribute("aria-invalid", "true");
      input.setAttribute("aria-describedby", hint + id);
      first = first || input;
    });
    first?.focus();
    return !first;
  };

  SC.link = path => {
    const m = SC.data?.mode === "mock" ? `${path.includes("?") ? "&" : "?"}mock=${encodeURIComponent(SC.data.scenario)}` : "";
    const [base, hash] = path.split("#");
    return base + m + (hash ? "#" + hash : "");
  };

  /** Mock mode says so on every screen. Live mode shows a chip only where the dev mock route is switched on. */
  SC.modeBanner = () => {
    const d = SC.data;
    if (d.mockRefused) {
      return `<div class="mode mode--notice" role="status"><div class="inline">Mock mode is switched off on this server. Showing live data.</div></div>`;
    }
    if (d.mode !== "mock") return "";
    const options = d.scenarios.map(s => `<option value="${SC.esc(s)}"${s === d.scenario ? " selected" : ""}>${SC.esc(s)}</option>`).join("");
    return `<div class="mode" role="status"><div class="inline"><span>SIMULATED DATA. Nothing is sent to the server.</span>
      <label class="inline" style="margin:0">Scenario <select id="scenario">${options}</select></label></div></div>`;
  };
  SC.bindMode = () => {
    const s = document.getElementById("scenario");
    if (s) s.onchange = () => { const u = new URL(location.href); u.searchParams.set("mock", s.value); location.href = u.toString(); };
  };

  /** Renders the app frame. nav: [{label, href, id, count, external}] */
  SC.shell = ({ active, nav, me }) => {
    const items = nav.map(n => `<a href="${SC.esc(n.href)}"${n.id === active ? ' aria-current="page"' : ""}${n.external ? ' target="_blank" rel="noopener"' : ""}>
      <span>${SC.esc(n.label)}${n.external ? ' <span aria-hidden="true">↗</span><span class="sr"> (opens in a new tab)</span>' : ""}</span>
      ${n.count ? `<span class="count">${+n.count}<span class="sr"> waiting</span></span>` : ""}</a>`).join("");
    const chip = SC.data.mode === "live" && SC.data.devServer ? ' <span class="tag tag--real">LIVE</span>' : "";
    document.getElementById("app").innerHTML = `${SC.modeBanner()}
      <a class="skip" href="#content">Skip to content</a>
      <div class="shell"><aside class="side"><div class="brand">SMART Material Value Engine${chip}<small>Europress compactors</small></div>
        <nav class="nav" aria-label="Main">${items}</nav>
        <div class="who"><div><strong>${SC.esc(me.tenant || "Platform administrator")}</strong>${SC.esc(me.email)}</div>
          <button id="signout">Sign out</button></div></aside>
        <main class="content" id="content" tabindex="-1"></main></div>`;
    SC.bindMode();
    document.getElementById("signout").onclick = async e => {
      if (await SC.busy(e.target, () => SC.data.logout())) location.href = SC.link("/portal");
    };
    return document.getElementById("content");
  };
  SC.head = (title, sub = "", right = "") => `<div class="page-head"><div><h1>${SC.esc(title)}</h1>${sub ? `<p>${SC.esc(sub)}</p>` : ""}</div>${right}</div>`;
})(window.SC);
