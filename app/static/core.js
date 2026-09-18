// Shared helpers, the token fetch wrapper (first, so every later request carries it), the theme and
// chart palette, saved settings, the section router and the phone bar.
// One of the dashboard's scripts (see dashboard.html): a classic script sharing the page's
// global scope with the others, loaded in the order the tags there give.

const $ = s => document.querySelector(s);

// Every request to /api/ carries the token the server stamped into <head> (see
// TOKEN in web.py): a page elsewhere on the internet cannot read that tag, so
// it cannot forge the header, and that is what stops it deleting watchlist rows
// through an <img> when the app is open on the phone. window.fetch is wrapped
// so the hundred-odd call sites, drawings.js included, need no change; the
// same header goes on XMLHttpRequest in case anything ever uses it.
const APP_TOKEN = ($('meta[name="app-token"]') || {}).content || "";

{
  const isApi = u => { try{ const x = new URL(u, location.href); return x.origin === location.origin && x.pathname.startsWith("/api/"); }catch(e){ return false; } };
  const rawFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = input instanceof Request ? input.url : String(input);
    if(APP_TOKEN && isApi(url)){
      init = Object.assign({}, init);
      const h = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
      h.set("X-App-Token", APP_TOKEN);
      init.headers = h;
    }
    return rawFetch(input, init);
  };
  const rawOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...rest){
    rawOpen.call(this, method, url, ...rest);
    if(APP_TOKEN && isApi(url)) this.setRequestHeader("X-App-Token", APP_TOKEN);
  };
}

// Almost everything rendered here is curated text from this project's own
// modules, but symbols and account names come from imported statements, and
// building HTML from those unescaped is how a stray ampersand silently eats the
// rest of a row.
const esc = v => String(v == null ? "" : v)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

// Links and image sources that come from fetched content — Substack posts,
// email bodies — are escaped for HTML but were never checked for scheme: a
// javascript: URL survives esc() intact. Anything that is not http or https
// is pointed at nothing.
// A data-derived href or src: an http or https URL, or one of the app's own paths (a
// single leading slash — "//host" would be scheme-relative and is refused).
// Until 2026-09-17 only those URLs passed, and the app's own /chart-x and
// /chart-image routes came out as "#": every chart from X and from the Value
// Trader's Patreon rendered as a blank card on Their charts since D127, while
// the Substack ones (CDN URLs) showed, which is how "the FPS chart from
// September" (his X post of 2026-09-15) looked missing (D132).
const safeUrl = u => /^(https?:\/\/|\/(?!\/))/i.test(u || "") ? u : "#";

const pctOrDash = n => n==null?"—":n;

// The one place a dollar figure is formatted. The sign goes BEFORE the "$" and
// is a real minus (U+2212): toLocaleString on a negative used to give "$-0.79"
// on every sell in the fills panel while the same loss read "−$0.79" elsewhere.
const money = n => n == null ? "—"
  : (n < 0 ? "−" : "") + "$" + Math.abs(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});

// A change in dollars, signed both ways: "+$1,234.56" / "−$1,234.56", and
// unsigned when it rounds to nothing (see FLAT below).
const moneyDelta = n => n == null ? "—" : sign(n) + money(Math.abs(n));

const pct = n => n == null ? "—" : (n*100).toFixed(2) + "%";

// Whole percents, for prose. Two decimals belong in a table, not a sentence.
const pct0 = n => n == null ? "—" : Math.round(n*100) + "%";

function line(points, w, h, min, max, color, dash){
  // An empty ledger produces a series of exactly ONE point, and i/(1-1) is
  // 0/0 — every coordinate came out NaN and the browser rejected the whole
  // path with 'Expected number, "MNaN 172.0"'. Nothing here has more than one
  // point until a transaction is imported, so this is the first chart a new
  // user ever sees.
  if(!points.length) return "";
  const xs = (i) => points.length < 2 ? w / 2 : (i/(points.length-1))*w;
  const ys = (v) => h - ((v-min)/((max-min)||1))*h;
  const d = points.map((p,i)=> (i?"L":"M") + xs(i).toFixed(1) + " " + ys(p).toFixed(1)).join(" ");
  // The user's line is 2.5px solid, a benchmark 1.5px dashed; non-scaling so
  // the weights hold whatever width the SVG is drawn at.
  return `<path d="${d}" fill="none" stroke="${color}" stroke-width="${dash ? 1.5 : 2.5}" vector-effect="non-scaling-stroke"
          stroke-linejoin="round" stroke-linecap="round" ${dash?`stroke-dasharray="5 4"`:""}/>`;
}

