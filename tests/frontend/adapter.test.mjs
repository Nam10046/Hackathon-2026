// Adapter rules, no browser and no server:  node --test adapter.test.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const here = new URL("../../backend/app/static/", import.meta.url);
const fixtures = JSON.parse(fs.readFileSync(new URL("dev/fixtures.json", here)));

function load(search = "", fetchImpl = async () => { throw new Error("no fetch"); }) {
  const window = { SC: {} };
  const scripts = [];
  const document = { createElement: () => ({}), head: { append: s => { scripts.push(s.src); queueMicrotask(() => s.onerror()); } } };
  const ctx = vm.createContext({ window, document, location: { search }, fetch: fetchImpl, URLSearchParams, console });
  vm.runInContext(fs.readFileSync(new URL("assets/data.js", here), "utf8"), ctx);
  return { SC: window.SC, scripts };
}
const now = new Date(fixtures.now).getTime();

test("device state comes from the last reading", () => {
  const { SC } = load();
  const at = last_ts => SC.normalize.device({ last_ts, weight_kg: 1 }, now).state;
  assert.equal(at("2026-11-07T11:55:00+00:00"), "connected");
  assert.equal(at("2026-11-06T22:10:00+00:00"), "offline");
  assert.equal(at(null), "no-data");
});

test("missing measurements stay missing, never become zero", () => {
  const { SC } = load();
  const d = SC.normalize.device({ weight_kg: null, last_ts: null, value_eur: null }, now);
  assert.equal(d.measured, false);
  assert.equal(d.value_eur, null);
});

test("alert origin separates simulated, AI model and rule", () => {
  const { SC } = load();
  const origin = (type, message) => SC.normalize.alert({ type, message }).origin;
  assert.equal(origin("ml_delayed_collection", "Simulated demo: x"), "Simulated");
  assert.equal(origin("ml_delayed_collection", "Lift too late"), "AI model");
  assert.equal(origin("contamination", "Density"), "Rule");
});

test("HTTP failures become typed errors", async () => {
  const { SC } = load();
  for (const [status, kind] of [[401, "auth"], [403, "forbidden"], [404, "notfound"], [500, "server"], [422, "invalid"]]) {
    const p = SC.liveProvider(async () => ({ ok: false, status, json: async () => ({ detail: "nope" }) }));
    await assert.rejects(p.compactors(), e => e.kind === kind && e.status === status);
  }
});

test("FastAPI validation lists become readable text", async () => {
  const { SC } = load();
  const p = SC.liveProvider(async () => ({ ok: false, status: 422, json: async () => ({ detail: [{ loc: ["body", "password"], msg: "too short" }] }) }));
  await assert.rejects(p.register({}), e => e.message === "password: too short");
});

test("a live network failure throws and contains no data", async () => {
  const { SC } = load();
  const p = SC.adapter(SC.liveProvider(async () => { throw new TypeError("failed"); }), () => now);
  await assert.rejects(p.compactors(), e => e.kind === "network");
});

test("without ?mock the mock script is never requested", async () => {
  const { SC, scripts } = load("", async () => ({ ok: false }));
  await SC.data.init();
  assert.equal(SC.data.mode, "live");
  assert.deepEqual(scripts, []);
});

test("?mock on a server with mock off stays live and says so", async () => {
  const { SC, scripts } = load("?mock=admin");
  await SC.data.init();
  assert.equal(SC.data.mode, "live");
  assert.equal(SC.data.mockRefused, true);
  assert.deepEqual(scripts, ["/dev/mock.js"]);
});

test("all required scenarios exist", () => {
  for (const s of ["no-devices", "device-connected", "device-offline", "cockpit-no-analysis", "cockpit-pending", "cockpit-decided", "api-error", "loading", "missing-measurements"]) {
    assert.ok(s in fixtures.scenarios, s);
  }
});
