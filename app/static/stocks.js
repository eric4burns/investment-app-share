// Stocks: the calls table, the watchlist, setups, buying back, the discovery scan and the method scanner.
// One of the dashboard's scripts (see dashboard.html): a classic script sharing the page's
// global scope with the others, loaded in the order the tags there give.

// -------------------------------------------------------------- outlook ----
// The verdict layer. Everything else on this page reports a measurement; this
// reports a conclusion, which is why each one is shown with the evidence that
// produced it and the price that would flip it. A call you cannot check is
// worth less than no call.
//
// Loaded separately from /api/performance because it is the slowest payload
// here — every holding gets structure, Ichimoku and Fibonacci on two
// timeframes — and blocking the whole dashboard behind it would trade a fast
// page for a feature you look at once a day.
let OUTLOOK = null;

// Why the sell ladder is not showing, when it is switched off. Empty when it
// is on. Carried on the payload so the page never hard-codes the reasoning.
let ladderOff = "";

// The watchlist is fetched separately and only when asked for. It is 145 names
// against 16 holdings, and loading it on every page view would make the tab
// slower for the list most people open it for.
let OUTLOOK_WL = null, WL_VERDICTS_PENDING = false;

// One request for the watchlist's verdicts, shared by the Outlook sub-tab, the
// Watchlist tab and Setups — three places that used to each fetch it. `lite=1`
// asks the server for the fields the page reads; an older server ignores it.
let OUTLOOK_WL_PROMISE = null;

function fetchOutlookWL(){
  if(OUTLOOK_WL) return Promise.resolve(OUTLOOK_WL);
  if(!OUTLOOK_WL_PROMISE){
    OUTLOOK_WL_PROMISE = fetch("/api/outlook?scope=watchlist&lite=1").then(r => r.json())
      .then(wl => { if(wl && !wl.error) OUTLOOK_WL = wl; return wl; })
      .finally(() => { OUTLOOK_WL_PROMISE = null; });
  }
  return OUTLOOK_WL_PROMISE;
}

const VD_LABEL = {buy:"buy", add:"add", hold:"hold", trim:"trim", sell:"sell"};

// A flip level on its own — "Flips at 20.97" — was the single most-asked
// question on the first review: flips from what, to what, and where is price
// now? Every place a flip is shown goes through this so it always carries all
// three.
function flipText(verdict, price, flip, note){
  if(flip == null) return "";
  const pctStr = (price && flip) ? ` (${flip > price ? "+" : ""}${((flip / price - 1) * 100).toFixed(1)}%)` : "";
  const dir = (!price) ? "" : flip > price ? "above" : "below";
  const v = (verdict || "").toUpperCase();
  const becomes = {sell: "the sell case ends", trim: "the next level up is",
                   buy: "this is wrong", add: "this is wrong", hold: "this breaks"}[verdict] || "this flips";
  const head = price ? `${v} at ${money(price)} · ${becomes} ${
    verdict === "trim" ? "at" : "on a close " + dir} ${money(flip)}${pctStr}` : `Flips at ${money(flip)}${pctStr}`;
  return `<div class="vdflip">${head}${note ? `<div class="note" style="margin-top:2px">${esc(note)}</div>` : ""}</div>`;
}

// Days to the next report, coloured by how close it is. Inside five days the
// call is a call into earnings, and the card says so in words.
// The book a held name is in, changeable in place. A watchlist name has none.
function bookCell(sym, b){
  if(!b) return `<span class="note">—</span>`;
  const val = b.book === "conviction" ? (b.trade_around ? "conviction+ta" : "conviction") : "swing";
  return `<select data-bookfor="${esc(sym)}" title="${esc(b.note || "")}" style="font-size:11.5px">
    <option value="swing"${val === "swing" ? " selected" : ""}>swing</option>
    <option value="conviction"${val === "conviction" ? " selected" : ""}>conviction</option>
    <option value="conviction+ta"${val === "conviction+ta" ? " selected" : ""}>conviction, traded around</option>
  </select>${b.default ? `<div class="note" style="font-size:11px">not set — reads as swing</div>` : ""}`;
}

document.addEventListener("change", async ev => {
  const el = ev.target;
  if(!el.dataset || !el.dataset.bookfor) return;
  const [book, ta] = el.value === "conviction+ta" ? ["conviction", "1"] : [el.value, "0"];
  el.disabled = true;
  try{
    const r = await (await fetch("/api/outlook?" + new URLSearchParams({action: "setbook", symbol: el.dataset.bookfor, value: book, trade_around: ta}))).json();
    if(r.error){ el.style.borderColor = "var(--down)"; el.title = r.error; }
    else { el.style.borderColor = "var(--up)"; OUTLOOK = null; loadOutlook(); }
  }catch(e){ el.style.borderColor = "var(--down)"; }
  el.disabled = false;
});

function earningsCell(e){
  if(!e) return `<span class="note">—</span>`;
  const col = e.days <= 5 ? "var(--down)" : e.days <= 14 ? "var(--warn)" : "inherit";
  const when = e.days === 0 ? "today" : e.days === 1 ? "tomorrow" : `${e.days}d`;
  return `<span style="color:${col};font-weight:${e.days <= 5 ? 700 : 400}" title="${esc(e.date)} ${esc(e.timing || "")}${
    e.eps_estimate != null ? `, consensus ${e.eps_estimate.toFixed(2)}` : ""}">${when}</span>`;
}

function earningsLine(e){
  if(!e || e.days > 14) return "";
  const urgent = e.days <= 5;
  return `<div class="${urgent ? "warn" : "note"}" style="margin:6px 0">
    <b>Reports ${e.days === 0 ? "today" : e.days === 1 ? "tomorrow" : `in ${e.days} days`}</b>
    (${esc(e.date)}${e.timing && e.timing !== "unknown" ? ", " + esc(e.timing) : ""}${
    e.eps_estimate != null ? `, consensus ${e.eps_estimate.toFixed(2)} a share` : ""}).
    ${urgent ? "Whatever the chart says, the next move is the report's, not the chart's." : ""}</div>`;
}

// One outlook request at a time. Boot fires this without waiting; a symbol
// page opened from a deep link needs the same payload a moment later and
// used to fire a second, identical, three-second request.
let OUTLOOK_PROMISE = null;

function loadOutlook(){
  if(OUTLOOK_PROMISE) return OUTLOOK_PROMISE;
  OUTLOOK_PROMISE = loadOutlookNow().finally(() => { OUTLOOK_PROMISE = null; });
  return OUTLOOK_PROMISE;
}

async function loadOutlookNow(){
  // A failed load used to return quietly, which left the verdict column absent
  // and three headed panels empty — indistinguishable from a feature that had
  // simply not been built. The most likely cause is a server still running the
  // code from before this shipped, since dashboard.html is read from disk on
  // every request and the Python is not, so the new panels appear against an
  // old API. Say that, rather than showing nothing.
  const fail = msg => {
    OUTLOOK = null;
    ["#mktmood", "#scorecard", "#jrnl"].forEach(id => {
      const el = $(id);
      if(el) el.innerHTML = `<div class="warn"><b>The outlook could not load.</b> ${esc(msg)}</div>`;
    });
  };
  let r;
  try{ r = await fetch("/api/outlook"); }
  catch(e){ return fail("The server did not answer."); }
  if(r.status === 404)
    return fail("This server is running an older build — /api/outlook does not exist on it. "
                + "Restart it: launchctl kickstart -k gui/$(id -u)/com.ericburns.investment-app.serve");
  if(!r.ok) return fail(`The server answered ${r.status}.`);
  try{ OUTLOOK = await r.json(); }
  catch(e){ return fail("The reply was not readable."); }
  if(OUTLOOK.error){ const m = OUTLOOK.error; return fail(m); }
  ladderOff = OUTLOOK.ladder_off || "";
  paintVerdicts();
  renderFreshness();
  renderMood();
  renderChanged();
  renderVerdictTable();
  renderScorecard();
  renderJournal();
  renderCrossCheck();
  renderCalibration();
  loadReplay();
  // The symbol page reads its row from this payload; a fresh one (a book
  // change, a recorded decision, refreshed prices) repaints the page.
  if(SYM) renderSymbolPage(SYM, true);
  if(TODO_DATA) renderTodo();
}

