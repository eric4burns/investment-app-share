// Trade bot: paper trading, the record (scorecard, calibration, journal, replay) and the backtest.
// One of the dashboard's scripts (see dashboard.html): a classic script sharing the page's
// global scope with the others, loaded in the order the tags there give.

function renderScorecard(){
  const el = $("#scorecard");
  if(!el || !OUTLOOK || !OUTLOOK.scorecard) return;
  const sc = OUTLOOK.scorecard;
  const side = (s, who) => `
    <div class="card">
      <div class="k">${who}</div>
      <div class="v">${s.n}</div>
      <div class="note">graded call${s.n === 1 ? "" : "s"}${
        s.open ? ` · ${s.open} still open` : ""}</div>
      ${s.n ? `<div class="note" style="margin-top:6px">hit rate ${
        Math.round((s.hit_rate||0)*100)}% · mean ${
        s.mean_score == null ? "—" : (s.mean_score>0?"+":"")+(s.mean_score*100).toFixed(2)+"% vs SPY"}</div>` : ""}
    </div>`;
  const cal = OUTLOOK.calibration || {};
  const firstGrade = cal.first_grade_on || (cal.overall && cal.overall.first_grade_on) || null;
  el.innerHTML = `<div class="cards">${side(sc.me, "Your trades")}${side(sc.app, "The app's calls")}</div>
    <div class="note" style="margin-top:9px">${esc(sc.note)}</div>
    <div class="note" style="margin-top:6px">${esc(sc.app.verdict)}${
      (!cal.overall || !cal.overall.n) ? ` Whether the confidence words mean anything is measured here once 20 calls on 10 separate days have been graded${firstGrade ? ` — the first grades land ${esc(firstGrade)}` : ""}.` : ""}</div>
    <ul class="note" style="margin-top:8px;padding-left:17px;line-height:1.6">${
      (sc.app.caveats||[]).map(c=>`<li>${esc(c)}</li>`).join("")}</ul>`;
}

// Not "is it right" — journal.py answers that. This answers "what would I
// change", which needs the same outcomes sliced by what produced them.
// Your own trades, read out of the ledger, against what the app had been saying
// about the same name. Not "does the app score well" but "when we disagreed,
// who was right" — the comparison the journal was built for and could not run
// while it only knew about calls typed in by hand.
function renderCrossCheck(){
  const el = $("#xcheck");
  if(!el || !OUTLOOK || !OUTLOOK.cross_check) return;
  const x = OUTLOOK.cross_check;
  const sc = (OUTLOOK.scorecard || {});
  const side = (s2, who) => !s2 ? "" : `
    <div class="card"><div class="k">${who}</div>
      <div class="v">${s2.n}</div>
      <div class="note">graded call${s2.n === 1 ? "" : "s"}</div>
      ${s2.n ? `<div class="note" style="margin-top:6px">hit ${
        Math.round((s2.hit_rate||0)*100)}% · ${
        s2.mean_score == null ? "—" : (s2.mean_score>0?"+":"")+(s2.mean_score*100).toFixed(2)+"% vs SPY"}</div>` : ""}
    </div>`;
  const rows = (x.rows||[]).filter(r=>r.agreed !== null).slice(0,25).map(r=>`<tr>
      <td class="note">${esc(r.date)}</td>
      <td><b>${esc(r.symbol)}</b></td>
      <td><span class="vd vd-${esc(r.action)}">${esc(r.action)}</span></td>
      <td>${r.app ? `<span class="vd vd-${esc(r.app.action)}">${esc(r.app.action)}</span>` : "—"}</td>
      <td style="color:${r.agreed ? "var(--muted)" : "var(--warn)"};font-weight:600">${
        r.agreed ? "agreed" : "DISAGREED"}</td></tr>`).join("");
  el.innerHTML =
    `<div class="note">${esc(x.note)}</div>
     ${rows ? `<table style="width:100%;margin-top:10px">
       <tr><th scope=col>Date</th><th scope=col>Symbol</th><th scope=col>You</th>
           <th scope=col>App said</th><th scope=col></th></tr>${rows}</table>` : ""}
     <div class="note" style="margin-top:9px">Your trades are read out of the
       ledger — every buy and sell is a decision made before the outcome was
       known. Multiple fills of one order on one day count once. A sale of most
       of a position is a sell; a slice is a trim.</div>`;
}

