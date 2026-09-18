// The symbol page: openSymbol, its five panels, plan & levels, my trades, the read.
// One of the dashboard's scripts (see dashboard.html): a classic script sharing the page's
// global scope with the others, loaded in the order the tags there give.

// ------------------------------------------------------------ the symbol page ----
// One page per name, five sub-tabs, reached from every name click in the app
// (research/audits/phase2-spec-2026-09-13.md, "Symbol page contract"). It
// replaced the verdict card that opened under the Outlook table and was
// reachable only from a pill on two tabs; a name clicked anywhere else went
// to a bare chart that showed none of the reasoning.
//
// Data: the enriched row the scope payloads carry (OUTLOOK for a holding,
// OUTLOOK_WL for a watchlist name — the followed authors' levels, wash,
// ladder, drawdown, buy-back, earnings), the per-symbol read
// (/api/outlook?symbol=: the position, the trade-around slice, the call
// history, the crowd — and the live verdict for a name on neither list), and
// the light chart payload (/api/chart: fills, the plan's levels, the round
// trips, the drawn levels). Each is promise-cached per symbol for five
// minutes; a book change or a recorded decision forces a re-read.
let SYM = null;                 // the name the Chart section is about

let SYM_STATE = "";             // "" | "loading" | "ready", for SYM

let SYM_SEQ = 0;                // the newest render wins; an older fetch never paints

let SYM_DATA = null;            // what the last paint was built from

let SYM_PROMISE = null;         // the render in flight, for a caller that must wait on it

const SYM_TTL = 5 * 60 * 1000;

const SYM_FETCH = {outlook: new Map(), chart: new Map(), posts: new Map(), xposts: new Map()};

function symFetch(kind, sym, url, force){
  const m = SYM_FETCH[kind], hit = m.get(sym);
  if(!force && hit && Date.now() - hit.at < SYM_TTL) return hit.promise;
  const promise = fetch(url).then(r => r.json());
  m.set(sym, {at: Date.now(), promise});
  promise.catch(() => m.delete(sym));      // a failure is not cached
  return promise;
}

const TF_NAME = {M: "monthly", W: "weekly", D: "daily"};

// The one way in. `sub` is one of the five tabs: a pill, an alert or a Today
// row opens The read, a chart click opens the chart. `reload` redraws the
// candles even when the same name is already on them — a caller that changed
// the timeframe or a structure toggle first.
function openSymbol(sym, sub, opts){
  sym = String(sym || "").trim().toUpperCase();
  if(!sym) return;
  if(!SECTIONS.chart.includes(sub)) sub = "read";
  showTab(`chart/${sub}?sym=${encodeURIComponent(sym)}`);
  if(opts && opts.reload && !chartInFlight()) loadChart(sym);
}

// The old card's entry point, kept: everything that opened the card opens the page.
function showVerdict(sym){ openSymbol(sym, "read"); }

// The row the page reads: the scope payloads' enriched row when the name is
// on a list, else the per-symbol verdict flattened the way the server
// flattens a scope row (outlook_payload in web.py), so every renderer below
// reads one shape. A flattened row carries no followed-author rows, no wash,
// no ladder — the scope run computes those — and says so with `unlisted`.
function symbolRow(sym, per){
  const held = OUTLOOK && OUTLOOK.verdicts && OUTLOOK.verdicts[sym];
  if(held) return held;
  const wl = OUTLOOK_WL && OUTLOOK_WL.verdicts && OUTLOOK_WL.verdicts[sym];
  if(wl) return wl;
  return per && per.verdict ? flattenVerdict(per.verdict, per.position) : null;
}

function flattenVerdict(v, pos){
  const d = v.daily || {}, w = v.weekly || {}, m = v.monthly || {};
  // _pick_watch: the first timeframe, in the book's order, with a level worth acting on.
  const order = pos && pos.book === "conviction" ? ["weekly", "monthly", "daily"] : ["daily", "weekly", "monthly"];
  let watch = null, watch_timeframe = "daily";
  for(const tf of order){ const x = (v[tf] || {}).watch; if(x && (x.buy_at || x.trim_at || x.stop_at)){ watch = x; watch_timeframe = tf; break; } }
  return {daily: d.verdict, weekly: w.verdict, monthly: m.insufficient ? null : m.verdict, monthly_confidence: m.confidence,
    headline: v.headline, headline_timeframe: v.headline_timeframe, headline_confidence: v.headline_confidence, quality: v.quality,
    confidence: d.confidence, weekly_confidence: w.confidence, weekly_insufficient: w.insufficient,
    monthly_bars: m.bars, monthly_first: m.first, monthly_needed: m.needed, weekly_bars: w.bars, weekly_first: w.first,
    flip: d.flip, flip_note: d.flip_note, price: d.price, change: d.change, near: d.near, trendlines: d.trendlines,
    moving_averages: d.moving_averages, leg_pos: d.leg_pos, cloud: d.cloud, sequence: d.sequence, conflict: v.conflict,
    proxy: v.proxy, value: pos ? pos.value : null, because: d.because || [], against: d.against || [],
    weekly_because: w.because, monthly_because: m.insufficient ? null : m.because, watch, watch_timeframe,
    tally: d.tally, book: pos ? {book: pos.book, trade_around: pos.trade_around, note: pos.book_note, default: pos.book_default} : null,
    record: {daily: d.record, weekly: w.record, monthly: m.record},
    measured: {daily: d.measured_score, weekly: w.measured_score, monthly: m.measured_score},
    outside: [], charts: [], unlisted: true};
}

function renderSymbolPage(sym, force){
  SYM_PROMISE = renderSymbolPageNow(sym, force);
  return SYM_PROMISE;
}

async function renderSymbolPageNow(sym, force){
  sym = String(sym || "").trim().toUpperCase();
  if(!sym) return;
  if(sym === SYM && SYM_STATE && !force) return;      // already on it, or on its way
  const fresh = sym !== SYM;
  SYM = sym; SYM_STATE = "loading";
  const seq = ++SYM_SEQ;
  if(fresh) paintSymbol(sym, null);                     // the skeleton, at once
  const q = new URLSearchParams({symbol: sym});
  const per = symFetch("outlook", sym, "/api/outlook?" + q, force).catch(e => ({error: String((e && e.message) || e)}));
  const chart = symFetch("chart", sym, "/api/chart?" + new URLSearchParams({symbol: sym, timeframe: "D", indicators: "", scope: ($("#scope") || {}).value || ""}), force)
    .catch(e => ({error: String((e && e.message) || e)}));
  const posts = symFetch("posts", sym, "/api/substack-charts?" + q, force).catch(() => null);
  // The charts posted on X are a separate table and payload. Until 2026-09-17
  // the page asked only for the Substack's, so a name charted on X alone —
  // FPS, whose only September chart was in his X post — showed nothing (D133).
  const xposts = symFetch("xposts", sym, "/api/x-charts?" + q, force).catch(() => null);
  // The held payload first: a holding's row is there, and it is already in
  // flight from boot. The watchlist's is asked for only when the name is not
  // held, and lands later — the page paints without it and repaints with it.
  if(!OUTLOOK) await loadOutlook().catch(() => {});
  const P = await per, C = await chart;
  if(seq !== SYM_SEQ) return;
  // The user's own things the page shows, fetched once and shared with their
  // own tabs: the watchlist's target and stop, the buy plans.
  if(!WATCHLIST) await fetchWatchlistRows().catch(() => {});
  if(seq !== SYM_SEQ) return;
  if(!PLANS) loadPlans();
  // The watchlist's scored rows are asked for only when the name is ON the
  // watchlist and not held: cold, that scoring takes minutes, and a scan hit
  // or a typed name would pay it for a row that is not there.
  const listed = (OUTLOOK && OUTLOOK.verdicts && OUTLOOK.verdicts[sym]) || (OUTLOOK_WL && OUTLOOK_WL.verdicts && OUTLOOK_WL.verdicts[sym]);
  const onWatchlist = !!(WATCHLIST && (WATCHLIST.rows || []).some(r => r.symbol === sym));
  const wlWait = (!listed && onWatchlist && !(P && P.position)) ? fetchOutlookWL().catch(() => null) : null;
  const D = {sym, per: P && !P.error ? P : null, perError: P && P.error, chart: C && !C.error ? C : null,
             row: symbolRow(sym, P), posts: null, xposts: null};
  SYM_DATA = D; SYM_STATE = "ready";
  paintSymbol(sym, D);
  posts.then(sc => { if(seq === SYM_SEQ && sc && sc.charts){ D.posts = sc.charts; renderSymFollow(sym, D); } });
  xposts.then(x => { if(seq === SYM_SEQ && x && x.charts){ D.xposts = x.charts; renderSymFollow(sym, D); } });
  if(wlWait) wlWait.then(wl => { if(seq === SYM_SEQ && wl && wl.verdicts && wl.verdicts[sym]){ D.row = wl.verdicts[sym]; paintSymbol(sym, D); } });
}