function vdPill(v, conf, record){
  const k = VD_LABEL[v] ? v : "none";
  // The confidence word is read off the past record; the title says which
  // numbers it came from, so "high" is never a bare adjective.
  const title = record && record.text ? ` title="${esc(record.text)}"` :
    (conf && conf !== "none" ? ` title="No measured record for this timeframe yet: the word comes from the fifth of the measured score alone."` : "");
  return `<span class="vd vd-${k}">${esc(VD_LABEL[v]||"—")}</span>` +
    (conf && conf !== "none" ? `<span class="vdconf"${title}>${esc(conf)}${record && record.mean_excess != null ? ` <span class="note">${record.mean_excess >= 0 ? "+" : ""}${(record.mean_excess*100).toFixed(1)}%</span>` : ""}</span>` : "");
}

// On a phone the wide tables kept every desktop column and scrolled sideways
// inside their panel — the Outlook holdings table was 1,464px on a 390px
// screen. Each table here keeps the columns named, by header text, and the
// rest get .phone-hide. Applied whenever rows are added, so a column painted
// later (the Holdings verdict) is handled too; on a desktop nothing changes.
const PHONE_COLS = {
  // The three prices are what a phone reader wants first; the pills follow.
  "#vdtable": ["symbol", "daily", "buy at", "sell into", "wrong below"],
  "#holdings": ["symbol", "price", "%", "call"],
  "#wlgroups table": ["symbol", "price", "1m", "rs", "call", "note"],
  // #setupslist stacks each row (.stacklist) rather than hiding columns.
  "#bench": ["", "index", "you", "difference"],
  "#conctable": ["symbol", "weight", "risk share", "risk vs weight"],
  "#outsidetable table": ["date", "symbol", "call", "21d", "what"],
  "#bgCats": ["category", "this month", "typical", "change"],
  "#themeexp": ["theme", "weight", "value", "1m"],
  "#accts": ["account", "cash", "value"],
  "#alerts table": ["", "your level", "app level", "call changed", "first reading", "floor", "ladder", "wash", "earnings", "market", "fear", "dca", "iren", "level"],
  "#trades": ["exited", "symbol", "p/l", "%", "held"],
  "#emailtrades table": ["traded", "action", "symbol", "price", "status"],
  "#posmoves table": ["symbol", "from peak", "given back", "worth a look"],
  "#acctrisk": ["account", "value", "max drawdown", "now"],
  "#sectorexp": ["sector", "weight", "1m", "3m", "avg"],
  "#resdetail table": ["symbol", "score"],
  "#bttable": ["universe", "cagr", "max dd", "vs spy"],
  "#bgUn": ["merchant", "total", "seen", "categorise"],
};

function applyPhoneColumns(){
  const phone = window.innerWidth <= 640;
  // A column that is a dash in every row says nothing and costs the width of
  // its header: "Next rung" on Holdings while the ladder is switched off. Hidden
  // at every width, and shown again the moment one cell has a value.
  document.querySelectorAll("#holdings").forEach(t => {
    const rows = [...t.querySelectorAll("tr")];
    const head = rows[0]; if(!head) return;
    const i = [...head.children].findIndex(th => th.textContent.trim().toLowerCase().startsWith("next rung"));
    if(i < 0) return;
    const body = rows.slice(1).filter(tr => tr.children.length > i + 1);
    const empty = body.length > 0 && body.every(tr => ["—", "…"].includes(tr.children[i].textContent.trim()));
    rows.forEach(tr => { if(tr.children[i] && tr.children.length > i + 1) tr.children[i].classList.toggle("col-empty", empty); });
  });
  Object.entries(PHONE_COLS).forEach(([sel, keep]) => {
    document.querySelectorAll(sel).forEach(t => {
      const head = t.querySelector("tr");
      if(!head) return;
      const ths = [...head.children];
      let keepIdx = ths.map((th, i) => { const txt = th.textContent.trim().toLowerCase(); return keep.some(k => k === "" ? txt === "" : txt.startsWith(k)) ? i : -1; }).filter(i => i >= 0);
      if(sel === "#alerts table") keepIdx = [0, 2, 3];          // tick, kind, message; the date is in the message's row order, the channel is noise
      if(!keepIdx.length) return;
      [...t.querySelectorAll("tr")].forEach(tr => {
        if(tr.children.length < 2) return;
        [...tr.children].forEach((c, i) => { c.classList.toggle("phone-hide", phone && !keepIdx.includes(i) && i < ths.length); });
      });
    });
  });
}

let PHONE_COLS_TIMER = null;

