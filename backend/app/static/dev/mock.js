/* DEV ONLY mock provider. Served only with FRONTEND_MOCK=true. Answers from fixtures.json, in the browser: no fetch to
   the API, no database, no MQTT. Changes live in memory and vanish on reload. Scenarios: docs/FRONTEND_HANDOFF_NAM.md */
window.SC = window.SC || {};
window.SC.createMock = async function (wanted) {
  const fx = await (await fetch("/dev/fixtures.json")).json();
  const names = Object.keys(fx.scenarios);
  const scenario = names.includes(wanted) ? wanted : names[0];
  const base = fx.scenarios[scenario];
  const s = JSON.parse(JSON.stringify({ ...fx.defaults, ...base }));
  const key = "sc_mock_session_" + scenario;
  const read = k => { try { return sessionStorage.getItem(k); } catch { return null; } };
  const write = (k, v) => { try { v === null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch { /* private window */ } };
  const Err = window.SC.ApiError;

  async function answer(section, value) {
    if (s.hang) await new Promise(() => {});                                  // loading state, forever
    if (s.fail && (!s.fail.only || s.fail.only.includes(section))) throw new Err(s.fail.status, s.fail.detail);
    return JSON.parse(JSON.stringify(value));
  }
  const session = () => s.me && read(key) !== "out" ? s.me : null;
  const signedIn = v => { if (!session()) throw new Err(401, "Sign in first"); return v; };

  const provider = {
    me: () => answer("me", signedIn(s.me)),
    async login(b) {
      if (String(b.email).includes("pending")) throw new Err(403, "Your account is waiting for approval");
      if (b.password === "wrong-password") throw new Err(401, "Wrong e-mail or password, or too many tries. Wait a few minutes.");
      s.me = s.me || fx.customer_me;
      write(key, null);
      return { token: "mock", role: s.me.role, grafana_ready: true, expires_at: fx.now };
    },
    register: () => answer("register", { status: "pending", message: "Thanks. An administrator will check your request before you can sign in." }),
    logout() { write(key, "out"); return answer("logout", { status: "signed out" }); },
    compactors: () => answer("compactors", s.compactors),
    alerts: () => answer("alerts", s.alerts),
    pickups: () => answer("pickups", s.pickups),
    registrations: status => answer("registrations", s.registrations.filter(r => r.status === status)),
    approve(id) { s.registrations = s.registrations.filter(r => r.id !== id); return answer("approve", { user_id: id, status: "active" }); },
    reject(id) { const r = s.registrations.find(x => x.id === id); if (r) r.status = "rejected"; return answer("reject", { user_id: id, status: "rejected" }); },
    tenants: () => answer("tenants", s.tenants),
    tenantStatus(id, status) { s.tenants.find(t => t.id === id).status = status; return answer("tenantStatus", { id, status }); },
    assign(id, cid) {
      const t = s.tenants.find(x => x.id === id), d = s.devices.find(x => x.id === cid);
      t.devices.push(cid); d.tenant_id = id; d.tenant = t.name;
      return answer("assign", { tenant_id: id, compactor_id: cid });
    },
    unassign(id, cid) {
      const t = s.tenants.find(x => x.id === id), d = s.devices.find(x => x.id === cid);
      t.devices = t.devices.filter(x => x !== cid); d.tenant_id = null; d.tenant = null;
      return answer("unassign", { tenant_id: id, compactor_id: cid, removed: true });
    },
    adminDevices: () => answer("adminDevices", s.devices),
    createDevice(b) { s.devices.push({ id: b.id, name: b.name, material: b.material, tenant_id: null, tenant: null }); return answer("createDevice", b); },
    actions: () => answer("actions", s.actions),
    evidence: id => answer("evidence", { action: s.actions.find(a => a.action_id === id), ...s.evidence }),
    decide(id, b) {
      const a = s.actions.find(x => x.action_id === id);
      a.decision = b.decision; a.decided_by = s.me.email; a.decision_note = b.note;
      a.status = b.decision === "REVERT" ? "PENDING" : b.decision === "APPROVE" ? "APPROVED" : "REJECTED";
      return answer("decide", { action_id: id, decision: b.decision, decided_by: s.me.email, status: a.status });
    },
  };
  return { provider, scenario, scenarios: names, now: new Date(fx.now).getTime() };
};
