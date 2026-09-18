/**
 * Does the app actually work in a browser?
 *
 * Every Python suite in this project can pass while the page is blank. That is
 * not a hypothetical: this app has shipped a blank page from a SyntaxError, a
 * chart built into a hidden panel that never painted, a stored drawing that
 * blanked the price pane, a loader that killed tab navigation, and a chart that
 * needed the Load button pressed before it would draw. All of them with a fully
 * green test run, because nothing opened the page.
 *
 * This opens the page.
 *
 * Run with ./smoke.sh, which starts a server on its own port against the real
 * database, READ ONLY — it never writes, and it uses a separate port so it
 * cannot disturb a dashboard you have open.
 */
import { chromium } from "playwright";

const BASE = process.env.SMOKE_URL || "http://127.0.0.1:8738";
const checks = [];
const check = (label, ok, detail = "") => checks.push({ label, ok: !!ok, detail });

// Every view — section/sub-tab — of the Phase 2 shell. This list is
// hardcoded rather than read from the page on purpose — it is what catches a
// tab silently disappearing — but that cuts both ways: a view ADDED and not
// listed here is never smoke-tested at all. Seven sections replaced the
// fifteen tabs on 2026-09-13 (research/audits/phase2-spec-2026-09-13.md).
const VIEWS = [
  "today/todo", "today/market", "today/alerts",
  "money/overview", "money/holdings", "money/trades", "money/risk", "money/sectors",
  "stocks/calls", "stocks/watchlist", "stocks/setups", "stocks/rebuy", "stocks/newstocks",
  "follow/graded", "follow/charts", "follow/methods", "follow/record",
  "bot/paper", "bot/record", "bot/backtest",
  "chart/chart", "chart/read", "chart/plan", "chart/follow", "chart/trades",
  "budget/summary", "budget/spending", "budget/recurring", "budget/plan", "budget/taxes", "budget/loose",
];
// Every OLD tab name, and the view its hash must land on. Bookmarks, the
// phone's home-screen link and every showTab("outlook") left in the script go
// through this table.
const OLD_HASHES = {
  overview: "money/overview", diagnose: "today/todo", holdings: "money/holdings",
  outlook: "stocks/calls", setups: "stocks/setups", newstocks: "stocks/newstocks",
  trades: "money/trades", risk: "money/risk", chart: "chart/chart",
  watchlist: "stocks/watchlist", sectors: "money/sectors", budget: "budget",   // bare section: the sub-tab it was last on, as SUB_KEY did
  research: "follow/methods", tradebot: "bot/paper", backtest: "bot/backtest",
};
// Opens a view the way a person does: the section button in the top bar,
// then the sub-tab in its row.
const go = async (pg, view) => {
  const [section, sub] = view.split("/");
  await pg.click(`#tabs button[data-section="${section}"]`);
  await pg.click(`.subtabs[data-section="${section}"] button[data-sub="${sub}"]`);
};
// The section and sub-panel that are actually on screen.
const shown = pg => pg.evaluate(() => {
  const sec = document.querySelector("section.tab:not([hidden])");
  const sub = sec && sec.querySelector(".subpanel:not([hidden])");
  return sec ? `${sec.dataset.panel}/${sub ? sub.dataset.subPanel : "?"}` : "none";
});

// Waits are on CONDITIONS, not on the clock. A fixed waitForTimeout was
// tuned to the slowest run anybody had seen and paid on every run: the tab
// tour alone slept six seconds across thirty-one views that had each
// already rendered. Every wait here polls for the thing the next check
// reads, and only the waits that guard "nothing happens" — a pan must not
// blank the chart, a fullscreen must not refit — still sleep, because
// nothing happening has no event to wait for.
// The chart's own request: loadChart stamps CHART_STARTED on entry and
// clears it as the response lands, before it paints, and the paint runs
// to completion in the same turn — so "cleared" means "drawn".
const chartSettled = pg => pg.waitForFunction(
  () => typeof CHART_STARTED !== "undefined" && CHART_STARTED === 0,
  null, { timeout: 30000 }).catch(() => {});
// "Reaches the server" is a question about persistence, not about the
// next 600 milliseconds: with the outlook payload building on another
// thread the write can land a second later and still be right. Poll.
const eventually = async (pg, fn, want, ms = 8000) => {
  const t0 = Date.now(); let v;
  while (Date.now() - t0 < ms) { v = await fn(); if (v === want) return v; await pg.waitForTimeout(250); }
  return v;
};

// Predicates for waitForFunction are FUNCTIONS, never strings. A string one is
// evaluated with eval() inside the page, and the server's Content-Security-
// Policy (web.py CSP, no 'unsafe-eval') refuses it — the wait then fails at
// once and the chart check reads "0 bars" against a chart that drew fine.
const browser = await chromium.launch();

// Console errors are failures. A page that renders but logs an exception is a
// page with a broken feature nobody has noticed yet.
const errors = [];
const watch = p => {
  p.on("pageerror", e => errors.push(String(e.message).slice(0, 120)));
  p.on("console", m => { if (m.type() === "error") errors.push(m.text().slice(0, 120)); });
  return p;
};
const page = watch(await browser.newPage({ viewport: { width: 1440, height: 900 } }));