new MutationObserver(() => { clearTimeout(PHONE_COLS_TIMER); PHONE_COLS_TIMER = setTimeout(applyPhoneColumns, 120); })
  .observe(document.body, {childList: true, subtree: true});

window.addEventListener("resize", () => { clearTimeout(PHONE_COLS_TIMER); PHONE_COLS_TIMER = setTimeout(applyPhoneColumns, 150); });

// The filter bar on a phone: one line that says what is set, tap to change.
function wireFilterToggle(){
  const t = $("#filtertoggle"), bar = $("#filters");
  if(!t || !bar || t.dataset.wired) return;
  t.dataset.wired = "1";
  const summary = () => {
    const per = $("#period"), sc = $("#scope");
    const perText = per && per.options[per.selectedIndex] ? per.options[per.selectedIndex].text : "";
    const scText = sc && sc.options[sc.selectedIndex] ? sc.options[sc.selectedIndex].text : "";
    const el = $("#filtersummary"); if(el) el.textContent = `· ${perText} · ${scText}`;
  };
  summary();
  ["period", "scope", "from", "to"].forEach(id => { const e = $("#" + id); if(e) e.addEventListener("change", summary); });
  t.addEventListener("click", () => { bar.classList.toggle("open"); t.setAttribute("aria-expanded", bar.classList.contains("open") ? "true" : "false"); });
}

document.addEventListener("DOMContentLoaded", wireFilterToggle);

document.addEventListener("DOMContentLoaded", () => { const a = $("#gsopen"); if(a) a.addEventListener("click", ev => { ev.preventDefault(); showTab("overview"); openGetStarted(); }); });
if(document.readyState !== "loading") wireFilterToggle();

// ---- the theme toggle -------------------------------------------------------
// System / Light / Dark in the header. The choice is stored as portfolio.theme
// and applied by the inline script in <head> before first paint; this wires
// the buttons and re-colours what the stylesheet cannot reach — the canvas
// charts, which hold their colours as literals from chartTheme().
const THEME_KEY = "portfolio.theme";

function themeChoice(){
  try{ const t = localStorage.getItem(THEME_KEY); return t === "light" || t === "dark" ? t : "system"; }
  catch(e){ return "system"; }
}

function applyTheme(choice, repaint){
  if(choice === "light" || choice === "dark") document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  try{ choice === "system" ? localStorage.removeItem(THEME_KEY) : localStorage.setItem(THEME_KEY, choice); }catch(e){}
  document.querySelectorAll("#theme button").forEach(b => {
    const on = b.dataset.theme === choice;
    b.classList.toggle("on", on); b.setAttribute("aria-pressed", on ? "true" : "false");
  });
  if(repaint) repaintCharts();
}

// Everything drawn on a canvas keeps the colours it was built with, so a
// theme change rebuilds the price chart for its symbol and re-skins the
// smaller charts in place. The SVG charts read the tokens and follow the
// stylesheet on their own.
function repaintCharts(){
  const th = chartTheme();
  PALETTE = palette();
  if(typeof STYLE !== "undefined" && STYLE){ STYLE = loadStyle(); if($("#cUp")) styleToForm(); }
  const skin = c => { try{ c.applyOptions({layout:{textColor:th.text}, grid:{horzLines:{color:th.grid}, vertLines:{color:"transparent"}},
    rightPriceScale:{borderColor:th.grid}, timeScale:{borderColor:th.grid}}); }catch(e){} };
  [typeof DD_CHART !== "undefined" && DD_CHART, typeof BT_CHART !== "undefined" && BT_CHART].forEach(c => c && skin(c));
  if(typeof CHART !== "undefined" && CHART && CHART_SYMBOL) loadChart(CHART_SYMBOL);
}

function wireTheme(){
  const box = $("#theme");
  if(!box || box.dataset.wired) return;
  box.dataset.wired = "1";
  applyTheme(themeChoice(), false);
  box.addEventListener("click", e => {
    const b = e.target.closest("button[data-theme]");
    if(b) applyTheme(b.dataset.theme, true);
  });
  // On "system" the charts follow the OS switch too.
  try{ matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if(themeChoice() === "system") repaintCharts(); }); }catch(e){}
}

document.addEventListener("DOMContentLoaded", wireTheme);
if(document.readyState !== "loading") wireTheme();

// ---- every table scrolls inside a .tscroll ----------------------------------
// The render functions write tables straight into their panels; rather than
// teach a hundred of them about the phone, a MutationObserver wraps each new
// table once. The wrapper is the scroll container on every width; on the
// phone the stylesheet fades its right edge and pins the first column when
// data-more says there is more to the right.
function wrapTable(t){
  if(!t.parentElement || t.parentElement.classList.contains("tscroll")) return;
  if(t.closest(".tscroll") && t.closest(".tscroll").querySelector("table") === t) return;
  const w = document.createElement("div");
  w.className = "tscroll";
  t.parentElement.insertBefore(w, t);
  w.appendChild(t);
  markScroll(w);
}

