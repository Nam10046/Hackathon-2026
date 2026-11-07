/* Portal screens. All data goes through SC.data, so the same code runs on the live API and on mock fixtures.
   Hiding something here is only for clarity: the backend decides what each account may do. */
(function (SC) {
  const { esc, tag, badge } = SC;
  const app = () => document.getElementById("app");
  const route = () => location.hash.slice(1);

  function deviceState(d) {
    const map = { connected: ["ok", "Connected"], offline: ["bad", "Offline"], "no-data": ["none", "No data yet"] };
    const [k, text] = map[d.state];
    return `<span class="inline"><span class="dot dot--${k}" aria-hidden="true"></span>${text}</span>`;
  }
  function meter(pct) {
    if (pct === null || pct === undefined) return "–";
    const level = pct >= 90 ? " meter--bad" : pct >= 70 ? " meter--warn" : "";
    return `<span class="inline"><span class="meter${level}" aria-hidden="true"><i style="width:${Math.min(100, +pct)}%"></i></span>${SC.num(pct, 0)}%</span>`;
  }
  const originTag = a => a.origin === "Simulated" ? tag("sim") : badge("info", a.origin);
  const sevBadge = s => badge(s === "critical" ? "bad" : s === "warning" ? "warn" : "info", s);
  const region = (label, html) => `<div class="table-wrap" tabindex="0" role="region" aria-label="${esc(label)}">${html}</div>`;

  /* ---------- signed out ---------- */
  function renderAuth(tab = "signin", notice = "") {
    app().innerHTML = `${SC.modeBanner()}<div class="auth"><header class="auth-brand">
        <h1>SMART Material Value Engine</h1>
        <p>One place to follow your compactors and the material they collect.</p>
        <ul><li>Weight and fill level per compactor</li><li>Estimated material value and CO₂</li><li>Alerts and pickup history</li></ul>
      </header><main class="auth-form" id="content"><div>
        <div class="seg" role="group" aria-label="Account">
          <button id="t-signin" aria-pressed="${tab === "signin"}">Sign in</button>
          <button id="t-register" aria-pressed="${tab === "register"}">Request access</button></div>
        <div id="auth-notice">${notice}</div><div id="auth-body"></div></div></main></div>`;
    SC.bindMode();
    document.getElementById("t-signin").onclick = () => renderAuth("signin");
    document.getElementById("t-register").onclick = () => renderAuth("register");
    tab === "signin" ? signInForm() : registerForm();
  }

  function signInForm() {
    const box = document.getElementById("auth-body");
    box.innerHTML = `<h2 style="margin-bottom:12px">Sign in</h2><form id="login" novalidate>
      <div class="field"><label for="le">E-mail</label><input id="le" type="email" autocomplete="username" required data-message="Enter your e-mail address"></div>
      <div class="field"><label for="lp">Password</label><input id="lp" type="password" autocomplete="current-password" required data-message="Enter your password"></div>
      <button class="primary">Sign in</button></form>
      <p class="hint" style="margin-top:12px">Forgot your password? Ask your administrator. Reset by e-mail is not available yet.</p>`;
    document.getElementById("login").onsubmit = async e => {
      e.preventDefault();
      if (!SC.validate(e.target)) return;
      const notice = document.getElementById("auth-notice");
      notice.innerHTML = "";
      const button = e.target.querySelector("button");
      button.disabled = true;
      try {
        const r = await SC.data.login({ email: le.value, password: lp.value });
        try { sessionStorage.setItem("grafana_ready", r.grafana_ready); } catch { /* private window */ }
        await start();
      } catch (err) {
        const pending = err.kind === "forbidden" && /waiting/i.test(err.message);
        notice.innerHTML = pending ? pendingNotice() : `<div class="notice notice--bad" role="alert" style="margin-bottom:12px">${esc(
          err.kind === "network" ? "Cannot reach the server. Check your connection and try again." : err.message)}</div>`;
        button.disabled = false;
      }
    };
  }
  const pendingNotice = () => `<div class="notice" role="status" style="margin-bottom:12px"><div><strong>Your request is being reviewed</strong>
    <ol class="steps"><li>✓ Request received</li><li>… An administrator connects you to your company and devices</li><li>Then you can sign in here</li></ol></div></div>`;

  function registerForm() {
    const box = document.getElementById("auth-body");
    box.innerHTML = `<h2 style="margin-bottom:12px">Request access</h2><form id="reg" novalidate>
      <div class="field"><label for="rc">Company</label><input id="rc" minlength="2" maxlength="120" required data-message="Enter your company name"></div>
      <div class="field"><label for="re">Work e-mail</label><input id="re" type="email" autocomplete="username" required data-message="Enter a valid e-mail address"></div>
      <div class="field"><label for="rp">Password</label><input id="rp" type="password" minlength="12" maxlength="128" autocomplete="new-password" required
        data-hint="rp-hint" aria-describedby="rp-hint" data-message="Use at least 12 characters"><p class="hint" id="rp-hint">At least 12 characters.</p></div>
      <button class="primary">Send request</button></form>
      <p class="hint" style="margin-top:12px">Sending a request gives no access. An administrator checks it and connects your devices.</p>`;
    document.getElementById("reg").onsubmit = async e => {
      e.preventDefault();
      if (!SC.validate(e.target)) return;
      const ok = await SC.busy(e.target.querySelector("button"), () =>
        SC.data.register({ company: rc.value, email: re.value, password: rp.value }));
      if (ok) renderAuth("signin", pendingNotice());
    };
  }

  /* ---------- customer ---------- */
  async function customerOverview(root, me) {
    root.innerHTML = SC.head("Overview", me.tenant) + SC.skeleton();
    try {
      const [devices, alerts, pickups] = await Promise.all([SC.data.compactors(), SC.data.alerts(6), SC.data.pickups(50)]);
      const sum = k => { const v = devices.map(d => d[k]).filter(x => x !== null && x !== undefined); return v.length ? v.reduce((a, b) => a + b, 0) : null; };
      const hours = devices.map(d => d.hours_to_full).filter(h => h !== null && h !== undefined);
      const open = pickups.filter(p => p.status === "booked" || p.status === "scheduled");
      const connected = devices.filter(d => d.state === "connected").length;
      const ready = (() => { try { return sessionStorage.getItem("grafana_ready"); } catch { return null; } })();
      if (!devices.length) {
        root.innerHTML = SC.head("Overview", me.tenant) + `<div class="card">${SC.state({ title: "No compactors yet",
          body: "Your account is active, but no device is connected to it. Your administrator hands devices to your company." })}</div>`;
        return;
      }
      root.innerHTML = SC.head("Overview", me.tenant, `<div>${badge("ok", "Account active")}</div>`) + `<div class="stack">
        <div class="notice notice--sim">${tag("sim")}<span>${esc(SC.SOURCE.weight)}</span></div>
        ${ready === "false" ? `<div class="notice notice--bad" role="status">Your dashboards are not ready yet. Sign in again in a moment, or contact your administrator.</div>` : ""}
        <div class="kpis">
          <div class="kpi"><div class="label">Connected</div><div class="value">${connected} of ${devices.length}</div></div>
          <div class="kpi"><div class="label">Weight now ${tag("sim")}</div><div class="value">${SC.kg(sum("weight_kg"))}</div></div>
          <div class="kpi"><div class="label">Material value ${tag("est")}</div><div class="value">${SC.eur(sum("value_eur"))}</div></div>
          <div class="kpi"><div class="label">Next full in ${tag("est")}</div><div class="value">${hours.length ? SC.num(Math.min(...hours), 1) + " h" : "–"}</div></div>
          <div class="kpi"><div class="label">Open pickups ${tag("sim")}</div><div class="value">${open.length}</div></div>
        </div>
        <section class="card"><h2>Compactors</h2>${region("Compactors", `<table><thead><tr><th>Compactor</th><th>Status</th><th>Fill</th><th class="r">Weight</th><th class="r">Value</th><th class="r">Full in</th><th>Last reading</th></tr></thead><tbody>
          ${devices.map(d => `<tr><td><strong>${esc(d.name)}</strong><br><span class="small muted">${esc(d.compactor_id)} · ${esc(d.material)}</span></td>
            <td>${deviceState(d)}</td><td>${meter(d.load_pct)}</td><td class="r num">${SC.kg(d.weight_kg)}</td><td class="r num">${SC.eur(d.value_eur)}</td>
            <td class="r num">${d.hours_to_full === null || d.hours_to_full === undefined ? "–" : SC.num(d.hours_to_full, 1) + " h"}</td><td class="small">${SC.date(d.last_ts)}</td></tr>`).join("")}
          </tbody></table>`)}</section>
        <section class="card"><h2>Latest alerts</h2>${alerts.length ? region("Latest alerts", `<table><thead><tr><th>Time</th><th>Compactor</th><th>Severity</th><th>Origin</th><th>What happened</th></tr></thead><tbody>
          ${alerts.map(a => `<tr><td class="small">${SC.date(a.ts)}</td><td>${esc(a.compactor_id)}</td><td>${sevBadge(a.severity)}</td><td>${originTag(a)}</td><td>${esc(a.message)}</td></tr>`).join("")}
          </tbody></table>`) : SC.state({ title: "No alerts", body: "Nothing needs your attention." })}</section>
        ${SC.legend()}</div>`;
    } catch (err) {
      showError(root, "Overview", err, () => customerOverview(root, me));
    }
  }
  function showError(root, title, err, retry) {
    root.innerHTML = SC.head(title) + SC.errorState(err);
    const b = document.getElementById("retry");
    if (b) b.onclick = retry;
  }

  /* ---------- admin ---------- */
  async function approvals(root, status = "pending") {
    root.innerHTML = SC.head("Approvals", "New accounts stay locked until you connect them to a customer.") + SC.skeleton(0, 6);
    try {
      const [rows, tenants, devices] = await Promise.all([SC.data.registrations(status), SC.data.tenants(), SC.data.adminDevices()]);
      const free = devices.filter(d => d.tenant_id === null);
      const seg = `<div class="seg" role="group" aria-label="Filter requests">${["pending", "rejected"].map(s =>
        `<button data-status="${s}" aria-pressed="${s === status}">${s === "pending" ? "Waiting" : "Rejected"}</button>`).join("")}</div>`;
      root.innerHTML = SC.head("Approvals", "New accounts stay locked until you connect them to a customer.", seg) + (rows.length ? `<div class="stack">${rows.map(u => status === "pending" ? `
        <form class="card" data-id="${+u.id}" novalidate><div class="row"><div><h2 style="margin:0">${esc(u.email)}</h2>
          <p class="small muted">Says they are from <strong>${esc(u.company_requested)}</strong>. This is not verified. ${SC.date(u.created_at)}</p></div>${badge("warn", "Waiting")}</div>
          <div class="grid2" style="margin-top:12px"><div class="field"><label for="t${+u.id}">Customer</label><select id="t${+u.id}" class="tenant"><option value="">New customer</option>
            ${tenants.map(t => `<option value="${+t.id}">${esc(t.name)}</option>`).join("")}</select></div>
          <div class="field newname"><label for="n${+u.id}">New customer name</label><input id="n${+u.id}" minlength="2" maxlength="120" required value="${esc(u.company_requested)}" data-message="Enter the customer's name"></div></div>
          <fieldset><legend>Devices to hand over</legend>${free.length ? free.map(d => `<label class="check"><input type="checkbox" value="${esc(d.id)}">${esc(d.id)} · ${esc(d.name)}</label>`).join("")
            : `<p class="hint">No free devices. Add one under Devices.</p>`}</fieldset>
          <div class="inline"><button class="approve" type="submit">Approve</button><button class="danger reject" type="button">Reject</button></div></form>` : `
        <div class="card"><div class="row"><div><strong>${esc(u.email)}</strong><p class="small muted">${esc(u.company_requested)} · ${SC.date(u.created_at)}</p></div>${badge("bad", "Rejected")}</div></div>`).join("")}</div>`
        : `<div class="card">${SC.state({ title: status === "pending" ? "Nobody is waiting" : "No rejected requests", body: status === "pending" ? "New requests appear here." : "" })}</div>`);
      root.querySelectorAll("[data-status]").forEach(b => { b.onclick = () => approvals(root, b.dataset.status); });
      root.querySelectorAll("form[data-id]").forEach(form => {
        const id = +form.dataset.id, select = form.querySelector(".tenant"), box = form.querySelector(".newname"), name = box.querySelector("input");
        select.onchange = () => { box.hidden = !!select.value; name.disabled = !!select.value; };
        form.onsubmit = async e => {
          e.preventDefault();
          if (!SC.validate(form)) return;
          const ids = [...form.querySelectorAll("input[type=checkbox]:checked")].map(c => c.value);
          const target = select.value ? select.selectedOptions[0].textContent : name.value;
          const yes = await SC.confirm({ title: "Approve this account?", yes: "Approve",
            body: `It joins ${target}${ids.length ? ` and receives ${ids.join(", ")}` : " with no devices"}. It can then see that customer's data.` });
          if (!yes) return;
          const body = { device_ids: ids, ...(select.value ? { tenant_id: +select.value } : { new_tenant_name: name.value }) };
          if (await SC.busy(form.querySelector(".approve"), () => SC.data.approve(id, body))) { SC.toast(SC.data.done("Approved")); refresh(); }
        };
        form.querySelector(".reject").onclick = async e => {
          if (await SC.confirm({ title: "Reject this request?", body: "This account will never be able to sign in.", yes: "Reject", danger: true })
              && await SC.busy(e.target, () => SC.data.reject(id))) { SC.toast(SC.data.done("Rejected")); refresh(); }
        };
      });
    } catch (err) { showError(root, "Approvals", err, () => approvals(root, status)); }
  }

  async function customers(root) {
    root.innerHTML = SC.head("Customers") + SC.skeleton(0, 6);
    try {
      const [tenants, devices] = await Promise.all([SC.data.tenants(), SC.data.adminDevices()]);
      const free = devices.filter(d => d.tenant_id === null);
      root.innerHTML = SC.head("Customers", "Each customer sees only the devices listed here.") + (tenants.length ? `<div class="stack">${tenants.map(t => `
        <section class="card" data-id="${+t.id}"><div class="row"><div><h2 style="margin:0">${esc(t.name)}</h2><p class="small muted">${+t.users} user(s)</p></div>
          <div class="inline">${badge(t.status === "active" ? "ok" : "bad", t.status === "active" ? "Active" : "Suspended")}
          <button class="${t.status === "active" ? "danger" : ""} toggle">${t.status === "active" ? "Suspend" : "Reactivate"}</button></div></div>
          <h3 style="margin-top:12px">Devices</h3>${t.devices.length ? `<div class="inline">${t.devices.map(d => `<span class="badge badge--info">${esc(d)}
            <button class="link-btn remove" data-device="${esc(d)}" aria-label="Take back ${esc(d)}">Take back</button></span>`).join("")}</div>` : `<p class="hint">No devices yet.</p>`}
          ${free.length ? `<div class="inline" style="margin-top:12px;align-items:flex-end"><div style="flex:1 1 200px"><label for="a${+t.id}">Hand over a free device</label><select id="a${+t.id}" class="pick">
            ${free.map(d => `<option value="${esc(d.id)}">${esc(d.id)} · ${esc(d.name)}</option>`).join("")}</select></div><button class="add">Hand over</button></div>` : ""}</section>`).join("")}</div>`
        : `<div class="card">${SC.state({ title: "No customers yet", body: "Approve a request to create the first customer." })}</div>`);
      root.querySelectorAll("section[data-id]").forEach(box => {
        const id = +box.dataset.id, name = box.querySelector("h2").textContent, toggle = box.querySelector(".toggle"), add = box.querySelector(".add");
        toggle.onclick = async () => {
          const suspend = toggle.textContent === "Suspend";
          const yes = await SC.confirm({ title: `${suspend ? "Suspend" : "Reactivate"} ${name}?`, danger: suspend, yes: suspend ? "Suspend" : "Reactivate",
            body: suspend ? "Its users are signed out and cannot see any data until you reactivate it." : "Its users can sign in and see their data again." });
          if (yes && await SC.busy(toggle, () => SC.data.tenantStatus(id, suspend ? "suspended" : "active"))) { SC.toast(SC.data.done(suspend ? "Suspended" : "Reactivated")); customers(root); }
        };
        box.querySelectorAll(".remove").forEach(b => { b.onclick = async () => {
          const cid = b.dataset.device;
          if (await SC.confirm({ title: `Take back ${cid}?`, body: `${name} will no longer see this device.`, yes: "Take back", danger: true })
              && await SC.busy(b, () => SC.data.unassign(id, cid))) { SC.toast(SC.data.done("Device taken back")); customers(root); }
        }; });
        if (add) add.onclick = async () => {
          const cid = box.querySelector(".pick").value;
          if (await SC.confirm({ title: `Hand ${cid} to ${name}?`, body: "This customer will see all of this device's data, including its history.", yes: "Hand over" })
              && await SC.busy(add, () => SC.data.assign(id, cid))) { SC.toast(SC.data.done("Device handed over")); customers(root); }
        };
      });
    } catch (err) { showError(root, "Customers", err, () => customers(root)); }
  }

  async function devicesPage(root) {
    root.innerHTML = SC.head("Devices") + SC.skeleton(0, 6);
    try {
      const devices = await SC.data.adminDevices();
      root.innerHTML = SC.head("Devices", "Every compactor and who owns it.") + `<div class="stack"><section class="card">${devices.length ? region("Devices", `<table><thead><tr><th>Device</th><th>Name</th><th>Material</th><th>Owner</th></tr></thead><tbody>
        ${devices.map(d => `<tr><td><strong>${esc(d.id)}</strong></td><td>${esc(d.name)}</td><td>${esc(d.material)}</td><td>${d.tenant ? esc(d.tenant) : badge("warn", "No owner")}</td></tr>`).join("")}</tbody></table>`)
        : SC.state({ title: "No devices", body: "Add the first one below." })}</section>
        <form class="card" id="dev" novalidate><h2>Add a device</h2><div class="grid2">
          <div class="field"><label for="di">Device id</label><input id="di" required pattern="[A-Za-z0-9_\\-]{1,32}" data-hint="di-hint" aria-describedby="di-hint" data-message="Use 1 to 32 letters, numbers, - or _"><p class="hint" id="di-hint">Also used in the MQTT topic.</p></div>
          <div class="field"><label for="dn">Name</label><input id="dn" required maxlength="120" data-message="Enter a name"></div>
          <div class="field"><label for="dm">Material</label><select id="dm"><option>cardboard</option><option>plastic</option><option>mixed</option></select></div>
          <div class="field"><label for="dc">Capacity (kg)</label><input id="dc" type="number" min="1" value="2000" required data-message="Enter a capacity above 0"></div>
          <div class="field"><label for="dv">Volume (m³)</label><input id="dv" type="number" min="1" value="8" required data-message="Enter a volume above 0"></div></div>
          <button class="primary">Add device</button></form></div>`;
      document.getElementById("dev").onsubmit = async e => {
        e.preventDefault();
        if (!SC.validate(e.target)) return;
        const body = { id: di.value, name: dn.value, material: dm.value, capacity_kg: +dc.value, volume_m3: +dv.value };
        if (await SC.busy(e.target.querySelector("button"), () => SC.data.createDevice(body))) { SC.toast(SC.data.done("Device added")); devicesPage(root); }
      };
    } catch (err) { showError(root, "Devices", err, () => devicesPage(root)); }
  }

  /* ---------- start ---------- */
  let me = null, root = null;
  function refresh() { show(); }
  async function show() {
    const page = me.role === "admin" ? (["customers", "devices"].includes(route()) ? route() : "approvals") : "overview";
    let waiting = 0;
    if (me.role === "admin") { try { waiting = (await SC.data.registrations("pending")).length; } catch { /* the page shows the error */ } }
    const grafana = SC.data.mode === "mock" ? [] : [{ label: "Dashboards", href: me.grafana_url, id: "grafana", external: true }];
    const nav = me.role === "admin"
      ? [{ label: "Approvals", href: SC.link("/portal#approvals"), id: "approvals", count: waiting }, { label: "Customers", href: SC.link("/portal#customers"), id: "customers" },
         { label: "Devices", href: SC.link("/portal#devices"), id: "devices" }, { label: "Decision cockpit", href: SC.link("/cockpit"), id: "cockpit" }, ...grafana]
      : [{ label: "Overview", href: SC.link("/portal"), id: "overview" }, ...grafana];
    root = SC.shell({ active: page, nav, me });
    ({ overview: () => customerOverview(root, me), approvals: () => approvals(root), customers: () => customers(root), devices: () => devicesPage(root) })[page]();
  }
  async function start() {
    try {
      me = await SC.data.me();
    } catch (err) {
      me = null;
      if (err.kind === "auth") { renderAuth(); return; }
      app().innerHTML = SC.modeBanner() + `<main class="content" id="content" style="margin:0 auto">${SC.head("Portal")}${SC.errorState(err)}</main>`;
      const b = document.getElementById("retry");
      if (b) b.onclick = start;
      return;
    }
    await show();
  }
  window.addEventListener("hashchange", () => { if (me) show(); });
  SC.data.init().then(start);
})(window.SC);