// The Plan-vs-actual tab compared an imported spreadsheet whose category names
// are its own, matched almost none of them, and reported 62,587 against 8,242.
// Targets from your own trailing average cannot fail to match, and "more than
// usual" is the comparison worth making anyway.
function renderGoals(g){
  const el = $("#bgGoals");
  if(!el) return;
  if(!g || !g.available){ el.innerHTML = `<div class="note">Not enough months yet.</div>`; return; }
  const cur = g.current;
  const bar = g.months.map(m=>{
    const h = Math.max(2, Math.min(46, Math.round(Math.abs(m.saved) / (g.goal * 2) * 46)));
    return `<i title="${esc(m.month)} — saved ${money(m.saved)}"
      style="height:${h}px;background:${m.met ? "var(--up)" : "var(--down)"}"></i>`;
  }).join("");
  el.innerHTML = `
    <div class="cards">
      <div class="card"><div class="k">Goal</div><div class="v">${money(g.goal)}</div>
        <div class="note">kept per month</div></div>
      <div class="card"><div class="k">You average</div>
        <div class="v" style="color:${g.average_saved >= g.goal ? "var(--up)" : "var(--down)"}">${money(g.average_saved)}</div>
        <div class="note">over the last ${g.trailing_months} months</div></div>
      <div class="card"><div class="k">Months met</div>
        <div class="v">${g.months_met}/${g.months_counted}</div>
        <div class="note">of the goal, historically</div></div>
      ${cur ? `<div class="card"><div class="k">This month</div>
        <div class="v" style="color:${cur.no_pay_yet ? "var(--muted)" : cur.on_track ? "var(--up)" : "var(--down)"}">${money(cur.saved)}</div>
        <div class="note">${Math.round(cur.elapsed*100)}% through · ${
          cur.no_pay_yet ? "no pay received yet this month — the bills land first" : cur.on_track ? "on track" : `${money(cur.goal_so_far - cur.saved)} behind pace`}</div></div>` : ""}
    </div>
    <div class="smbars" style="height:50px;margin-top:12px">${bar}</div>
    <div class="smfoot">Income minus spending, month by month.
      <span style="color:var(--up)">Green</span> met the goal,
      <span style="color:var(--down)">red</span> missed it.</div>
    ${g.categories.length ? `<table style="width:100%;margin-top:14px">
      <tr><th scope=col>Category</th><th class=num scope=col>Usual month</th>
          <th class=num scope=col>So far this month</th><th class=num scope=col>Against pace</th></tr>
      ${g.categories.map(c=>`<tr>
        <td>${esc(c.category)}</td>
        <td class=num>${money(c.target)}</td>
        <td class=num>${money(c.spent)}</td>
        <td class=num style="color:${c.over ? "var(--down)" : "var(--muted)"}">${
          c.over ? "+" + money(c.over_by).slice(1) + " over the month" : c.ahead ? "paid ahead of pace, under the month" : "ok"}</td></tr>`).join("")}
    </table>` : ""}
    <div class="note" style="margin-top:10px">${esc(g.note)}</div>`;
}

// Year-to-date says whether you are over the line. In September the question is
// whether you WILL be, and by then a Roth contribution made on the wrong
// assumption has already been made.
function renderCrossings(c){
  const el = $("#bgCross");
  if(!el || !c || !c.roth) return;
  const tone = st => st === "will_exceed" || st === "will_cross" ? "var(--down)"
                   : st === "will_partial" ? "var(--warn)" : "var(--muted)";
  const box = (title, o) => `
    <div class="finding" style="border-left:3px solid ${tone(o.state)};padding-left:10px;margin-bottom:10px">
      <h4 style="margin:0 0 4px">${title}</h4>
      <div class="note">${esc(o.message || "")}</div></div>`;
  el.innerHTML =
    `<div class="note" style="margin-bottom:8px">${esc(c.projection.method || "")}</div>` +
    box("Roth", c.roth) + box("Tax bracket", c.bracket);
}