// Repaint from what is in hand — after the watchlist or the plans land.
function repaintSymbol(){ if(SYM && SYM_DATA && SYM_STATE === "ready") paintSymbol(SYM, SYM_DATA); }

function paintSymbol(sym, D){
  renderSymHead(sym, D); renderSymRead(sym, D); renderSymPlan(sym, D); renderSymFollow(sym, D); renderSymTrades(sym, D);
  // The chart may already be up for this name; give it the three prices.
  if(sym && D && typeof drawVerdictLines === "function") drawVerdictLines(sym);
}

const symPosition = D => (D && D.per && D.per.position) || (D && D.chart && D.chart.position) || null;

const SYM_EMPTY = `<div class="note">No name chosen yet. Click a symbol anywhere — a holding, a watchlist row, a setup, an alert — and its page opens here; or type one above.</div>`;

function renderSymHead(sym, D){
  const el = $("#symhead"); if(!el) return;
  const form = `<form id="symgoform" autocomplete="off"><input id="symgo" list="symlist" placeholder="another name" aria-label="Open another name"><button type="submit">Open</button></form>`;
  if(!sym){ el.innerHTML = `<div class="symname">No name yet</div><div class="note">Click a symbol anywhere in the app, or type one.</div>${form}`; wireSymGo(); return; }
  const v = D && D.row, p = symPosition(D);
  const price = v && v.price != null ? v.price : (p ? p.price : null);
  const chg = v && v.change != null ? `<span style="color:${v.change >= 0 ? "var(--up)" : "var(--down)"};font-weight:600;margin-left:6px">${v.change >= 0 ? "+" : "−"}${Math.abs(v.change * 100).toFixed(2)}%</span>` : "";
  const tf = v ? (TF_NAME[v.headline_timeframe] || "daily") : "";
  const pill = v ? `${vdPill(v.headline || v.daily, v.headline_confidence || v.confidence, v.record && v.record[tf])} <span class="note">${tf} call</span>`
                 : (D ? `<span class="vd vd-none">no read</span> <span class="note">${esc((D.perError || "no price history").slice(0, 80))}</span>` : `<span class="note">reading…</span>`);
  // The position is the user's own: marked as such, and ahead of the form.
  const pos = p && p.quantity ? `<div class="sympos"><span class="minetag" style="margin:0 6px 0 0">yours</span>${Number(p.quantity).toLocaleString(undefined, {maximumFractionDigits: 2})} shares · ${money(p.value)} ·
      <span style="${col(p.unrealised)}">${moneyDelta(p.unrealised)}${p.unrealised_pct == null ? "" : ` (${p.unrealised_pct >= 0 ? "+" : ""}${(p.unrealised_pct * 100).toFixed(0)}%)`}</span>${p.weight != null ? ` · ${(p.weight * 100).toFixed(0)}% of the book` : ""}</div>`
    : (D ? `<div class="sympos note">not held${v && v.unlisted ? " · not on the watchlist" : ""}</div>` : "");
  el.innerHTML = `<div><span class="symname">${esc(sym)}</span><span class="symprice">${price == null ? "" : money(price)}</span>${chg}${price != null ? ` <span class="note">last close</span>` : ""}</div>
    <div>${pill}</div>${pos}${form}`;
  wireSymGo();
}

function wireSymGo(){
  const f = $("#symgoform"); if(!f || f.dataset.wired) return;
  f.dataset.wired = "1";
  f.addEventListener("submit", ev => {
    ev.preventDefault();
    const v = $("#symgo").value.trim().toUpperCase();
    if(v) openSymbol(v, SUB, {reload: SUB === "chart"});
  });
}

// What the cloud is and which side price is on — the most-cited reason in
// every verdict, and meaningless as three words.
function cloudText(v){
  if(!v.cloud || v.cloud.top == null || v.price == null) return "";
  const {top, bottom} = v.cloud;
  const where = v.price > top
    ? `<b style="color:var(--up)">above the cloud</b> — it sits ${Math.abs((v.price / top - 1) * 100).toFixed(1)}% below price as support`
    : v.price < bottom
    ? `<b style="color:var(--down)">below the cloud</b> — it sits ${Math.abs((bottom / v.price - 1) * 100).toFixed(1)}% above price and caps rallies`
    : `<b style="color:var(--warn)">inside the cloud</b>, which is the definition of no trend`;
  const thick = top - bottom, span = (top + bottom) / 2;
  const thin = span ? (thick / span) < 0.06 : false;
  // The summary is a flex box (details > summary.note), which drops the
  // whitespace between its text and the <b>; one span keeps it one item.
  return `<details style="margin-top:8px"><summary class="note" style="cursor:pointer"><span>The cloud runs ${money(bottom)}–${money(top)} and price is ${where}. What that means.</span></summary>
    <div class="note" style="margin-top:4px">The cloud is the gap between two lines: one is the midpoint of the last 9 and 26
      sessions' range, the other the midpoint of the last 52. Both are plotted <b>26 sessions ahead</b> of the bars they are
      computed from, which is why it extends past the last candle and why it can act as support before price gets there.
      Green shading means the faster line is on top (the market has been rising into it), red means the slower one is.
      Here it is <b>${thin ? "thin" : "thick"}</b> — ${thin ? "a narrow cloud is weak support and price tends to cut through it"
                                                       : "a thick cloud took a wide range to build and tends to hold"}.</div></details>`;
}