// The column is added to the rendered table rather than built into it, so the
// holdings table still paints in full the moment /api/performance lands and
// does not sit empty waiting on the slower call.
function paintVerdicts(){
  const t = $("#holdings");
  if(!t || !OUTLOOK || !OUTLOOK.verdicts) return;
  fillRungs();
  if(t.dataset.verdicts) return;
  t.dataset.verdicts = "1";
  [...t.rows].forEach((tr, i) => {
    if(i === 0){
      const th = document.createElement("th");
      th.scope = "col";
      th.title = "The app's headline call on the name — the same one Today, the watchlist and the name's page show — with the timeframe it was read on. Click for the working.";
      th.textContent = "Call";
      tr.appendChild(th);
      return;
    }
    const td = document.createElement("td");
    td.style.whiteSpace = "nowrap";
    const sym = tr.dataset.sym;
    const v = sym && OUTLOOK.verdicts[sym];
    if(v){
      // The HEADLINE, not the daily. This column showed v.daily while Today,
      // the watchlist and the name's page showed the headline, so DGXX read
      // "hold" here and "add" everywhere else on the same night (the daily is
      // the one timeframe the replay found carries no information). One call
      // per name, the timeframe named so a monthly add beside a weak daily is
      // read as what it is.
      const tf = {D: "daily", W: "weekly", M: "monthly"}[v.headline_timeframe] || "";
      const rec = v.record && v.record[tf];
      const conf = v.headline_confidence && v.headline_confidence !== "none" ? esc(v.headline_confidence) : "";
      // One line under the pill: confidence, the record's edge, the
      // timeframe, the conflict mark — not four stacked rows.
      const under = [conf + (rec && rec.mean_excess != null ? ` ${rec.mean_excess >= 0 ? "+" : ""}${(rec.mean_excess*100).toFixed(1)}%` : ""),
                     tf ? tf.replace("daily", "day").replace("weekly", "wk").replace("monthly", "mo") : ""].filter(Boolean).join(" · ");
      td.innerHTML = `<span class="vdwrap" data-vd="${esc(sym)}">${vdPill(v.headline || v.daily)}` +
        (under ? `<span class="vdconf"${rec && rec.text ? ` title="${esc(rec.text)}"` : ""}>${under}${v.conflict ? ` <span class="vdarrow" title="${esc(v.conflict)}">⚠</span>` : ""}</span>` : "") + `</span>`;
    }else if(sym){
      td.innerHTML = `<span class="vd vd-none" title="Not enough price history to read structure from">—</span>`;
    }
    tr.appendChild(td);
  });
  // The pill opens the name's page on The read; the row itself opens the same
  // page on the chart. stopPropagation so one click is one destination.
  t.addEventListener("click", e => {
    const w = e.target.closest("[data-vd]");
    if(w){ e.stopPropagation(); openSymbol(w.dataset.vd, "read"); }
  }, true);
}

// A change log, not a fresh outlook. Most days this says nothing changed, and
// that is the output working rather than failing: a panel that reads
// differently every morning when nothing happened teaches you to skim it.
// CNN's Fear and Greed index. Market-wide, so it belongs above the per-name
// list rather than inside it — and it is reported here every day while only
// carrying weight in a verdict at the extremes.
// Prices are cached and refreshed after the close, so during the session the
// whole tab is scored off yesterday's bars. That is defensible; saying nothing
// about it is not.
function renderFreshness(){
  const el = $("#pricefresh");
  if(!el || !OUTLOOK) return;
  const asof = OUTLOOK.prices_asof;
  // Against the last SESSION, not the calendar: on a Sunday "prices to
  // Friday" is current, and the warning with its Refresh button was wrong
  // two days a week.
  const ny = new Date(new Date().toLocaleString("en-US", {timeZone: "America/New_York"}));
  while(ny.getDay() === 0 || ny.getDay() === 6) ny.setDate(ny.getDate() - 1);
  const lastSession = ny.toLocaleDateString("en-CA");
  const stale = asof && asof < lastSession;
  el.innerHTML = stale
    ? `<span class="warn" style="display:inline-block;padding:6px 10px">
         Scored from prices to <b>${esc(asof)}</b>, not today.
         ${marketOpen() ? "The market is open now." : "The nightly refresh runs at 18:30."}
         <button id="pricepull" style="margin-left:8px;padding:3px 9px;font-size:12px">
           Refresh prices</button></span>`
    : `Prices current to <b>${esc(asof || "—")}</b>.`;
  const btn = $("#pricepull");
  if(btn) btn.addEventListener("click", async () => {
    btn.disabled = true; btn.textContent = "fetching…";
    // The response used to be ignored: {ok:false, error:"no Alpaca
    // credentials"} or a 500 both led straight to a reload of the same old
    // bars, and the button looked like it had done nothing.
    let r;
    try{
      const res = await fetch("/api/outlook?action=refresh");
      r = await res.json();
      if(!res.ok && !r.error) r.error = `server error ${res.status}`;
    }
    catch(e){ r = {ok: false, error: "the server did not answer"}; }
    if(!r || !r.ok){
      btn.disabled = false; btn.textContent = "Refresh prices";
      el.insertAdjacentHTML("beforeend", ` <span class="warn" style="display:inline-block;padding:6px 10px;margin-left:6px">Refresh failed: ${esc((r && r.error) || "unknown error")}</span>`);
      return;
    }
    OUTLOOK = null; OUTLOOK_WL = null;
    await loadOutlook();
    const done = $("#pricefresh");
    if(done) done.insertAdjacentHTML("beforeend", ` <span class="note">Refreshed: ${r.priced || 0} priced${r.failed ? `, ${r.failed} failed` : ""}${r.prices_asof ? `, bars to ${esc(r.prices_asof)}` : ""}.</span>`);
  });
}

function renderChanged(){
  const el = $("#changed");
  if(!el || !OUTLOOK) return;
  const rows = OUTLOOK.changed || [];
  if(!rows.length){
    el.innerHTML = `<div class="note">Nothing changed. Every holding sits where it
      sat at the last reading — which is what most days look like.</div>`;
    return;
  }
  el.innerHTML = rows.slice(0, 10).map(r => `
    <div class="vdrow">
      <div class="vdsym">${esc(r.symbol)}<div class="jsrc">${r.timeframe === "W" ? "weekly" : "daily"}</div></div>
      <div class="vdbody">
        <div>${r.from ? `<span class="vd vd-${esc(r.from)}">${esc(r.from)}</span><span class="vdarrow">→</span>` : ""}
             ${vdPill(r.verdict, r.confidence)}
             ${r.kind === "new" ? `<span class="note">first reading</span>` : ""}</div>
        <ul>${(r.because||[]).slice(0,2).map(x=>`<li>${esc(x)}</li>`).join("")}</ul>
        ${flipText(r.verdict, r.price, r.flip, r.flip_note)}
      </div>
    </div>`).join("") +
    (rows.length > 10 ? `<div class="note" style="margin-top:8px">${rows.length - 10} more.</div>` : "");
}

