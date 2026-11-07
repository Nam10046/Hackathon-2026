// Real-browser checks. Run against a server, see docs/FRONTEND_HANDOFF_NAM.md.
//   mock:  BASE=http://localhost:8000 CHROME_PATH=<chrome> node browser.mjs mock
//   live:  plus CUSTOMER_EMAIL, CUSTOMER_PASSWORD, ADMIN_EMAIL, ADMIN_PASSWORD, OTHER_DEVICE:  node browser.mjs live
import fs from "node:fs";
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE || "http://localhost:8000";
const SHOTS = process.env.SHOTS || "";
const axe = fs.readFileSync(new URL("node_modules/axe-core/axe.min.js", import.meta.url), "utf8");
const fixtures = JSON.parse(fs.readFileSync(new URL("../../backend/app/static/dev/fixtures.json", import.meta.url)));
const DESKTOP = { width: 1280, height: 800 }, MOBILE = { width: 390, height: 844 };
const wait = ms => new Promise(r => setTimeout(r, ms));
const out = [];
const check = (name, ok, detail = "") => { out.push(!!ok); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "   [" + detail + "]"}`); };
const text = p => p.evaluate(() => document.body.innerText);

async function page(browser, viewport = DESKTOP) {
  const ctx = await browser.createBrowserContext();
  const p = await ctx.newPage();
  await p.setViewport(viewport);
  p.apiCalls = [];
  p.errors = [];
  p.on("request", r => { if (new URL(r.url()).pathname.startsWith("/api/")) p.apiCalls.push(r.method() + " " + new URL(r.url()).pathname); });
  p.on("pageerror", e => p.errors.push(e.message));
  return p;
}
async function layout(p, name, viewport) {
  await p.setViewport(viewport);
  await wait(250);
  await p.evaluate(axe);
  const v = await p.evaluate(async () => (await axe.run(document, { runOnly: ["wcag2a", "wcag2aa", "best-practice"], rules: { "color-contrast": { enabled: true } } })).violations
    .map(x => `${x.impact}:${x.id}[${x.nodes[0].target}]`));
  const wide = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  check(`${name} ${viewport.width}px: no page overflow`, !wide);
  check(`${name} ${viewport.width}px: axe clean`, !v.length, v.join(" "));
  if (SHOTS) await p.screenshot({ path: `${SHOTS}/${name}_${viewport.width}.png`, fullPage: true });
}

const EXPECT = {
  "signed-out": { portal: "Sign in", cockpit: "Please sign in" },
  "device-connected": { portal: "Mock cardboard press", cockpit: "Decision cockpit" },
  "device-offline": { portal: "Offline", cockpit: "Decision cockpit" },
  "missing-measurements": { portal: "No data yet", cockpit: "Decision cockpit" },
  "no-devices": { portal: "No compactors yet", cockpit: "Decision cockpit" },
  admin: { portal: "new.user@example.com", cockpit: "Dispute invoice" },
  "cockpit-pending": { portal: "Approvals", cockpit: "Dispute invoice" },
  "cockpit-decided": { portal: "Approvals", cockpit: "Need a decision" },
  "cockpit-no-analysis": { portal: "Approvals", cockpit: "No proposals yet" },
  "api-error": { portal: "The server had a problem", cockpit: "The server had a problem" },
  "network-error": { portal: "Cannot reach the server", cockpit: "Cannot reach the server" },
  forbidden: { portal: "Mock cardboard press", cockpit: "You do not have access" },
  loading: { portal: "", cockpit: "" },
};

async function mock(browser) {
  check("every scenario has a browser expectation", Object.keys(fixtures.scenarios).every(s => s in EXPECT));
  for (const scenario of Object.keys(fixtures.scenarios)) {
    for (const path of ["portal", "cockpit"]) {
      const p = await page(browser);
      await p.goto(`${BASE}/${path}?mock=${scenario}`, { waitUntil: "domcontentloaded" });
      await wait(700);
      const t = await text(p);
      check(`${scenario}/${path}: SIMULATED DATA banner`, scenario === "loading" || t.includes("SIMULATED DATA"), t.slice(0, 80));
      if (EXPECT[scenario][path]) check(`${scenario}/${path}: shows "${EXPECT[scenario][path]}"`, t.includes(EXPECT[scenario][path]), t.slice(0, 200));
      check(`${scenario}/${path}: no call reached /api`, p.apiCalls.length === 0, p.apiCalls.join(","));
      check(`${scenario}/${path}: no script errors`, p.errors.length === 0, p.errors.join(";"));
      if (scenario !== "loading") { await layout(p, `${scenario}_${path}`, DESKTOP); await layout(p, `${scenario}_${path}`, MOBILE); }
      await p.browserContext().close();
    }
  }
  let p = await page(browser);
  await p.goto(`${BASE}/portal?mock=signed-out`, { waitUntil: "networkidle2" });
  await p.click("#login button");
  await wait(100);
  check("empty sign-in shows a reason per field", (await text(p)).includes("Enter your e-mail address"));
  check("focus moves to the first wrong field", await p.evaluate(() => document.activeElement.id === "le"));
  await p.type("#le", "someone.pending@example.com"); await p.type("#lp", "any"); await p.click("#login button"); await wait(200);
  check("waiting account sees the approval steps", (await text(p)).includes("being reviewed"));
  await p.click("#t-register"); await p.type("#rc", "Co"); await p.type("#re", "a@b.co"); await p.type("#rp", "short"); await p.click("#reg button"); await wait(100);
  check("short password is explained", (await text(p)).includes("at least 12 characters"));
  await p.browserContext().close();

  p = await page(browser);
  await p.goto(`${BASE}/portal?mock=admin`, { waitUntil: "networkidle2" });
  await wait(400);
  await p.keyboard.press("Tab");
  const first = await p.evaluate(() => document.activeElement.textContent);
  await p.keyboard.press("Tab");
  check("keyboard reaches the skip link or scenario control first", /Skip|signed-out/.test(first) || (await p.evaluate(() => document.activeElement.className)) === "skip", first);
  await p.click("button.approve"); await wait(150);
  check("approve asks first", await p.$("dialog[open]"));
  await p.keyboard.press("Escape"); await wait(150);
  check("Esc cancels, nothing changes", !(await p.$("dialog[open]")) && (await text(p)).includes("new.user@example.com"));
  await p.click("button.approve"); await wait(150);
  await p.click('dialog button[value="yes"]'); await wait(500);
  const after = await text(p);
  check("mock approval says it was only simulated", after.includes("simulated, nothing was saved"), after.slice(0, 200));
  check("mock approval sent nothing", p.apiCalls.length === 0);
  await p.goto(`${BASE}/portal?mock=admin#customers`); await wait(500); await p.reload(); await wait(600);
  check("customers page loads", (await text(p)).includes("Mock Suspended Oy"));
  await p.click(".toggle"); await wait(150);
  check("suspend asks first", (await text(p)).includes("Suspend Mock Customer Oy?"));
  await p.keyboard.press("Escape"); await wait(100);
  await layout(p, "admin_customers", DESKTOP); await layout(p, "admin_customers", MOBILE);
  await p.goto(`${BASE}/portal?mock=admin#devices`); await p.reload(); await wait(600);
  await p.click("#dev button"); await wait(100);
  check("device form explains missing fields", (await text(p)).includes("Use 1 to 32 letters"));
  await layout(p, "admin_devices", DESKTOP); await layout(p, "admin_devices", MOBILE);
  const nav = await p.$$eval(".nav a", a => a.map(x => x.getAttribute("href")));
  check("links keep the scenario", nav.every(h => h.includes("mock=admin")), nav.join(" "));
  await p.browserContext().close();

  p = await page(browser);
  await p.goto(`${BASE}/cockpit?mock=cockpit-pending`, { waitUntil: "networkidle2" });
  await wait(500);
  await p.click(".show-ev"); await wait(300);
  check("evidence opens with history", (await text(p)).includes("Decision history"));
  await p.type(".note", "mock note");
  await p.click('[data-decision="REJECT"]'); await wait(150);
  check("decision names the account in the dialog", (await text(p)).includes("mock.admin@example.com"));
  await p.click('dialog button[value="yes"]'); await wait(600);
  const t = await text(p);
  check("mock decision is labelled simulated", t.includes("simulated, nothing was saved"), t.slice(0, 200));
  await p.click('[data-filter="REJECTED"]'); await wait(150);
  check("decision moves to rejected, with the account", (await text(p)).includes("REJECT by mock.admin@example.com"));
  check("mock decision sent nothing", p.apiCalls.length === 0, p.apiCalls.join(","));
  await p.browserContext().close();
}