function renderCalibration(){
  const el = $("#calib");
  if(!el || !OUTLOOK || !OUTLOOK.calibration) return;
  const c = OUTLOOK.calibration;
  // Empty until the first grades land (the record panel says when); an empty
  // measurement panel is not information.
  el.hidden = !(c.overall && c.overall.n);
  if(!el.hidden) el.innerHTML = `<div class="k" style="margin-bottom:6px">Is the algorithm working?</div>` + calibrationHTML(c);
  const mine = $("#mycalib");
  if(mine && OUTLOOK.my_calibration){
    const m = OUTLOOK.my_calibration;
    mine.hidden = !(m.overall && m.overall.n);
    if(!mine.hidden) mine.innerHTML = `<div class="k" style="margin-bottom:6px">How you trade, by book and by what happened</div>
      <div class="note" style="margin-bottom:6px">Calls you logged by hand, graded the same way. Tag each one
          under "Calls made" with what happened, and put it in a book, and the slices below fill in.</div>` + calibrationHTML(m);
  }
}

// The same layout serves the live journal and the replay, since they are the
// same measurement on two different records.
function calibrationHTML(c){
  const bucket = (label, b) => !b || !b.n ? "" : `<tr>
      <td>${esc(label)}</td>
      <td class=num>${b.n}</td>
      <td class=num>${b.days}</td>
      <td class=num>${b.hit_rate == null ? "—" : Math.round(b.hit_rate*100)+"%"}</td>
      <td class=num style="${b.mean_score>0?"color:var(--up)":"color:var(--down)"}">${
        b.mean_score == null ? "—" : (b.mean_score*100).toFixed(2)}</td>
      <td class="note">${b.enough ? "" : "too few to judge"}</td></tr>`;
  const table = (title, obj) => {
    const rows = Object.entries(obj || {}).map(([k,v]) => bucket(k,v)).join("");
    return !rows ? "" : `<div style="margin-top:12px"><b>${title}</b>
      <table style="width:100%;margin-top:4px">
      <tr><th scope=col></th><th class=num scope=col>Calls</th><th class=num scope=col>Days</th>
          <th class=num scope=col>Hit</th><th class=num scope=col>Pts vs SPY</th><th></th></tr>
      ${rows}</table></div>`;
  };
  const conds = (list, title) => !list.length ? "" : `<div style="margin-top:12px"><b>${title}</b>
    <table style="width:100%;margin-top:4px">${list.map(x=>`<tr>
      <td>${esc(x.condition)}${x.stance?` <span class="pill">${esc(x.stance)}</span>`:""}</td>
      <td class=num>${x.with.n}</td>
      <td class=num style="${x.edge>0?"color:var(--up)":"color:var(--down)"}">${
        x.edge == null ? "—" : (x.edge*100).toFixed(2)+" pts"}</td></tr>`).join("")}</table></div>`;

  return `<div>${esc(c.headline)}</div>
    ${table("By action", c.by_action)}
    ${table("By timeframe", c.by_timeframe)}
    ${table("By book", c.by_bucket)}
    ${table("By what happened", c.by_tag)}
    ${table("By confidence", c.by_confidence.buckets)}
    <div class="note" style="margin-top:6px">${esc(String(c.by_confidence.finding || "").replace(/\s*That is the first thing to fix\.?$/, ""))}</div>
    ${conds(c.best || [], "Conditions helping most")}
    ${conds(c.worst || [], "Conditions helping least")}
    <div class="note" style="margin-top:10px">${esc(c.by_condition.caveat)}</div>
    <div class="note" style="margin-top:6px">${esc(c.flip_levels.finding)}</div>`;
}