// Both timeframes on one row, side by side and never blended. The two
// disagreeing is the useful part: a daily buy inside a weekly downtrend is a
// bounce to trade, and inside a weekly uptrend it is an entry. Averaging them
// into a single score would erase exactly that.
function renderVerdictTable(){
  const el = $("#vdtable");
  const src = OUTLOOK;
  if(!el || !src || !src.verdicts) return;
  // Holdings sort by money at stake. A watchlist name has none, so it sorts by
  // how decisive the call is instead — a list of 145 names ordered by nothing
  // is a list nobody reads.
  // Within one call, rank by SETUP rather than by nothing. A screen full of
  // "add" was ordered by position size or by name, neither of which answers
  // "which of these is the better trade".
  const rank = {buy: 0, add: 1, trim: 2, sell: 3, hold: 4};
  const q = v => (v.quality && v.quality.score != null) ? v.quality.score : -1;
  // What changed since the last reading sits ON the row, and changed rows sort
  // first. The separate "What changed" list above the table repeated the same
  // names and the user read it as redundant, which it was.
  const changedBy = {};
  (OUTLOOK && OUTLOOK.changed || []).forEach(r => {
    if(!changedBy[r.symbol]) changedBy[r.symbol] = r;
  });
  const rows = Object.entries(src.verdicts).sort((a, b) =>
    ((changedBy[b[0]] ? 1 : 0) - (changedBy[a[0]] ? 1 : 0))
    || (rank[a[1].headline] - rank[b[1].headline])
    || (q(b[1]) - q(a[1]))
    || ((b[1].value || 0) - (a[1].value || 0))
    || a[0].localeCompare(b[0]));
  el.innerHTML =
    `<tr><th scope=col>Symbol</th><th class=num scope=col>Value</th>
      <th class=num scope=col>Price</th>
      <th scope=col title="Which book the position is in. Swing: the calls apply as written. Conviction: never a sell — a broken trend is where the schedule buys; trim still fires. Trade-around: a conviction core with a slice traded against it.">Book</th>
      <th class=num scope=col title="Days until the next earnings report, from the Nasdaq calendar. A chart stops mattering for a day around one.">Earnings</th>
      <th scope=col title="The longest timeframe with enough history, and the one that leads">Monthly</th>
      <th scope=col title="Confidence on every timeframe is read off the past record: what replayed calls in this call's fifth of the measured score did against SPY over 21 days — how often they beat it and by how much on average. High needs a mean of +3% or better with at least 45% winners, across 200 calls on 30 dates; medium a mean of +1.5%; else low. Hover a word for the numbers. In-sample: the weights were fitted on the same record. A weekly buy or add still comes only from the top fifth.">Weekly</th><th scope=col>Daily</th>
      <th class=num scope=col title="The level to buy or add at, from the timeframe that made the call; a dash means nothing tested enough on that side to trade">Buy at</th>
      <th class=num scope=col title="The level to sell into — the slice, on a trade-around name">Sell into</th>
      <th class=num scope=col title="Under here the reason for holding stops applying">Wrong below</th>
      <th class=num scope=col title="Reward against risk, adjusted for how far price is from the level worth acting at and how many timeframes agree">Setup</th>
      <th class=num scope=col title="Measured, weekly: the sum of what the evidence items this call carries were followed by in the replay, after the market's drift is taken out — in percent of 21-day return over SPY. Fitted on the whole record, so in-sample; the out-of-sample test is in research/audits. Positive is good whatever the call says.">Measured</th>
      <th class=num scope=col title="How far up its own swing leg price is trading">Swing</th>
      <th scope=col class="prose">Pivots</th>
      <th class=num scope=col title="Nearest level price has turned at before, below and above">Support / resistance</th>
      <th class=num scope=col title="The price that would change the daily call">Flips at</th></tr>` +
    rows.map(([sym, v]) => `<tr class="clickable" data-vd="${esc(sym)}"${changedBy[sym] ? ' style="background:rgba(255,255,255,.03)"' : ""}>
      <td><b>${esc(sym)}</b>${v.conflict ? ` <span class="vdarrow" title="${esc(v.conflict)}">⚠</span>` : ""}${
        v.wash && (v.headline === "buy" || v.headline === "add") ? ` <span class="vd vd-sell" title="${esc(v.wash.possible
          ? `Sold on ${v.wash.date} (confirmation email). If that was a loss, buying back before ${v.wash.window_closes} is a wash sale.`
          : `Sold ${Math.abs(v.wash.quantity)} shares at a loss of ${money(Math.abs(v.wash.loss))} on ${v.wash.date}. Buying back before ${v.wash.window_closes} disallows the loss.`)}">wash ${v.wash.days_left}d</span>` : ""}${
        v.ladder && (v.ladder.stage > 0 || v.ladder.near || v.ladder.armed) ? ` <span class="vd ${v.ladder.stage > 0 ? "vd-sell" : "vd-none"}" title="${esc(v.ladder.summary || "")}">${
          v.ladder.stage > 0 ? `ladder ${v.ladder.stage}/3` : v.ladder.armed ? "ladder armed" : "rung 1 near"}</span>` : ""}${
        changedBy[sym] ? `<div class="note" title="${esc((changedBy[sym].because||[]).slice(0,2).join("; "))}">${
          changedBy[sym].kind === "new" ? "first reading" :
          `${esc(changedBy[sym].from || "")} → ${esc(changedBy[sym].verdict)} ${changedBy[sym].timeframe === "W" ? "wk" : "day"}`}</div>` : ""}</td>
      <td class=num>${v.value == null ? "—" : money(v.value)}</td>
      <td class=num>${v.price == null ? "—" : money(v.price)}</td>
      <td>${bookCell(sym, v.book)}</td>
      <td class=num>${earningsCell(v.earnings)}</td>
      <td>${v.monthly
            ? vdPill(v.monthly, v.monthly_confidence, v.record && v.record.monthly)
            : `<span class="vd vd-none" title="A monthly reading needs ${v.monthly_needed || 24} monthly bars — two years. This name has ${v.monthly_bars ?? "fewer"} month${v.monthly_bars === 1 ? "" : "s"} of cached history${v.monthly_first ? ", from " + v.monthly_first : ""}. If the company is older than that, the cache starts late, not the company.">too new · ${v.monthly_bars ?? "?"} mo</span>`}</td>
      <td>${v.weekly_insufficient
            ? `<span class="vd vd-none" title="A weekly reading needs 60 weekly bars — over a year of daily history. This name has ${v.weekly_bars ?? "fewer"}${v.weekly_first ? ", from " + v.weekly_first : ""}.">too new · ${v.weekly_bars ?? "?"} wk</span>`
            : vdPill(v.weekly, v.weekly_confidence, v.record && v.record.weekly)}</td>
      <td>${vdPill(v.daily, v.confidence, v.record && v.record.daily)}</td>
      ${threeLevels(v)}
      <td class=num title="${esc((v.quality && v.quality.why) || "")}">${
        v.quality && v.quality.score != null
          ? `<b>${v.quality.score.toFixed(2)}</b><div class="note">${
              v.quality.reward_risk.toFixed(1)}:1</div>`
          : "—"}</td>
      <td class=num>${(v.measured && v.measured.weekly != null)
            ? `<span style="color:${v.measured.weekly > 0 ? "var(--up)" : "var(--down)"}">${v.measured.weekly > 0 ? "+" : ""}${v.measured.weekly.toFixed(1)}</span>`
            : "—"}</td>
      <td class=num>${v.leg_pos == null ? "—" : Math.round(v.leg_pos * 100) + "%"}</td>
      <td class="note prose">${esc(v.sequence || "—")}</td>
      <td class=num style="white-space:nowrap">${
        (v.near && v.near.support ? money(v.near.support.high) : "—")
        + " / " +
        (v.near && v.near.resistance ? money(v.near.resistance.low) : "—")}</td>
      <td class=num title="${v.flip == null ? "" : esc(v.flip_note || "")}">${v.flip == null ? "—" :
        `${money(v.flip)}<div class="note">${v.price ? (v.flip > v.price ? "above, " : "below, ") + (v.flip > v.price ? "+" : "") + ((v.flip / v.price - 1) * 100).toFixed(1) + "%" : ""}</div>`}</td></tr>`).join("");
  // A row opens the name's page on The read; the book select on it must not.
  el.addEventListener("click", e => {
    if(e.target.closest("select, button, a")) return;
    const tr = e.target.closest("[data-vd]");
    if(tr) openSymbol(tr.dataset.vd, "read");
  });
}

// The three prices a reading resolves to, as three cells: buy at / sell into
// / wrong below, each with the distance from here under the figure, coloured
// by role. A dash carries its reason in the title — "no level" is a finding
// the reading makes, not a blank. Used by the Holdings calls table and the
// Setups list; the label above the figure shows on the phone only, where the
// header row is gone and each row stacks.
function threeLevels(v, opts){
  const w = (v && v.watch) || {};
  const ta = v && v.book && v.book.trade_around;
  const none = opts && opts.noneWhy;
  const cell = (cls, label, px, pctv, why, missing) => px
    ? `<td class="num lvl lvl-${cls}" title="${esc(why || "")}"><span class="lvlk">${label}</span><b>${money(px)}</b><span class="lvld">${pctv == null ? "" : (pctv === 0 ? "here now" : (pctv > 0 ? "+" : "") + pctv + "%")}</span></td>`
    : `<td class="num lvl none" title="${esc(none || missing)}"><span class="lvlk">${label}</span><b>—</b><span class="lvld">${none ? "not a call" : "no level"}</span></td>`;
  return cell("buy", "buy at", w.buy_at, w.buy_pct, w.buy_why, "No buy level: nothing tested enough on that side to trade.")
       + cell("sell", ta ? "sell slice into" : "sell into", w.trim_at, w.trim_pct, w.trim_why, "No sell level: nothing tested enough on that side to trade.")
       + cell("stop", "wrong below", w.stop_at, w.stop_pct, "under here the reason for holding stops applying", "No invalidation level: nothing tested enough on that side to trade.");
}

// Expand/collapse state is remembered per group key, so the sections you care
// about stay open across reloads rather than resetting every time.
const WL_OPEN_KEY = "investment-app.watchlist.open.v1";

function openGroups(){
  try{ return new Set(JSON.parse(localStorage.getItem(WL_OPEN_KEY) || "[]")); }
  catch(e){ return new Set(); }
}

function rememberGroups(){
  try{
    const open = [...document.querySelectorAll("#wlgroups details[open]")].map(d=>d.dataset.key);
    localStorage.setItem(WL_OPEN_KEY, JSON.stringify(open));
  }catch(e){}
}

// The last /api/watchlist payload. Sorting, grouping and filtering are all
// done in the browser from it (renderWatchlist); the request (7.7 s) is only
// made to load the list or to change it.
let WATCHLIST = null;

// The rows alone, for the symbol page's "your target and stop": NOT
// loadWatchlist, whose render asks for the watchlist's verdicts — a
// minutes-long scoring on a cold server, for a column this page never shows.
let WATCHLIST_PROMISE = null;

function fetchWatchlistRows(){
  if(WATCHLIST) return Promise.resolve(WATCHLIST);
  if(!WATCHLIST_PROMISE)
    WATCHLIST_PROMISE = fetch("/api/watchlist").then(r => r.json())
      .then(d => { if(d && !d.error) WATCHLIST = d; return d; })
      .finally(() => { WATCHLIST_PROMISE = null; });
  return WATCHLIST_PROMISE;
}

async function loadWatchlist(action){
  const q = new URLSearchParams(action || {});
  const d = await (await fetch("/api/watchlist?"+q)).json();
  if(d.error){ $("#wlnote").textContent = d.error; return; }
  if(action && action.action) DISCOVER = null;   // the scan leaves out watched names
  WATCHLIST = d;
  renderWatchlist();
}

function renderWatchlist(){
  const d = WATCHLIST;
  if(!d) return;
  const sel = $("#wlfilter"), keep = sel.value;
  sel.innerHTML = `<option value="">All tags</option>` +
    d.tags.map(t=>`<option value="${esc(t.tag)}">${esc(t.tag)} (${t.count})</option>`).join("");
  sel.value = keep;

  let rows = keep ? d.rows.filter(r=>r.tags.includes(keep)) : d.rows;

  const sortKey = $("#wlsort").value;
  const sortVal = r => sortKey === "symbol" ? r.symbol : (r[sortKey] ?? -Infinity);
  rows = [...rows].sort((x,y)=> sortKey === "symbol"
    ? x.symbol.localeCompare(y.symbol) : sortVal(y) - sortVal(x));

  // Themes are the granular layer; a name can hold several, so it appears under
  // each — the same reason theme weights sum past 100% elsewhere.
  const THEME_LABEL = {};
  (d.themes || []).forEach(t => THEME_LABEL[t.key] = t.label);
  const themeOf = r => {
    const t = r.tags.filter(x => x !== "yahoo" && THEME_LABEL[x]);
    return t.length ? t : ["untagged"];
  };

  const mode = $("#wlgroup").value;
  const tree = {};
  rows.forEach(r=>{
    let outer, inners;
    if(mode === "sector-theme"){ outer = r.sector || "Unknown"; inners = themeOf(r); }
    else if(mode === "theme"){ outer = null; inners = themeOf(r); }
    else if(mode === "sector"){ outer = null; inners = [r.sector || "Unknown"]; }
    else if(mode === "owned"){ outer = null; inners = [r.owned ? "Owned" : "Watching"]; }
    else { outer = null; inners = ["All"]; }
    const key = outer || "_";
    tree[key] = tree[key] || {};
    inners.forEach(i => { (tree[key][i] = tree[key][i] || []).push(r); });
  });

  const open = openGroups();
  const arrow = v => v==null ? "—" : `<span style="${col(v)}">${pct(v)}</span>`;
  const avg = list => { const v = list.map(r=>r.chg_1m).filter(x=>x!=null);
                        return v.length ? v.reduce((a,b)=>a+b,0)/v.length : null; };

  const table = list => `<div class="tscroll"><table>
    <tr><th scope=col>Symbol</th><th scope=col>Sector</th><th class=num scope=col>Price</th><th class=num scope=col>1w</th>
      <th class=num scope=col>1m</th><th class=num scope=col>3m</th><th class=num scope=col>12m</th>
      <th class=num scope=col title="Relative strength against the other names on this list: the most recent quarter counts double, then the six- and twelve-month and one-month moves. 99 is the strongest name here, 1 the weakest.">RS</th>
      <th class=num scope=col>RSI</th>
      <th scope=col>Trend</th><th class=num scope=col>From 52w high</th>
      <th class=num scope=col title="Open-market insider purchases less sales over the last 90 days, from SEC Form 4 filings. Awards and option exercises are not counted.">Insiders 90d</th>
      <th class=num scope=col>Position</th>
      <th scope=col title="The app's headline call on the name, from the Outlook's watchlist scope, with the price that would change it">Call</th>
      <th scope=col title="Your note, target and stop. Click the pencil to set them.">Note · target · stop</th>
      <th scope=col>Tags</th><th scope=col></th></tr>` +
    list.map(r=>`<tr>
      <td class="clickable" data-sym="${esc(r.symbol)}"><b>${esc(r.symbol)}</b></td>
      <td class="note">${esc(r.sector)}</td>
      <td class=num>${money(r.price)}</td>
      <td class=num>${arrow(r.chg_1w)}</td><td class=num>${arrow(r.chg_1m)}</td>
      <td class=num>${arrow(r.chg_3m)}</td><td class=num>${arrow(r.chg_12m)}</td>
      <td class=num>${r.rs_rank==null?"—":`<b style="color:${r.rs_rank>=80?"var(--up)":r.rs_rank<=20?"var(--down)":"inherit"}">${r.rs_rank}</b>`}</td>
      <td class=num>${r.rsi==null?"—":r.rsi.toFixed(0)}</td>
      <td>${r.above_200==null?"—":`<span class="pill" style="color:${r.above_200?"var(--up)":"var(--down)"}">${
        r.above_50&&r.above_200?"above 50/200":r.above_200?"above 200":"below 200"}</span>`}</td>
      <td class=num>${arrow(r.from_52w_high)}</td>
      <td class=num title="${r.insiders ? esc((r.insiders.buyers||[]).concat(r.insiders.sellers||[]).join("; ")) : ""}">${
        !r.insiders ? "—" : r.insiders.net_usd >= 0
          ? `<span style="color:var(--up)">+${money(r.insiders.net_usd)}</span>`
          : `<span style="color:var(--down)">−${money(Math.abs(r.insiders.net_usd))}</span>`}</td>
      <td class=num>${r.owned?`<span class="pill" style="color:var(--up)">own</span> ${pct(r.unrealised_pct)}`:""}</td>
      <td>${callCell(r.symbol)}</td>
      <td class="note" style="max-width:260px">${noteCell(r)}</td>
      <td class="note">${esc(r.tags.filter(t=>t!=="yahoo").join(", "))}</td>
      <td><button data-del="${esc(r.symbol)}" title="Remove">×</button></td></tr>`).join("") +
    `</table></div>`;
  // The app's call, from the Outlook's watchlist scope (fetched once, reused).
  const callCell = sym => {
    const v = OUTLOOK_WL && OUTLOOK_WL.verdicts && OUTLOOK_WL.verdicts[sym];
    if(!v) return `<span class="note">${OUTLOOK_WL ? "—" : "…"}</span>`;
    const tf = {D: "day", W: "wk", M: "mo"}[v.headline_timeframe] || "";
    return `<span class="vd vd-${/buy|add/.test(v.headline) ? "buy" : /sell|trim/.test(v.headline) ? "sell" : "none"}">${esc(v.headline || v.verdict || "")}</span> <span class="note">${tf}${v.headline_confidence ? " " + esc(v.headline_confidence) : ""}${v.flip ? ` · flips ${money(v.flip)}` : ""}</span>`;
  };
  const noteCell = r => `<span data-wlshow="${esc(r.symbol)}">${r.note ? esc(r.note) : ""}${r.target ? ` <b>target ${money(r.target)}</b>${r.to_target != null ? ` (${r.to_target > 0 ? "+" : ""}${(r.to_target*100).toFixed(0)}%)` : ""}` : ""}${r.stop ? ` <span style="color:var(--down)">stop ${money(r.stop)}</span>` : ""}</span>
    <button data-wledit="${esc(r.symbol)}" title="Set note, target and stop" style="padding:0 5px">✎</button>
    <span data-wlform="${esc(r.symbol)}" hidden><input data-f="note" placeholder="note" value="${esc(r.note || "")}" style="width:150px"> <input data-f="target" type="number" step="0.01" placeholder="target" value="${r.target ?? ""}" style="width:80px"> <input data-f="stop" type="number" step="0.01" placeholder="stop" value="${r.stop ?? ""}" style="width:80px"> <button data-wlsave="${esc(r.symbol)}">save</button></span>`;

  const inner = (label, list, key) => `
    <details class="sub" data-key="${key}"${open.has(key)?" open":""}>
      <summary>${THEME_LABEL[label] || label}
        <span class="count">${list.length}</span>
        <span class="spark" title="The average one-month price change of the names in this group — the same 1m column, averaged. Not the sector fund: that is under Money → Sectors.">avg 1m ${arrow(avg(list))}</span></summary>
      ${table(list)}
    </details>`;

  let html = "";
  const outerKeys = Object.keys(tree).sort((a,b)=>
    a === "Unknown" ? 1 : b === "Unknown" ? -1 : a.localeCompare(b));
  outerKeys.forEach(ok=>{
    const inners = tree[ok];
    const all = Object.values(inners).flat();
    const uniq = [...new Set(all.map(r=>r.symbol))];
    const innerKeys = Object.keys(inners).sort();
    const body = innerKeys.map(ik => inner(ik, inners[ik], `${ok}/${ik}`)).join("");
    if(ok === "_"){ html += body; }
    else {
      html += `<details class="group" data-key="${ok}"${open.has(ok)?" open":""}>
        <summary>${ok}<span class="count">${uniq.length} names · ${innerKeys.length} themes</span>
          <span class="spark" title="The average one-month price change of the names in this group — the same 1m column, averaged. Not the sector fund: that is under Money → Sectors.">avg 1m ${arrow(avg(all))}</span></summary>${body}</details>`;
    }
  });
  $("#wlgroups").innerHTML = html || `<div class="panel note">Nothing matches this filter.</div>`;
  if(!OUTLOOK_WL && !WL_VERDICTS_PENDING){
    WL_VERDICTS_PENDING = true;
    // The verdicts land later than the rows; repaint from the rows in hand
    // rather than fetching the list again.
    fetchOutlookWL().then(wl => { if(wl && !wl.error) renderWatchlist(); }).catch(() => {}).finally(() => { WL_VERDICTS_PENDING = false; });
  }
  // Row clicks, the pencil, save and delete are all handled by ONE delegated
  // listener on #wlgroups (bound once, below loadWatchlist). Binding per row
  // here put 220 × 4 listeners on the page, and the [data-sym] one doubled
  // the document-level delegate, so a symbol click fired the chart twice.
  document.querySelectorAll("#wlgroups details").forEach(dt =>
    dt.addEventListener("toggle", rememberGroups));

  const owned = rows.filter(r=>r.owned).length;
  $("#wlnote").innerHTML = `${rows.length} names${keep?` tagged “${keep}”`:""}, ${owned} owned.
    Grouped by ${$("#wlgroup").selectedOptions[0].textContent.toLowerCase()}, sorted by
    ${$("#wlsort").selectedOptions[0].textContent.toLowerCase()}. A name carries several themes,
    so it appears under each one it belongs to.`;
}

// The methods run across the whole liquid market, nightly; what qualifies
// and is not yet watched. One click adds a name to the list, where the
// verdict engine will read it properly.
async function loadRebuy(){
  const el = $("#rebuylist");
  if(!el || el.dataset.loaded) return;
  el.innerHTML = loadingHTML("Reading the names you sold…");
  let d;
  try{ d = await (await fetch("/api/rebuy")).json(); }
  catch(e){ el.innerHTML = `<div class="note">Could not read them: ${esc(String(e).slice(0, 120))}</div>`; return; }
  el.dataset.loaded = "1";
  renderRebuy(el, d);
}

function renderRebuy(el, d){
  // Held names are not here: their buy-back readings sit on the Outlook card
  // under the ladder, so a name is in one list, not two.
  const rows = (d.rows || []).filter(r => r.why_here !== "sold part");
  if(!rows.length){ el.innerHTML = `<div class="note">Nothing sold out of in the last year and no watchlist names with bars.</div>`; return; }
  const tone = s => /confirmed/.test(s) ? "vd-buy" : /floor|washed/.test(s) ? "vd-buy" : /zone|sale/.test(s) ? "vd-none" : "vd-none";
  const ready = rows.filter(r => r.state !== "not yet"), rest = rows.filter(r => r.state === "not yet");
  const row = r => {
    const R = r.readings;
    return `<tr class="clickable" data-sym="${esc(r.symbol)}" title="Open the chart">
      <td><b>${esc(r.symbol)}</b><div class="note">${esc(r.why_here)}${r.ladder ? ` · ladder ${r.ladder.stage}/3` : ""}</div></td>
      <td><span class="vd ${tone(r.state)}">${esc(r.state)}</span>${r.wash ? ` <span class="vd vd-sell" title="Buying back before ${esc(r.wash.window_closes)} disallows the loss">wash ${r.wash.days_left}d</span>` : ""}</td>
      <td class=num>${money(R.price)}</td>
      <td class=num><span style="${col(R.drawdown)}">${sign(R.drawdown)}${Math.abs(R.drawdown*100).toFixed(0)}%</span>${R.drawdown <= -0.55 ? ` <span class="yn yes" title="washed out: 55% or more off the high">✓</span>` : ""}</td>
      <td class=num>${R.wr_done == null ? "—" : R.wr_done}${R.wr_done != null && R.wr_done <= -97 ? ` <span class="yn yes" title="at the floor">✓</span>` : ""}${R.wr_now != null && R.wr_now !== R.wr_done ? ` <span class="note">(${R.wr_now} so far)</span>` : ""}</td>
      <td class=num>${r.sale ? saleCell(r.sale, R.price) : "—"}</td>
      <td class=num>${r.zones.length ? r.zones.slice(0, 2).map(z => `<div title="${esc(z.note)}">${esc(z.author)} ${z.lo === z.hi ? money(z.lo) : `${money(z.lo)}–${money(z.hi)}`} <span class="note">${z.inside ? "inside" : `${(z.distance*100) > 0 ? "+" : ""}${(z.distance*100).toFixed(0)}%`}</span></div>`).join("") : "—"}</td>
      <td style="max-width:520px;font-size:13px">${r.have.map(h => `<div>+ ${esc(h)}</div>`).join("")}${r.missing.map(m => `<div class="note">− ${esc(m)}</div>`).join("")}</td>
    </tr>`;
  };
  // Was it a good sell? Price lower than where you sold is the one plain
  // answer: you have the cash and could buy back cheaper. Green for that, red
  // for a name that ran away, the words in the cell rather than a bare sign.
  const saleCell = (sale, now) => {
    const move = now / sale.price - 1;
    const good = move < 0;
    const colour = Math.abs(move) < 0.02 ? "inherit" : good ? "var(--up)" : "var(--down)";
    const word = Math.abs(move) < 0.02 ? "about where you sold" : good ? `${Math.abs(move*100).toFixed(0)}% lower — good sell` : `${(move*100).toFixed(0)}% higher — sold early`;
    return `<div>sold ${esc(sale.date)} at ${money(sale.price)}</div><div style="color:${colour};font-weight:600">now ${word}</div>`;
  };
  const table = rs => `<table><tr><th scope=col>Name</th><th scope=col>State</th><th class=num scope=col>Price</th>
      <th class=num scope=col title="Close against the 52-week high. IREN's washed-out lows sat 55–66% down.">From high</th>
      <th class=num scope=col title="Weekly Williams %R (14) on the last closed week. The floor is −97 with 40%+ off the high: on IREN since 2023 every such reading was within 8% of a low; in 2022 it fired three times and kept falling.">Weekly %R</th>
      <th class=num scope=col title="Your last sale on the name, and whether it was a good one: green when price is now lower than you sold (you could buy back cheaper), red when it has gone higher since. Buying back 30% under the sale kept more shares on only 9 of 36 names.">Your sale — was it good?</th>
      <th class=num scope=col title="Buy and downside zones the people you follow have named, with price against them">Followed zones</th>
      <th scope=col>What is there, and what is not</th></tr>${rs.map(row).join("")}</table>`;
  el.innerHTML = (ready.length ? table(ready) : `<div class="note">No name has a reading in place tonight.</div>`) +
    (rest.length ? `<details style="margin-top:8px"><summary class="note">${rest.length} more with nothing in place yet</summary>${table(rest)}</details>` : "") +
    `<div class="note" style="margin-top:8px">${esc(d.note || "")}</div>`;
}

async function loadSetups(){
  loadRebuy();
  // The scan first: it is cached nightly and paints at once, while the
  // watchlist's verdicts can take a while cold. The list then renders the
  // holdings as soon as they are known and adds the watchlist when it lands.
  loadDiscover();
  const el = $("#setupslist");
  if(el){
    el.innerHTML = loadingHTML("Reading tonight's setups…");
    try{
      const held = OUTLOOK || await (await fetch("/api/outlook")).json();
      let scan = null;
      try{ scan = await fetchDiscover(); }catch(e){ scan = null; }
      const wlPromise = fetchOutlookWL();
      let lastWl = null;
      const paint = (wl) => { lastWl = wl; renderSetups(el, held, wl, scan); };
      ["suHeld", "suWatch", "suScan"].forEach(id => { const c = $("#" + id); if(c && !c.dataset.wired){ c.dataset.wired = "1"; c.addEventListener("change", () => paint(lastWl)); } });
      paint(null);
      // A failed or slow watchlist read must not blank the holdings that are
      // already on the page — it did, and the tab read "unavailable".
      let wl = null;
      try{ wl = await wlPromise; }catch(e){ wl = {error: String(e)}; }
      if(wl && !wl.error){ OUTLOOK_WL = OUTLOOK_WL || wl; paint(wl); }
      else {
        const n = $("#setupswl");
        if(n) n.textContent = "The watchlist could not be read just now" + (wl && wl.error ? ` (${String(wl.error).slice(0, 80)})` : "") + " — the holdings above are complete; open the tab again in a minute for the watchlist names.";
      }
    }catch(e){ el.innerHTML = `<div class="note">Setups unavailable: ${esc(String(e).slice(0, 120))}</div>`; }
  }
}

function renderSetups(el, held, wl, scan){
  const rows = [];
  const tfName = {M: "monthly", W: "weekly", D: "daily"};
  const reasonFor = (v) => {
    const parts = [];
    const lead = tfName[v.headline_timeframe] || "daily";
    const because = (v.headline_timeframe === "M" ? (v.monthly_because || v.weekly_because || v.because)
                   : v.headline_timeframe === "W" ? (v.weekly_because || v.because) : (v.because || v.weekly_because)) || [];
    const w = v.watch || {};
    // The plan first, in the three numbers, before any evidence. A reading
    // that opens with which timeframe said what asks the reader to blend
    // three verdicts into one decision, which is the work the app is for.
    const bk = (v.book && v.book.book) || "swing";
    parts.push(`Held as a ${bk} (${bk === "conviction" ? "months" : "days to weeks"}).`);
    const plan = [];
    if(w.buy_at) plan.push(`BUY AT ${money(w.buy_at)}${w.buy_now ? " — price is at it now" : ` (${w.buy_pct}%)`}`);
    // On a trade-around name the core is never sold; the slice is.
    const ta = v.book && v.book.trade_around;
    if(w.trim_at) plan.push(`${ta ? "SELL THE SLICE INTO" : "SELL INTO"} ${money(w.trim_at)} (${w.trim_pct > 0 ? "+" : ""}${w.trim_pct}%)`);
    if(w.stop_at) plan.push(`WRONG BELOW ${money(w.stop_at)} (${w.stop_pct}%)`);
    if(plan.length) parts.push(plan.join(" · ") + ".");
    // What each level is being taken FOR, measured from the LEVEL rather than
    // from today's price — the reader is being told to wait, so a number off
    // the current price describes a different trade from the one on offer.
    if(w.buy_at && w.buy_target){
      let s = `Buying ${money(w.buy_at)} targets ${money(w.buy_target)} (${w.buy_target_pct > 0 ? "+" : ""}${w.buy_target_pct}%)`;
      if(w.buy_rr) s += ` against ${money(w.stop_at)} (${w.buy_risk_pct}%) — ${w.buy_rr} to 1`;
      parts.push(s + ".");
    }
    if(w.trim_at && w.sell_target)
      parts.push(`Selling into ${money(w.trim_at)} targets a pullback to ${money(w.sell_target)} (${w.sell_target_pct}%).`);
    if(w.stop_at && w.trim_at) parts.push(`Nothing to do between ${money(w.stop_at)} and ${money(w.trim_at)}.`);
    // A blank side is a finding, not an oversight, so it is stated.
    const missing = [["buy level", w.buy_at], ["sell level", w.trim_at],
                     ["invalidation level", w.stop_at]].filter(m => !m[1]).map(m => m[0]);
    if(missing.length) parts.push(`No ${missing.join(", no ")} — nothing tested enough on that side to trade.`);
    // An add level UNDER the invalidation level is worth saying out loud: by
    // the time it prints, the reason for owning the name is already gone.
    if(w.buy_at && w.stop_at && w.buy_at < w.stop_at)
      parts.push(`The add level sits below the invalidation level — if it gets to ${money(w.buy_at)}, the reason to own it has already broken.`);
    if(w.trim_why) parts.push(`That sell level: ${w.trim_why}.`);
    if(because.length) parts.push(`Evidence (${lead}): ${because.slice(0, 2).join("; ")}.`);
    const rec = v.record && v.record[tfName[v.headline_timeframe]];
    if(rec && rec.mean_excess != null) parts.push(`Record: calls with this evidence ${rec.mean_excess >= 0 ? "beat" : "lagged"} SPY by ${(rec.mean_excess*100).toFixed(1)}% on average over 21 days, right ${Math.round(rec.share*100)}% of the time (${rec.calls.toLocaleString()} replayed).`);
    if(v.earnings && v.earnings.days != null && v.earnings.days <= 10) parts.push(`Reports in ${v.earnings.days} day${v.earnings.days === 1 ? "" : "s"}.`);
    // The most recent followed-author level that is a place to BUY (a zone or
    // a downside zone), else their most recent level of any kind.
    if(v.wash && (v.headline === "buy" || v.headline === "add")){
      parts.push(v.wash.possible
        ? `WASH-SALE RISK: you sold this on ${v.wash.date} (from the confirmation email; if at a loss, buying back before ${v.wash.window_closes} disallows it — ${v.wash.days_left} days to wait).`
        : `WASH SALE: you sold ${Math.abs(v.wash.quantity)} shares at a loss of ${money(Math.abs(v.wash.loss))} on ${v.wash.date}; buying back before ${v.wash.window_closes} disallows that loss — ${v.wash.days_left} days to wait.`);
    }
    const zones = (v.outside || []).filter(x => x.level && /zone|buy/.test(x.action));
    const o = zones[0] || (v.outside || []).find(x => x.level);
    if(o){
      const rel = v.price ? ((o.level / v.price - 1) * 100) : null;
      const lvl = o.hi && o.hi !== o.level ? `${money(o.level)}–${money(o.hi)}` : money(o.level);
      parts.push(`${esc(o.author.split(" (")[0])} (${o.date.slice(5)}): ${esc(o.action)} ${lvl}${rel == null ? "" : `, ${rel > 0 ? "+" : ""}${rel.toFixed(0)}% from here`}${rel != null && rel < -3 && /zone/.test(o.action) && (v.headline === "buy" || v.headline === "add") ? " — below the app's level; the app is earlier, they are cheaper" : ""}.`);
    }
    return parts.join(" ");
  };
  // A setup is a name you could act on tonight with more than one thing
  // lining up. A monthly BUY whose act level is 14% below price, on its own,
  // is not one — and that was 71 of 71 watchlist rows, ranked by a
  // confidence word the replay found unordered. Each row now needs price at
  // its act level AND at least one confirmation; the rest fold away.
  const SECTOR_STRENGTH = Object.assign({}, (held && held.sector_strength) || {}, (wl && wl.sector_strength) || {});
  const sectorNote = (v) => {
    const ss = v.sector && SECTOR_STRENGTH[v.sector];
    if(!ss) return "";
    if(ss.score > 0 && ss.rank <= 4) return ` Sector: ${esc(v.sector)} is leading the market (rank ${ss.rank} of ${ss.of}) — supporting, not a reason on its own.`;
    return ss.score < -0.05 ? ` Sector caution: ${esc(v.sector)} is lagging the market (rank ${ss.rank} of ${ss.of}).` : ` Sector: ${esc(v.sector)}, rank ${ss.rank} of ${ss.of} — middling.`;
  };
  const linesUp = (v) => {
    const out = [];
    const rec = v.record && v.record[tfName[v.headline_timeframe]];
    if(rec && rec.mean_excess != null && rec.mean_excess >= 0.03 && rec.calls >= 200)
      out.push(`the record: calls with this evidence beat SPY by ${(rec.mean_excess*100).toFixed(1)}% on average over 21 days (${rec.calls.toLocaleString()} replayed)`);
    if(v.weekly === "buy" || v.weekly === "add") out.push("the weekly agrees");
    if(v.headline_timeframe !== "D" && (v.daily === "buy" || v.daily === "add")) out.push("the daily agrees");
    const zones = (v.outside || []).filter(o => o.level && v.price && /zone|buy/.test(o.action) && Math.abs(o.level / v.price - 1) <= 0.05);
    if(zones.length) out.push(`${esc(zones[0].author.split(" (")[0])}'s ${esc(zones[0].action)} at ${money(zones[0].level)} is here too`);
    const cup = (v.because || []).concat(v.weekly_because || [], v.monthly_because || []).find(r => /cup/i.test(r || ""));
    if(cup) out.push("a cup and handle: " + esc(cup));
    if(v.rebuy && /floor|washed/.test(v.rebuy.state)) out.push(`buy-back reading: ${esc(v.rebuy.state)}`);
    // Sector strength: leading counts for it; lagging is said in the reason
    // and counts for nothing.
    // Supporting only: half the watchlist is Technology, so "sector leading"
    // on its own would put every Technology name at its level on the list.
    // It is written into the reason but cannot be the one thing lining up.
    const ss = v.sector && SECTOR_STRENGTH[v.sector];
    if(ss && ss.score > 0 && ss.rank <= 4 && out.length) out.push(`its sector, ${esc(v.sector)}, is leading the market (relative strength rank ${ss.rank} of ${ss.of})`);
    if(v.ladder && v.ladder.armed === false && v.ladder.stage === 0 && v.rebuy == null && (v.because || []).some(r => /Williams/i.test(r) && /-9\d/.test(r))) out.push("weekly Williams %R at the floor");
    return out;
  };
  const atLevel = (v) => { const w = v.watch || {}; return w.buy_at == null || w.buy_pct == null || Math.abs(w.buy_pct) <= 3; };
  const take = (src, where) => Object.entries((src && src.verdicts) || {}).forEach(([sym, v]) => {
    if(v.headline !== "buy" && v.headline !== "add") return;
    const rec = v.record && v.record[tfName[v.headline_timeframe]];
    const lines = linesUp(v), here = atLevel(v);
    const w = v.watch || {};
    rows.push({sym, where, call: v.headline, conf: v.headline_confidence, tf: v.headline_timeframe,
               price: v.price, v, lines, here,
               setup: here && lines.length > 0,
               reason: (lines.length ? `Lines up: ${lines.join("; ")}. ` : "") + reasonFor(v) + (lines.some(l => /its sector/.test(l)) ? "" : sectorNote(v)),
               // the record first, then how close the act level is; the confidence word last
               rank: [-(rec && rec.mean_excess != null ? rec.mean_excess : -1), Math.abs(w.buy_pct || 0), -(lines.length)]});
  });
  take(held, "held"); if(wl) take(wl, "watchlist");
  const onLists = new Set(rows.map(r => r.sym));
  if(scan && scan.day){
    Object.entries(scan.methods || {}).forEach(([key, m]) => (m.hits || []).forEach(h => {
      if(onLists.has(h.symbol)) return;
      rows.push({sym: h.symbol, where: "scan", call: "scan", conf: h.pct >= 0.9 ? "high" : h.pct >= 0.75 ? "medium" : "low", tf: null,
                 price: h.price, scanName: m.name, scanKey: key,
                 reason: `Meets ${Math.round((h.pct || 0)*100)}% of the ${m.name} conditions; relative-strength rank ${h.rs_rank ?? "—"} across the screen; flagged ${h.days_flagged} of the last 7 nights. ${(h.name || "").slice(0, 60)}. A scan hit is a name to look at, not a call: the replay found the encoded methods carry little edge on their own.`,
                 rank: [3 + (h.pct >= 0.9 ? 0 : 1), -(h.pct || 0), -(h.rs_rank || 0)]});
    }));
  }
  const show = {held: $("#suHeld") ? $("#suHeld").checked : true, watchlist: $("#suWatch") ? $("#suWatch").checked : true, scan: $("#suScan") ? $("#suScan").checked : true};
  const sorter = (a, b) => { for(let i = 0; i < 3; i++){ if(a.rank[i] !== b.rank[i]) return a.rank[i] - b.rank[i]; } return a.sym.localeCompare(b.sym); };
  // The scan can return a thousand names; the list is for reading. The
  // strongest 25 scan hits ride along, the rest are counted.
  const SCAN_CAP = 25;
  const scanRows = rows.filter(r => r.where === "scan").sort(sorter);
  const scanHidden = Math.max(0, scanRows.length - SCAN_CAP);
  const listed = rows.filter(r => show[r.where] && (r.where !== "scan" || scanRows.indexOf(r) < SCAN_CAP));
  const vis = listed.filter(r => r.where === "scan" ? true : r.setup).sort(sorter);
  const rest = listed.filter(r => r.where !== "scan" && !r.setup).sort(sorter);
  const restNote = rest.length ? `<details style="margin-top:8px"><summary class="note" style="cursor:pointer">${rest.length} more read buy or add but are not a setup tonight — ${rest.filter(r => !r.here).length} with the act level more than 3% away, ${rest.filter(r => r.here && !r.lines.length).length} at a level with nothing else lining up. Open to see them.</summary>
      <div class="note" style="margin:6px 0">${rest.map(r => `<span style="display:inline-block;margin:2px 10px 2px 0"><b>${esc(r.sym)}</b> ${esc(tfName[r.tf] || "")} ${esc(r.conf || "")}${r.v && r.v.watch && r.v.watch.buy_pct != null ? ` · act at ${money(r.v.watch.buy_at)} (${r.v.watch.buy_pct > 0 ? "+" : ""}${r.v.watch.buy_pct}%)` : ""}</span>`).join("")}</div></details>` : "";
  // The three prices lead — buy at, sell into, wrong below — then the name,
  // the call and one line of why; the paragraph folds under "why". A scan hit
  // has no verdict, so its three cells are dashes that say so.
  const oneLine = r => r.lines && r.lines.length ? `Lines up: ${r.lines.join("; ")}.` : (r.reason.split(/(?<=\.)\s/)[0] || r.reason);
  el.innerHTML = (!vis.length ? `<div class="note">${wl ? "No setup tonight: nothing reads buy or add at a level to act on with something else lining up." : "Nothing held is a setup tonight."}</div>` :
    `<div class="tscroll"><table class="stacklist">
      <tr><th scope=col>#</th><th class=num scope=col>Buy at</th><th class=num scope=col>Sell into</th><th class=num scope=col>Wrong below</th><th scope=col>Symbol</th><th scope=col>Call</th><th scope=col style="min-width:360px">Why</th><th scope=col></th></tr>
      ${vis.map((r, i) => `<tr class="clickable" data-setup="${esc(r.sym)}" data-where="${r.where}">
        <td class="note">${i + 1}</td>
        ${threeLevels(r.v, r.where === "scan" ? {noneWhy: "A scan hit is a name to look at, not a call: open it for the read and its levels."} : null)}
        <td style="min-width:120px"><b>${esc(r.sym)}</b> <span class="note">${r.price == null ? "" : money(r.price)}</span><div class="note">${r.where === "held" ? "held" : r.where === "watchlist" ? "watchlist" : "scan"}${r.tf ? ` · ${tfName[r.tf]}` : r.scanName ? ` · ${esc(r.scanName)}` : ""}</div></td>
        <td>${r.call === "scan" ? `<span class="vd vd-none">scan</span><span class="vdconf">${esc(r.conf)}</span>` : vdPill(r.call, r.conf, r.v && r.v.record && r.v.record[tfName[r.tf]])}</td>
        <td class="wide prose" style="font-size:13px;line-height:1.45">${esc(oneLine(r))}
          <details><summary class="note" style="cursor:pointer;min-height:28px;display:inline-flex;align-items:center">why</summary><div class="note" style="margin-top:4px">${esc(r.reason)}</div></details></td>
        <td>${r.where === "scan" ? `<button data-discadd="${esc(r.sym)}" title="Add to the watchlist">+ watch</button>` : ""}</td></tr>`).join("")}
    </table></div>`) + restNote + (show.scan && scanHidden ? `<div class="note" style="margin-top:6px">${scanHidden} more scan hits not shown here — the scan's full table is under New Stocks.</div>` : "");
  // A row opens the name's page on The read, for a holding, a watchlist name
  // or a scan hit alike — the page reads a name on neither list live.
  el.querySelectorAll("tr[data-setup]").forEach(tr => tr.addEventListener("click", (ev) => {
    if(ev.target.closest("button, details, summary, a")) return;
    openSymbol(tr.dataset.setup, "read");
  }));
  el.querySelectorAll("[data-discadd]").forEach(b => b.addEventListener("click", async ev => {
    ev.preventDefault(); ev.stopPropagation();
    b.disabled = true; b.textContent = "adding…";
    try{ await loadWatchlist({action: "add", symbol: b.dataset.discadd}); b.textContent = "watching"; }
    catch(e){ b.disabled = false; b.textContent = "+ watch"; }
  }));
  if(!wl) el.insertAdjacentHTML("beforeend", `<div class="note" id="setupswl" style="margin-top:6px">Watchlist names are still being read…</div>`);
}