// The read: the call on three timeframes, the case for and against, where it
// flips, the tally that produced it, the book, the decision recorder, and
// what was called before.
function renderSymRead(sym, D){
  const el = $("#symread"); if(!el) return;
  if(!sym){ el.innerHTML = SYM_EMPTY; return; }
  if(!D){ el.innerHTML = loadingHTML(`Reading ${esc(sym)}…`); return; }
  const v = D.row;
  if(!v){ el.innerHTML = `<div class="note">No read for ${esc(sym)}: ${esc(D.perError || "no price history to read structure from")}.</div>`; return; }
  const hist = OUTLOOK ? ((D.per && D.per.history) || (OUTLOOK.recent || []).filter(r => r.symbol === sym)) : [];
  el.innerHTML = `<div class="symread">
    <div style="display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center">
         <span style="white-space:nowrap">${v.monthly ? vdPill(v.monthly, v.monthly_confidence, v.record && v.record.monthly) + ` <span class="note">monthly</span>`
                     : `<span class="vd vd-none" title="A monthly reading needs ${v.monthly_needed || 24} monthly bars; this name has ${v.monthly_bars ?? "fewer"}.">too new · monthly</span>`}</span>
         <span style="white-space:nowrap">${v.weekly_insufficient ? `<span class="vd vd-none" title="A weekly reading needs 60 weekly bars; this name has ${v.weekly_bars ?? "fewer"}.">too new · weekly</span>`
                                 : vdPill(v.weekly, v.weekly_confidence, v.record && v.record.weekly) + ` <span class="note">weekly</span>`}</span>
         <span style="white-space:nowrap">${vdPill(v.daily, v.confidence, v.record && v.record.daily)} <span class="note">daily</span></span>
         ${v.headline_timeframe ? `<span class="note">· the ${TF_NAME[v.headline_timeframe]} leads</span>` : ""}
         ${v.unlisted ? `<span class="note" style="margin-left:8px">· read live; not on your lists, so no followed-author levels, wash or ladder</span>` : ""}</div>
    ${v.quality && v.quality.score != null ? `<div class="note" style="margin-top:6px"><b>Setup ${v.quality.score.toFixed(2)}</b> — ${esc(v.quality.why)}</div>` : ""}
    ${earningsLine(v.earnings)}
    ${v.proxy ? `<div class="warn" style="margin-top:6px">${esc(v.proxy.note)}</div>` : ""}
    ${v.conflict ? `<div class="note" style="margin-top:5px">⚠ ${esc(v.conflict)}</div>` : ""}
    ${v.sequence ? `<div class="note" style="margin-top:5px">Pivots: ${esc(v.sequence)}${v.leg_pos != null ? ` · ${Math.round(v.leg_pos * 100)}% up its own swing` : ""}</div>` : ""}
    <div style="margin-top:8px"><b>Because</b><ul>${(v.because || []).map(r => `<li>${esc(r)}</li>`).join("") || `<li class="note">nothing recorded on the daily</li>`}</ul></div>
    ${(v.against || []).length ? `<div style="margin-top:6px"><b>Against it</b><ul>${v.against.map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>` : ""}
    ${flipText(v.headline || v.daily, v.price, v.flip, v.flip_note)}
    ${tallyBlock(v)}
    ${cloudText(v)}
    ${drawdownBlock(v)}
    <div class="vdacts mine" style="margin-top:12px;align-items:center">
      <span class="note" style="margin-right:4px">This name is in my</span>
      ${v.book ? bookCell(sym, v.book) : `<span class="note">— no book: not held —</span>`}
    </div>
    <div class="vdacts mine" style="margin-top:8px;align-items:center">
      <span class="note" style="margin-right:4px">Record my own call<span class="minetag">yours</span></span>
      <select id="vdbucket" title="Which book the position belongs to. Calibration slices your record by it.">
        <option value="">— book —</option>
        ${((OUTLOOK && OUTLOOK.buckets) || []).map(b => `<option value="${esc(b)}">${esc(b)}</option>`).join("")}
      </select>
      <input id="vdwhy" placeholder="why, in one line" style="flex:1;min-width:160px"
             title="The reason, in your words. It is stored with the call and read back when it is graded.">
    </div>
    <div class="vdacts mine" style="margin-top:6px">
      <span class="note" style="align-self:center;margin-right:4px">I decided to</span>
      ${["buy", "add", "hold", "trim", "sell"].map(a =>
        // NOT data-sym: the document-wide delegate opens the page for anything
        // carrying it, and recording a decision must not navigate.
        `<button data-rec="${a}" data-recsym="${esc(sym)}">${a}</button>`).join("")}
      <button data-chartfor="${esc(sym)}" class="primary" style="margin-left:auto">See it on the chart</button>
    </div>
    <div class="note" id="vdsaved" style="margin-top:6px"></div>
    ${hist.length ? `<div style="margin-top:14px">
      <div class="k">What was called before</div>
      <div class="note" style="margin-bottom:4px">Past readings, not today's — the app's nightly calls and your own, graded at 21 days.
        A verdict recorded on an earlier date can differ from the one above, and that difference is the point of keeping them.</div>
      ${hist.slice(0, 8).map(jrnlRow).join("")}</div>` : ""}
  </div>`;
  // The chart's own reading (the Technical read under this card) is drawn by
  // loadChart; when the page was opened on The read the candles are not up
  // yet, so it is drawn here from the light chart payload instead.
  if(D.chart && CHART_DRAWN !== sym) renderAnalysis(D.chart.analysis);
  el.querySelectorAll("[data-chartfor]").forEach(b => b.addEventListener("click", ev => {
    ev.preventDefault(); ev.stopPropagation();
    chartForVerdict(b.dataset.chartfor);
  }));
  el.querySelectorAll("[data-rec]").forEach(b => b.addEventListener("click", async ev => {
    ev.preventDefault(); ev.stopPropagation();
    const sym2 = b.dataset.recsym, act = b.dataset.rec;
    b.disabled = true; b.textContent = "saving…";
    const q = new URLSearchParams({action: "record", symbol: sym2, decision: act,
                                   price: (v.price == null ? "" : v.price),
                                   bucket: ($("#vdbucket") && $("#vdbucket").value) || "",
                                   note: ($("#vdwhy") && $("#vdwhy").value.trim()) || ""});
    let ok = false;
    try{ ok = (await (await fetch("/api/outlook?" + q)).json()).ok === true; }
    catch(e){ ok = false; }
    if(!ok){ b.disabled = false; b.textContent = act;
      $("#vdsaved").innerHTML = `<span style="color:var(--down)">Could not record that.</span>`;
      return; }
    // The record lives in the outlook payload and in this name's history:
    // both are re-read, and the page repainted from them.
    OUTLOOK = null;
    await loadOutlook();
    await (SYM_PROMISE || Promise.resolve());
    // Confirmation, because a save with no acknowledgement is indistinguishable
    // from one that failed — which is exactly how the first one was read.
    const note = $("#vdsaved");
    if(note) note.innerHTML = `<span style="color:var(--up)">Recorded: you ${esc(act)} ${esc(sym2)} today.
      It is under "What was called before" here and "Calls made" under My Money → Trades, and is scored against SPY once 21 trading days have passed.</span>`;
  }));
}

// Plan & levels: every price this name has a reason to be watched at, in one
// ladder — the three the reading resolves to (buy at / sell into / wrong
// below) with the move each starts, the flip, the buy-back floor, the ladder's
// next sell, what the people you follow named, and everything that is YOURS:
// your average cost, your target and stop, your drawn levels, your buy plan.
function renderSymPlan(sym, D){
  const el = $("#symplan"); if(!el) return;
  if(!sym){ el.innerHTML = SYM_EMPTY; return; }
  if(!D){ el.innerHTML = loadingHTML(`Reading ${esc(sym)}'s levels…`); return; }
  const v = D.row || {}, w = v.watch || {}, p = symPosition(D);
  const price = v.price != null ? v.price : (p ? p.price : null);
  const plan = (D.chart && D.chart.plan) || {};
  const rows = [];
  const add = r => { if(r.price != null && !isNaN(r.price)) rows.push(r); };
  const lvlWhy = px => { const l = (w.levels || []).find(x => x.price === px); return l ? `${l.label} — ${l.why}` : ""; };
  const ta = v.book && v.book.trade_around;
  // The three the reading resolves to, always listed — a missing one is a
  // finding ("nothing tested enough on that side"), not a gap.
  const three = [
    {price: w.buy_at, label: "Buy at", col: "var(--buy)", why: lvlWhy(w.buy_at) || w.buy_why,
     move: w.buy_target ? `Buying here targets ${money(w.buy_target)} (${w.buy_target_pct > 0 ? "+" : ""}${w.buy_target_pct}%)${w.buy_rr ? `, against ${money(w.stop_at)} (${w.buy_risk_pct}%): ${w.buy_rr} to 1` : ""}.` : "",
     missing: "No buy level: nothing tested enough on that side to trade."},
    {price: w.trim_at, label: ta ? "Sell the slice into" : "Sell into", col: "var(--trim)", why: lvlWhy(w.trim_at) || w.trim_why,
     move: w.sell_target ? `Selling into it targets a pullback to ${money(w.sell_target)} (${w.sell_target_pct}%).` : "",
     missing: "No sell level: nothing tested enough on that side to trade."},
    {price: w.stop_at, label: "Wrong below", col: "var(--down)", why: lvlWhy(w.stop_at) || "under here the reason for holding stops applying",
     move: w.stop_at && w.trim_at ? `Nothing to do between ${money(w.stop_at)} and ${money(w.trim_at)}.` : "",
     missing: "No invalidation level: nothing tested enough on that side to trade."},
  ];
  three.forEach(t => add(Object.assign({}, t, {what: [t.why, t.move].filter(Boolean).join(". ").replace(/\.\./g, ".")})));
  if(w.buy_at && w.stop_at && w.buy_at < w.stop_at)
    three[0].warn = `The add level sits below the invalidation level — if it gets to ${money(w.buy_at)}, the reason to own it has already broken.`;
  if(v.flip != null && ![w.buy_at, w.trim_at, w.stop_at].includes(v.flip)){
    const verdict = (v.headline || v.daily || "").toLowerCase();
    const becomes = {sell: "the sell case ends", trim: "the next level up is", buy: "this is wrong", add: "this is wrong", hold: "this breaks"}[verdict] || "the call flips";
    const fn = v.flip_note ? v.flip_note.charAt(0).toUpperCase() + v.flip_note.slice(1).replace(/\.?$/, ".") : "";
    add({price: v.flip, label: "Call flips", col: "var(--muted)", what: `On a close ${price != null && v.flip > price ? "above" : "below"} here ${becomes}.${fn ? " " + fn : ""}`});
  }
  if(plan.sell_at) add({price: plan.sell_at, label: "Ladder sell", col: "var(--trim)", what: plan.sell_why || "the sell ladder's next rung, as a price"});
  if(plan.buy_back) add({price: plan.buy_back, label: "Buy back", col: "var(--up-strong)", mine: /your /i.test(plan.buy_why || ""), what: plan.buy_why || "the buy-back floor"});
  // What the people you follow named, with the date; the plan's own named
  // levels fill in anything they missed (a price not already on the ladder).
  const outside = (v.outside || []).filter(o => o.level);
  outside.forEach(o => add({price: o.level, hi: o.hi && o.hi !== o.level ? o.hi : null, label: `${o.author.split(" (")[0]} · ${o.action}`,
    col: /sell|trim|downside/.test(o.action) ? "var(--down)" : /target/.test(o.action) ? "var(--trim)" : "var(--up)",
    what: `${o.date}${o.note ? " — " + o.note : ""}`}));
  (plan.named || []).forEach(n => { if(!rows.some(r => Math.abs(r.price - n.level) < 0.005)) add({price: n.level, label: "Named level", col: "var(--muted)", mine: /your /i.test(n.source || ""), what: n.source || ""}); });
  // Yours: cost, target and stop, drawn levels, buy plans. These are the
  // only rows the amber marks.
  if(p && p.avg_cost) add({price: p.avg_cost, label: "Your average cost", col: "var(--mine-cost)", mine: true,
    what: `${Number(p.quantity).toLocaleString(undefined, {maximumFractionDigits: 2})} shares, ${money(p.cost_basis)} in${p.basis_source === "broker" ? ", the broker's basis" : ", FIFO from the ledger"}.`});
  const wlr = WATCHLIST && (WATCHLIST.rows || []).find(r => r.symbol === sym);
  if(wlr && wlr.target) add({price: wlr.target, label: "Your target", col: "var(--up)", mine: true, what: wlr.note ? `your note: ${wlr.note}` : "set on the watchlist row"});
  if(wlr && wlr.stop) add({price: wlr.stop, label: "Your stop", col: "var(--down)", mine: true, what: wlr.note && !wlr.target ? `your note: ${wlr.note}` : "set on the watchlist row"});
  ((D.chart && D.chart.drawings) || []).filter(d => d.kind === "level" && d.pane === "price" && d.points && d.points[0])
    .forEach(d => add({price: d.points[0][1], label: "Your drawn level", col: "var(--mine-level)", mine: true, what: `drawn on the chart ${String(d.created_at || "").slice(0, 10)}; the nightly alert fires when a close crosses it`}));
  (PLANS || []).filter(x => x.symbol === sym).forEach(x => add({price: x.max_price, label: "Your buy plan", col: "var(--buy)", mine: true, planId: x.id,
    what: `at or below ${money(x.max_price)}, wait if it opens up ${x.gap_pct}%+ · set ${x.created}${x.note ? " · " + x.note : ""}${Object.keys(x.today || {}).length ? ` · <b style="color:var(--up)">today: ${Object.entries(x.today).map(([k, px]) => `${k.replace("_", " ")} at ${money(px)}`).join(", ")}</b>` : ""}`}));
  if(price != null) rows.push({price, now: true});
  rows.sort((a, b) => b.price - a.price);
  const dist = px => price ? `${px >= price ? "+" : ""}${((px / price - 1) * 100).toFixed(1)}%` : "";
  const missing = three.filter(t => !t.price);
  const trow = r => r.now
    ? `<tr class="now"><td>Price now</td><td class="num lvlprice">${money(r.price)}</td><td class="num note">—</td><td class="note">last close${v.change != null ? `, ${v.change >= 0 ? "+" : "−"}${Math.abs(v.change * 100).toFixed(2)}% on the day` : ""}</td></tr>`
    : `<tr${r.mine ? ' class="mine"' : ""}><td><b style="color:${r.col}">${esc(r.label)}</b>${r.mine ? `<span class="minetag">yours</span>` : ""}</td>
        <td class="num lvlprice" style="color:${r.col}">${money(r.price)}${r.hi ? `–${money(r.hi)}` : ""}</td>
        <td class="num note">${dist(r.price)}</td>
        <td class="note prose">${r.what || ""}${r.warn ? `<div style="color:var(--warn)">${esc(r.warn)}</div>` : ""}${r.planId ? ` <button class="attngo" data-planrm="${r.planId}" style="margin-left:6px">done</button>` : ""}</td></tr>`;
  const wash = v.wash ? `<div class="warn mine" style="margin:10px 0"><b>Wash sale.</b> ${v.wash.possible
      ? `You sold ${esc(sym)} on ${esc(v.wash.date)} — seen in the confirmation email, shares and cost not in yet. If that sale was at a loss, buying back before <b>${esc(v.wash.window_closes)}</b> disallows it (${v.wash.days_left} days to wait).`
      : `You sold ${Math.abs(v.wash.quantity)} shares at a loss of ${money(Math.abs(v.wash.loss))} on ${esc(v.wash.date)}. Buying back before <b>${esc(v.wash.window_closes)}</b> disallows that loss this year (${v.wash.days_left} days to wait); the loss would move into the new shares' basis instead.`}</div>` : "";
  el.innerHTML = `
    <div class="note" style="margin-bottom:6px">Every level this name has a reason to be watched at, highest first. The three the reading resolves to —
      <b style="color:var(--buy)">buy at</b>, <b style="color:var(--trim)">sell into</b>, <b style="color:var(--down)">wrong below</b> — come from the
      ${esc(v.watch_timeframe || "daily")} chart${v.book ? `, read for a ${esc(v.book.book)} book` : ""}. Rows marked <span class="minetag" style="margin:0">yours</span> are things you set.</div>
    <div class="tscroll"><table class="ladder"><tr><th scope=col>Level</th><th class=num scope=col>Price</th><th class=num scope=col>From here</th><th scope=col>What it is, and the move it starts</th></tr>
      ${rows.length ? rows.map(trow).join("") : `<tr><td colspan=4 class="note">No levels yet — no read for this name.</td></tr>`}</table></div>
    ${missing.length ? `<div class="note" style="margin-top:6px">${missing.map(m => esc(m.missing)).join(" ")}</div>` : ""}
    ${wash}
    ${ladderBlock(sym, v)}
    ${(v.near || v.trendlines || v.moving_averages) ? `<details style="margin-top:8px"><summary class="note" style="cursor:pointer">The structure the read used — support, resistance, trendlines, averages</summary>${levelsBlock(v)}</details>` : ""}
    <div class="mine" style="margin-top:12px">${planForm(sym, v)}</div>`;
}

// Who I follow on it: their calls and levels on this name, their charts (the
// Value Trader's from the Patreon mail, the Substack posts' images, the
// posts on X), and whether the crowd is already here.
function renderSymFollow(sym, D){
  const el = $("#symfollow"); if(!el) return;
  if(!sym){ el.innerHTML = SYM_EMPTY; return; }
  if(!D){ el.innerHTML = loadingHTML(`Reading who you follow on ${esc(sym)}…`); return; }
  const v = D.row || {}, price = v.price;
  const rows = v.outside || [];
  const table = !rows.length ? `<div class="note">Nobody you follow has named a level or made a call on ${esc(sym)} in the last 90 days${v.unlisted ? " — and the name is not on your lists, where the followed accounts are matched" : ""}.</div>`
    : `<div class="tscroll"><table><tr><th scope=col>When</th><th scope=col>Who</th><th scope=col>Said</th><th class=num scope=col>Level</th><th scope=col>In their words</th></tr>${rows.map(o => {
        const rel = o.level && price ? (o.level / price - 1) * 100 : null;
        return `<tr><td class="note date">${esc(o.date)}</td><td><b>${esc(o.author.split(" (")[0])}</b></td>
          <td><span class="vd vd-${/sell|trim|downside/.test(o.action) ? "sell" : /target/.test(o.action) ? "none" : "buy"}">${esc(o.action)}</span></td>
          <td class=num>${o.level ? (o.hi && o.hi !== o.level ? `${money(o.level)}–${money(o.hi)}` : money(o.level)) : "—"}${rel == null ? "" : ` <span class="note">(${rel > 0 ? "+" : ""}${rel.toFixed(0)}%)</span>`}</td>
          <td class="note prose">${esc(o.note || "")}</td></tr>`; }).join("")}</table></div>
      <div class="note" style="margin-top:4px">Graded like the app's own calls under Who I Follow → Their calls, graded.</div>`;
  const vt = (v.charts || []).map(c => `<div class="panel" style="padding:8px">
      ${c.has_image ? `<a href="/chart-image?id=${esc(c.post_id)}" target="_blank" rel="noopener" title="Open the chart full size"><img src="/chart-image?id=${esc(c.post_id)}" alt="" loading="lazy" decoding="async" style="width:100%;height:auto;border-radius:6px;border:1px solid var(--line)"></a>` : ""}
      <div style="margin-top:6px"><b>The Value Trader</b> <span class="note">${esc(c.date)}</span>${c.action ? ` <span class="vd vd-${c.action === "sell" ? "sell" : "buy"}">${esc(c.action)}</span>` : ""}</div>
      <div style="font-size:13px"><b>${esc(c.subject)}</b></div><div class="note">${esc(c.teaser || "")}</div>
      ${c.url ? `<a href="${esc(safeUrl(c.url))}" target="_blank" rel="noopener" class="note">the post</a>` : ""}</div>`);
  // The Substack's and X's rows share a shape; newest first across both, so
  // his X chart of a name from this week sits before his Substack one from
  // last month. Where and when is on every card.
  const posted = (D.posts || []).map(r => ({...r, where: "Substack"})).concat((D.xposts || []).map(r => ({...r, where: "X"})))
    .sort((a, b) => (b.date || "").localeCompare(a.date || "")).slice(0, 12);
  const sc = posted.map(r => `<div class="panel" style="padding:8px">
      <a href="${esc(safeUrl(r.images[0]))}" target="_blank" rel="noopener"><img src="${esc(safeUrl(r.images[0]))}" alt="" loading="lazy" decoding="async" style="width:100%;height:auto;border-radius:6px"></a>
      <div style="margin-top:6px"><b>${esc((r.author || r.where).split(" (")[0])}</b> <span class="note">${esc(r.where)}${r.timeframe ? " · " + esc(r.timeframe) : ""} · ${esc(r.date)}</span></div>
      <div class="note" style="font-size:13px;margin-top:4px">${esc((r.text || "").slice(0, 200))}${(r.text || "").length > 200 ? "…" : ""}</div>
      ${r.post_url ? `<a href="${esc(safeUrl(r.post_url))}" target="_blank" rel="noopener" class="note">the post</a>` : ""}</div>`);
  const charts = vt.concat(sc);
  const crowd = D.per && D.per.crowd, cov = D.per && D.per.crowd_coverage;
  let crowdHtml;
  if(!D.per || !("crowd" in D.per)) crowdHtml = `<span class="note">The crowd reading is not in this server build — restart it to get one.</span>`;
  else if(!crowd) crowdHtml = `<span class="note">No crowd reading for this name.</span>`;
  else {
    const thin = cov && cov.thin;
    const colr = crowd.state === "crowded" ? "var(--down)" : crowd.state === "warming" ? "var(--warn)" : "var(--up)";
    const word = thin && !crowd.accounts ? "no data" : crowd.state;
    crowdHtml = `<b style="color:${thin && !crowd.accounts ? "var(--muted)" : colr};text-transform:uppercase;letter-spacing:.04em">${esc(word)}</b>
      <span class="note"> — ${crowd.accounts} account${crowd.accounts === 1 ? "" : "s"} you follow posted the ticker in the last 30 days${crowd.accounts_before != null ? ` (${crowd.accounts_before} the 30 before)` : ""}${crowd.handles && crowd.handles.length ? `: ${crowd.handles.slice(0, 6).map(esc).join(", ")}` : ""}${crowd.first_seen ? ` · first seen ${esc(crowd.first_seen)}` : ""}.
      Early is nobody, warming two or more, crowded four or more — a judgement, not a measurement.${thin ? ` <b>Only ${cov.days} day(s) of posts are on disk, so "no data" is shown instead of "early".</b>` : ""}</span>`;
  }
  el.innerHTML = `<h3 style="margin:0 0 6px">Their calls and levels on ${esc(sym)}</h3>${table}
    <h3 style="margin:14px 0 6px">Their charts <span class="note" style="font-weight:400">— the levels are drawn, not written, so the app cannot read them; look at them beside its own</span></h3>
    ${charts.length ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px">${charts.join("")}</div>`
                    : `<div class="note">No saved chart of ${esc(sym)} from the people you follow${D.posts == null || D.xposts == null ? " yet — still reading the saved posts" : ""}.</div>`}
    <h3 style="margin:14px 0 6px">The crowd</h3><div>${crowdHtml}</div>`;
}

// My trades: the position and its cost, every fill on the name with the
// running position after each, the round trips, and the trade-around slice
// when the position has one. All of it is the user's own, so it is marked so.
function renderSymTrades(sym, D){
  const el = $("#symtrades"); if(!el) return;
  if(!sym){ el.innerHTML = SYM_EMPTY; return; }
  if(!D){ el.innerHTML = loadingHTML(`Reading your trades in ${esc(sym)}…`); return; }
  const p = symPosition(D), v = D.row || {};
  const fills = ((D.chart && D.chart.fills) || []).slice();
  const trips = (D.chart && D.chart.trades) || [];
  const n = x => x == null ? "—" : Number(x).toLocaleString(undefined, {maximumFractionDigits: 2});
  const cards = p && p.quantity ? `<div class="cards mine" style="margin-bottom:12px">
      <div class="card"><div class="k">Shares</div><div class="v">${n(p.quantity)}</div><div class="d">${p.lots ? `${p.lots} lot${p.lots === 1 ? "" : "s"} · ` : ""}since ${esc(p.oldest_lot || "?")}${p.held_days ? `, ${p.held_days} days` : ""}${p.long_term ? " · long-term" : ""}</div></div>
      <div class="card"><div class="k">Average cost</div><div class="v">${money(p.avg_cost)}</div><div class="d">${money(p.cost_basis)} in${basisPill(p)}</div></div>
      <div class="card"><div class="k">Value</div><div class="v">${money(p.value)}</div><div class="d">at ${money(p.price)}${p.weight != null ? ` · ${(p.weight * 100).toFixed(1)}% of the book` : ""}</div></div>
      <div class="card"><div class="k">Unrealised</div><div class="v ${p.unrealised > 0 ? "up" : p.unrealised < 0 ? "down" : ""}">${moneyDelta(p.unrealised)}</div><div class="d">${p.unrealised_pct == null ? "" : `${p.unrealised_pct >= 0 ? "+" : ""}${(p.unrealised_pct * 100).toFixed(1)}% on cost`}${v.book ? ` · ${esc(v.book.book)} book${v.book.trade_around ? ", traded around" : ""}` : ""}</div></div>
    </div>` : `<div class="note mine" style="margin-bottom:10px">You do not hold ${esc(sym)}${fills.length ? ` now; you traded it before — ${fills.length} fill${fills.length === 1 ? "" : "s"}, the last on ${esc(fills[fills.length - 1].date)}` : " and have never traded it"}.${v.rebuy ? ` Buy-back reading: <b>${esc(v.rebuy.state)}</b>.` : ""}</div>`;
  // Running position and average after each fill, oldest to newest; shown
  // newest first, which is the order you look for a fill in.
  let runQty = 0, runCost = 0;
  const walked = fills.map(f => {
    if(f.side === "buy"){ runQty += f.qty; runCost += f.value; }
    else { const avg = runQty ? runCost / runQty : 0; runCost -= avg * f.qty; runQty -= f.qty; }
    return Object.assign({}, f, {after: runQty, avg: runQty > 1e-9 ? runCost / runQty : null});
  }).reverse();
  const frow = f => `<tr><td class="date">${esc(f.date)}</td>
      <td><span class="pill" style="color:${f.side === "buy" ? "var(--mine-buy)" : "var(--mine-sell)"}">${esc(f.side)}</span></td>
      <td class=num>${n(f.qty)}</td><td class=num>${money(f.price)}</td><td class=num>${money(f.value)}</td>
      <td class=num>${f.after > 1e-9 ? n(f.after) : "flat"}</td><td class=num>${f.avg ? money(f.avg) : "—"}</td></tr>`;
  const head = `<tr><th scope=col>Date</th><th scope=col>Side</th><th class=num scope=col>Shares</th><th class=num scope=col>Price</th><th class=num scope=col>Value</th><th class=num scope=col>Position after</th><th class=num scope=col>Avg cost after</th></tr>`;
  const fillsHtml = !walked.length ? "" : `<h3 style="margin:0 0 6px">Your fills <span class="note" style="font-weight:400">— ${walked.length}, newest first${fills.some(f => f.split_adjusted) ? "; prices split-adjusted" : ""}</span></h3>
    <div class="tscroll mine"><table>${head}${walked.slice(0, 30).map(frow).join("")}</table></div>
    <div class="note" style="margin-top:4px">"Avg cost after" is FIFO from the ledger's fills, so it can differ from the broker's basis in the card above — the broker assigns lots its own way.</div>
    ${walked.length > 30 ? `<details style="margin-top:6px"><summary class="note" style="cursor:pointer">show all ${walked.length}</summary><div class="tscroll"><table>${head}${walked.slice(30).map(frow).join("")}</table></div></details>` : ""}`;
  const tripsHtml = !trips.length ? "" : `<h3 style="margin:14px 0 6px">Round trips</h3><div class="tscroll"><table>
    <tr><th scope=col>Opened</th><th scope=col>Closed</th><th class=num scope=col>Bought</th><th class=num scope=col>Sold</th><th class=num scope=col>Shares in</th><th class=num scope=col>Shares out</th><th class=num scope=col>Fills</th><th class=num scope=col>Held</th></tr>
    ${trips.map(t => `<tr><td class="date">${esc(t.entry_date)}</td><td class="date">${t.open ? `<span class="pill">open · ${n(t.remaining)} left</span>` : esc(t.exit_date || "")}</td>
      <td class=num>${money(t.bought)}</td><td class=num>${money(t.sold)}</td><td class=num>${n(t.shares_in)}</td><td class=num>${n(t.shares_out)}</td><td class=num>${t.fills}</td><td class=num>${t.held_days}d</td></tr>`).join("")}</table></div>`;
  const ta = p && p.trade_around ? `<div id="tradearound" class="panel mine" style="margin:12px 0 0"><span class="note">Working out the round trip…</span></div>` : "";
  el.innerHTML = cards + fillsHtml + tripsHtml + ta
    + `<div class="note" style="margin-top:10px">The closed round trips with their P/L, worst and best are under My Money → Trades; your own calls on this name are under The read.</div>`;
  if(ta) loadTradeAround(sym, D.per);
}

// Where the position sits in its own drawdown, and what followed for names
// that got that deep. Measured 2026-09-10 (research/audits/edge-log.md): the
// point is the LAST number — even a 20% break has usually not finished falling,
// and the median name goes on to lose another 46% before it bottoms.
//
// The base rates describe the moment a name FIRST crossed each depth, so two
// cases must not borrow them: anything deeper than -40%, where nothing was
// measured, and a position that crossed months ago, where the remaining odds
// are not the odds on the day it broke.
function drawdownBlock(v){
  const d = v.drawdown;
  if(!d) return "";
  const pct = x => `${(x*100).toFixed(0)}%`;
  const o = d.odds;
  const deep = d.drawdown >= 0.30;
  let body;
  if(d.odds_note){
    body = `<div class="note">${esc(d.odds_note)}.</div>`;
  }else if(o){
    body = `<div style="font-size:13px;margin-top:4px">
      Of names that first fell this far (<b>n=${o.n}</b>):
      <b>${pct(o.never_recovered)}</b> never got back to the peak ·
      the rest took <b>${o.median_months_back}</b> months in the middle,
      ${o.p75_months_back} at the 75th ·
      and the median one fell <b>another ${pct(Math.abs(o.median_further_fall))}</b> first.
      </div>
      <div class="note" style="margin-top:3px">Base rates, not a forecast${o.stale
        ? ` — and this position crossed that line ${d.months_since_peak} months ago, so they describe the day it broke, not today`
        : ""}.</div>`;
  }else{
    body = `<div class="note">Shallower than anything measured.</div>`;
  }
  return `<div class="panel" style="margin:0 0 10px;padding:8px 10px">
    <div class="k">Drawdown <span class="vd ${deep ? "vd-sell" : "vd-none"}">${pct(d.drawdown)}</span>
      <span class="note">from ${money(d.peak)} on ${esc(d.peak_date)}, ${d.months_since_peak} months ago</span></div>
    ${body}</div>`;
}

// The sell ladder on a held name: three rungs from the position's entry,
// which have fired and at what, and the price or reading the next one needs.
// Read off IREN's anatomy, kept after 36 names it was not read from (D69),
// and the rule that would have held the winners sold early since 2022 (D71).
function ladderBlock(sym, v){
  const L = v.ladder;
  // The ladder is off (2026-09-10). A card that simply vanished would read as
  // a bug or, worse, as "no rung is near" — so the reason is shown once, on
  // the names that used to carry it, with the buy-back readings kept because
  // those never depended on the ladder.
  if(!L) return !ladderOff ? "" : `<div class="panel" style="margin:0 0 10px;padding:8px 10px">
    <div class="k">Sell ladder <span class="vd vd-none">off</span></div>
    <div class="note" style="margin:2px 0 0">${esc(ladderOff)}</div>
    ${v.rebuy ? `<div style="margin-top:8px;padding-top:6px;border-top:1px solid var(--line)"><span class="k">Buy-back readings</span> <span class="vd ${/confirmed|floor|washed/.test(v.rebuy.state) ? "vd-buy" : "vd-none"}">${esc(v.rebuy.state)}</span>
      <div style="font-size:13px;margin-top:3px">${(v.rebuy.have || []).map(h => `<div>+ ${esc(h)}</div>`).join("")}${(v.rebuy.missing || []).map(m => `<div class="note">− ${esc(m)}</div>`).join("")}</div></div>` : ""}
  </div>`;
  const pct = x => x == null ? "—" : `${x > 0 ? "+" : ""}${(x*100).toFixed(0)}%`;
  const row = r => {
    const fired = !!r.fired;
    let need = "";
    if(r.n === 1) need = r.level ? `${money(r.level)} <span class="note">(${pct(r.distance)} from here; now ${pct(r.reading)} above the 50-day)</span>` : "—";
    else if(r.n === 2) need = `weekly RSI 85 <span class="note">(now ${r.reading == null ? "—" : r.reading})</span>`;
    else need = `weekly close under RSI 70 after 80+ <span class="note">(${r.armed ? `armed — it reached ${r.peak8}` : `not armed; 8-week peak ${r.peak8 == null ? "—" : r.peak8}`}; now ${r.reading == null ? "—" : r.reading})</span>`;
    return `<tr><td class="note">${r.n}</td><td>${esc(r.name)}</td>
      <td>${fired ? `<span class="vd vd-sell">sold ${esc(r.fired)} @ ${money(r.fired_at)}</span>` : (L.next === r.n ? `<b>next</b>` : `<span class="note">waiting</span>`)}</td>
      <td class=num>${fired ? "" : need}</td></tr>`;
  };
  return `<div class="panel" style="margin:0 0 10px;padding:8px 10px">
    <div class="k">Sell ladder <span class="note">from your entry ${esc(L.since)}${L.runs_done ? ` · ${L.runs_done} earlier run${L.runs_done === 1 ? "" : "s"} done` : ""}</span></div>
    <div class="note" style="margin:2px 0 6px">${esc(L.summary || "")}</div>
    <table style="font-size:13px">${L.rungs.map(row).join("")}</table>
    ${v.rebuy ? `<div style="margin-top:8px;padding-top:6px;border-top:1px solid var(--line)"><span class="k">Buy-back readings</span> <span class="vd ${/confirmed|floor|washed/.test(v.rebuy.state) ? "vd-buy" : "vd-none"}">${esc(v.rebuy.state)}</span>
      <div style="font-size:13px;margin-top:3px">${(v.rebuy.have || []).map(h => `<div>+ ${esc(h)}</div>`).join("")}${(v.rebuy.missing || []).map(m => `<div class="note">− ${esc(m)}</div>`).join("")}</div></div>` : ""}
    <div class="note" style="margin-top:6px">Half the position is a core this never touches; each rung sells a third of the other half. Weekly readings count on the week's close only. Measured: 78% of these sells within 25% of a real top on 36 names it was not read from; on your own trades since 2022 the rungs fired after you had sold the winners (NBIS, OKLO, EOSE, RKLB).</div>
  </div>`;
}

// Trading around a core: the numbers a round trip needs, on the card of a
// name flagged for it. Fetched on its own because it reads every lot in every
// account and counts two years of first passages.
async function loadTradeAround(sym, pre){
  const el = $("#tradearound");
  if(!el) return;
  let d = pre;
  // The symbol page hands over the read it already has; a save re-fetches.
  if(!d) try{ d = await (await fetch("/api/outlook?" + new URLSearchParams({symbol: sym}))).json(); }
  catch(e){ el.innerHTML = `<span class="note">Could not work out the round trip.</span>`; return; }
  const t = d.trade_around;
  if(!t || t.error){ el.innerHTML = `<span class="note">${esc((t && t.error) || "No round trip to show.")}</span>`; return; }
  const n = v => v == null ? "—" : Number(v).toLocaleString(undefined, {maximumFractionDigits: 2});
  const pct = v => v == null ? "" : ` (${v > 0 ? "+" : ""}${v.toFixed(1)}%)`;
  const odds = t.odds && t.odds.days ? `From a spot like this one, over the last ${t.odds.days} sessions, price reached the
      <b>lower</b> level first <b>${Math.round(t.odds.down_first * 100)}%</b> of the time and the upper first
      ${Math.round(t.odds.up_first * 100)}%${t.odds.neither > 0.05 ? `; neither within 60 days ${Math.round(t.odds.neither * 100)}%` : ""}.`
    : "Not enough history to count the odds.";
  const accounts = (t.accounts || []).map(a => `<tr><td>${esc(a.account)}</td>
      <td class="note">${esc(a.tax_status.replace("_", " "))}</td>
      <td class=num>${n(a.quantity)}</td><td class=num>${money(a.avg_cost)}</td></tr>`).join("");
  const tp = t.taxable_plan;
  const tax = t.taxable_needed > 0 ? `<div class="note" style="margin-top:6px"><b>${n(t.taxable_needed)} of the slice would have to come from the taxable account.</b>
      ${tp ? `Highest-cost lots first: ${tp.lots.map(l => `${n(l.qty)} from ${esc(l.date)} at ${money(l.cost)} (${l.gain >= 0 ? "+" : "−"}${money(Math.abs(l.gain))}${l.long_term ? ", long-term" : ", short-term"})`).join("; ")}.
      Net ${tp.gain >= 0 ? "gain" : "loss"} ${money(Math.abs(tp.gain))}. ${esc(tp.wash_note)}.` : ""}</div>`
    : `<div class="note" style="margin-top:6px">The whole slice fits inside the tax-free accounts: no tax, no wash-sale rule. Trade it there.</div>`;
  const past = (t.past || []).filter(p => p.gained != null);
  const record = past.length ? `<div style="margin-top:8px"><b>The record</b> — every past sale bought back within sixty days, in shares:
      <table style="width:100%;margin-top:4px"><tr><th scope=col>Sold</th><th class=num scope=col>Shares</th><th class=num scope=col>At</th><th class=num scope=col>Bought back</th><th class=num scope=col>Avg</th><th class=num scope=col>Gained</th></tr>
      ${past.slice(-8).map(p => `<tr><td class="note">${esc(p.sold_on)}</td><td class=num>${n(p.sold)}</td><td class=num>${money(p.at)}</td>
        <td class=num>${n(p.bought_back)}</td><td class=num>${money(p.avg_buy)}</td>
        <td class=num style="color:${p.gained >= 0 ? "var(--up)" : "var(--down)"}">${p.gained >= 0 ? "+" : ""}${n(p.gained)}</td></tr>`).join("")}</table>
      <div class="note">Total ${past.reduce((a, p) => a + p.gained, 0) >= 0 ? "+" : ""}${n(past.reduce((a, p) => a + p.gained, 0))} shares from ${past.length} round trip${past.length === 1 ? "" : "s"}.</div></div>` : "";
  el.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px">
      <b>Trading around the core</b>
      <span class="note">core <input id="coreshares" type="number" step="1" min="0" value="${t.core}" style="width:90px"
        title="Shares that are never sold. Everything above it is the slice."> of ${n(t.quantity)} shares${t.core_default ? " (default: three quarters — set it)" : ""}
        <button id="coresave" style="font-size:11px">save</button></span></div>
    <div style="margin-top:6px">Slice <b>${n(t.slice)}</b> shares. ${t.sell_at && t.buy_back
      ? `Sell it into <b>${money(t.sell_at)}</b>${pct(t.sell_pct)}, buy back at <b>${money(t.buy_back)}</b>${pct(t.buy_pct)}:
         <b>+${n(t.shares_gained)} shares</b> (+${t.gained_pct}%) if it completes.`
      : t.sell_at ? `Sell it into <b>${money(t.sell_at)}</b>${pct(t.sell_pct)}. No level below sits 30% or more under that sale yet, so no buy-back is planned.`
      : t.next_rung ? `No sell price today: the next rung is ${esc(t.next_rung)} — a weekly reading, not a price.`
      : "No sell level at least 30% above price today."}</div>
    ${t.sell_why ? `<div class="note" style="margin-top:3px">Sell level: ${esc(t.sell_why)}.${t.buy_why ? ` Buy-back: ${esc(t.buy_why)}.` : ""}</div>` : ""}
    ${(t.named || []).length ? `<div class="note" style="margin-top:3px">Also named below: ${t.named.filter(x => x.level !== t.buy_back).slice(0, 5).map(x => `${money(x.level)} — ${esc(x.source)}`).join("; ")}.</div>` : ""}
    <div class="note" style="margin-top:4px">${odds}</div>
    <table style="width:100%;margin-top:6px"><tr><th scope=col>Account</th><th scope=col></th><th class=num scope=col>Shares</th><th class=num scope=col>Avg cost</th></tr>${accounts}</table>
    ${tax}${record}
    <div class="note" style="margin-top:6px">The intraday poll alerts at both levels. Nothing here places a trade.</div>`;
  const btn = $("#coresave");
  if(btn) btn.addEventListener("click", async ev => {
    ev.preventDefault(); ev.stopPropagation();
    btn.disabled = true; btn.textContent = "saving…";
    try{
      const r = await (await fetch("/api/outlook?" + new URLSearchParams({action: "setcore", symbol: sym, value: $("#coreshares").value}))).json();
      btn.textContent = r.error ? "failed" : "saved";
      if(!r.error){ SYM_FETCH.outlook.delete(sym); loadTradeAround(sym); }
    }catch(e){ btn.textContent = "failed"; }
    btn.disabled = false;
  });
}