// The replay: the engine run at every week-end since 2022 and graded the same
// way. Fetched on its own because the first computation takes a while and the
// rest of the tab must not wait on it.
let REPLAY_LOADED = false;

async function loadReplay(){
  const el = $("#replay");
  if(!el || REPLAY_LOADED) return;
  REPLAY_LOADED = true;
  el.innerHTML = loadingHTML("Grading the replayed calls…");
  let r;
  try{ r = await (await fetch("/api/replay?horizon=21")).json(); }
  catch(e){ el.innerHTML = `<div class="note">Replay unavailable.</div>`; REPLAY_LOADED = false; return; }
  if(r.none){ el.innerHTML = `<div class="note">${esc(r.note || "No replayed calls yet.")}</div>`; return; }
  const st = r.status || {};
  el.innerHTML = `
    <div class="note" style="margin-bottom:8px">
      <b>${(st.calls||0).toLocaleString()} calls</b> on ${st.symbols} names across ${st.days} week-ends,
      ${esc(st.first||"")} to ${esc(st.last||"")}${r.running ? " — <b>still running</b>, figures will grow" : ""}.
      Computed ${esc(r.computed_at||"")}.</div>
    ${calibrationHTML(r)}
    <ul class="note" style="margin:10px 0 0;padding-left:18px;line-height:1.6">${
      (r.caveats||[]).map(c=>`<li>${esc(c)}</li>`).join("")}</ul>`;
}

function jrnlRow(r){
  const h = (r.horizons && r.horizons[21]) || {};
  const scored = h.status === "scored";
  const col = scored ? (h.right ? "var(--up)" : "var(--down)") : "var(--muted)";
  const mine = r.source === "me" || r.source === "trade";
  // Your own calls carry the book they were in and, once they have played
  // out, a word for what happened. The app's calls carry neither.
  const tagSel = !mine ? "" : `<select data-tagfor="${r.id}" title="What happened, in a word. Calibration slices your record by it."
      style="font-size:11px;margin-left:6px">
      <option value="">${r.tag ? "— clear —" : "tag it…"}</option>
      ${(OUTLOOK.tags||[]).map(t=>`<option value="${esc(t)}"${r.tag===t?" selected":""}>${esc(t)}</option>`).join("")}</select>`;
  const bucketSel = !mine ? "" : `<select data-bucketfor="${r.id}" title="Which book" style="font-size:11px;margin-left:4px">
      <option value="">${r.bucket ? "— clear —" : "book…"}</option>
      ${(OUTLOOK.buckets||[]).map(b=>`<option value="${esc(b)}"${r.bucket===b?" selected":""}>${esc(b)}</option>`).join("")}</select>`;
  return `<div class="jrow">
    <div class="note">${esc(r.date)}${r.source === "trade" ? `<div class="jsrc">traded</div>` : r.source === "me" ? `<div class="jsrc">you</div>` : ""}</div>
    <div><b>${esc(r.symbol)}</b></div>
    <div><span class="vd vd-${esc(r.action)}">${esc(r.action)}</span></div>
    <div class="note">${r.entry == null ? "" : "at " + money(r.entry)}${
      r.flip != null ? ` · flips ${r.entry ? (r.flip > r.entry ? "above" : "below") + " " : "at "}${money(r.flip)}` : ""}${
      mine && r.rationale ? `<div class="note" style="font-style:italic">${esc(r.rationale)}</div>` : ""}${
      mine ? `<div style="margin-top:2px">${bucketSel}${tagSel}</div>` : ""}</div>
    <div style="color:${col};font-weight:600;text-align:right">${
      scored ? (h.excess >= 0 ? "+" : "−") + Math.abs(h.excess*100).toFixed(1) + "% vs SPY"
             : `<span class="jsrc">${esc(h.status||"open")}</span>`}</div>
  </div>`;
}