// One request for the scan, shared. Opening Setups fetched /api/discover
// twice at once (loadDiscover and loadSetups' own copy) and New Stocks a
// third time. Forgotten when the watchlist changes, because the scan leaves
// out names already on the list.
let DISCOVER = null;

function fetchDiscover(force){
  if(force || !DISCOVER){
    DISCOVER = fetch("/api/discover").then(r => r.json());
    DISCOVER.catch(() => { DISCOVER = null; });   // a failure is not cached
  }
  return DISCOVER;
}

async function loadDiscover(force){
  const el = $("#discover");
  if(!el) return;
  let d;
  try{ d = await fetchDiscover(force); }
  catch(e){ el.innerHTML = `<div class="note">Discovery unavailable.</div>`; return; }
  // Accumulation goes FIRST and is rendered even when the method scan has not
  // run, because it is the one discovery signal here with a measured edge:
  // CORRECTED 2026-09-10. The headline used to be "11.5% quadrupled within a
  // year against a 1.5% base rate". That is true and it is about the PEAK, which
  // you only capture with perfect timing. Traded as a portfolio the same signals
  // compound at a geometric mean of 1.011 over a year and 0.943 over a quarter —
  // nothing, and a loss. The panel now leads with what the money does.
  // (research/audits/edge-log.md, 2026-09-09). The method blocks below it are
  // condition screens with no such measurement behind them.
  const acc = d.accumulation || [];
  // What a row has to say for the tab to be worth opening: the company and
  // its business in words, how it has moved, and who among the followed
  // accounts has posted it. A ticker and a volume multiple were the whole row
  // until 2026-09-13 and the user's reading was "nothing useful".
  const arrowPct = v => v == null ? "—" : `<span style="${col(v)}">${pct(v)}</span>`;
  const whatItIs = r => `<div><b>${esc((r.name || "").replace(/ (Common|Ordinary) (Stock|Shares?)( Class A| Ordinary Shares?)?$/i, "").replace(/, Inc\.?$/, "").slice(0, 44))}</b></div>` +
    `<div class="note">${[r.sector, r.business].filter(Boolean).map(esc).join(" · ") || "not in EDGAR yet — the nightly scan looks it up"}${r.rs_rank != null ? ` · RS ${r.rs_rank}` : ""}</div>`;
  const crowdCell = (c, cov) => {
    if(!c) return `<span class="note">\u2014</span>`;
    const colr = c.state === "crowded" ? "var(--down)" : c.state === "warming" ? "var(--warn)" : "var(--up)";
    const thin = cov && cov.thin;
    const label = (thin && c.accounts === 0) ? "no data" : c.state;
    const who = (c.handles || []).slice(0, 3).map(h => "@" + h).join(", ");
    return `<span style="color:${thin && c.accounts === 0 ? "var(--muted)" : colr}">${esc(label)}</span>`
         + (c.accounts ? ` <span class="note" title="${esc((c.handles || []).map(h => "@" + h).join(", "))}">${c.accounts}${who ? ": " + esc(who) : ""}</span>` : "");
  };
  const accBlock = !acc.length ? "" : `
    <details class="sub" open><summary>Quietly accumulating <span class="count">${acc.length}</span></summary>
      <div class="note" style="margin:6px 0">Dollar volume has expanded 4–20x against its own six-month base
        while the price has <b>not</b> yet run.
        <b>Read this as a place to look, not as an edge.</b> Bought mechanically and held a year, these names
        compound at 1.01x — nothing — and held a quarter, 0.94x, a loss; 40% end below where they flagged.
        The often-quoted "11.5% reach 4x" is true of the highest price they touch, which you only get with
        perfect timing. What the scan does reliably is surface names early: it found IREN at 3.75 (bought at
        10.47) and DGXX at 1.38 (bought at 4.42), and missed six of twelve holdings entirely. The work of
        deciding which ones are worth owning is still yours. Names on this list do go to zero — UPC did —
        so this argues for many small positions rather than a few large.
        <b>Crowd</b> counts how many accounts you follow have posted the ticker in the last 30 days:
        <span style="color:var(--up)">early</span> is nobody, <span style="color:var(--warn)">warming</span> two or more,
        <span style="color:var(--down)">crowded</span> four or more. Those cut-offs are a judgement, not a
        measurement — testing them needs post history from before each name ran, which is not on disk.
        ${d.crowd_coverage && d.crowd_coverage.thin
          ? `<b>Right now the crowd column is unreliable</b>: only ${d.crowd_coverage.days} day(s) of posts have been
             pulled (${esc(d.crowd_coverage.first || "")}\u2013${esc(d.crowd_coverage.last || "")}, ${d.crowd_coverage.handles} accounts),
             so "no data" is shown instead of "early". Run the weekly X pull and
             <code>python3 research/x-mentions.py</code> to fill it in.`
          : ""}</div>
      <div class="tscroll"><table>
        <tr><th scope=col>Symbol</th><th scope=col title="The company, its sector and the line the SEC has on what it does">What it is</th>
            <th class=num scope=col title="Recent dollar volume against its own 126-session base">Vol ×</th>
            <th class=num scope=col title="Price now against 126 sessions ago — under 1.25 means it has not run">Run-up</th>
            <th class=num scope=col>Price</th>
            <th class=num scope=col>1w</th><th class=num scope=col>1m</th><th class=num scope=col>3m</th>
            <th class=num scope=col title="Close against the highest price of the last year">From 52w high</th>
            <th class=num scope=col>$/day</th>
            <th scope=col title="When it first qualified">First seen</th>
            <th class=num scope=col title="Sessions it has qualified on">Nights</th>
            <th scope=col title="How many accounts you follow have posted about it in the last 30 days, and who">Crowd</th>
            <th scope=col></th></tr>
        ${acc.map(r => `<tr>
          <td class="clickable" data-sym="${esc(r.symbol)}"><b>${esc(r.symbol)}</b></td>
          <td style="max-width:260px">${whatItIs(r)}</td>
          <td class=num><b>${r.surge == null ? "—" : r.surge.toFixed(1) + "×"}</b></td>
          <td class=num>${r.runup == null ? "—" : r.runup.toFixed(2)}</td>
          <td class=num>${money(r.price)}</td>
          <td class=num>${arrowPct(r.chg_1w)}</td><td class=num>${arrowPct(r.chg_1m)}</td><td class=num>${arrowPct(r.chg_3m)}</td>
          <td class=num>${arrowPct(r.from_52w_high)}</td>
          <td class=num>${r.dollar_volume == null ? "—" : "$" + (r.dollar_volume / 1e6).toFixed(0) + "M"}</td>
          <td class="note">${esc(r.first_day || "")}</td>
          <td class=num>${r.nights}</td>
          <td>${crowdCell(r.crowd, d.crowd_coverage)}</td>
          <td><button data-discadd="${esc(r.symbol)}" title="Add to the watchlist">+ watch</button></td></tr>`).join("")}
      </table></div></details>`;
  if(!d.day){
    el.innerHTML = accBlock + `<div class="note">The method scan has not run yet. <code>python3 -m app.discover screen</code> once
      (half an hour, weekly), then <code>python3 -m app.discover scan</code> nightly — the nightly job runs it.</div>`;
    el.querySelectorAll("[data-discadd]").forEach(b => b.addEventListener("click", async ev => {
      ev.preventDefault(); ev.stopPropagation(); b.disabled = true; b.textContent = "adding…";
      try{ await loadWatchlist({action: "add", symbol: b.dataset.discadd}); b.textContent = "watching"; loadDiscover(true); }
      catch(e){ b.disabled = false; b.textContent = "+ watch"; }
    }));
    return;
  }
  const blocks = Object.entries(d.methods || {}).map(([key, m]) => {
    const rows = (m.hits || []).slice(0, 15);
    if(!rows.length) return "";
    return `<details class="sub" open><summary>${esc(m.name)} <span class="count">${m.hits.length}</span></summary>
      <div class="tscroll"><table>
        <tr><th scope=col>Symbol</th><th scope=col title="The company, its sector and the line the SEC has on what it does">What it is</th><th class=num scope=col title="Share of the method's weighted conditions met">Score</th>
            <th class=num scope=col title="Relative strength rank across every screened name">RS</th>
            <th class=num scope=col>Price</th>
            <th class=num scope=col>1m</th><th class=num scope=col>3m</th>
            <th class=num scope=col title="Close against the highest price of the last year">From 52w high</th>
            <th class=num scope=col title="Average daily dollar volume">$/day</th>
            <th class=num scope=col title="How many of the last seven scans flagged it">Nights</th><th scope=col></th></tr>
        ${rows.map(r => `<tr>
          <td class="clickable" data-sym="${esc(r.symbol)}"><b>${esc(r.symbol)}</b></td>
          <td style="max-width:260px">${whatItIs({...r, rs_rank: null})}</td>
          <td class=num>${r.pct == null ? "—" : r.pct.toFixed(2)}</td>
          <td class=num>${r.rs_rank == null ? "—" : `<b style="color:${r.rs_rank >= 80 ? "var(--up)" : r.rs_rank <= 20 ? "var(--down)" : "inherit"}">${r.rs_rank}</b>`}</td>
          <td class=num>${money(r.price)}</td>
          <td class=num>${arrowPct(r.chg_1m)}</td><td class=num>${arrowPct(r.chg_3m)}</td>
          <td class=num>${arrowPct(r.from_52w_high)}</td>
          <td class=num>${r.dollar_volume == null ? "—" : "$" + (r.dollar_volume / 1e6).toFixed(0) + "M"}</td>
          <td class=num>${r.days_flagged}</td>
          <td><button data-discadd="${esc(r.symbol)}" title="Add to the watchlist">+ watch</button></td></tr>`).join("")}
      </table></div></details>`;
  }).join("");
  el.innerHTML = `<div class="note" style="margin-bottom:8px">Scan of ${esc(d.day)} across ${(d.universe || 0).toLocaleString()} names
      that trade at least $5M a day, screened ${esc(d.screened_at || "")}. Names already on your list are left out.
      A high score on a momentum method is a name that has already gone up; the replay's finding about the engine's
      edge applies here too. This surfaces names to look at — it does not add anything on its own.</div>`
    + accBlock
    + (blocks || `<div class="note">Nothing qualified on the last method scan.</div>`);
  el.querySelectorAll("[data-discadd]").forEach(b => b.addEventListener("click", async ev => {
    ev.preventDefault(); ev.stopPropagation();
    b.disabled = true; b.textContent = "adding…";
    try{
      await loadWatchlist({action: "add", symbol: b.dataset.discadd});
      b.textContent = "watching";
      loadDiscover(true);
    }catch(e){ b.disabled = false; b.textContent = "+ watch"; }
  }));
}

