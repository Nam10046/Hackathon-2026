/* Decision cockpit. Shows only fields the API returns. The system proposes; a signed-in admin decides (backend enforces it). */
(function (SC) {
  const { esc, tag, badge } = SC;
  let filter = "PENDING", rows = [], root = null, me = null;
  const STATUS = { PENDING: ["warn", "Pending"], APPROVED: ["ok", "Approved"], REJECTED: ["bad", "Rejected"] };
  const EVIDENCE = { OBSERVED: "Observed in records", ESTIMATED: "Estimated", HYPOTHETICAL: "Hypothetical" };
  const has = v => v !== null && v !== undefined && v !== "";
  const line = (label, v) => has(v) ? `<div><span class="muted">${esc(label)}:</span> ${esc(v)}</div>` : "";

  function impact(r) {
    if (has(r.expected_value_eur)) {
      return `<div class="impact">${SC.eur(r.expected_value_eur)}</div><div class="small muted">Expected value${has(r.ev_low_eur)
        ? `, range ${SC.eur(r.ev_low_eur)} to ${SC.eur(r.ev_high_eur)}` : ""}. Values overlap between proposals, so do not add them up.</div>`;
    }
    return `<div class="impact">${SC.eur(r.flagged_invoice_eur)}</div><div class="small muted">Sum of flagged invoice lines for this device.</div>`;
  }
  function card(r) {
    const [kind, text] = STATUS[r.status] || ["info", r.status];
    const id = esc(r.action_id);
    return `<article class="card proposal" data-id="${id}">
      <div class="proposal-head row"><div><h2 class="proposal-title">${esc(r.label)}</h2>
        <div class="small muted">${esc(r.customer_name)} · device ${esc(r.device_id)}</div></div>${badge(kind, text)}</div>
      <div class="proposal-body">
        <div><h3>What was found</h3><p>${esc(r.rationale)}</p></div>
        <div><h3>Affected</h3>${line("Customer", r.customer_name)}${line("Operator", r.operator_name)}${line("Contract", r.contract_id)}${line("Device", r.device_id)}
          ${r.notice_period_days ? line("Notice period", r.notice_period_days + " days") : ""}</div>
        <div><h3>Evidence</h3>${line("Type", EVIDENCE[r.evidence_tag] || r.evidence_tag)}${line("Data known on", r.snapshot_date)}${line("Records", r.evidence)}${line("Calculation", r.calculation)}${line("Uncertainty", r.uncertainty)}
          <button class="link-btn show-ev" aria-expanded="false" aria-controls="ev-${id}">Show source records</button></div>
        <div><h3>Estimated impact ${tag("est")}</h3>${impact(r)}</div>
      </div>
      <div class="evidence" id="ev-${id}" hidden></div>
      <div class="proposal-foot">${has(r.decided_by) ? `<p class="small" style="margin-bottom:8px">${tag("real")} ${esc(r.decision)} by ${esc(r.decided_by)}${r.decision_note ? `: ${esc(r.decision_note)}` : ""}</p>` : ""}
        <div class="decide"><div class="field"><label for="n-${id}">Note (optional)</label><input id="n-${id}" class="note" maxlength="500"></div>
        ${r.status === "PENDING" ? `<button class="approve" data-decision="APPROVE">Approve</button><button class="danger" data-decision="REJECT">Reject</button>`
          : `<button data-decision="REVERT">Revert to pending</button>`}</div></div></article>`;
  }

  function render() {
    const count = s => rows.filter(r => r.status === s).length;
    const shown = rows.filter(r => filter === "ALL" || r.status === filter);
    const seg = `<div class="seg" role="group" aria-label="Filter proposals">${[["PENDING", "Pending"], ["APPROVED", "Approved"], ["REJECTED", "Rejected"], ["ALL", "All"]].map(([k, t]) =>
      `<button data-filter="${k}" aria-pressed="${k === filter}">${t} ${k === "ALL" ? rows.length : count(k)}</button>`).join("")}</div>`;
    root.innerHTML = SC.head("Decision cockpit", "The system proposes. You decide, and every decision is logged under your account.") + `<div class="stack">
      <div class="notice notice--sim">${tag("sim")}<span>Proposals come from the synthetic Europress dataset. Differences can have several causes, so treat them as discrepancies to check, not accusations.</span></div>
      ${rows.length ? `<div class="kpis"><div class="kpi"><div class="label">Need a decision</div><div class="value">${count("PENDING")}</div></div>
        <div class="kpi"><div class="label">Approved</div><div class="value">${count("APPROVED")}</div></div>
        <div class="kpi"><div class="label">Rejected</div><div class="value">${count("REJECTED")}</div></div></div>
        <div>${seg}</div>${shown.length ? shown.map(card).join("") : `<div class="card">${SC.state({ title: "Nothing here", body: "No proposals with this status." })}</div>`}`
      : `<div class="card">${SC.state({ title: "No proposals yet", body: "Either nothing was found, or the analysis has not been built. To build it, run: docker compose run --rm analytics" })}</div>`}
      ${SC.legend()}</div>`;
    root.querySelectorAll("[data-filter]").forEach(b => { b.onclick = () => { filter = b.dataset.filter; render(); }; });
    root.querySelectorAll(".proposal").forEach(box => {
      box.querySelectorAll("[data-decision]").forEach(b => { b.onclick = () => decide(box, b); });
      box.querySelector(".show-ev").onclick = e => evidence(box, e.target);
    });
  }

  async function decide(box, button) {
    const id = box.dataset.id, decision = button.dataset.decision, note = box.querySelector(".note").value || null;
    const words = { APPROVE: "Approve", REJECT: "Reject", REVERT: "Revert" }[decision];
    const yes = await SC.confirm({ title: `${words} this proposal?`, yes: words, danger: decision === "REJECT",
      body: `This is logged under ${me.email}. You can revert it later, and the history is kept.` });
    if (yes && await SC.busy(button, () => SC.data.decide(id, { decision, note }))) { SC.toast(SC.data.done({ APPROVE: "Approved", REJECT: "Rejected", REVERT: "Back to pending" }[decision])); await load(); }
  }

  async function evidence(box, button) {
    const panel = box.querySelector(".evidence");
    if (!panel.hidden) { panel.hidden = true; button.setAttribute("aria-expanded", "false"); button.textContent = "Show source records"; return; }
    panel.hidden = false;
    panel.innerHTML = '<span class="skeleton"></span><span class="skeleton"></span>';
    button.setAttribute("aria-expanded", "true");
    button.textContent = "Hide source records";
    try {
      const d = await SC.data.evidence(box.dataset.id);
      panel.innerHTML = (d.findings.length ? `<div class="table-wrap" tabindex="0" role="region" aria-label="Source records"><table><thead><tr><th>Date</th><th>Record</th><th>Finding</th><th>Calculation</th><th>Likely cause</th><th class="r">At stake</th></tr></thead><tbody>
        ${d.findings.map(f => `<tr><td class="small">${esc(String(f.found_at || "").slice(0, 10))}</td><td class="small">${esc(f.entity_type)}<br>${esc(f.entity_id)}</td><td>${esc(f.explanation)}</td>
          <td>${esc(f.calculation || f.evidence)}</td><td>${esc(f.likely_cause || "")}</td><td class="r num">${SC.eur(f.eur_at_stake)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="hint">No source records for this device.</p>`)
        + (d.decision_history.length ? `<h3 style="margin-top:12px">Decision history ${tag("real")}</h3><p class="small">${d.decision_history.map(h =>
          `${esc(h.decision)} by ${esc(h.decided_by)} (${esc(String(h.decided_at).slice(0, 16))})`).join(" → ")}</p>` : "");
    } catch (err) {
      panel.innerHTML = `<div class="notice notice--bad" role="alert">Could not load the records: ${esc(err.message)}</div>`;
    }
  }

  async function load() {
    root.innerHTML = SC.head("Decision cockpit") + SC.skeleton(3, 7);
    try {
      rows = await SC.data.actions();
      render();
    } catch (err) {
      root.innerHTML = SC.head("Decision cockpit") + SC.errorState(err);
      const b = document.getElementById("retry");
      if (b) b.onclick = load;
    }
  }

  async function start() {
    try {
      me = await SC.data.me();
    } catch (err) {
      document.getElementById("app").innerHTML = SC.modeBanner() + `<main class="content" id="content" style="margin:0 auto">${SC.head("Decision cockpit")}${SC.errorState(err)}</main>`;
      const b = document.getElementById("retry");
      if (b) b.onclick = start;
      return;
    }
    const grafana = SC.data.mode === "mock" ? [] : [{ label: "Dashboards", href: me.grafana_url, id: "grafana", external: true }];
    const nav = me.role === "admin"
      ? [{ label: "Approvals", href: SC.link("/portal#approvals"), id: "approvals" }, { label: "Customers", href: SC.link("/portal#customers"), id: "customers" },
         { label: "Devices", href: SC.link("/portal#devices"), id: "devices" }, { label: "Decision cockpit", href: SC.link("/cockpit"), id: "cockpit" }, ...grafana]
      : [{ label: "Overview", href: SC.link("/portal"), id: "overview" }, ...grafana];
    root = SC.shell({ active: "cockpit", nav, me });
    await load();
  }
  SC.data.init().then(start);
})(window.SC);