// One delegated listener for every tag and book select the journal renders.
document.addEventListener("change", async ev => {
  const el = ev.target;
  const kind = el.dataset && (el.dataset.tagfor ? "tag" : el.dataset.bucketfor ? "bucket" : null);
  if(!kind) return;
  const id = el.dataset.tagfor || el.dataset.bucketfor;
  el.disabled = true;
  try{
    const r = await (await fetch("/api/outlook?" + new URLSearchParams({action: kind, id, value: el.value}))).json();
    if(r.error){ el.style.borderColor = "var(--down)"; el.title = r.error; }
    else { el.style.borderColor = "var(--up)"; }
  }catch(e){ el.style.borderColor = "var(--down)"; }
  el.disabled = false;
});

// Two hosts from one payload: the whole log under AI Trade Bot → Its record,
// and the user's own decisions alone under My Money → Trades, where they sit
// beside the fills they became.
function renderJournal(){
  if(!OUTLOOK) return;
  const rows = OUTLOOK.recent || [];
  const el = $("#jrnl");
  if(el){
    el.innerHTML = !rows.length
      ? `<div class="note">No calls recorded yet. The nightly job writes the app's verdicts; your own decisions are recorded on a name's page, under The read.</div>`
      : `<div class="note" style="margin-bottom:8px">Scored at 21 trading days,
        against SPY over the same dates. A call that made money in a month the index made
        more is a loss here, which is the point.</div>` + rows.slice(0, 40).map(jrnlRow).join("");
  }
  const mine = $("#jrnl2");
  if(mine){
    const own = OUTLOOK.recent_mine || rows.filter(r => r.source === "me" || r.source === "trade");
    mine.innerHTML = !own.length
      ? `<div class="note">No decision of your own is recorded yet. Record one on a name's page (Chart → The read: "I decided to"); every buy and sell in the ledger is graded here too.</div>`
      : `<div class="note" style="margin-bottom:8px">Your own calls — typed on a name's page or read out of the ledger — scored at 21 trading days against SPY. The app's calls are under AI Trade Bot → Its record.</div>` + own.slice(0, 40).map(jrnlRow).join("");
  }
}

// Opening the tab fills the picker and explains each method. It deliberately
// does NOT run: a walk-forward over two universes takes about thirty seconds,
// and firing one off because somebody clicked a tab meant the method dropdown
// sat empty for that whole time on a method nobody had chosen. Empty controls
// during a long silent computation is indistinguishable from a broken tab,
// which is exactly how it was read.
async function loadBacktestMethods(){
  const sel = $("#btmethod");
  if(!sel || sel.options.length){ describeMethod(); loadPaper(); return showLastBacktest(); }
  let d;
  try{ d = await (await fetch("/api/backtest?catalogue=1")).json(); }
  catch(e){ $("#btnote").textContent = "Could not load the method list."; return; }
  BT_CATALOGUE = d.catalogue || [];
  // How long a run takes is set by how many rebalance dates the method's own
  // timeframe produces, and the spread is large: a monthly method is a few
  // seconds and a daily one is minutes. Saying so on the option itself is the
  // difference between waiting and assuming it has hung.
  sel.innerHTML = BT_CATALOGUE.map(m =>
    `<option value="${esc(m.key)}">${esc(m.name)} — ${esc(BT_COST[m.timeframe] || "")}</option>`
  ).join("");
  // Default to the weekly method rather than to whatever sorts first. The
  // catalogue happens to start with a DAILY method, which is the slowest run
  // here by a wide margin, so opening the tab and pressing Run landed on a
  // multi-minute job nobody had chosen.
  if(BT_CATALOGUE.some(m => m.key === BT_DEFAULT)) sel.value = BT_DEFAULT;
  describeMethod();
  showLastBacktest();
  loadPaper();
}

let BT_CATALOGUE = [];

const BT_DEFAULT = "momentum-relative-strength";

const BT_COST = {D: "minutes to run", W: "about 30 seconds", M: "a few seconds", Q: "a few seconds"};