let METHOD_ROWS = [];

// Open the one method scanner on a given method — a link from a followed
// author's setup page (#stocks/newstocks?method=…) lands here.
function openMethodScan(key){
  const fold = $("#methodsfold"); if(!fold) return;
  fold.open = true; fold.dataset.loaded = "1";
  loadMethods(key);
  fold.scrollIntoView({block: "start"});
}

async function loadMethods(want){
  const sel = $("#methodsel");
  const key = (typeof want === "string" && want) || sel.value || "";
  const d = await (await fetch("/api/methods?method="+encodeURIComponent(key))).json();
  if(d.error){ $("#methodnote").textContent = d.error; return; }

  if(!sel.options.length){
    sel.innerHTML = d.catalogue.map(m=>`<option value="${m.key}">${m.name}</option>`).join("");
  }
  if(key && [...sel.options].some(o => o.value === key)) sel.value = key;
  const spec = d.catalogue.find(m=>m.key === d.method) || d.catalogue[0];
  $("#methoddesc").innerHTML = `
    <div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap">
      <b>${spec.name}</b>
      <span class="pill">${ {D:"daily",W:"weekly",M:"monthly"}[spec.timeframe] || spec.timeframe }</span>
      <span class="note">${spec.source}</span>
    </div>
    <p style="margin:8px 0 0;font-size:14px">${spec.thesis}</p>
    <details style="margin-top:8px"><summary class="note" style="cursor:pointer">Evidence, invalidation, and what it ignores</summary>
      <ul class="note" style="margin:8px 0 0;padding-left:18px;display:flex;flex-direction:column;gap:5px">
        ${spec.evidence.map(e=>`<li>${e}</li>`).join("")}
      </ul>
      <p class="note" style="margin:8px 0 0"><b>Invalidated by:</b> ${spec.invalidation}</p>
      <p class="note" style="margin:6px 0 0"><b>Ignores:</b> ${spec.ignores.join("; ")}</p>
      <p class="note" style="margin:6px 0 0"><b>Caveats:</b> ${spec.caveats.join("; ")}</p>
    </details>`;

  METHOD_ROWS = d.rows;
  const held = new Set(d.held || []);
  let rows = d.rows;
  if($("#heldonly").checked) rows = rows.filter(r=>held.has(r.symbol));
  if($("#qualonly").checked) rows = rows.filter(r=>r.pct >= 0.75);

  $("#methodscan").innerHTML =
    `<tr><th scope=col>Symbol</th><th scope=col></th><th class=num scope=col>Score</th><th class=num scope=col>Met</th>
      <th class=num scope=col>Close</th><th scope=col>Missing</th></tr>` +
    (rows.length ? rows.map(r=>`<tr class="clickable" data-m="${esc(r.symbol)}">
      <td><b>${esc(r.symbol)}</b></td>
      <td>${held.has(r.symbol)?`<span class="pill" style="color:var(--up)">own</span>`:""}</td>
      <td class=num style="${r.pct>=0.75?"color:var(--up)":""}"><b>${pct(r.pct)}</b></td>
      <td class=num>${r.met}/${r.total}</td>
      <td class=num>${money(r.close)}</td>
      <td class="note">${r.missing.join(", ") || "—"}</td></tr>`).join("")
     : `<tr><td colspan=6 class="note">Nothing meets the filter.</td></tr>`);

  document.querySelectorAll("#methodscan [data-m]").forEach(el =>
    el.addEventListener("click", ()=> showMethodDetail(el.dataset.m)));

  $("#methodnote").innerHTML =
    `${d.rows.length} names scored on the ${ {D:"daily",W:"weekly",M:"monthly"}[d.timeframe] } chart,
     ${d.skipped.length} skipped for short history, ${d.qualifying.length} at or above 75%.
     <b>Scores, not signals.</b> Each name shows which conditions it fails, so the method can be
     argued with rather than obeyed — and it is a reading of someone's public content, not their
     stated system.`;
}