// Where price sits between the levels either side of it. This is the question
// the tab was asked most directly — "what are the major support areas" — and
// the engine had no answer at all until horizontal zones existed: Fibonacci and
// the Ichimoku cloud both describe moving boundaries, and neither is what
// anybody means by support.
// "4.5 bullish against 4.0 bearish" was a number with nowhere to look. Asked
// what it meant, there was no answer on the page — so the arithmetic is shown,
// itemised, adding up in front of you.
function tallyBlock(v){
  const t = v.tally;
  if(!t) return "";
  const bar = (label, val, colour) => {
    const w = (t.bull + t.bear) || 1;
    return `<div style="display:flex;align-items:center;gap:8px;margin:2px 0">
      <span class="note" style="width:52px">${label}</span>
      <span style="flex:0 0 ${Math.round((val / w) * 160)}px;height:9px;background:${colour};border-radius:2px"></span>
      <b>${val.toFixed(1)}</b></div>`;
  };
  const rows = (t.items || []).map(i => `<tr>
      <td style="color:${i.stance === "bull" ? "var(--up)"
                       : i.stance === "bear" ? "var(--down)" : "var(--warn)"};
                 font-weight:600;width:52px">+${i.weight.toFixed(1)}</td>
      <td style="width:120px">${esc(i.name)}</td>
      <td class="note">${esc(i.detail)}</td></tr>`).join("");
  const ctx = (t.context || []).map(i => `<tr>
      <td class="note" style="width:52px">0.0</td>
      <td class="note" style="width:120px">${esc(i.name)}</td>
      <td class="note">${esc(i.detail)}</td></tr>`).join("");
  return `<details style="margin-top:9px">
    <summary style="cursor:pointer"><b>Why this call</b> —
      ${t.bull.toFixed(1)} bullish vs ${t.bear.toFixed(1)} bearish
      (${Math.round(t.bull_share * 100)}% bullish)</summary>
    <div style="margin-top:8px">
      ${bar("bullish", t.bull, "var(--up)")}
      ${bar("bearish", t.bear, "var(--down)")}
      <table style="width:100%;margin-top:8px">${rows}
        ${ctx ? `<tr><td colspan=3 class="note" style="padding-top:8px">
          <b>Counted but not scored</b> — reported because it is worth knowing,
          weighted zero because price is not interacting with it:</td></tr>${ctx}` : ""}
      </table>
      <div class="note" style="margin-top:8px">${esc(t.explain)}</div>
    </div></details>`;
}