// What you are about to test, before you spend thirty seconds testing it.
// Each method carries its own thesis, what invalidates it and what it ignores,
// and choosing between three names in a dropdown without any of that is a
// guess rather than a choice.
function describeMethod(){
  const el = $("#btabout"), key = $("#btmethod") && $("#btmethod").value;
  const m = BT_CATALOGUE.find(x => x.key === key);
  if(!el) return;
  if(!m){ el.innerHTML = ""; return; }
  el.innerHTML = `
    <div><b>${esc(m.name)}</b> <span class="pill">${esc(
      {D:"daily", W:"weekly", M:"monthly", Q:"quarterly"}[m.timeframe] || m.timeframe)}</span>
      <span class="note">· ${esc(BT_COST[m.timeframe] || "")}</span></div>
    <div class="note" style="margin-top:6px">${esc(m.thesis)}</div>
    <div class="note" style="margin-top:8px"><b>Invalidated by:</b> ${esc(m.invalidation||"—")}</div>
    ${(m.ignores||[]).length ? `<div class="note" style="margin-top:4px"><b>Ignores:</b> ${
      esc(m.ignores.join("; "))}</div>` : ""}
    ${(m.caveats||[]).length ? `<ul class="note" style="margin-top:8px;padding-left:17px;line-height:1.6">${
      m.caveats.map(c=>`<li>${esc(c)}</li>`).join("")}</ul>` : ""}
    <div class="note" style="margin-top:8px">Source: ${esc(m.source||"—")}</div>`;
}

async function loadBacktest(){
  const btn = $("#btrun");
  if(btn){ btn.disabled = true; btn.textContent = "Running…"; }
  const tf = (BT_CATALOGUE.find(m => m.key === $("#btmethod").value) || {}).timeframe;
  $("#btnote").textContent =
    `Running walk-forward on both universes — ${BT_COST[tf] || "this takes a while"}. `
    + "The page stays usable; come back to this tab when it is done.";
  try{ await runBacktest(); }
  finally{ if(btn){ btn.disabled = false; btn.textContent = "Run"; } }
}

async function runBacktest(){
  const q = new URLSearchParams({
    method: $("#btmethod").value || "momentum-relative-strength",
    from: $("#btfrom").value, positions: $("#btpos").value,
    threshold: $("#btthresh").value, cost: $("#btcost").value,
  });
  const d = await (await fetch("/api/backtest?"+q)).json();
  if(d.error){ $("#btnote").textContent = d.error; return; }
  renderBacktest(d);
}