try {
  // The chart goes FIRST, on a page of its own opened straight to #chart.
  //
  // Two things forced this ordering. Reaching the chart after touring every
  // other tab hides the defect the user actually hit, because by then the
  // watchlist has already supplied the symbol — a mutant that reintroduced the
  // "press Load first" bug survived that ordering untouched. And the tab tour
  // fires all eleven loaders within a few seconds against a CPU-bound Python
  // server behind a GIL, so anything opened afterwards starves for half a
  // minute on the backlog; closing the touring page does not help, because
  // those requests are already running. So the cold path gets the quiet server
  // it is meant to measure, and the tour follows.
  const cold = watch(await browser.newPage({ viewport: { width: 1440, height: 900 } }));
  // "Clear all" asks before wiping, since there is no undo. Playwright dismisses
  // dialogs by default, so without this the confirm silently answers no and the
  // clear check passes for the wrong reason.
  cold.on("dialog", d => d.accept());
  await cold.goto(`${BASE}/#chart/chart`, { waitUntil: "domcontentloaded" });
  await cold.waitForFunction(
    () => typeof CANDLES !== 'undefined' && CANDLES && CANDLES.data().length > 0,
    null, { timeout: 45000 }).catch(() => {});
  const bars = await cold.evaluate(
    "(typeof CANDLES !== 'undefined' && CANDLES && CANDLES.data) ? CANDLES.data().length : 0");
  check("the chart draws candles without pressing Load", bars > 100, `${bars} bars`);

  // Toggling an annotation must not move the price scale, and must not take the
  // candles with it.
  const lastY = "CANDLES.priceToCoordinate(CANDLES.data()[CANDLES.data().length - 1].close)";
  // Take the baseline only once the scale has stopped moving on its own. The
  // chart is still finishing its initial fit right after the tab is shown, and
  // measuring into that settle blames the annotations for the fit.
  const stableY = async () => {
    let prev = null;
    for (let i = 0; i < 25; i++) {
      const y = await cold.evaluate(lastY);
      if (prev !== null && y !== null && Math.abs(y - prev) < 0.5) return y;
      prev = y;
      await cold.waitForTimeout(400);
    }
    return prev;
  };
  const yBefore = await stableY();
  // The drawing and structure toolbars collapse now, so a real user opens the
  // disclosure before reaching a control inside it — and so must this. Without
  // it Playwright waits on a hidden checkbox until it times out. A reload closes
  // them again, hence a helper rather than one call.
  const openTools = pg =>
    pg.$$eval("details.toolgroup", els => els.forEach(d => { d.open = true; }));
  await openTools(cold);
  for (const box of ["#stChannel", "#stFib", "#stLabels"]) {
    await cold.check(box);          // each one reloads the chart
    await chartSettled(cold);
  }
  const after = {
    bars: await cold.evaluate("CANDLES.data().length"),
    y: await stableY(),
  };
  check("candles survive turning every annotation on", after.bars > 100, `${after.bars} bars`);

  // The main chart drew the cloud as two AREA series, each filling from its own
  // line to the FLOOR of the pane, so most of the chart came out shaded and
  // only the overlap looked like a band. Same defect the mini chart had; same
  // canvas overlay fixes it. Measured as shape, because "something is shaded"
  // was true of the broken version too.
  // Ichimoku has to be TURNED ON first. Written as "measure it if it happens to
  // be enabled, otherwise pass", this reported success without ever looking —
  // the default indicator set is volume and two moving averages, so the escape
  // branch is the one that always ran.
  await cold.evaluate(() => {
    INDS = [{ name: "ichimoku", args: [9, 26, 52] }];
    loadChart(CHART_SYMBOL);
  });
  await cold.waitForFunction(
    () => document.querySelector("#pricechart canvas.cloudband"),
    { timeout: 30000 }).catch(() => {});
  const mainCloud = await cold.evaluate(() => {
    const cv = document.querySelector("#pricechart canvas.cloudband");
    if (!cv || !cv.width) return null;
    const px = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data;
    let filled = 0;
    for (let i = 0; i < px.length; i += 4) if (px[i + 3] > 5) filled++;
    return { pct: filled / (px.length / 4) };
  });
  check("chart: the Ichimoku cloud is drawn on the main chart",
        mainCloud !== null,
        mainCloud ? "overlay present" : "no overlay canvas after enabling Ichimoku");
  check("chart: the cloud is a band, not a wash over the pane",
        mainCloud && mainCloud.pct < 0.35,
        mainCloud ? `${(mainCloud.pct * 100).toFixed(1)}% of the canvas` : "not drawn");

  // Five unlabelled lines is a puzzle, not a chart. Each is named, and the
  // lagging span — the one plotted 26 sessions in the PAST, and the easiest to
  // misread as current — is off unless asked for.
  const key = await cold.$eval("#cloudkey", el => el.innerText.replace(/\s+/g, " "));
  check("chart: every Ichimoku line is named", /span A/.test(key) && /span B/.test(key)
        && /[Cc]onversion/.test(key) && /base/.test(key), key.slice(0, 70));
  check("chart: the lagging span is off unless asked for",
        /lagging span is hidden/i.test(key), key.slice(-70));
  check("annotations do not move the price scale",
        Math.abs(after.y - yBefore) < 4, `moved ${Math.abs(after.y - yBefore).toFixed(1)}px`);
  // ---------------------------------------------------------- drawings ----
  // Every check here is one of the things that went wrong the first time these
  // shipped: a placed shape that never appeared in the menu, no way to select
  // or delete it, and the price pane going blank during a pan.
  // Every gesture recomputes where the chart is, immediately before using it.
  // The chart sits below the fold, so it has to be scrolled to — and clicking
  // any toolbar button scrolls that button into view, which moves the chart out
  // from under coordinates measured a moment earlier. Measuring once produced a
  // run where all five drawing checks failed against a perfectly working app.
  const at = async (fx, fy) => {
    await cold.$eval("#pricechart", el => el.scrollIntoView({ block: "center" }));
    // The frame after the scroll, so the rectangle read next is the settled one.
    await cold.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
    const r = await cold.$eval("#pricechart", el => {
      const b = el.getBoundingClientRect();
      return { x: b.x, y: b.y, w: b.width, h: b.height };
    });
    return { x: r.x + r.w * fx, y: r.y + r.h * fy, box: r };
  };
  const probe = await at(0.5, 0.5);
  const vh = await cold.evaluate("innerHeight");
  check("the chart is on screen, with the candles under the drag point",
        probe.box.y >= 0 && probe.box.y + probe.box.h <= vh + 1 &&
        await cold.evaluate(`(() => {
          const el = document.querySelector("#pricechart");
          const h = document.elementFromPoint(${probe.x}, ${probe.y});
          return !!h && el.contains(h);
        })()`),
        `y ${probe.box.y.toFixed(0)} h ${probe.box.h} vh ${vh}`);

  check("the drawing toolbar is on the page",
        await cold.$("#drawbar") !== null);
  // Every check below assumes the chart starts with nothing drawn on it, and
  // since the user's shelf levels were loaded (2026-09-03) the copied ledger
  // has four on this symbol. The copy is a throwaway, so clear it here and
  // reload the chart, rather than assume a state the real database no
  // longer has.
  await cold.evaluate(
    `fetch("/api/drawings?action=clear&symbol=" + CHART_SYMBOL + "&timeframe=" + document.querySelector("#tf").value)
       .then(r => r.json())`);
  await cold.evaluate("loadChart(CHART_SYMBOL)");
  await cold.waitForFunction(() => /nothing drawn/i.test(document.querySelector("#drawlist").innerText)
                                   || document.querySelectorAll(".drawrow").length === 0, { timeout: 30000 }).catch(() => {});
  const emptyNote = await cold.$eval("#drawlist", el => el.innerText.trim());
  check("an empty chart says so rather than showing an empty strip",
        /nothing drawn/i.test(emptyNote), emptyNote.slice(0, 40));

  // Place a trendline by dragging, the way a person would.
  await openTools(cold);
  await cold.click('.dtool[data-tool="trend"]');
  const a = await at(0.35, 0.65), b = await at(0.72, 0.30);
  await cold.mouse.move(a.x, a.y);
  await cold.mouse.down();
  await cold.mouse.move(b.x, b.y, { steps: 12 });
  await cold.mouse.up();
  await cold.waitForFunction(() => document.querySelectorAll(".drawrow").length === 1, null, { timeout: 5000 }).catch(() => {});

  const listed = await cold.$$eval(".drawrow", rows => rows.length);
  check("a drawn trendline appears in the list", listed === 1, `${listed} rows`);
  check("the tool returns to Select after placing one",
        await cold.$eval('.dtool[data-tool="cursor"]', el => el.getAttribute("aria-pressed")) === "true");

  // It has to reach the server, not just the screen. A line that survives only
  // until reload is the same as no line on a phone.
  const storedNow = () => cold.evaluate(
    `fetch("/api/drawings?symbol=" + CHART_SYMBOL + "&timeframe=" + document.querySelector("#tf").value)
       .then(r => r.json()).then(j => (j.drawings || []).length)`);
  const stored = await eventually(cold, storedNow, 1);
  check("the trendline was saved server-side", stored === 1, `${stored} stored`);

  // The reported catastrophe: panning made the whole chart vanish. The overlay
  // must not be able to do that, because it never touches the chart's data.
  const beforePan = await cold.evaluate("CANDLES.data().length");
  const mid = await at(0.5, 0.5);
  await cold.mouse.move(mid.x, mid.y);
  await cold.mouse.down();
  await cold.mouse.move(mid.x - 260, mid.y, { steps: 20 });
  await cold.mouse.up();
  await cold.waitForTimeout(500);
  const afterPan = await cold.evaluate("CANDLES.data().length");
  check("panning does not blank the chart", afterPan === beforePan && afterPan > 100,
        `${beforePan} -> ${afterPan}`);
  check("panning does not delete the drawing",
        await cold.$$eval(".drawrow", r => r.length) === 1);

  // Every shape gets drawn, not just the easy one. A channel is placed in two
  // gestures and spends the gap between them with one anchor missing, which
  // threw on every animation frame — a hundred exceptions the earlier version
  // of this test never saw, because it only ever drew a trendline.
  const place = async (tool, path) => {
    await cold.click(`.dtool[data-tool="${tool}"]`);
    const from = await at(path[0], path[1]), to = await at(path[2], path[3]);
    const had = await cold.evaluate("DRAW ? DRAW.items.length : 0");
    await cold.mouse.move(from.x, from.y);
    await cold.mouse.down();
    await cold.mouse.move(to.x, to.y, { steps: 10 });
    await cold.mouse.up();
    // Placed, or — a channel, whose first gesture only sets the base line —
    // drafted and waiting for its third click.
    await cold.waitForFunction(n => DRAW && (DRAW.items.length > n || (DRAW.draft && DRAW.draft.placed >= 2)),
                               had, { timeout: 5000 }).catch(() => {});
  };
  await place("ray", [0.10, 0.80, 0.28, 0.55]);
  await place("fib", [0.40, 0.78, 0.55, 0.25]);
  await place("level", [0.50, 0.15, 0.50, 0.15]);
  await place("channel", [0.62, 0.72, 0.86, 0.45]);
  const third = await at(0.86, 0.28);
  const hadFour = await cold.evaluate("DRAW.items.length");
  await cold.mouse.move(third.x, third.y, { steps: 8 });
  await cold.mouse.down(); await cold.mouse.up();
  await cold.waitForFunction(n => DRAW.items.length > n, hadFour, { timeout: 5000 }).catch(() => {});

  const kinds = await cold.evaluate("DRAW.items.map(d => d.kind).sort().join(',')");
  check("every shape can be placed", kinds === "channel,fib,level,ray,trend", kinds);

  // They have to come back. A drawing that lives until reload is no use on the
  // phone this app is meant to be read from.
  await cold.reload({ waitUntil: "domcontentloaded" });
  await openTools(cold);
  await cold.waitForFunction(
    () => typeof DRAW !== 'undefined' && DRAW && DRAW.items.length > 0, null, { timeout: 45000 })
    .catch(() => {});
  const survived = await cold.evaluate(
    "(typeof DRAW !== 'undefined' && DRAW) ? DRAW.items.length : 0");
  check("drawings survive a reload", survived === 5, `${survived} of 5`);

  await cold.click("#dClear").catch(() => {});
  await cold.waitForFunction(() => DRAW && DRAW.items.length === 0, null, { timeout: 5000 }).catch(() => {});

  // Back to one trendline for the selection and delete checks below.
  await place("trend", [0.35, 0.65, 0.72, 0.30]);

  // Moving and reshaping, which is the whole point of storing anchors rather
  // than pixels — and the only exercise the server's move endpoint gets.
  const anchors = () => cold.evaluate("JSON.stringify(DRAW.items[0].points)");
  const savedAnchors = () => cold.evaluate(
    `fetch("/api/drawings?symbol=" + CHART_SYMBOL + "&timeframe=" + document.querySelector("#tf").value)
       .then(r => r.json()).then(j => JSON.stringify((j.drawings[0] || {}).points))`);

  const beforeMove = await anchors();
  const grab = await at(0.535, 0.475);        // the midpoint of the line just drawn
  await cold.mouse.move(grab.x, grab.y);
  await cold.mouse.down();
  await cold.mouse.move(grab.x, grab.y - 60, { steps: 12 });
  await cold.mouse.up();
  await cold.waitForFunction(b => JSON.stringify(DRAW.items[0].points) !== b, beforeMove, { timeout: 3000 }).catch(() => {});
  const afterMove = await anchors();
  check("dragging a drawing moves it", afterMove !== beforeMove);
  check("the move reaches the server", await eventually(cold, savedAnchors, afterMove) === afterMove);

  // Reshaping: grab the handle at the second anchor and pull it.
  const ends = await cold.evaluate(`(() => {
    const d = DRAW.items[0], p = DRAW.pointsOf(d);
    const r = document.querySelector("#pricechart").getBoundingClientRect();
    return p ? { x: r.x + p[1][0], y: r.y + p[1][1] } : null;
  })()`);
  check("a selected drawing exposes its handles", ends !== null);
  if (ends) {
    const beforeShape = await anchors();
    await cold.mouse.move(ends.x, ends.y);
    await cold.mouse.down();
    await cold.mouse.move(ends.x - 40, ends.y + 50, { steps: 12 });
    await cold.mouse.up();
    await cold.waitForFunction(b => JSON.stringify(DRAW.items[0].points) !== b, beforeShape, { timeout: 3000 }).catch(() => {});
    const afterShape = await anchors();
    check("dragging a handle reshapes it", afterShape !== beforeShape);
    check("the reshape reaches the server", await eventually(cold, savedAnchors, afterShape) === afterShape);
    const n = await cold.$$eval(".drawrow", r => r.length);
    check("reshaping does not create a second drawing", n === 1, `${n} rows`);
  }

  // Select it from the list, which is the affordance that was missing.
  await cold.click(".drawrow");
  await cold.waitForFunction(() => !document.querySelector("#dDelete").disabled, null, { timeout: 3000 }).catch(() => {});
  check("selecting from the list enables Delete",
        await cold.$eval("#dDelete", el => !el.disabled));

  await cold.click("#dDelete");
  await cold.waitForFunction(() => document.querySelectorAll(".drawrow").length === 0, null, { timeout: 3000 }).catch(() => {});
  check("Delete removes it from the list",
        await cold.$$eval(".drawrow", r => r.length) === 0);
  const leftNow = () => cold.evaluate(
    `fetch("/api/drawings?symbol=" + CHART_SYMBOL + "&timeframe=" + document.querySelector("#tf").value)
       .then(r => r.json()).then(j => (j.drawings || []).length)`);
  const left = await eventually(cold, leftNow, 0);
  check("Delete removes it server-side too", left === 0, `${left} left`);

  // -------------------------------------------------- remembered view ----
  // Zoom in, reload, and land where you left off. Three separate code paths
  // called fitContent, so the chart reset itself on load, on switching to the
  // tab, and on going fullscreen.
  const range = () => cold.evaluate(
    "JSON.stringify(CHART.timeScale().getVisibleRange())");
  const spanBars = () => cold.evaluate(`(() => {
    const r = CHART.timeScale().getVisibleLogicalRange();
    return r ? Math.round(r.to - r.from) : null;
  })()`);

  const wide = await spanBars();
  // Phase 2, commit 4: a fresh browser opens on the last year of bars, not on
  // every bar there is — 250 daily candles plus the right-hand gap. The "All"
  // side of the toggle is the old behaviour, one click away.
  check("the chart opens on the last year, not all of history",
        wide !== null && wide >= 240 && wide <= 262, `${wide} bars visible`);
  check("the range toggle reads 1Y by default",
        await cold.$eval("#rangetoggle button.on", b => b.dataset.range) === "1y");
  await cold.evaluate(`CHART.timeScale().setVisibleLogicalRange(
    {from: CANDLES.data().length - 120, to: CANDLES.data().length})`);
  await cold.waitForTimeout(900);            // past the save debounce
  const zoomed = await spanBars();
  check("the chart can be zoomed in", zoomed !== null && zoomed < wide,
        `${wide} bars -> ${zoomed} bars`);
  const savedRange = await range();

  await cold.reload({ waitUntil: "domcontentloaded" });
  await openTools(cold);
  await cold.waitForFunction(
    () => typeof CANDLES !== 'undefined' && CANDLES && CANDLES.data().length > 0,
    null, { timeout: 45000 });
  await cold.waitForTimeout(700);
  const afterReload = await spanBars();
  check("the zoom survives a reload",
        afterReload !== null && Math.abs(afterReload - zoomed) <= 6,
        `${zoomed} bars -> ${afterReload} bars`);

  // Switching away and back must not quietly refit either.
  await cold.click(`#tabs button[data-section="money"]`);
  await cold.waitForTimeout(300);
  await cold.click(`#tabs button[data-section="chart"]`);
  await cold.waitForTimeout(600);
  const afterTab = await spanBars();
  check("the zoom survives switching tabs",
        afterTab !== null && Math.abs(afterTab - afterReload) <= 6,
        `${afterReload} bars -> ${afterTab} bars`);

  // Fullscreen gives you more of the same chart, not all of history back.
  await cold.evaluate(`document.querySelector("#fullscreen").click()`);
  await cold.waitForTimeout(900);
  const afterFull = await spanBars();
  check("going fullscreen does not reset the zoom",
        afterFull !== null && Math.abs(afterFull - afterTab) <= 10,
        `${afterTab} bars -> ${afterFull} bars`);
  await cold.evaluate(`document.querySelector("#fullscreen").click()`);
  await cold.waitForTimeout(500);

  await cold.close();

  await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });

  // The app is allowed to be slow. It is not allowed to be blank with no
  // explanation, which is what made a slow load read as a crash.
  await page.waitForSelector("#boot, #cards", { timeout: 5000 });
  check("something is on screen within 5s (a loading line counts)", true);

  await page.waitForFunction(
    () => { const c = document.querySelector("#cards"); return c && /\$/.test(c.innerText); },
    { timeout: 60000 });
  check("the portfolio value appears within 60s", true);
  // My Money → Overview is the landing screen; the URL carries the view. Read
  // once the page is up — the router runs after the first portfolio fetch.
  check("the app lands on My Money → Overview", await shown(page) === "money/overview", await shown(page));
  check("the address bar names the view", await page.evaluate(() => location.hash) === "#money/overview",
        await page.evaluate(() => location.hash));

  // Net worth is the number that needs all three halves present — investments,
  // bank cash and card debt — so an empty panel here means one of them broke.
  await page.waitForFunction(
    () => { const n = document.querySelector("#networth");
            return n && /\$/.test(n.innerText); }, { timeout: 60000 }).catch(() => {});
  const nw = await page.$eval("#networth", el => el.innerText.replace(/\s+/g, " "));
  check("overview: net worth is computed", /net worth/i.test(nw) && /\$[\d,]{4,}/.test(nw),
        nw.slice(0, 60));
  check("overview: its three parts are all shown",
        /investments/i.test(nw) && /cash/i.test(nw) && /debt/i.test(nw));
  check("overview: the savings rate is shown", /%/.test(nw) && /income/i.test(nw));

  const value = await page.$eval("#cards", el => el.innerText.replace(/\s+/g, " ").slice(0, 40));
  check("the value is a real number, not a placeholder", /\$[\d,]{4,}/.test(value), value);

  // Every view must switch AND put something in its panel. A tab that toggles
  // but renders nothing is the failure mode this app keeps having.
  for (const view of VIEWS) {
    await go(page, view);
    // Until the panel is on screen with something in it — which for most
    // views is immediate, and for a view whose loader is still out is what
    // the check below reads anyway.
    await page.waitForFunction(v => {
      const sec = document.querySelector("section.tab:not([hidden])");
      const sub = sec && sec.querySelector(".subpanel:not([hidden])");
      return sec && sub && `${sec.dataset.panel}/${sub.dataset.subPanel}` === v && sub.innerText.trim().length > 15;
    }, view, { timeout: 15000 }).catch(() => {});
    const on = await shown(page);
    const txt = await page.evaluate(v => {
      const [s, sub] = v.split("/");
      const el = document.querySelector(`[data-panel="${s}"] [data-sub-panel="${sub}"]`);
      return el ? el.innerText.trim().length : -1;
    }, view);
    check(`${view}: the panel is shown`, on === view && txt > 15, `${on}, ${txt} chars`);
  }
  // Every old hash still opens something, and the right something.
  const misrouted = [];
  for (const [old, want] of Object.entries(OLD_HASHES)) {
    await page.evaluate(h => { location.hash = h; }, "#" + old);
    // hashchange is asynchronous; showTab rewrites the hash to the view it landed on.
    await page.waitForFunction(h => location.hash !== h, "#" + old, { timeout: 5000 }).catch(() => {});
    const on = await shown(page);
    const hash = await page.evaluate(() => location.hash);
    // The chart's address carries its symbol (#chart/chart?sym=IREN).
    const bare = hash.replace(/\?.*$/, "");
    const ok = want.includes("/") ? on === want && bare === "#" + want : on.startsWith(want + "/") && bare === "#" + on;
    if (!ok) misrouted.push(`#${old} -> ${on} (${hash})`);
  }
  check("every old hash redirects to its new home", misrouted.length === 0, misrouted.join(", "));
  // The sub-tab a section was last on is remembered per section.
  await go(page, "money/risk");
  await go(page, "budget/taxes");
  await page.click(`#tabs button[data-section="money"]`);
  check("a section reopens on the sub-tab it was last on", await shown(page) === "money/risk", await shown(page));


  // The budget tab renders from a different half of the ledger than every other
  // tab, so "the panel is shown" would pass on an empty one.
  await go(page, "budget/summary");
  await page.waitForFunction(
    () => { const c = document.querySelector("#bgCards"); return c && /\$/.test(c.innerText); },
    { timeout: 30000 }).catch(() => {});
  const bgCards = await page.$eval("#bgCards", el => el.innerText.replace(/\s+/g, " "));
  check("budget: real figures, not an empty shell", /\$[\d,]{3,}/.test(bgCards),
        bgCards.slice(0, 60));
  const trend = await page.$eval("#bgTrend", el => el.innerText.replace(/\s+/g, " "));
  check("budget: this month is compared against its own history",
        /\d{4}-\d{2}/.test(trend) && /typical/i.test(trend), trend.slice(0, 70));

  const recur = await page.$eval("#bgRecur", el => el.innerText.replace(/\s+/g, " "));
  check("budget: recurring charges are found and priced",
        /subscriptions/i.test(recur) && /\$[\d,]+\.\d\d/.test(recur), recur.slice(0, 60));
  const subRows = await page.$$eval("#bgRecur table tr", r => r.length);
  check("budget: subscriptions are listed individually", subRows > 3, `${subRows} rows`);

  // Saved-per-month has a zero line and signed bars, so "it rendered" is not
  // enough — a sign error would still draw 25 columns. Assert it states a rate
  // and drew a bar per month.
  const saved = await page.$eval("#bgSaved", el => el.innerText.replace(/\s+/g, " "));
  check("budget: savings per month is stated with a rate",
        /savings rate/i.test(saved) && /\$[\d,]+/.test(saved), saved.slice(0, 70));
  const svCols = await page.$$eval("#bgSaved .svcol", c => c.length);
  check("budget: one savings column per month", svCols > 12, `${svCols} columns`);

  const bgRows = await page.$$eval("#bgCats tr", r => r.length);
  check("budget: spending is broken down by category", bgRows > 3, `${bgRows} rows`);
  // Assert the substance, not the sentence: the panel has to say how much left
  // the bank for cards and how much of that is itemised. Matching the exact
  // wording made this fail on a copy edit while the number was correct.
  const blind = await page.$eval("#bgBlind", el => el.innerText.replace(/\s+/g, " "));
  check("budget: card spending is reconciled, not hidden",
        /\$[\d,]{3,}/.test(blind) && /card/i.test(blind) &&
        /(unaccounted|itemised|accounted)/i.test(blind), blind.slice(0, 70));


  // The verdict layer loads on its own timer AFTER the performance payload, so
  // "the holdings panel is shown" passes whether or not any of it arrived. It
  // is also the only column on this page produced by a second fetch, which is
  // exactly the shape of thing that renders blank without anybody noticing.
  await go(page, "money/holdings");
  await page.waitForFunction(
    () => document.querySelector("#holdings") &&
          document.querySelector("#holdings").dataset.verdicts === "1",
    { timeout: 60000 }).catch(() => {});
  const vdCells = await page.$$eval("#holdings .vd", e => e.length);
  check("holdings: a verdict is painted on the positions", vdCells > 2,
        `${vdCells} verdicts`);
  const vdHead = await page.$eval("#holdings tr:first-child", el => el.innerText);
  // "Call", not "Verdict", since D120: the column is the headline call the
  // rest of the app shows, not the daily read.
  check("holdings: the call column has a header", /\bcall\b/i.test(vdHead), vdHead.slice(-40));

  // Clicking one must open the working. A verdict with no visible evidence is
  // the thing this feature must never become. The working is the symbol page
  // now (Chart → The read), reached from every name click through one door.
  const pillSym = await page.$eval("#holdings [data-vd]", el => el.dataset.vd);
  await page.click("#holdings [data-vd]");
  await page.waitForSelector("#symread .vd", { timeout: 30000 }).catch(() => {});
  const jumped = await shown(page);
  check("holdings: clicking a verdict opens the name's page on The read", jumped === "chart/read", jumped);
  const pageHash = await page.evaluate(() => location.hash);
  check("the address names the page and the name", pageHash === `#chart/read?sym=${pillSym}`, pageHash);
  const detail = await page.$eval("#symread", el => el.innerText.replace(/\s+/g, " "));
  check("holdings: a verdict opens its evidence", detail.length > 40, detail.slice(0, 70));
  check("holdings: the evidence carries real numbers, not adjectives",
        /\d/.test(detail), detail.slice(0, 70));
  const recBtns = await page.$$eval("#symread [data-rec]", e => e.length);
  check("holdings: your own decision can be recorded from there", recBtns === 5,
        `${recBtns} buttons`);
  // The header is the page's identity: the name, its price, the call, and —
  // for a holding — the position, marked as the user's own.
  const head = await page.$eval("#symhead", el => el.innerText.replace(/\s+/g, " "));
  check("symbol page: the header names the symbol, price and call",
        head.startsWith(pillSym) && /\$[\d,]+\.\d\d/.test(head) && /(buy|add|hold|trim|sell)/i.test(head), head.slice(0, 80));
  check("symbol page: a held name shows its position as the user's own",
        /shares/.test(head) && /yours/.test(head), head.slice(0, 120));
  check("symbol page: the header sits above the sub-tab row", await page.evaluate(() => {
    const h = document.querySelector("#symhead").getBoundingClientRect(), t = document.querySelector('.subtabs[data-section="chart"]').getBoundingClientRect();
    return h.bottom <= t.top + 1; }));

  // The evidence lives under Stocks → Holdings calls (the old Outlook tab);
  // the Holdings column only jumps to it.
  await go(page, "stocks/calls");
  await page.waitForSelector("#vdtable tr[data-vd]", { timeout: 30000 }).catch(() => {});
  const vdRows = await page.$$eval("#vdtable tr", r => r.length);
  check("outlook: every holding is listed with both timeframes", vdRows > 5,
        `${vdRows} rows`);
  const vdHdr = await page.$eval("#vdtable tr:first-child", el => el.innerText);
  check("outlook: daily and weekly are separate columns",
        /daily/i.test(vdHdr) && /weekly/i.test(vdHdr), vdHdr.replace(/\s+/g, " "));
  check("outlook: support and resistance are on the table itself",
        /support/i.test(vdHdr) && /resistance/i.test(vdHdr), vdHdr.replace(/\s+/g, " "));

  // The three prices every reading resolves to are ON the table, as figures.
  check("outlook: buy at / sell into / wrong below are columns of the table",
        /buy at/i.test(vdHdr) && /sell into/i.test(vdHdr) && /wrong below/i.test(vdHdr), vdHdr.replace(/\s+/g, " ").slice(0, 120));
  const lvlCells = await page.$$eval("#vdtable td.lvl", tds => tds.filter(td => /\$\d/.test(td.innerText)).length);
  check("outlook: the level columns carry prices, not prose", lvlCells >= 6, `${lvlCells} priced cells`);

  // A row opens the name's page. The page has to lead with the current price,
  // name the horizontal levels with their touch counts, and show the averages
  // — all of which the old card did and the page must not lose.
  const rowSym = await page.$eval("#vdtable tr[data-vd]:nth-of-type(3)", el => el.dataset.vd);
  await page.click("#vdtable tr[data-vd]:nth-of-type(3) td:first-child");
  await page.waitForFunction(s => document.querySelector("#symhead").innerText.startsWith(s) && document.querySelector("#symplan .ladder"), rowSym, { timeout: 30000 }).catch(() => {});
  check("outlook: a table row opens the name's page", await shown(page) === "chart/read" && (await page.evaluate(() => location.hash)).includes(rowSym), await page.evaluate(() => location.hash));
  const det = await page.$eval("#symhead", el => el.innerText.replace(/\s+/g, " "));
  check("outlook: the page leads with the current price", /\$[\d,]+\.\d\d/.test(det), det.slice(0, 60));
  await page.evaluate(() => document.querySelectorAll("#symplan details").forEach(d => { d.open = true; }));
  const plan = await page.$eval("#symplan", el => el.innerText.replace(/\s+/g, " "));
  check("outlook: horizontal support and resistance are named with touch counts",
        /touches/i.test(plan) && /(support|resistance)/i.test(plan), plan.slice(0, 90));
  check("outlook: moving averages are shown", /-day average/i.test(plan));
  // Plan & levels is ONE ladder: the three prices, the current price as a
  // rule across it, and the user's own rows marked.
  check("symbol page: the ladder holds buy at, sell into and wrong below (or says why not)",
        /(Buy at|No buy level)/.test(plan) && /(Sell (the slice )?into|No sell level)/.test(plan) && /(Wrong below|No invalidation level)/.test(plan), plan.slice(0, 200));
  check("symbol page: the ladder has the current price on it", /Price now/.test(plan));
  const ladderMine = await page.$$eval("#symplan .ladder tr.mine", r => r.length);
  check("symbol page: the user's own levels are marked on the ladder", ladderMine >= 1, `${ladderMine} rows marked yours`);
  const ladderOrder = await page.$$eval("#symplan .ladder .lvlprice", els => els.map(e => parseFloat(e.innerText.replace(/[^\d.]/g, ""))));
  check("symbol page: the ladder is in price order", ladderOrder.every((v, i) => !i || v <= ladderOrder[i - 1] + 1e-9), ladderOrder.slice(0, 6).join(" > "));
  check("symbol page: the plan form is on the page", await page.$("#symplan [data-planadd]") !== null);
  // A plain hold has no dissent to show — its tally already states both sides —
  // so this has to find a DECISIVE call rather than trusting whichever row
  // happens to be third. Pinning the row number made this fail on a data change
  // that was not a regression.
  let sawAgainst = false, sawTally = false;
  const rowSyms = await page.$$eval("#vdtable tr[data-vd]", r => r.map(x => x.dataset.vd));
  for (const sym of rowSyms.slice(0, 8)) {
    await page.evaluate(s => openSymbol(s, "read"), sym);
    await page.waitForFunction(s => document.querySelector("#symhead").innerText.startsWith(s) && document.querySelector("#symread .vd"), sym, { timeout: 30000 }).catch(() => {});
    const d = await page.$eval("#symread", el => el.innerText);
    if (/against it/i.test(d)) sawAgainst = true;
    if (/bullish vs .* bearish/i.test(d)) sawTally = true;
    if (sawAgainst && sawTally) break;
  }
  check("outlook: a decisive call shows the case against it too", sawAgainst,
        "a verdict listing only confirming evidence is advocacy");
  check("outlook: the tally that produces the call is shown, not just its total",
        sawTally, "'4.5 bullish against 4.0 bearish' with nowhere to look");
  // The five sub-tabs of one name, each with its own content.
  await page.evaluate(() => openSymbol("IREN", "read"));
  await page.waitForFunction(() => document.querySelector("#symhead").innerText.startsWith("IREN") && document.querySelector("#symtrades .card, #symtrades .note"), null, { timeout: 30000 }).catch(() => {});
  const subs = {};
  for (const sub of ["chart", "read", "plan", "follow", "trades"]) {
    await page.click(`.subtabs[data-section="chart"] button[data-sub="${sub}"]`);
    if (sub === "chart") await page.waitForFunction(() => CHART_DRAWN === "IREN" && CHART_STARTED === 0
      && typeof CANDLES !== "undefined" && CANDLES && CANDLES.data().length > 100, null, { timeout: 30000 }).catch(() => {});
    else await page.waitForFunction(sb => { const el = document.querySelector(`[data-panel="chart"] [data-sub-panel="${sb}"]`);
      return el && !el.hidden && el.innerText.trim().length > 40; }, sub, { timeout: 15000 }).catch(() => {});
    subs[sub] = await page.evaluate(sb => { const el = document.querySelector(`[data-panel="chart"] [data-sub-panel="${sb}"]`); return el && !el.hidden ? el.innerText.replace(/\s+/g, " ").length : -1; }, sub);
  }
  check("symbol page: all five sub-tabs render for IREN", Object.values(subs).every(n => n > 40), JSON.stringify(subs));
  const follow = await page.$eval("#symfollow", el => el.innerText.replace(/\s+/g, " "));
  check("symbol page: who I follow on it lists their calls and the crowd", /Their calls/.test(follow) && /The crowd/.test(follow), follow.slice(0, 80));
  // A chart posted on X about the page's name is on the page. IREN is charted
  // on X in the copied ledger; if the nightly pull has none, the check says so
  // rather than passing on nothing (D133).
  const xOnPage = await page.evaluate(async () => {
    const x = await (await fetch("/api/x-charts?symbol=IREN")).json();
    const cards = [...document.querySelectorAll("#symfollow img")].map(i => i.getAttribute("src"));
    return {saved: (x.charts || []).length, shown: cards.filter(u => /^\/chart-x\?/.test(u)).length};
  });
  check("symbol page: the charts posted on X about the name are on its Follow tab", xOnPage.saved === 0 || xOnPage.shown > 0, JSON.stringify(xOnPage));
  const trades = await page.$eval("#symtrades", el => el.innerText.replace(/\s+/g, " "));
  check("symbol page: my trades shows the fills with a running position", /Your fills/.test(trades) && /Position after/i.test(trades), trades.slice(0, 80));
  check("symbol page: the chart draws for the page's name", await page.evaluate(() => typeof CANDLES !== "undefined" && CANDLES && CANDLES.data().length > 100 && CHART_DRAWN === "IREN"));
  // What is the user's is on the chart, louder than anything the app drew:
  // the average cost as a 2px line with its price on the axis, and the three
  // prices the read resolves to (buy at / sell into / wrong below) plus the
  // flip — one line per level the verdict actually has, so the chart and the
  // Plan & levels ladder agree.
  await page.waitForFunction(() => typeof VERDICT_LINES !== "undefined" && VERDICT_LINES.length > 0, null, { timeout: 30000 }).catch(() => {});
  const lines = await page.evaluate(() => {
    const w = (SYM_DATA && SYM_DATA.row && SYM_DATA.row.watch) || {};
    const flip = SYM_DATA && SYM_DATA.row ? SYM_DATA.row.flip : null;
    const want = ["buy_at", "trim_at", "stop_at"].filter(k => w[k] != null).length
      + (flip != null && ![w.buy_at, w.trim_at, w.stop_at].includes(flip) ? 1 : 0);
    const titles = VERDICT_LINES.map(l => l.options().title);
    return { want, titles, cost: COST_LINE ? COST_LINE.options() : null, avg: SYM_DATA && SYM_DATA.chart && SYM_DATA.chart.position && SYM_DATA.chart.position.avg_cost };
  });
  check("chart: IREN's average cost is a 2px line with an axis label",
        lines.cost && lines.cost.lineWidth === 2 && lines.cost.axisLabelVisible && lines.cost.title === "avg cost" && Math.abs(lines.cost.price - lines.avg) < 0.01,
        JSON.stringify(lines.cost));
  check("chart: the verdict's prices are drawn, one line per level it has",
        lines.want > 0 && lines.titles.length === lines.want
        && lines.titles.every(t => ["buy at", "sell into", "wrong below", "flips"].includes(t)),
        JSON.stringify(lines));
  check("chart: one attribution for the whole chart, not one per pane",
        await page.$$eval("#chartpanel a[href*='tradingview']", a => a.length) === 1
        && await page.evaluate(() => PANES.length) >= 1,
        `${await page.$$eval("#chartpanel a[href*='tradingview']", a => a.length)} logos over ${await page.evaluate(() => PANES.length + 1)} panes`);
  // The linear axis never runs below zero for a name that never has.
  const axisFloor = await page.evaluate(() => {
    const y = CANDLES.priceToCoordinate(0);
    const h = document.querySelector("#pricechart").clientHeight - CHART.timeScale().height();
    return { zeroY: y, paneH: h };
  });
  check("chart: the price axis stops at zero on a linear scale",
        axisFloor.zeroY == null || axisFloor.zeroY >= axisFloor.paneH - 1, JSON.stringify(axisFloor));
  // The chrome above the candles is one row plus two closed folds.
  const chrome = await page.evaluate(() => ({
    tools: document.querySelector("#toolsfold").open, levels: document.querySelector("#levelsfold").open,
    setupInRow: !!document.querySelector("#chartbar #setup"),
    rowItems: ["symbol", "tf", "rangetoggle", "loadsym", "refresh", "fullscreen"].every(id => document.querySelector(`#chartbar #${id}`)),
    top: document.querySelector("#pricechart").getBoundingClientRect().top + scrollY,
  }));
  check("chart: the toolbar is one row and the folds start closed",
        chrome.rowItems && !chrome.setupInRow && !chrome.tools && !chrome.levels && chrome.top < 560, JSON.stringify(chrome));

  // The method picker used to be filled only by a COMPLETED run, so it sat
  // empty for the ~30s a cold walk-forward takes and the tab read as broken.
  // It must be populated and explained the moment the tab opens, with nothing
  // computed until Run is pressed.
  await go(page, "bot/backtest");
  await page.waitForFunction(
    () => document.querySelector("#btmethod") &&
          document.querySelector("#btmethod").options.length > 0,
    { timeout: 15000 }).catch(() => {});
  const btOpts = await page.$eval("#btmethod", e => e.options.length);
  check("backtest: methods are listed without running anything", btOpts >= 3,
        `${btOpts} methods`);
  const btAbout = await page.$eval("#btabout", el => el.innerText.replace(/\s+/g, " "));
  check("backtest: the selected method explains itself before you run it",
        /invalidated by/i.test(btAbout) && btAbout.length > 120, btAbout.slice(0, 70));
  // Opening the tab may SHOW a stored run (with its date on it) but must not
  // compute one: the Run button stays enabled and nothing says "Running".
  const btRunBtn = await page.$eval("#btrun", el => ({disabled: el.disabled, text: el.innerText}));
  const btNote = await page.$eval("#btnote", el => el.innerText.replace(/\s+/g, " "));
  const btIdle = await page.$eval("#btcards", el => el.innerText.trim());
  check("backtest: opening the tab does not kick off a 30-second run",
        !btRunBtn.disabled && !/running/i.test(btRunBtn.text) && !/^Running/.test(btNote),
        `${btRunBtn.text} · ${btNote.slice(0, 50)}`);
  check("backtest: figures shown on open are a dated stored run, or nothing",
        btIdle === "" || /From the run on \d{4}-\d{2}-\d{2}/.test(btNote) || /No run recorded/.test(btNote),
        btNote.slice(0, 60));

  // Actually press Run once. Everything above proves the controls are filled;
  // only this proves a run completes and draws, which is the half that was
  // broken. The monthly method is chosen deliberately — it has the fewest
  // rebalance dates and finishes in a few seconds, where the daily one takes
  // minutes and would dominate the whole test run.
  await page.selectOption("#btmethod", "cantonese-cat-monthly-reversion");
  // Changing the method fetches that method's stored run and fills the form
  // from it. Let that land before pressing Run, or the run goes out with the
  // previous method's parameters and the stored-run render races the click.
  await page.waitForResponse(r => /\/api\/backtest\?last=1/.test(r.url()), { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(300);
  // Wait for the RUN's own response, not for figures or for the button: a
  // stored run's cards already carry a percent sign, and reading the button on
  // a timer measured how busy the smoke server was (a watchlist outlook and a
  // research scan from earlier tabs were still running, and the same 12-second
  // backtest took 68 seconds beside them). The response is the one event that
  // says the run finished; the button is judged after it.
  const btT0 = Date.now();
  const btRun = page.waitForResponse(r => /\/api\/backtest\?method=/.test(r.url()), { timeout: 330000 });
  await page.click("#btrun");
  const btWasBusy = await page.$eval("#btrun", el => el.disabled);
  check("backtest: pressing Run greys the button out while it runs", btWasBusy);
  const btResp = await btRun.catch(() => null);
  const btSecs = ((Date.now() - btT0) / 1000).toFixed(0);
  await page.waitForFunction(() => !document.querySelector("#btrun").disabled, { timeout: 20000 }).catch(() => {});
  const btCards = await page.$eval("#btcards", el => el.innerText.replace(/\s+/g, " "));
  check("backtest: a run produces figures for BOTH universes",
        /watchlist/i.test(btCards) && /control/i.test(btCards) && /%/.test(btCards),
        btCards.slice(0, 70));
  const btCanvas = await page.$$eval("#btchart canvas", c => c.length);
  check("backtest: the equity curve is drawn", btCanvas > 0, `${btCanvas} canvases`);
  const btBtn = await page.$eval("#btrun", e => e.disabled);
  check("backtest: the Run button comes back when the run finishes", btBtn === false,
        btResp ? `HTTP ${btResp.status()} after ${btSecs}s` : `no response within ${btSecs}s`);

  // The change-log panel was retired with the Phase 2 shell (it was
  // permanently hidden); the payload still carries the log, so the check
  // moves to that — an array, present even when nothing changed.
  const changed = await page.evaluate(() => typeof OUTLOOK !== "undefined" && OUTLOOK && Array.isArray(OUTLOOK.changed) ? OUTLOOK.changed.length : -1);
  check("outlook: the change log is carried, even when nothing changed",
        changed >= 0, `${changed} changes`);
  // A verdict names levels in words; the chart is where you check them. Going
  // to a bare chart and leaving somebody to find the toggles that reproduce
  // what they were just told is most of why it read as unverifiable.
  //
  // The tab switch is load-bearing: this block sits after the backtest section,
  // so the outlook panel is hidden and every selector below it times out
  // without saying which tab it was looking at.
  await go(page, "stocks/calls");
  await page.waitForSelector("#vdtable tr[data-vd]");
  await page.click("#vdtable tr[data-vd]:nth-of-type(2) td:first-child");
  await page.waitForSelector("#symread [data-chartfor]", { timeout: 30000 });
  await page.click("#symread [data-chartfor]");
  await page.waitForFunction(() => TAB === "chart" && CHART_STARTED === 0 && document.querySelector("#pricechart canvas"),
    null, { timeout: 30000 }).catch(() => {});
  const onChart = await page.evaluate(() =>
    [...document.querySelectorAll("#tabs button")].find(b => b.classList.contains("on")).dataset.section);
  check("outlook: a verdict can be seen on the chart", onChart === "chart", onChart);
  const toggles = await page.evaluate(() => ["stLines", "stZones", "stFib"]
    .filter(i => document.querySelector("#" + i) && document.querySelector("#" + i).checked));
  check("outlook: it turns on the structure the verdict was read from",
        toggles.length === 3, toggles.join(","));
  const canv = await page.$$eval("#pricechart canvas", c => c.length);
  check("outlook: and the chart actually draws", canv > 0, `${canv} canvases`);

  // The cloud is the most-cited reason in every verdict. It used to be drawn
  // on the card's mini chart and checked there; the mini chart is retired
  // with the card, and the main chart's cloud is measured above (drawn as a
  // band, not a wash). What the card's legend said — what the cloud IS and
  // which side price is on — the read still says, and it must follow the
  // chart when panned, which the overlay canvas only does if it is repainted
  // from the chart's own coordinates.
  await page.evaluate(() => { INDS = [{ name: "ichimoku", args: [9, 26, 52] }]; loadChart(CHART_SYMBOL); });
  await page.waitForFunction(() => document.querySelector("#pricechart canvas.cloudband"), null, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(600);
  const bandAt = () => page.evaluate(() => {
    const cv = document.querySelector("#pricechart canvas.cloudband");
    if (!cv || !cv.width) return { n: 0, cx: 0 };
    const px = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data;
    const W = cv.width;
    let n = 0, sx = 0;
    for (let i = 0; i < px.length; i += 4) { if (px[i + 3] > 5) { n++; sx += (i / 4) % W; } }
    return { n, cx: n ? Math.round(sx / n) : 0 };
  });
  const bandBefore = await bandAt();
  check("chart: the cloud is drawn at all", bandBefore.n > 2000, JSON.stringify(bandBefore));
  await page.$eval("#pricechart", el => el.scrollIntoView({ block: "center" }));
  const cbox = await page.locator("#pricechart").boundingBox();
  await page.mouse.move(cbox.x + cbox.width / 2, cbox.y + cbox.height / 2);
  await page.mouse.down();
  // Backwards in time, which always has somewhere to go; dragging the other way
  // sits against the newest bar and moves nothing.
  await page.mouse.move(cbox.x + cbox.width / 2 + 220, cbox.y + cbox.height / 2, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(600);
  const bandAfter = await bandAt();
  check("chart: the cloud follows the chart when it is panned",
        bandAfter.cx !== bandBefore.cx || bandAfter.n !== bandBefore.n,
        `${JSON.stringify(bandBefore)} -> ${JSON.stringify(bandAfter)}`);

  // The chart ended at MAX(txn_date) — the last time anything was TRADED —
  // so every chart stopped on the date of the most recent transaction in the
  // ledger while the price data ran days past it. Refreshing prices could not
  // move it, because prices were never the limit.
  // Compared PER SYMBOL. Against the ledger-wide newest bar this failed on a
  // benchmark that legitimately lags its own feed, which is a different fact
  // from the chart being clamped.
  const freshness = await page.evaluate(async () => {
    const o = await (await fetch("/api/outlook")).json();
    const sym = Object.keys(o.verdicts || {})[0];
    if (!sym) return null;
    // The newest bar anything was scored from, not the date of the scoring:
    // before the close those differ by a day, and the chart is right to end
    // at the last close.
    const scoredTo = o.verdicts[sym].price != null ? (o.prices_asof || o.asof) : null;
    const c = await (await fetch(
      `/api/chart?symbol=${encodeURIComponent(sym)}&timeframe=D`)).json();
    const bars = c.bars || [];
    return { sym, chart: bars.length ? bars[bars.length - 1].time : null,
             scoredTo };
  });
  check("the chart runs to the last CLOSE, not to the last trade",
        freshness && freshness.chart && freshness.scoredTo
        && freshness.chart >= freshness.scoredTo,
        JSON.stringify(freshness));

  await page.click('.subtabs[data-section="chart"] button[data-sub="read"]');
  await page.evaluate(() => document.querySelectorAll("#symread details").forEach(d => { d.open = true; }));
  const cloudText = await page.$eval("#symread", el => el.innerText);
  // What the cloud IS and which side price is on. The periods used to be
  // spelled out here too and were removed as clutter, so this no longer asserts
  // them — a test that pins wording nobody wants is a test that blocks removing
  // it.
  check("the read: it explains what the cloud is",
        /26 sessions ahead/.test(cloudText) && /(above|below|inside) the cloud/.test(cloudText),
        cloudText.slice(0, 60));
  // The chart's own reading sits under the card, labelled as a second reading.
  const ta = await page.$eval("#tapanel", el => el.innerText.replace(/\s+/g, " "));
  check("the read: the technical read is drawn under the card", ta.length > 40, ta.slice(0, 60));

  // Fear reads red and greed green, the way everybody publishes this index. The
  // contrarian argument is the opposite and belongs in the sentence, not the
  // colour, where it would just look like a bug. The mood lives under Today →
  // Market now.
  await go(page, "today/market");
  const mood = await page.evaluate(() => {
    const el = document.querySelector("#mktmood div[style*='font-size:30px']");
    if (!el) return null;
    return { colour: getComputedStyle(el).color,
             score: parseFloat(el.textContent.trim()) };
  });
  if (mood) {
    const red = /rgb\(2\d\d, ?\d?\d, ?\d?\d\)/.test(mood.colour)
             || /rgb\(25\d, ?1\d\d, ?\d?\d\)/.test(mood.colour);
    check("outlook: a fearful reading is painted red, not green",
          mood.score >= 45 || red, `${mood.score} is ${mood.colour}`);
  } else {
    check("outlook: the fear and greed panel rendered", false, "no score element");
  }

  // The calibration panel is hidden until it has grades; until then the record
  // panel carries the sample floor and the date the first grades land. The
  // record is under AI Trade Bot → Its record.
  await go(page, "bot/record");
  const cal = await page.$eval("#calib", el => el.hidden ? "" : el.innerText.replace(/\s+/g, " "));
  const rec = await page.$eval("#scorecard", el => el.innerText.replace(/\s+/g, " "));
  check("outlook: the record states the calibration's own sample floors",
        /\d+ calls spanning \d+ separate days/.test(cal) || /By confidence/i.test(cal) || /20 calls on 10 separate days/.test(rec),
        (cal || rec).slice(0, 80));

  const score = await page.$eval("#scorecard", el => el.innerText.replace(/\s+/g, " "));
  check("holdings: the record states its sample size before any claim",
        /graded call/i.test(score) && /SPY/i.test(score), score.slice(0, 70));

  // ----------------------------------------------------- Today → What to do ----
  // ONE ranked list: dollars first, every row saying what it is and what to
  // do, ticks that hide a row, and a name that opens the page.
  await go(page, "today/todo");
  await page.waitForFunction(() => document.querySelector("#todo .attnrow") || /Nothing needs you today/.test(document.querySelector("#todo").innerText), null, { timeout: 60000 }).catch(() => {});
  // Rows past the cap sit in a closed fold, where innerText is empty; open it to read them.
  await page.evaluate(() => document.querySelectorAll("#todo details").forEach(d => { d.open = true; }));
  const todoRows = await page.$$eval("#todo .attnrow", rows => rows.map(r => ({
    amt: parseFloat((r.querySelector(".attnamt").innerText || "0").replace(/[^\d.]/g, "")) || 0,
    what: (r.querySelector(".todo1") || {}).innerText || "", todo: (r.querySelector(".todo2") || {}).innerText || "",
    kind: r.dataset.kind, tick: !!r.querySelector("input[data-look]"), go: (r.querySelector(".attngo") || {}).innerText || "" })));
  check("today: the list has rows (or says nothing needs you)", todoRows.length > 0 || /Nothing needs you today/.test(await page.$eval("#todo", el => el.innerText)), `${todoRows.length} rows`);
  // A plan whose condition fired today is URGENT and sits above the money
  // order by design (todoItems sorts urgent first); the dollar order holds
  // from the first non-plan row down. Checking every row read a fired plan
  // as a broken sort on 2026-09-14.
  const fromMoney = todoRows.slice(todoRows.findIndex(r => r.kind !== "plan"));
  const dollared = fromMoney.filter(r => r.amt > 0).map(r => r.amt);
  check("today: rows are ranked by dollars at stake", dollared.every((v, i) => !i || v <= dollared[i - 1]), dollared.slice(0, 5).join(" > "));
  check("today: every row says what it is and what to do", todoRows.every(r => r.what.length > 8 && r.todo.length > 12 && r.tick && r.go.length > 1),
        JSON.stringify(todoRows.find(r => !(r.what.length > 8 && r.todo.length > 12)) || {}).slice(0, 120));
  check("today: no row is a severity word alone", todoRows.every(r => !/^(act|warn|info)$/i.test(r.what.trim())));
  const todoKinds = new Set(todoRows.map(r => r.kind));
  check("today: the list merges more than one source", todoKinds.size >= 2 || todoRows.length < 2, [...todoKinds].join(","));
  const dupes = await page.evaluate(() => { const ks = [...document.querySelectorAll("#todo input[data-look]")].map(i => i.dataset.lookkind + "|" + i.dataset.look); return ks.length - new Set(ks).size; });
  check("today: the list is deduped", dupes === 0, `${dupes} duplicate keys`);
  const capped = await page.$$eval("#todo > .attnrow", r => r.length);
  check("today: the list is capped, with the rest behind a fold", capped <= 12 && (todoRows.length <= 12 || await page.$("#todo details") !== null), `${capped} shown of ${todoRows.length}`);
  // A tick hides the row (and the same tick on the source panel), and comes
  // back through "show them".
  if (todoRows.length) {
    const before = await page.$$eval("#todo .attnrow", r => r.length);
    await page.click("#todo .attnrow input[data-look]");
    await page.waitForFunction(n => document.querySelectorAll("#todo .attnrow").length !== n, before, { timeout: 3000 }).catch(() => {});
    const after = await page.$$eval("#todo .attnrow", r => r.length);
    check("today: ticking a row hides it", after === before - 1, `${before} -> ${after}`);
    await page.click("#todo [data-showlooked]").catch(() => {});
    await page.waitForFunction(() => document.querySelector("#todo .attnrow.looked"), null, { timeout: 3000 }).catch(() => {});
    check("today: 'show them' brings it back, marked", await page.$$eval("#todo .attnrow.looked", r => r.length) === 1);
    await page.click("#todo .attnrow.looked input[data-look]");
    await page.waitForFunction(() => !document.querySelector("#todo .attnrow.looked"), null, { timeout: 3000 }).catch(() => {});
  }
  // A name on the list opens its page on The read (a plan row opens Plan &
  // levels on purpose, so the check takes the first row that is not one).
  const goSym = await page.$("#todo .attngo[data-open]:not([data-opensub])");
  if (goSym) {
    const want = await goSym.evaluate(b => b.dataset.open);
    await goSym.click();
    await page.waitForFunction(s => document.querySelector("#symhead").innerText.startsWith(s), want, { timeout: 30000 }).catch(() => {});
    const h = await page.evaluate(() => location.hash);
    check("today: a name on the list opens its page on The read", await shown(page) === "chart/read" && h === `#chart/read?sym=${want}`, h);
  } else check("today: a name on the list opens its page on The read", true, "no named row today");
  // The full log is its own sub-tab, deduped, with the tick filter.
  await go(page, "today/alerts");
  const logRows = await page.$$eval("#alerts tr.alertrow", r => r.length);
  // One row per name, kind and day (the tick key is coarser on purpose: it
  // strips the numbers so the same fact on a later day stays ticked).
  const logDup = await page.evaluate(() => { const ks = [...document.querySelectorAll("#alerts tr.alertrow")].map(r => r.dataset.key); return ks.length - new Set(ks).size; });
  check("alerts: the full log is under Today → All alerts, deduped", logRows > 0 && logDup === 0, `${logRows} rows, ${logDup} dupes`);
  const alertOpen = await page.$("#alerts [data-open]");
  if (alertOpen) {
    const want = await alertOpen.evaluate(b => b.dataset.open);
    await alertOpen.click();
    await page.waitForFunction(s => document.querySelector("#symhead").innerText.startsWith(s), want, { timeout: 30000 }).catch(() => {});
    check("alerts: an alert opens the name's page on The read", await shown(page) === "chart/read", await shown(page));
  }
  // A plain name click — a watchlist row — opens the page on the chart.
  await go(page, "money/holdings");
  await page.waitForSelector("#holdings tr[data-sym]");
  const rowSym2 = await page.$eval("#holdings tr[data-sym]", el => el.dataset.sym);
  await page.click("#holdings tr[data-sym] td:nth-child(2)");
  await page.waitForFunction(s => location.hash === `#chart/chart?sym=${s}`, rowSym2, { timeout: 5000 }).catch(() => {});
  check("a name click anywhere opens the page on the chart", await shown(page) === "chart/chart" && (await page.evaluate(() => location.hash)) === `#chart/chart?sym=${rowSym2}`, await page.evaluate(() => location.hash));

  // ----------------------------------------------------------- setups ----
  // Every row leads with the three prices; the paragraph is behind "why".
  await go(page, "stocks/setups");
  await page.waitForSelector("#setupslist .lvl, #setupslist .note", { timeout: 120000 }).catch(() => {});
  const suHdr = await page.$eval("#setupslist tr:first-child", el => el.innerText.replace(/\s+/g, " ")).catch(() => "");
  const suFirst = await page.$$eval("#setupslist tr[data-setup]", rows => rows.length ? [...rows[0].querySelectorAll("td.lvl")].map(td => td.innerText.replace(/\s+/g, " ")) : []);
  const suRows = await page.$$eval("#setupslist tr[data-setup]", r => r.length);
  if (suRows) {
    check("setups: the columns lead with buy at / sell into / wrong below", /buy at.*sell into.*wrong below/i.test(suHdr), suHdr.slice(0, 80));
    check("setups: a row carries the three prices (a dash where none qualifies)", suFirst.length === 3 && suFirst.every(t => /\$\d|—/.test(t)), suFirst.join(" | "));
    check("setups: the paragraph is folded under why", await page.$("#setupslist tr[data-setup] details") !== null);
    const suSym = await page.$eval("#setupslist tr[data-setup]", el => el.dataset.setup);
    await page.click("#setupslist tr[data-setup] td:nth-child(5)");
    await page.waitForFunction(s => document.querySelector("#symhead").innerText.startsWith(s), suSym, { timeout: 30000 }).catch(() => {});
    check("setups: a row opens the name's page on The read", await shown(page) === "chart/read", await shown(page));
  } else check("setups: no setup tonight, said in words", /No setup tonight|Nothing held/.test(await page.$eval("#setupslist", el => el.innerText)));

  // ------------------------------------------------ Calls made, twice ----
  await go(page, "money/trades");
  await page.evaluate(() => { const d = document.querySelector("#jrnlfold"); if (d) d.open = true; });
  const j2 = await page.$eval("#jrnl2", el => el.innerText.replace(/\s+/g, " "));
  check("Calls made renders under Money → Trades too", j2.length > 40 && /SPY/.test(j2), j2.slice(0, 60));
  const j2App = await page.$$eval("#jrnl2 .jrow", rows => rows.filter(r => !/you|traded/i.test(r.children[0].innerText)).length);
  check("...and carries only the user's own calls there", j2App === 0, `${j2App} app rows`);
  await go(page, "bot/record");
  check("...while Its record keeps the whole log", await page.$eval("#jrnl", el => el.innerText.length) > 40);

  // --------------------------------- the 2026-09-13 review, on screen ----
  // Eric's first read of Phase 2 (D120–D127). Each item is checked where he
  // would look for it, because every one of them was a feature that either
  // rendered the wrong thing or nothing at all.
  // Holdings: the call column is the headline, the same word Today shows.
  await go(page, "money/holdings");
  await page.waitForFunction(() => document.querySelector("#holdings") && document.querySelector("#holdings").dataset.verdicts === "1", null, { timeout: 60000 }).catch(() => {});
  const callCells = await page.$$eval("#holdings [data-vd]", els => els.map(e => ({ sym: e.dataset.vd, word: (e.querySelector(".vd") || {}).innerText || "", tf: (e.querySelector(".vdconf") || {}).innerText || "" })));
  const headline = await page.evaluate(() => Object.fromEntries(Object.entries((OUTLOOK && OUTLOOK.verdicts) || {}).map(([s, v]) => [s, v.headline])));
  const mismatched = callCells.filter(c => headline[c.sym] && c.word.toLowerCase() !== headline[c.sym].toLowerCase());
  check("holdings: the call column shows the headline, not the daily", callCells.length > 2 && mismatched.length === 0, JSON.stringify(mismatched.slice(0, 2)));
  check("holdings: the call names its timeframe", callCells.some(c => /\b(day|wk|mo)\b/.test(c.tf)), callCells.slice(0, 2).map(c => c.tf).join(" | "));
  const dcaNote = await page.$eval("#panel-money", el => el.innerText).catch(() => "");
  check("holdings: the DCA tier is explained as sizing, not a call", /answer different questions/.test(dcaNote));

  // Watchlist: the group figure says what it is.
  await go(page, "stocks/watchlist");
  await page.waitForSelector("#wlgroups details", { timeout: 60000 }).catch(() => {});
  await page.selectOption("#wlgroup", "sector").catch(() => {});
  await page.waitForTimeout(500);
  const spark = await page.$eval("#wlgroups details summary .spark", el => el.innerText).catch(() => "");
  check("watchlist: the sector figure is labelled as the average one-month move", /avg 1m/.test(spark), spark);

  // Buy back: the sale column says whether it was a good sell, in words.
  await go(page, "stocks/rebuy");
  await page.waitForSelector("#rebuylist table tr", { timeout: 90000 }).catch(() => {});
  const rb = await page.$eval("#rebuylist", el => el.innerText.replace(/\s+/g, " ")).catch(() => "");
  check("buy back: the sale column says good sell or sold early", /good sell|sold early|about where you sold/.test(rb), rb.slice(0, 80));
  const rbTone = await page.$$eval("#rebuylist td div[style*='color']", els => els.map(e => e.style.color)).catch(() => []);
  check("buy back: the verdict on the sale is coloured", rbTone.some(c => /--up|--down/.test(c)), rbTone.slice(0, 3).join(","));

  // New Stocks: a row says what the company is and how it has moved.
  await go(page, "stocks/newstocks");
  await page.waitForSelector("#discover table tr", { timeout: 60000 }).catch(() => {});
  const nsHdr = await page.$eval("#discover table tr:first-child", el => el.innerText.replace(/\s+/g, " ")).catch(() => "");
  const nsRow = await page.$eval("#discover table tr:nth-child(2)", el => el.innerText.replace(/\s+/g, " ")).catch(() => "");
  check("new stocks: the columns say what it is and how it moved", /What it is/i.test(nsHdr) && /1m/i.test(nsHdr) && /52w/i.test(nsHdr), nsHdr.slice(0, 100));
  check("new stocks: a row carries a business line or says it is being looked up", /·|not in EDGAR/.test(nsRow), nsRow.slice(0, 100));

  // Their charts: one grid, filters by who, and side by side by name.
  await go(page, "follow/charts");
  await page.waitForFunction(() => document.querySelector("#sccharts") && document.querySelector("#sccharts").children.length > 0, null, { timeout: 60000 }).catch(() => {});
  const scAll = await page.$$eval("#sccharts .panel", e => e.length);
  // Every card's image is a real URL: http(s) or one of the app's own paths.
  // safeUrl used to pass only http(s), so every chart from X (/chart-x) and
  // from the Patreon (/chart-image) was an <img src="#"> — a blank card that
  // looked exactly like a chart never saved (D132).
  const scSrcs = await page.$$eval("#sccharts .panel img", els => els.map(e => e.getAttribute("src")));
  check("their charts: no card has lost its image to the URL guard", scSrcs.length > 0 && scSrcs.every(u => /^(https?:\/\/|\/(?!\/))/.test(u)), `${scSrcs.filter(u => !/^(https?:\/\/|\/(?!\/))/.test(u)).length} of ${scSrcs.length} bad`);
  const guard = await page.evaluate(() => [safeUrl("/chart-x?id=1&n=0"), safeUrl("https://a.b/c.png"), safeUrl("javascript:alert(1)"), safeUrl("//evil.example/x"), safeUrl("")]);
  check("safeUrl passes http(s) and the app's own paths, refuses scripts and scheme-relative hosts",
    guard[0] === "/chart-x?id=1&n=0" && guard[1] === "https://a.b/c.png" && guard[2] === "#" && guard[3] === "#" && guard[4] === "#", guard.join(" "));
  const whoOpts = await page.$$eval("#scauthor option", o => o.map(x => x.value).filter(Boolean));
  // One person, one entry: an "@handle" suffix on an X row must not make a
  // second "StonkChris" beside the Substack's (D134).
  const whoBare = whoOpts.map(w => w.split(" (")[0]);
  check("their charts: the Who list names each person once across X, Substack and Patreon", whoOpts.every(w => !/ \(@/.test(w)) && new Set(whoBare).size === whoBare.length, whoOpts.filter(w => / \(@/.test(w) || whoBare.filter(b => b === w.split(" (")[0]).length > 1).join(", "));
  if (scAll && whoOpts.length) {
    await page.selectOption("#scauthor", whoOpts[0]);
    await page.waitForTimeout(400);
    const scOne = await page.$$eval("#sccharts .panel", e => e.length);
    const scWho = await page.$$eval("#sccharts .panel .note", els => els.map(e => e.innerText));
    check("their charts: filtering by who narrows the grid to that person", scOne <= scAll && scWho.length > 0 && scWho.every(t => t.includes(whoOpts[0].split(" (")[0]) || !/·/.test(t)), `${scOne} of ${scAll}, ${whoOpts[0]}`);
    await page.selectOption("#scauthor", "");
    await page.check("#scbyname");
    await page.waitForTimeout(400);
    const groups = await page.$$eval("#sccharts details.group", ds => ds.map(d => d.querySelector("summary").innerText.replace(/\s+/g, " ")));
    check("their charts: side by side groups the charts by name with the people who posted them", groups.length > 0 && /\d+ (person|people)/.test(groups[0]), groups.slice(0, 2).join(" | "));
    await page.uncheck("#scbyname");
  } else check("their charts: nothing saved, said in words", /No charts saved|No saved chart/.test(await page.$eval("#scnote", el => el.innerText)));

  // Taxes: the taxable account's year is in the floor, and the gap is in words.
  await go(page, "budget/taxes");
  await page.waitForFunction(() => document.querySelector("#bgTax") && /Trades in the taxable account|No tax table/.test(document.querySelector("#bgTax").innerText), null, { timeout: 30000 }).catch(() => {});
  const tax = await page.$eval("#bgTax", el => el.innerText.replace(/\s+/g, " "));
  check("taxes: trades, dividends and interest are rows in the floor", /Trades in the taxable account/.test(tax) && /Dividends and interest/.test(tax), tax.slice(0, 80));
  check("taxes: what investing did to the bill is its own row", /(Extra tax from|Tax saved by) investing/.test(tax));
  check("taxes: the withholding gap is worded as paid in against what is owed", /Paid in (more|less) than the floor owes/.test(tax) || !/Paid in so far/.test(tax));

  // Recurring: every price a charge has billed at is on its row.
  await go(page, "budget/recurring");
  await page.waitForSelector("#bgRecur table.reclist tr", { timeout: 30000 }).catch(() => {});
  const recHdr = await page.$eval("#bgRecur table.reclist tr:first-child", el => el.innerText.replace(/\s+/g, " ")).catch(() => "");
  const recChain = await page.$$eval("#bgRecur table.reclist tr td:nth-child(5)", tds => tds.map(t => t.innerText.replace(/\s+/g, " ")));
  check("recurring: a price-over-time column", /Price over time/i.test(recHdr), recHdr.slice(0, 80));
  check("recurring: a repriced bill shows its steps and the change since the first", recChain.some(t => /→/.test(t) && /[+−-]\d+% since/.test(t)), recChain.filter(t => /→/.test(t)).slice(0, 2).join(" | "));

  // ------------------------------------------------------------ phone ----
  // The same shell at 390px: the top bar gives way to a bottom bar, More
  // opens the three sections that do not fit, sub-tabs are a chip row, and
  // nothing pushes the page sideways.
  const phone = watch(await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }));
  await phone.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
  // The bars are wired after the first portfolio fetch lands, so wait for it.
  await phone.waitForFunction(
    () => { const c = document.querySelector("#cards"); return c && /\$/.test(c.innerText); },
    { timeout: 60000 }).catch(() => {});
  check("phone: lands on My Money → Overview too", await shown(phone) === "money/overview", await shown(phone));
  const navBars = await phone.evaluate(() => ({
    top: getComputedStyle(document.querySelector("#tabs")).display,
    bottom: getComputedStyle(document.querySelector("#phonebar")).display,
    fixed: getComputedStyle(document.querySelector("#phonebar")).position,
  }));
  check("phone: the bottom bar replaces the top one", navBars.top === "none" && navBars.bottom === "flex" && navBars.fixed === "fixed",
        JSON.stringify(navBars));
  await phone.click(`#phonebar button[data-section="stocks"]`);
  await phone.waitForFunction(() => document.querySelector("section.tab:not([hidden])").dataset.panel === "stocks", null, { timeout: 3000 }).catch(() => {});
  check("phone: the bottom bar switches sections", (await shown(phone)).startsWith("stocks/"), await shown(phone));
  await phone.click("#phonemore");
  await phone.waitForFunction(() => !document.querySelector("#moresheet").hidden, null, { timeout: 3000 }).catch(() => {});
  check("phone: More opens a sheet", await phone.$eval("#moresheet", el => !el.hidden && el.querySelectorAll("button").length === 3));
  await phone.click(`#moresheet button[data-section="bot"]`);
  await phone.waitForFunction(() => document.querySelector("section.tab:not([hidden])").dataset.panel === "bot", null, { timeout: 3000 }).catch(() => {});
  check("phone: the sheet opens its section and closes",
        (await shown(phone)).startsWith("bot/") && await phone.$eval("#moresheet", el => el.hidden), await shown(phone));
  await phone.click(`#phonebar button[data-section="money"]`);
  await phone.click(`.subtabs[data-section="money"] button[data-sub="sectors"]`);
  await phone.waitForFunction(() => document.querySelector('.subtabs[data-section="money"] button.on').dataset.sub === "sectors", null, { timeout: 3000 }).catch(() => {});
  const chip = await phone.evaluate(() => {
    const row = document.querySelector('.subtabs[data-section="money"]');
    const b = row.querySelector("button.on"), r = b.getBoundingClientRect(), rr = row.getBoundingClientRect();
    return { on: b.dataset.sub, inView: r.left >= rr.left - 1 && r.right <= rr.right + 1, scrolls: row.scrollWidth > row.clientWidth };
  });
  check("phone: the active sub-tab chip is scrolled into view", chip.on === "sectors" && chip.inView, JSON.stringify(chip));
  const overflow = await phone.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check("phone: nothing pushes the page sideways", overflow <= 0, `${overflow}px over`);
  // The symbol page stacks header → chip row → content, and its tap targets
  // are real ones.
  await phone.evaluate(() => openSymbol("IREN", "plan"));
  await phone.waitForSelector("#symplan .ladder", { timeout: 60000 }).catch(() => {});
  const stack = await phone.evaluate(() => {
    const h = document.querySelector("#symhead").getBoundingClientRect(), t = document.querySelector('.subtabs[data-section="chart"]').getBoundingClientRect(), c = document.querySelector("#symplan").getBoundingClientRect();
    const small = [...document.querySelectorAll("#symhead button, #symplan button, .subtabs[data-section=chart] button")].filter(b => b.getBoundingClientRect().height < 40).length;
    return { order: h.bottom <= t.top + 1 && t.bottom <= c.top + 1, small, over: document.documentElement.scrollWidth - document.documentElement.clientWidth };
  });
  check("phone: the symbol page stacks header, chips, content", stack.order && stack.over <= 0, JSON.stringify(stack));
  check("phone: its tap targets are at least 40px", stack.small === 0, `${stack.small} small`);
  // The chart on the phone: the viewport less the chrome, never under 420px,
  // with the OHLC readout on one line that clips rather than wraps.
  await phone.click(`.subtabs[data-section="chart"] button[data-sub="chart"]`);
  await phone.waitForFunction(() => typeof CANDLES !== "undefined" && CANDLES && CANDLES.data().length > 0 && CHART_DRAWN === "IREN", null, { timeout: 60000 }).catch(() => {});
  await phone.waitForTimeout(800);
  const phoneChart = await phone.evaluate(() => ({
    h: document.querySelector("#pricechart").getBoundingClientRect().height,
    readout: document.querySelector("#readout").getBoundingClientRect().height,
    span: (() => { const r = CHART.timeScale().getVisibleLogicalRange(); return r ? Math.round(r.to - r.from) : null; })(),
    over: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  }));
  check("phone: the chart is at least 420px tall", phoneChart.h >= 420 && phoneChart.over <= 0, JSON.stringify(phoneChart));
  check("phone: the OHLC readout is one line", phoneChart.readout > 0 && phoneChart.readout <= 24, `${phoneChart.readout}px`);
  await phone.click(`#phonebar button[data-section="today"]`);
  await phone.click(`.subtabs[data-section="today"] button[data-sub="todo"]`);
  await phone.waitForSelector("#todo .attnrow", { timeout: 30000 }).catch(() => {});
  const wrap = await phone.evaluate(() => {
    const r = document.querySelector("#todo .attnrow"); if (!r) return null;
    const a = r.querySelector(".attnamt").getBoundingClientRect(), t = r.querySelector(".attntext").getBoundingClientRect(), g = r.querySelector(".attngo").getBoundingClientRect();
    return { amtClear: a.bottom <= t.top + 1 || a.right <= t.left, goTall: g.height >= 40, over: document.documentElement.scrollWidth - document.documentElement.clientWidth };
  });
  check("phone: a Today row wraps with the dollar figure clear of the text", !wrap || (wrap.amtClear && wrap.goTall && wrap.over <= 0), JSON.stringify(wrap));
  await phone.close();

  check("no console errors anywhere in that run", errors.length === 0,
        errors.slice(0, 2).join(" | "));
} catch (err) {
  check("the run completed without throwing", false, String(err.message).slice(0, 140));
} finally {
  await browser.close();
}

const failed = checks.filter(c => !c.ok);
for (const c of checks) {
  console.log(`  ${c.ok ? "PASS" : "FAIL"}  ${c.label.padEnd(58)} ${c.detail}`);
}
console.log(`\n  ${checks.length - failed.length}/${checks.length} passed`);
process.exit(failed.length ? 1 : 0);