async function signIn(p, email, password) {
  await p.goto(`${BASE}/portal`, { waitUntil: "networkidle2" });
  await p.type("#le", email); await p.type("#lp", password);
  await p.click("#login button");
  await wait(1800);
}
async function live(browser) {
  const { CUSTOMER_EMAIL, CUSTOMER_PASSWORD, ADMIN_EMAIL, ADMIN_PASSWORD, OTHER_DEVICE } = process.env;
  let p = await page(browser);
  await p.goto(`${BASE}/portal?mock=admin`, { waitUntil: "networkidle2" });
  await wait(400);
  let t = await text(p);
  check("?mock on a mock-off server is refused and shown", t.includes("Mock mode is switched off") && !t.includes("SIMULATED DATA"), t.slice(0, 160));
  check("?mock on a mock-off server shows no fixture", !t.includes("new.user@example.com"));
  check("/dev files are not served", (await p.evaluate(async () => [(await fetch("/dev/mock.js")).status, (await fetch("/dev/fixtures.json")).status])).every(s => s === 404));
  await p.browserContext().close();

  p = await page(browser);
  await signIn(p, CUSTOMER_EMAIL, CUSTOMER_PASSWORD);
  t = await text(p);
  check("live customer sees the overview", t.includes("Overview") && t.includes("Account active"), t.slice(0, 200));
  check("live customer sees no other customer's device", !t.includes(OTHER_DEVICE));
  check("live customer has no admin navigation", !t.includes("Approvals") && !t.includes("Decision cockpit"));
  check("live data is still labelled simulated", t.includes("No physical load cell"));
  check("live page has no mock banner", !t.includes("SIMULATED DATA"));
  await layout(p, "live_customer", DESKTOP); await layout(p, "live_customer", MOBILE);
  await p.goto(`${BASE}/cockpit`, { waitUntil: "networkidle2" }); await wait(800);
  t = await text(p);
  check("live customer is refused in the cockpit", t.includes("You do not have access") && !t.includes("Need a decision"), t.slice(0, 200));

  await p.goto(`${BASE}/portal`, { waitUntil: "networkidle2" });
  await p.setRequestInterception(true);
  let mode = "abort";
  const intercept = r => {
    if (!r.url().includes("/api/compactors")) return r.continue();
    return mode === "abort" ? r.abort() : r.respond({ status: 500, contentType: "application/json", body: "{}" });
  };
  p.on("request", intercept);
  await p.reload({ waitUntil: "domcontentloaded" }); await wait(900);
  t = await text(p);
  check("live network failure shows an error, no data", t.includes("Cannot reach the server") && !t.includes(" kg") && !t.includes("Mock"), t.slice(0, 200));
  mode = "500";
  await p.click("#retry"); await wait(700);
  t = await text(p);
  check("live 500 shows an error, no data", t.includes("The server had a problem") && !t.includes(" kg") && !t.includes("Mock"), t.slice(0, 200));
  p.off("request", intercept);
  await p.setRequestInterception(false);
  await p.reload({ waitUntil: "networkidle2" }); await wait(800);
  await p.click("#signout"); await wait(900);
  check("sign out returns to sign in", (await text(p)).includes("Request access"));
  await p.goto(`${BASE}/portal`, { waitUntil: "networkidle2" }); await wait(500);
  check("session is really gone", (await text(p)).includes("Request access"));
  await p.browserContext().close();

  p = await page(browser);
  await signIn(p, ADMIN_EMAIL, ADMIN_PASSWORD);
  t = await text(p);
  check("live admin sees approvals", t.includes("Approvals") && t.includes("Decision cockpit"), t.slice(0, 200));
  await layout(p, "live_admin", DESKTOP);
  await p.goto(`${BASE}/portal#customers`); await p.reload({ waitUntil: "networkidle2" }); await wait(800);
  t = await text(p);
  check("live admin sees every customer", t.includes("Demo Customer 1") && t.includes("Demo Customer 2"), t.slice(0, 200));
  await layout(p, "live_admin_customers", DESKTOP); await layout(p, "live_admin_customers", MOBILE);
  await p.goto(`${BASE}/portal#devices`); await p.reload({ waitUntil: "networkidle2" }); await wait(800);
  check("live admin sees devices without an owner", (await text(p)).includes("No owner"));
  await p.goto(`${BASE}/cockpit`, { waitUntil: "networkidle2" }); await wait(900);
  t = await text(p);
  check("live cockpit loads for admin", t.includes("Decision cockpit") && t.includes("No proposals yet"), t.slice(0, 200));
  await layout(p, "live_cockpit", DESKTOP);
  check("no script errors in live", p.errors.length === 0, p.errors.join(";"));
  await p.browserContext().close();
}

const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH, headless: "shell", args: ["--no-sandbox"] });
try {
  await ({ mock, live }[process.argv[2] || "mock"])(browser);
} finally {
  await browser.close();
}
const failed = out.filter(x => !x).length;
console.log(`\n${out.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