// The paper book: the weekly engine's calls traded on Alpaca's paper account
// from the day it started. A forward record nobody can backfill.
async function loadPaper(){
  const el = $("#paper");
  if(!el) return;
  let d;
  try{ d = await (await fetch("/api/paper")).json(); }
  catch(e){ el.innerHTML = `<div class="panel note">Paper book unavailable.</div>`; return; }
  const rules = `<ul class="note" style="margin:6px 0 0;padding-left:18px;line-height:1.6">${(d.rules||[]).map(r=>`<li>${esc(r)}</li>`).join("")}</ul>`;
  if(!d.latest){
    el.innerHTML = `<div class="panel"><div class="note">Not started yet. <code>python3 -m app.paper run</code> places the first orders after the close; the nightly job runs it.</div>${rules}</div>`;
    return;
  }
  const L = d.latest, eq = L.equity, first = d.curve[0], last = d.curve[d.curve.length - 1];
  // Both from the $100,000 the account started with: SPY is normalised to
  // that in the payload, and dividing equity by the day-one close instead
  // put the two on different bases (−1.6% shown against −2.4% real).
  const ret = eq ? eq / 100000 - 1 : null;
  const spyRet = (last && last.spy) ? last.spy / 100000 - 1 : null;
  const pos = (L.positions || []).map(p => `<tr><td><b>${esc(p.symbol)}</b></td><td class=num>${p.qty.toLocaleString()}</td>
      <td class=num>${money(p.avg)}</td><td class=num>${money(p.value)}</td>
      <td class=num style="${col(p.pl_pct)}">${sign(p.pl_pct)}${Math.abs(p.pl_pct * 100).toFixed(1)}%</td></tr>`).join("");
  const orders = (d.orders || []).slice(0, 15).map(o => `<tr><td class="note date">${esc(o.day)}</td>
      <td><span class="vd vd-${o.side === "buy" ? "buy" : "sell"}">${esc(o.side)}</span></td>
      <td class=num>${o.qty}</td><td><b>${esc(o.symbol)}</b></td>
      <td class="note">${esc(o.status || "")}${o.filled_price ? " @ " + money(o.filled_price) : ""}</td>
      <td class="note">${esc((o.reason || "").slice(0, 90))}</td></tr>`).join("");
  el.innerHTML = `
    <div class="cards">
      <div class="card"><div class="k">Equity</div><div class="v">${money(eq)}</div>
        <div class="k" style="margin-top:4px">since ${esc(d.started)}</div></div>
      <div class="card"><div class="k">Return</div><div class="v ${ret > 0 ? "up" : ret < 0 ? "down" : ""}">${ret == null ? "—" : pct(ret)}</div>
        <div class="k" style="margin-top:4px">SPY ${spyRet == null ? "—" : pct(spyRet)} over the same days</div></div>
      <div class="card"><div class="k">Cash</div><div class="v">${money(L.cash)}</div></div>
      <div class="card"><div class="k">Positions</div><div class="v">${(L.positions || []).length}</div></div>
    </div>
    <div class="panel" style="margin-top:12px">${pos ? `<table style="width:100%"><tr><th scope=col>Held</th><th class=num scope=col>Shares</th><th class=num scope=col>Avg</th><th class=num scope=col>Value</th><th class=num scope=col>P/L</th></tr>${pos}</table>` : `<div class="note" style="margin-top:8px">Nothing held.</div>`}
    ${orders ? `<div style="margin-top:10px"><b>Orders</b><table style="width:100%;margin-top:4px">${orders}</table></div>` : ""}
    ${rules}</div>`;
}

// The stored result for the selected method, so the tab opens with figures
// rather than an empty frame. Instant: nothing is computed.
async function showLastBacktest(){
  const key = $("#btmethod") && $("#btmethod").value;
  if(!key) return;
  let d;
  try{ d = await (await fetch("/api/backtest?last=1&method=" + encodeURIComponent(key))).json(); }
  catch(e){ return; }
  if(!d || d.none || d.error){
    ["#btverdict","#btcards","#bttable"].forEach(id => { const el = $(id); if(el) el.innerHTML = ""; });
    const ch = $("#btchart"); if(ch) ch.innerHTML = "";
    $("#btnote").textContent = "No run recorded for this method yet. Press Run.";
    return;
  }
  if(d.params){
    if(d.params.from) $("#btfrom").value = d.params.from;
    if(d.params.positions) $("#btpos").value = d.params.positions;
    if(d.params.threshold) $("#btthresh").value = d.params.threshold;
    if(d.params.cost != null) $("#btcost").value = d.params.cost;
  }
  renderBacktest(d);
}