function showMethodDetail(symbol){
  const r = METHOD_ROWS.find(x=>x.symbol === symbol);
  if(!r) return;
  const p = $("#methoddetail");
  p.style.display = "";
  p.innerHTML = `<div style="display:flex;gap:10px;align-items:baseline;margin-bottom:8px">
      <b>${esc(r.symbol)}</b><span class="note">${money(r.close)} · as of ${esc(r.as_of)}</span>
      <span class="pill" style="color:${r.pct>=0.75?"var(--up)":"var(--muted)"}">${pct(r.pct)}</span>
      <button data-chart="${esc(r.symbol)}" style="margin-left:auto">Chart it</button>
    </div>
    <div class="tscroll"><table>
      <tr><th scope=col></th><th scope=col>Condition</th><th scope=col>Reading</th><th class=num scope=col>Weight</th><th scope=col>Why it is in the method</th></tr>
      ${r.conditions.map(c=>`<tr>
        <td>${yesNo(c.met)}</td>
        <td>${c.condition}</td><td class="note">${c.detail}</td>
        <td class=num>${c.weight}</td><td class="note">${c.why}</td></tr>`).join("")}
    </table></div>`;
  p.querySelector("[data-chart]").addEventListener("click", ()=>{
    $("#tf").value = "M"; openSymbol(r.symbol, "chart", {reload: true});
  });
}
