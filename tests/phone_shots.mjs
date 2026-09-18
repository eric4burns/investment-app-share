// Render every tab at iPhone width and report anything wider than the screen.
// node tests/phone_shots.mjs  -> screenshots in the scratch folder named below.
import { chromium } from "playwright";
const out = process.env.PHONE_OUT || "/private/tmp/claude-501/-Users-ericburns/78e6ac2d-6072-431e-ab6b-d0f8d953a33e/scratchpad/phone";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", e => errors.push(String(e).slice(0, 160)));
// Every view of the Phase 2 shell, as section/sub-tab. A hardcoded list
// silently stops covering whatever is added next, which is how a new tab ships
// without ever being measured at phone width.
const tabs = [
  "today/todo", "today/market", "today/alerts",
  "money/overview", "money/holdings", "money/trades", "money/risk", "money/sectors",
  "stocks/calls", "stocks/watchlist", "stocks/setups", "stocks/rebuy", "stocks/newstocks",
  "follow/graded", "follow/charts", "follow/methods", "follow/record",
  "bot/paper", "bot/record", "bot/backtest",
  "chart/chart", "chart/read", "chart/plan", "chart/follow", "chart/trades",
  "budget/summary", "budget/spending", "budget/recurring", "budget/plan", "budget/taxes", "budget/loose",
];
const report = {};
const measure = async () => page.evaluate(() => {
  const cw = document.documentElement.clientWidth;
  const wide = [...document.querySelectorAll("section.tab:not([hidden]) *")]
    .filter(e => { const r = e.getBoundingClientRect(); return r.width > 40 && r.right > cw + 2 && getComputedStyle(e).overflowX !== "auto"; })
    .slice(0, 6).map(e => `${e.tagName.toLowerCase()}${e.id ? "#" + e.id : ""}${typeof e.className === "string" && e.className ? "." + e.className.split(" ")[0] : ""} right=${Math.round(e.getBoundingClientRect().right)}`);
  const tiny = [...document.querySelectorAll("section.tab:not([hidden]) td, section.tab:not([hidden]) .note")]
    .filter(e => parseFloat(getComputedStyle(e).fontSize) < 11).length;
  return { scrollW: document.documentElement.scrollWidth, clientW: cw, pageH: document.documentElement.scrollHeight, wide, tiny };
});
const BASE = process.env.PHONE_URL || "http://127.0.0.1:8737";
for (const tab of tabs) {
  const name = tab.replace("/", "-");
  await page.goto(`${BASE}/?p=${Date.now()}#${tab}${tab.startsWith("chart/") ? "?sym=IREN" : ""}`, { waitUntil: "load" });
  await page.waitForTimeout(["chart/chart", "stocks/setups", "follow/methods"].includes(tab) ? 12000 : 8000);
  if (tab === "chart/chart") { try { await page.evaluate(() => { if (typeof loadChart === "function") loadChart("IREN"); }); await page.waitForTimeout(7000); } catch (e) {} }
  report[tab] = await measure();
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: false });
  await page.screenshot({ path: `${out}/${name}-full.png`, fullPage: true });
  // A row of the calls table opens the symbol page (Chart → The read); measure
  // that landing too, since it is where every name click ends up.
  if (tab === "stocks/calls") {
    try { await page.click('tr[data-vd="IREN"] td:first-child'); await page.waitForTimeout(4000);
      report["stocks/calls→page"] = await measure();
      await page.screenshot({ path: `${out}/stocks-calls-page.png`, fullPage: true });
    } catch (e) { report["stocks/calls→page"] = String(e).slice(0, 100); }
  }
}
for (const [k, v] of Object.entries(report)) console.log(k.padEnd(16), JSON.stringify(v));
console.log("page errors:", errors.length ? errors : "none");
await browser.close();
