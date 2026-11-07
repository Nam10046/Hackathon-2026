/* Data adapter. UI -> SC.data -> live provider (FastAPI) or mock provider (dev only). Both return raw API shapes and go
   through the same normalize step, so screens cannot tell them apart. A failed live call throws. It never turns into mock. */
window.SC = window.SC || {};
(function (SC) {
  const OFFLINE_AFTER_MS = 2 * 3600 * 1000;       // no reading for this long = offline

  class ApiError extends Error {
    constructor(status, message) {
      super(message);
      this.status = status;
      this.kind = status === 0 ? "network" : status === 401 ? "auth" : status === 403 ? "forbidden" : status === 404 ? "notfound"
        : status >= 500 ? "server" : "invalid";
    }
  }
  SC.ApiError = ApiError;

  /** FastAPI sends detail as text, or as a list for validation errors. */
  function detailText(data) {
    const d = data && data.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d[0]?.msg) return `${d[0].loc?.slice(-1)[0] || "Field"}: ${d[0].msg}`;
    return "The request could not be completed";
  }

  const normalize = {
    device(raw, now) {
      const last = raw.last_ts ? new Date(raw.last_ts).getTime() : null;
      const state = last === null ? "no-data" : now - last > OFFLINE_AFTER_MS ? "offline" : "connected";
      return { ...raw, state, measured: raw.weight_kg !== null && raw.weight_kg !== undefined };
    },
    alert(raw) {
      const simulated = String(raw.message).startsWith("Simulated demo:");
      const origin = simulated ? "Simulated" : String(raw.type).startsWith("ml_") ? "AI model" : "Rule";
      return { ...raw, origin };
    },
    action(raw) {
      const label = String(raw.action || "").replaceAll("_", " ").toLowerCase();
      return { ...raw, label: label.charAt(0).toUpperCase() + label.slice(1), status: raw.status || "PENDING" };
    },
  };
  SC.normalize = normalize;

  function liveProvider(fetchImpl) {
    async function call(path, method = "GET", body) {
      let r;
      try {
        r = await fetchImpl(path, { method, credentials: "same-origin",
          headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
      } catch {
        throw new ApiError(0, "Cannot reach the server");
      }
      const data = await r.json().catch(() => null);
      if (!r.ok) throw new ApiError(r.status, detailText(data));
      return data;
    }
    const post = (path, body) => call(path, "POST", body ?? undefined);
    const id = encodeURIComponent;
    return {
      me: () => call("/api/auth/me"),
      login: b => post("/api/auth/login", b),
      register: b => post("/api/auth/register", b),
      logout: () => post("/api/auth/logout"),
      compactors: () => call("/api/compactors"),
      alerts: limit => call(`/api/alerts?limit=${+limit}`),
      pickups: limit => call(`/api/pickups?limit=${+limit}`),
      registrations: status => call(`/api/admin/registrations?status=${id(status)}`),
      approve: (uid, b) => post(`/api/admin/registrations/${+uid}/approve`, b),
      reject: uid => post(`/api/admin/registrations/${+uid}/reject`),
      tenants: () => call("/api/admin/tenants"),
      tenantStatus: (tid, status) => post(`/api/admin/tenants/${+tid}/status`, { status }),
      assign: (tid, compactor_id) => post(`/api/admin/tenants/${+tid}/devices`, { compactor_id }),
      unassign: (tid, cid) => call(`/api/admin/tenants/${+tid}/devices/${id(cid)}`, "DELETE"),
      adminDevices: () => call("/api/admin/devices"),
      createDevice: b => post("/api/admin/devices", b),
      actions: () => call("/api/cockpit/actions"),
      evidence: aid => call(`/api/cockpit/actions/${id(aid)}/evidence`),
      decide: (aid, b) => post(`/api/cockpit/actions/${id(aid)}/decision`, b),
    };
  }
  SC.liveProvider = liveProvider;

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = reject;
      document.head.append(s);
    });
  }

  /** Same screens, either source. Raw methods pass through; lists get normalized here. */
  function adapter(provider, now) {
    return {
      ...provider,
      compactors: async () => (await provider.compactors()).map(d => normalize.device(d, now())),
      alerts: async limit => (await provider.alerts(limit)).map(normalize.alert),
      actions: async () => (await provider.actions()).map(normalize.action),
    };
  }
  SC.adapter = adapter;

  /** Mock needs BOTH ?mock=<scenario> in the URL and FRONTEND_MOCK=true on the server, which is what serves /dev/mock.js. */
  SC.data = {
    mode: "live", scenario: null, scenarios: [], mockRefused: false, devServer: false,
    now: () => Date.now(),
    done: text => text,
    async init() {
      const wanted = new URLSearchParams(location.search).get("mock");
      let provider = liveProvider((...a) => fetch(...a));
      if (wanted !== null) {
        try {
          await loadScript("/dev/mock.js");
          const mock = await SC.createMock(wanted);
          provider = mock.provider;
          this.mode = "mock";
          this.scenario = mock.scenario;
          this.scenarios = mock.scenarios;
          this.now = () => mock.now;
          this.done = text => `${text} (simulated, nothing was saved)`;
        } catch {
          this.mockRefused = true;   // stays live, and the banner says so
        }
      } else {
        this.devServer = await fetch("/dev/mock.js", { method: "HEAD" }).then(r => r.ok).catch(() => false);
      }
      Object.assign(this, adapter(provider, () => this.now()));
    },
  };
})(window.SC);