// The three prices worth having in your head for this name. Deliberately ahead
// of the evidence and the chart: "what do I do and at what price" is the
// question, and everything below it is the working.
function watchBlock(v){
  const w = v.watch;
  if(!w || !w.price || !(w.levels||[]).length) return "";
  const col = {up:"var(--up)", down:"var(--down)", flag:"var(--warn)",
               muted:"var(--muted)"};
  // Each level says what it MEANS. These were three fixed headings — "Buy /
  // add at", "Trim into", "Wrong below" — shown whatever the verdict was, so
  // IREN read SELL above "Buy / add at 32.24" and "Wrong below 32.24": one
  // number under two contradictory labels, on a name the app said to exit.
  return `<div class="panel" style="margin:8px 0;padding:2px 0">
    <table style="width:100%">${w.levels.map(l=>`<tr>
      <td style="width:46%"><b>${esc(l.label)}</b>
        <div class="note" style="margin-top:2px">${esc(l.why)}</div></td>
      <td class=num style="font-size:17px;font-weight:700;color:${col[l.tone]||"var(--text)"};
                           white-space:nowrap;vertical-align:top">
        ${money(l.price)}
        <div class="note" style="font-weight:400">${
          l.pct === 0 ? "here now" : (l.pct > 0 ? "+" : "") + l.pct + "% away"}</div></td>
    </tr>`).join("")}</table></div>`;
}

