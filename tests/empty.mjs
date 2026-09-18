// The first screen after a fresh clone.
//
// Everything asserted here failed at some point against an empty ledger while
// all 31 Python suites and the full browser smoke test were green, because all
// of them run against a database that already has transactions in it.
import { chromium } from "playwright";

const BASE = process.env.SMOKE_URL || "http://127.0.0.1:8739";
const CHECKS = [];
const check = (label, ok, detail = "") => CHECKS.push([label, !!ok, detail]);

const browser = await chromium.launch();
const errors = [];
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.setDefaultTimeout(60000);
page.on("pageerror", e => errors.push(String(e.message).slice(0, 140)));
page.on("console", m => { if (m.type() === "error") errors.push(m.text().slice(0, 140)); });

try {
  await page.goto(`${BASE}/#overview`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(6000);

  // The failure that started this: init() threw and the boot line never left.
  check("a fresh install finishes loading", (await page.$("#boot")) === null,
        "still showing the boot line means init() threw");

  // Accurate zeroes tell a new user nothing. It has to say what to do.
  const alert = await page.$eval("#alert", el => el.innerText.replace(/\s+/g, " "));
  check("it says there is no data yet", /no data yet/i.test(alert), alert.slice(0, 60));
  check("...and names the folder the files go in", /data\//.test(alert), alert.slice(0, 90));
  check("...and names the command that imports them", /update\.sh/.test(alert));
  check("...and points at the setup document", /SETUP\.md/.test(alert));

  // "A tab that toggles but renders nothing" is this project's recurring
  // failure, and an empty ledger is the easiest way to cause it.
  const tabs = await page.$$eval("#tabs button", b => b.map(x => x.dataset.section));
  const subs = await page.$$eval(".subtabs button", b => b.map(x => x.closest(".subtabs").dataset.section + "/" + x.dataset.sub));
  check("every section and sub-tab is present", tabs.length === 7 && subs.length >= 31,
        `${tabs.length} sections, ${subs.length} sub-tabs`);
  const blank = [];
  for (const v of subs) {
    const [t, sub] = v.split("/");
    await page.click(`#tabs button[data-section="${t}"]`);
    await page.click(`.subtabs[data-section="${t}"] button[data-sub="${sub}"]`);
    // On a condition, not the clock: Today → Market waits on the outlook,
    // which a cold server answers in ten seconds or more, and a 400 ms
    // sleep read it as blank on 2026-09-14 while the request was in flight.
    await page.waitForFunction(([t, sub]) => {
      const el = document.querySelector(`[data-panel="${t}"] [data-sub-panel="${sub}"]`);
      return el && el.innerText.trim().length >= 15;
    }, [t, sub], { timeout: 30000 }).catch(() => {});
    const txt = await page.$eval(`[data-panel="${t}"] [data-sub-panel="${sub}"]`, e => e.innerText.trim());
    if (txt.length < 15) blank.push(`${v}(${txt.length})`);
  }
  check("no view renders an empty panel", blank.length === 0, blank.join(", "));

  // The sample year: in, every tab has something on it, out again with the
  // ledger empty as before. This is the one path a friend takes before they
  // have gathered a single export (D129).
  // The panel opens itself on an empty ledger; the header link toggles it,
  // so it is clicked only when the panel is closed.
  const openSetup = async () => {
    await page.click("#tabs button[data-section=\"money\"]");
    // The tour above left My Money on its last sub-tab; the panel lives on Overview.
    await page.click(".subtabs[data-section=\"money\"] button[data-sub=\"overview\"]");
    if (await page.$eval("#getstarted", e => e.hidden)) await page.click("#gsopen");
    await page.waitForSelector("#getstarted:not([hidden])", { timeout: 15000 }).catch(() => {});
  };
  await openSetup();
  await page.waitForSelector("#gssample", { timeout: 15000 }).catch(() => {});
  check("sample: an empty ledger offers the sample year", (await page.$("#gssample")) !== null);
  // The page reloads itself once the load and the price fetch land (Yahoo,
  // ~15 s), so: the POST first, then the navigation, then the boot line gone.
  const settled = async (btn) => {
    await Promise.all([
      page.waitForResponse(r => r.url().includes("/api/setup") && r.request().method() === "POST", { timeout: 120000 }).catch(() => {}),
      page.click(btn).catch(() => {})]);
    await page.waitForNavigation({ waitUntil: "load", timeout: 30000 }).catch(() => {});
    await page.waitForFunction(() => !document.querySelector("#boot"), null, { timeout: 60000 }).catch(() => {});
  };
  await settled("#gssample");
  await page.click("#tabs button[data-section=\"money\"]");
  await page.click(".subtabs[data-section=\"money\"] button[data-sub=\"holdings\"]");
  await page.waitForSelector("#holdings tr[data-sym]", { timeout: 30000 }).catch(() => {});
  const held = await page.$$eval("#holdings tr[data-sym]", r => r.map(x => x.dataset.sym));
  check("sample: the holdings table fills with the sample names, priced", held.includes("VTI") && held.includes("NVDA"), held.join(","));
  const priced = await page.$eval("#holdings", el => (el.innerText.match(/\$[\d,]+\.\d\d/g) || []).length);
  check("sample: and the figures are dollars, not dashes", priced > 10, `${priced} dollar figures`);
  await page.click("#tabs button[data-section=\"budget\"]");
  await page.click(".subtabs[data-section=\"budget\"] button[data-sub=\"recurring\"]");
  await page.waitForFunction(() => /NETFLIX/.test((document.querySelector("#bgRecur") || {}).innerText || ""), null, { timeout: 30000 }).catch(() => {});
  check("sample: the budget half fills too (Netflix on the Recurring tab)", /NETFLIX/.test(await page.$eval("#bgRecur", el => el.innerText)));
  await openSetup();
  await page.waitForSelector("#gsunsample", { timeout: 15000 }).catch(() => {});
  check("sample: the banner says it is sample data and offers to remove it", (await page.$("#gsunsample")) !== null);
  await settled("#gsunsample");
  await page.waitForFunction(() => /No data yet/.test(document.body.innerText), null, { timeout: 60000 }).catch(() => {});
  check("sample: removing it leaves the ledger empty again", /No data yet/.test(await page.$eval("#alert", el => el.innerText)));

  // One data point is 0/0 in the x scale, which produced d="MNaN 172.0" and a
  // path the browser refused outright.
  check("no console errors on an empty ledger", errors.length === 0,
        errors.slice(0, 3).join(" | "));
} catch (e) {
  check("the empty-ledger run completed", false, String(e.message).slice(0, 120));
} finally {
  await browser.close();
}

const failures = CHECKS.filter(c => !c[1]);
for (const [label, ok, detail] of CHECKS)
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${label.padEnd(56)} ${detail}`);
console.log(`\n  ${CHECKS.length - failures.length}/${CHECKS.length} passed`);
process.exit(failures.length ? 1 : 0);