function markScroll(w){
  const more = w.scrollWidth > w.clientWidth + 2 && w.scrollLeft + w.clientWidth < w.scrollWidth - 2;
  if(more) w.dataset.more = "1"; else delete w.dataset.more;
}

function wrapTables(root){
  (root || document).querySelectorAll("table").forEach(wrapTable);
}

document.addEventListener("scroll", e => { const w = e.target && e.target.classList && e.target.classList.contains("tscroll") ? e.target : null; if(w) markScroll(w); }, true);

window.addEventListener("resize", () => document.querySelectorAll(".tscroll").forEach(markScroll));

{
  let pending = false;
  const mo = new MutationObserver(() => {
    if(pending) return;
    pending = true;
    // After the render that queued it, so a table's width is measurable.
    requestAnimationFrame(() => { pending = false; wrapTables(); document.querySelectorAll(".tscroll").forEach(markScroll); });
  });
  const start = () => { wrapTables(); mo.observe(document.body, {childList:true, subtree:true}); };
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
}

// ---- loading state -----------------------------------------------------------
// A skeleton row and one sentence. A bare "Loading…" in the same grey as an
// empty state was indistinguishable from a panel that had failed.
function loadingHTML(what){
  return `<div class="loading" aria-busy="true"><div class="skel"></div><div class="skel short"></div><div class="note">${what || "Loading…"}</div></div>`;
}

// A yes/no cell: a glyph and a colour, then the word — a grey "no" beside a
// grey "yes" was a matrix nobody could scan.
function yesNo(ok){
  return ok ? `<span class="yn yes" title="yes">✓ yes</span>` : `<span class="yn no" title="no">✕ no</span>`;
}

// ---- axis labels for the SVG charts ------------------------------------------
// The SVG scales to its box, so text inside it came out at 6px on a phone.
// Labels are HTML placed over the host at the same fraction of the viewBox,
// and keep their 11px whatever the width.
function axisLabels(host, W, H, labels){
  host.style.position = "relative";
  host.querySelectorAll(".axl").forEach(e => e.remove());
  labels.forEach(l => {
    const d = document.createElement("div");
    d.className = "axl" + (l.end ? " end" : "") + (l.bottom ? " bottom" : "");
    d.style.left = (l.x / W * 100) + "%";
    d.style.top = (l.y / H * 100) + "%";
    d.textContent = l.text;
    host.appendChild(d);
  });
}

// Zero is neither a gain nor a loss. Anything that rounds to nothing at the
// displayed precision gets ink rather than a colour — otherwise a cash position
// with no P/L at all renders "−0.00" in red, which reads as a loss on money
// that cannot have one.
const FLAT = 0.005;

const col = v => v==null || Math.abs(v)<FLAT ? ""
  : `color:${v>0?"var(--up)":"var(--down)"}`;

const sign = v => Math.abs(v)<FLAT ? "" : (v>0 ? "+" : "−");

// Remembered locally, per browser. Nothing leaves the machine — it is the same
// principle as the rest of the app, and it means the phone and the desktop can
// each keep their own view without fighting over one shared setting.
const SETTINGS_KEY = "investment-app.settings.v1";

function saveSettings(){
  try{
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({
      tab: curView(),
      wlgroup: $("#wlgroup") ? $("#wlgroup").value : null,
      wlsort: $("#wlsort") ? $("#wlsort").value : null,
      period: $("#period").value, from: $("#from").value, to: $("#to").value,
      scope: $("#scope").value,
      benchmarks: [...$("#bm").selectedOptions].map(o=>o.value),
      indicators: INDS,
      timeframe: $("#tf").value,
      setup: $("#setup") ? $("#setup").value : null,
      compare: $("#compare").value, cmode: $("#cmode").value,
      symbol: CHART_SYMBOL,
      scale: $("#scale") ? $("#scale").value : null,
      paneSize: $("#paneSize") ? $("#paneSize").value : null,
      hist: $("#hist") ? $("#hist").value : null,
      // The 1Y / All toggle. Added beside the older keys rather than folded
      // into the view store, which is per symbol; this is one choice.
      range: CHART_RANGE,
      structure: $("#stLines") ? {
        lines:$("#stLines").checked, channel:$("#stChannel").checked,
        zones:$("#stZones") ? $("#stZones").checked : true,
        zonesAll:$("#stZonesAll") ? $("#stZonesAll").checked : false,
        vprof:$("#stVprof") ? $("#stVprof").checked : true,
        fib:$("#stFib").checked, labels:$("#stLabels").checked,
        osc:$("#stOsc").checked, pivots:$("#stPivots").value,
        fibback:$("#stFibBack").value,
      } : null,
      drawColour: $("#dColour") ? $("#dColour").value : null,
      bgStatus: $("#bgStatus") ? $("#bgStatus").value : null,
      bgAge: $("#bgAge") ? $("#bgAge").value : null,
    }));
  }catch(e){ /* private window, or storage disabled — the app still works */ }
}