function renderBacktest(d){
  const L = d.live, C = d.control;
  if(L.error){ $("#btnote").textContent = L.error; return; }

  // The verdict leads, because the headline number on a hand-picked universe is
  // the one most likely to mislead.
  const good = (C.excess ?? -1) > 0.05;
  $("#btverdict").innerHTML = `<div class="finding ${good?"note":"critical"}">
    <h4>${good ? "Survives a survivorship-free universe" : "Does not survive a survivorship-free universe"}</h4>
    <p>${d.verdict || ""}</p></div>`;

  // The return is coloured by its own sign, like every other figure on the
  // page. It used to go red for LOSING TO SPY — a +40% painted red, a rule
  // used nowhere else — so the "vs SPY" figure is now its own coloured number.
  const row = (label, r) => `
    <div class="card"><div class="k">${label}</div>
      <div class="v" style="${col(r.total_return)}">${pct(r.total_return)}</div>
      <div class="k" style="margin-top:4px">SPY ${pct(r.benchmark_total)} ·
        <b style="${col(r.excess)}">${r.excess == null ? "—" : sign(r.excess) + pct(Math.abs(r.excess))}</b> vs SPY</div></div>`;
  $("#btcards").innerHTML =
    row("Your watchlist", L) + row("Neutral ETFs (control)", C) + `
    <div class="card"><div class="k">CAGR</div><div class="v">${pct(L.cagr)}</div>
      <div class="k" style="margin-top:4px">control ${pct(C.cagr)}</div></div>
    <div class="card"><div class="k">Max drawdown</div><div class="v down">${pct(L.max_drawdown)}</div>
      <div class="k" style="margin-top:4px">control ${pct(C.max_drawdown)}</div></div>
    <div class="card"><div class="k">Sharpe</div>
      <div class="v">${L.sharpe==null?"—":L.sharpe.toFixed(2)}</div>
      <div class="k" style="margin-top:4px">control ${C.sharpe==null?"—":C.sharpe.toFixed(2)}</div></div>
    <div class="card"><div class="k">Trades</div><div class="v">${L.trades}</div>
      <div class="k" style="margin-top:4px">${L.turnover_per_rebalance.toFixed(1)} per rebalance</div></div>`;

  const el = $("#btchart"); el.innerHTML = ""; el.style.height = "300px";
  const th = chartTheme();
  // Same leak, once per backtest run.
  if(BT_CHART){ try{ BT_CHART.remove(); }catch(e){} BT_CHART = null; }
  const bc = BT_CHART = LightweightCharts.createChart(el, {
    autoSize:true, height:300,
    layout:{background:{color:"transparent"}, textColor:th.text, fontSize:11},
    grid:{vertLines:{color:"transparent"}, horzLines:{color:th.grid}},
    rightPriceScale:{borderColor:th.grid}, timeScale:{borderColor:th.grid},
  });
  const add = (data, colour, dash) => {
    const ls = bc.addLineSeries({color:colour, lineWidth:2, priceLineVisible:false,
      lineStyle: dash?2:0});
    ls.setData(data.filter(p=>p.value!=null).map(p=>({time:p.date, value:p.value})));
  };
  add(L.equity, th.accent, false);
  add(C.equity, th.line, false);
  if(L.bench && L.bench.length) add(L.bench, th.muted, true);
  bc.timeScale().fitContent();
  $("#btlegend").innerHTML =
    `<span><i style="background:${th.accent}"></i>on your watchlist</span>
     <span><i style="background:${th.line}"></i>on neutral ETFs</span>
     <span><i style="background:${th.muted}"></i>SPY</span>`;

  $("#bttable").innerHTML =
    `<tr><th scope=col>Universe</th><th class=num scope=col>Names</th><th class=num scope=col>Rebalances</th>
      <th class=num scope=col>Total</th><th class=num scope=col>CAGR</th><th class=num scope=col>Max DD</th>
      <th class=num scope=col>Sharpe</th><th class=num scope=col>vs SPY</th></tr>` +
    [["Your watchlist", L], ["Neutral ETFs", C]].map(([n,r])=>`<tr>
      <td>${n}</td><td class=num>${r.universe}</td><td class=num>${r.rebalances}</td>
      <td class=num style="${col(r.total_return)}">${pct(r.total_return)}</td><td class=num>${pct(r.cagr)}</td>
      <td class=num style="color:var(--down)">${pct(r.max_drawdown)}</td>
      <td class=num>${r.sharpe==null?"—":r.sharpe.toFixed(2)}</td>
      <td class=num style="${col(r.excess)}">${r.excess == null ? "—" : sign(r.excess) + pct(Math.abs(r.excess))}</td></tr>`).join("");

  $("#btnote").innerHTML =
    (d.ran_at ? `<div style="margin-bottom:6px"><b>From the run on ${esc(d.ran_at)}</b>${
      d.params ? ` — from ${esc(d.params.from)}, ${d.params.positions} positions, threshold ${d.params.threshold}, ${d.params.cost} bps` : ""}. Press Run to recompute.</div>` : "")
    + L.caveats.map(c=>`• ${c}`).join("<br>");
}