function levelsBlock(v){
  const n = v.near || {};
  const row = (label, z, colour) => {
    if(!z) return `<tr><td class="note">${label}</td><td class="note" colspan=2>none found</td></tr>`;
    return `<tr>
      <td class="note">${label}</td>
      <td style="color:${colour};font-weight:600">${money(z.low)} – ${money(z.high)}</td>
      <td class="note">${z.touches} touches${z.flipped
        ? ` · <b>flipped</b> — has held as both support and resistance` : ""}
        · last ${esc(z.last)}</td></tr>`;
  };
  const tl = (v.trendlines || []).slice(0, 2).map(l => `<tr>
      <td class="note">${l.flipped_from ? `prior ${esc(l.flipped_from)}, now ${esc(l.side)}` : esc(l.side) + " line"}</td>
      <td style="font-weight:600">${money(l.to.price)}</td>
      <td class="note">${l.flipped_from ? `broken ${esc(l.broke_on)}, retested ${l.retests} time${l.retests === 1 ? "" : "s"} since` : `${l.touches} touches since ${esc(l.from.time)}`}${
        v.price != null ? (v.price > l.to.price ? " · price above it" : " · price below it") : ""}</td>
    </tr>`).join("");
  const ma = Object.entries(v.moving_averages || {}).map(([n_, val]) => `<tr>
      <td class="note">${esc(n_)}-day average</td>
      <td style="font-weight:600">${money(val)}</td>
      <td class="note">${v.price > val ? "price above" : "price below"}</td></tr>`).join("");
  return `<table style="margin:8px 0 4px;width:100%">
    ${row("Resistance", n.resistance, "var(--down)")}
    ${n.at ? row("At level", n.at, "var(--warn)") : ""}
    ${row("Support", n.support, "var(--up)")}
    ${tl}${ma}</table>`;
}