function loadSettings(){
  try{ return JSON.parse(localStorage.getItem(SETTINGS_KEY) || "null"); }
  catch(e){ return null; }
}

let CHART = null, CANDLES = null, CHART_SYMBOL = null, TRADES = [];

// The symbol whose candles are actually on the pane. CHART_SYMBOL is the one
// asked for; the two differ while a request is in flight and when the pane
// was hidden at the time (loadChart draws nothing into a zero-width host).
let CHART_DRAWN = null;

// The section on screen and its sub-tab. TAB keeps its old name because the
// keyboard handlers test it (`TAB !== "chart"`); together they name a view,
// "money/overview", which is what the hash, the loaders and the settings use.
let TAB = "money", SUB = "overview";

const curView = () => TAB + "/" + SUB;

// Holdings from the last load(), so the chart can default to the largest
// position without reading a variable that is not in scope.
let LAST_HOLDINGS = [];

// Held so they can be disposed; both are created with autoSize, which attaches
// a ResizeObserver that innerHTML = "" does not remove.
let DD_CHART = null, BT_CHART = null;

let DRAW = null;   // the hand-drawing overlay for the price pane

// Each tab fetches its own data the first time it is opened, not on page load.
// Loading everything eagerly meant the first paint waited on the slowest
// endpoint — diagnosis takes ~5s on its own — so the page looked broken for
// fifteen seconds while five requests raced.
// US market hours in the viewer's own clock, so it is right wherever the phone
// happens to be. Weekends are excluded; market holidays are not, which costs an
// unnecessary fetch about nine times a year and is not worth a holiday
// calendar to avoid.
function marketOpen(){
  const now = new Date();
  const et = new Date(now.toLocaleString("en-US", {timeZone: "America/New_York"}));
  const day = et.getDay();
  if(day === 0 || day === 6) return false;
  const mins = et.getHours()*60 + et.getMinutes();
  return mins >= 9*60 + 30 && mins <= 16*60;
}

// The seven sections, their sub-tabs in order, and where each of the fifteen
// old tabs went. Every showTab("outlook") left in this file, every bookmark
// and every deep link in the smoke test resolves through OLD_TABS, so nothing
// that used to open a tab has to know the new address.
const SECTIONS = {
  today:  ["todo", "market", "alerts"],
  money:  ["overview", "holdings", "trades", "risk", "sectors"],
  stocks: ["calls", "watchlist", "setups", "rebuy", "newstocks"],
  follow: ["graded", "charts", "methods", "record"],
  bot:    ["paper", "record", "backtest"],
  chart:  ["chart", "read", "plan", "follow", "trades"],
  budget: ["summary", "spending", "recurring", "plan", "taxes", "loose"],
};

const OLD_TABS = {
  overview: "money/overview", diagnose: "today/todo", holdings: "money/holdings",
  outlook: "stocks/calls", setups: "stocks/setups", newstocks: "stocks/newstocks",
  trades: "money/trades", risk: "money/risk", chart: "chart/chart",
  watchlist: "stocks/watchlist", sectors: "money/sectors", budget: "budget",
  research: "follow/methods", tradebot: "bot/paper", backtest: "bot/backtest",
};

const HOME_VIEW = "money/overview";

// The sub-tab a section was last on, per section, per device — the pattern
// Budget had ("portfolio.budget.sub"), now one key per section.
const subKey = section => `portfolio.${section}.sub`;

function lastSub(section){
  try{ return localStorage.getItem(subKey(section)) || ""; }catch(e){ return ""; }
}

// "outlook", "money/holdings", "chart/read?sym=IREN" or "#chart" → the view
// it names, or the home view for anything unknown. A bare section name opens
// the sub-tab it was last on.
function resolveView(name){
  const [path, qs] = String(name || "").replace(/^#/, "").split("?");
  const mapped = OLD_TABS[path] || path;
  let [section, sub] = mapped.split("/");
  if(!SECTIONS[section]) [section, sub] = HOME_VIEW.split("/");
  const subs = SECTIONS[section];
  if(!sub || !subs.includes(sub)) sub = subs.includes(lastSub(section)) ? lastSub(section) : subs[0];
  return {section, sub, query: new URLSearchParams(qs || "")};
}

// What each view fetches the first time it is opened, keyed "section/sub".
// A "section/*" entry covers every sub-tab of that section with one load —
// Budget renders all six from one payload, and the chart's read is drawn by
// the same call that draws the candles. Each loader is idempotent; most are
// promise-cached behind their fetch helpers, so a second call is free.
// Nothing here runs on boot beyond what Overview needs: load() renders the
// whole of My Money from the performance payload and fires the outlook for
// the Holdings verdict column, as it always did.
const VIEW_LOADERS = {
  "today/todo":       () => loadDiagnose(),
  "today/market":     () => OUTLOOK ? null : loadOutlook(),
  "money/sectors":    () => loadRotation(),
  "stocks/calls":     () => OUTLOOK ? null : loadOutlook(),
  "stocks/watchlist": () => loadWatchlist(),
  "stocks/setups":    () => loadSetups(),
  "stocks/rebuy":     () => loadRebuy(),
  // The scan; the two method folds under it load themselves when opened.
  "stocks/newstocks": () => loadDiscover(),
  "follow/charts":    () => Promise.all([loadSubstackCharts(), loadValueTrader()]),
  "follow/*":         () => loadResearch(),
  "bot/paper":        () => loadPaper(),
  "bot/record":       () => OUTLOOK ? null : loadOutlook(),
  "bot/backtest":     () => loadBacktestMethods(),
  // The symbol page: its five panels paint from the per-symbol reads, and
  // the candles are drawn only when their pane is on screen (loadChart bails
  // on a hidden host) — so a page opened on The read draws them when the
  // Chart sub-tab is opened, from showTab. Opening the chart during the
  // session refetches, so what is on screen is the current price rather
  // than Friday's close.
  "chart/*":          () => {
    const s = SYM || CHART_SYMBOL;
    if(!s) return null;
    renderSymbolPage(s);
    return (SUB === "chart" && CHART_DRAWN !== s && !chartInFlight()) ? loadChart(s, {refresh: marketOpen()}) : null;
  },
  "budget/*":         () => Promise.all([loadBudget(), loadAmazon()]),
};

const TAB_LOADED = new Set();

// The loader key a view resolves to: its own entry, else its section's "*".
function loaderKey(name){
  if(VIEW_LOADERS[name]) return name;
  const star = name.split("/")[0] + "/*";
  return VIEW_LOADERS[star] ? star : null;
}

// The panel a view's failure banner goes in: the sub-panel, or the section
// when the loader is shared by every sub-tab of it.
function viewPanel(name){
  const [section, sub] = name.split("/");
  return document.querySelector(`.tab[data-panel="${section}"] .subpanel[data-sub-panel="${sub}"]`)
      || document.querySelector(`.tab[data-panel="${section}"]`);
}

// A loader that rejected used to be logged to the console and nothing else,
// and six of the tabs render nothing until their loader finishes — so a server
// error, a timeout or a bad JSON body looked exactly like a feature that had
// not been built. The failure is said in the panel, with the way to retry.
function tabFailed(name, e){
  TAB_LOADED.delete(loaderKey(name) || name);   // let a failure be retried
  console.error(`tab ${name} failed`, e);
  const panel = viewPanel(name);
  if(!panel) return;
  let msg = (e && e.message) || String(e || "unknown error");
  // A 500 comes back as an HTML page, which JSON.parse reports as a stray "<".
  if(/JSON|Unexpected token/.test(msg)) msg = "the server answered with an error page instead of data — see logs/";
  if(/Failed to fetch|NetworkError|Load failed/.test(msg)) msg = "the server did not answer";
  let b = panel.querySelector(".tabfail");
  if(!b){ b = document.createElement("div"); b.className = "tabfail warn"; panel.prepend(b); }
  b.innerHTML = `<b>This tab could not load:</b> ${esc(msg)} <button type="button" data-retry="${esc(name)}">Retry</button>`;
  b.querySelector("[data-retry]").addEventListener("click", () => ensureTab(name));
}

// Runs the view's loader once. Takes a view ("stocks/setups") or an old tab
// name ("setups"), the way showTab does.
function ensureTab(name){
  const {section, sub} = resolveView(name);
  name = section + "/" + sub;
  const key = loaderKey(name);
  const fn = key && VIEW_LOADERS[key];
  if(!fn || TAB_LOADED.has(key)) return;
  TAB_LOADED.add(key);
  const panel = viewPanel(name);
  const stale = panel && panel.querySelector(".tabfail");
  if(stale) stale.remove();
  // fn() is called BEFORE Promise.resolve wraps it, so a synchronous throw
  // escaped this catch — and ensureTab runs inside showTab, so that broke tab
  // navigation entirely.
  let started;
  try { started = fn(); }
  catch (e) { tabFailed(name, e); return; }
  Promise.resolve(started).catch(e => tabFailed(name, e));
}

// Opens a view. Accepts the new address ("money/holdings"), a bare section
// ("budget" — lands on the sub-tab it was last on), an old tab name
// ("outlook"), or a hash with a query ("chart/chart?sym=IREN").
function showTab(name){
  const {section, sub, query} = resolveView(name);
  TAB = section;
  document.querySelectorAll(".tab").forEach(p => p.hidden = p.dataset.panel !== section);
  document.querySelectorAll("#tabs button, #phonebar button, #moresheet button").forEach(b => {
    const on = b.dataset.section === section;
    b.classList.toggle("on", on);
    // Screen readers take the selected tab from aria-selected, not from a class.
    if(b.getAttribute("role") === "tab"){
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
    }
  });
  // "More" on the phone is lit when the section it opens is the one on screen.
  const more = $("#phonemore");
  if(more) more.classList.toggle("on", ["follow", "bot", "chart"].includes(section));
  closeMore();
  showSub(section, sub);
  // The symbol page: ?sym= names the symbol (the address carries it, so a
  // link to #chart/read?sym=IREN is a link to IREN's page); without one the
  // page stays on the name it was on. The candles draw only when their pane
  // is on screen, so arriving on the Chart sub-tab with another name up, or
  // none, draws them here — once the section's loader has had its first run.
  const sym = (query.get("sym") || "").trim().toUpperCase();
  if(section === "chart"){
    if(sym) renderSymbolPage(sym);
    const want = sym || SYM || CHART_SYMBOL;
    if(sub === "chart" && want && TAB_LOADED.has("chart/*") && CHART_DRAWN !== want && !chartInFlight()) loadChart(want);
  }
  // replaceState, not location.hash = …: every tab switch used to push a
  // history entry, so Back walked through every tab visited before leaving.
  const hash = "#" + section + "/" + sub + (section === "chart" && (sym || SYM) ? "?sym=" + encodeURIComponent(sym || SYM) : "");
  if(location.hash !== hash) history.replaceState(null, "", hash);
  saveSettings();
  // A link into the one method scanner names its method.
  const method = query.get("method");
  if(section === "stocks" && sub === "newstocks" && method) openMethodScan(method);
  ensureTab(section + "/" + sub);
  // Charts sized while hidden collapse to zero width, so the range has to be
  // reapplied on reveal — but to where you left it, not to the whole history.
  if(section === "chart" && CHART) restoreView();
  window.scrollTo(0, 0);
}

// Which sub-tab of a section is on screen. Pure show/hide — showTab runs the
// loader — and the choice is remembered per section, per device. On the
// phone the row scrolls so the active chip is in view.
function showSub(section, name){
  const known = SECTIONS[section] || [];
  if(!known.includes(name)) name = known[0];
  SUB = name;
  const sec = document.querySelector(`.tab[data-panel="${section}"]`);
  if(!sec) return;
  sec.querySelectorAll(".subpanel").forEach(p => p.hidden = p.dataset.subPanel !== name);
  const row = sec.querySelector(".subtabs");
  sec.querySelectorAll(".subtabs button").forEach(b => {
    const on = b.dataset.sub === name;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
    // scrollLeft rather than scrollIntoView, which would also scroll the page
    // vertically to the row on every switch.
    if(on && row && row.scrollWidth > row.clientWidth)
      row.scrollLeft = Math.max(0, b.offsetLeft - (row.clientWidth - b.offsetWidth) / 2);
  });
  // A private window or a full quota must not take the tab down with it.
  try{ localStorage.setItem(subKey(section), name); }catch(e){ /* view state is a nicety */ }
  // The drawdown chart was fitted while its panel was hidden (zero width), so
  // it opened showing the last third of the curve; refit once it is on screen.
  if(section === "money" && name === "risk" && DD_CHART) requestAnimationFrame(() => { try{ DD_CHART.timeScale().fitContent(); }catch(e){} });
}

// The phone's More sheet: the three sections that do not fit in five slots.
function openMore(){
  const sh = $("#moresheet"), bk = $("#moreback"), b = $("#phonemore");
  if(!sh) return;
  sh.hidden = false; if(bk) bk.hidden = false;
  if(b) b.setAttribute("aria-expanded", "true");
}

function closeMore(){
  const sh = $("#moresheet"), bk = $("#moreback"), b = $("#phonemore");
  if(!sh || sh.hidden) return;
  sh.hidden = true; if(bk) bk.hidden = true;
  if(b) b.setAttribute("aria-expanded", "false");
}

// Lightweight Charts parses colours itself and understands only hex, rgb and
// rgba — NOT color-mix(), which is a CSS function the canvas never sees. Giving
// it one throws "Cannot parse color" from inside the library's draw loop, which
// is after setData and therefore outside any try/catch around the drawing call:
// the whole price pane simply renders blank.
function rgba(hex, alpha){
  const h = (hex || "").trim().replace("#", "");
  if(h.length !== 6) return hex;
  const n = parseInt(h, 16);
  return `rgba(${(n>>16)&255}, ${(n>>8)&255}, ${n&255}, ${alpha})`;
}

// Whether the page is dark right now: the header toggle (data-theme on the
// root) wins, and only when it is unset does the system setting decide.
function isDark(){
  const t = document.documentElement.dataset.theme;
  if(t === "dark") return true;
  if(t === "light") return false;
  return matchMedia("(prefers-color-scheme: dark)").matches;
}

function chartTheme(){
  const dark = isDark();
  // The same literals as the stylesheet's tokens, per theme. Lightweight
  // Charts parses colours itself and cannot resolve a CSS custom property, so
  // the canvas gets the hex the token holds rather than the token's name.
  // Candles are TradingView's own pair in both themes; the text variants of
  // up and down (lighter in dark, darker in light) are for the DOM only.
  return {
    dark,
    bg:      dark ? "#1B1F2B" : "#FFFFFF",
    text:    dark ? "#8A90A2" : "#666B79",      // --axis
    muted:   dark ? "#8A90A2" : "#666B79",      // --muted: crosshair, reference lines
    grid:    dark ? "#2A2E39" : "#E0E3EB",      // --grid
    up:   "#089981", down: "#F23645",           // --up-strong / --down-strong
    wickUp: "#089981", wickDown: "#F23645",
    upStrong: "#089981", downStrong: "#F23645",
    volUp:   "rgba(8,153,129,.55)", volDown: "rgba(242,54,69,.55)",
    // Generic furniture — auto support and resistance, trendlines, fib —
    // sits at half strength so the user's own marks read over it.
    furniture:       dark ? "rgba(138,144,162,.5)" : "rgba(106,111,125,.55)",
    furnitureStrong: dark ? "rgba(138,144,162,.85)" : "rgba(106,111,125,.85)",
    // The furniture colour flattened onto the card ground, for the colour
    // pickers, which cannot hold an alpha.
    furnitureHex:    dark ? "#535866" : "#B5B8C0",
    // Buy and sell fills are the user's own marks: blue and magenta, outside
    // the red/green candle vocabulary on purpose — a purchase on a down day
    // painted green would read as an up candle.
    buy:  dark ? "#5280FF" : "#2962FF",         // --mine-buy
    sell: dark ? "#F06BD8" : "#C405E5",         // --mine-sell
    mineCost:  dark ? "#5280FF" : "#2962FF",    // --mine-cost
    mineLevel: "#F59E0B",                       // --mine-level: amber, reserved for the user's levels
    trim: "#F59E0B",                            // --trim-strong
    // The three prices the read resolves to, the same tokens the ladder
    // paints them in, so the chart and the table agree by construction.
    buyAt:  dark ? "#5280FF" : "#2962FF",       // --buy
    trimAt: dark ? "#FFB020" : "#A06707",       // --trim
    stopAt: dark ? "#FF5A63" : "#E90F20",       // --down
    line:    dark ? "#B39DDB" : "#7E57C2",      // --s4: the compare series, channels
    accent:  dark ? "#5280FF" : "#2962FF",      // --accent
    accentFill: "#2962FF",
    ma: dark ? ["#F59E0B", "#B39DDB", "#5280FF"] : ["#F59E0B", "#7E57C2", "#2962FF"],
  };
}

// Indicator colours, in the order indicators are added. The first three are
// the spec's --ma3/--ma2/--ma1 (blue, purple, amber) so the usual 20/50/200
// stack reads the same as everyone's TradingView; then the up and down
// strongs, then the sell magenta — six slots, none of them the muted grey
// the furniture uses.
function palette(){
  const t = chartTheme();
  return [t.ma[2], t.ma[1], t.upStrong, t.downStrong, t.ma[0], t.sell];
}
