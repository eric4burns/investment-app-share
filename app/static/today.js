// Today: the ranked list, the alert log, attention, the Diagnose findings, market mood, buy plans.
// One of the dashboard's scripts (see dashboard.html): a classic script sharing the page's
// global scope with the others, loaded in the order the tags there give.

// The exposure dial: four ratio gauges, each +1 or −1, summed. Clear skies,
// windy, or risk-off, in RonnieV's words, from Cantonese Cat's charts.
function regimeHTML(r){
  if(!r) return "";
  const tone = r.state === "on" ? "var(--up)" : r.state === "off" ? "var(--down)" : "var(--warn)";
  // One line. The gauge table and the caveat fold away: by its own text the
  // dial carries no weight in any verdict, so it does not get a panel's worth
  // of the page.
  return `<div style="margin-top:10px;padding-top:8px;border-top:1px solid var(--line)">
    <details><summary style="cursor:pointer;list-style:none"><span class="k">Exposure dial</span>
      <b style="color:${tone};margin-left:8px">${esc(r.label)}</b> <span class="note">${r.score > 0 ? "+" : ""}${r.score} of 4 — ${(r.gauges || []).map(g => `${esc(g.name)} ${g.score > 0 ? "+" : g.score < 0 ? "−" : "0"}`).join(", ")} · no weight in any verdict</span></summary>
    <table style="margin-top:4px;font-size:13px">${(r.gauges || []).map(g => `<tr>
      <td style="width:2.4em;color:${g.score > 0 ? "var(--up)" : g.score < 0 ? "var(--down)" : "var(--muted)"};font-weight:700">${g.score > 0 ? "+1" : g.score < 0 ? "−1" : "0"}</td>
      <td><b>${esc(g.name)}</b> ${esc(g.state)}</td><td class="note">${esc(g.what)}</td></tr>`).join("")}</table>
    ${r.note ? `<div class="note" style="margin-top:4px">${esc(r.note)}</div>` : ""}</details>
  </div>` + indexHTML(OUTLOOK && OUTLOOK.index);
}

function indexHTML(ix){
  if(!ix || !ix.indices || !Object.keys(ix.indices).length) return "";
  const tone = ix.state === "with" ? "var(--up)" : ix.state === "against" ? "var(--down)" : "var(--warn)";
  const word = ix.state === "with" ? "with you" : ix.state === "against" ? "against you" : "neutral";
  const call = v => `<span style="font-weight:700;color:${v === "buy" || v === "add" ? "var(--up)" : v === "sell" || v === "trim" ? "var(--down)" : "var(--muted)"}">${esc((v || "—").toUpperCase())}</span>`;
  // One line: the state and each index's trend. The engine's own calls on
  // the indices were fitted on stocks and are not shown.
  return `<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--line)">
    <span class="k">The indices</span> <b style="color:${tone};margin-left:8px">${word}</b>
    <span class="note">— ${Object.entries(ix.indices).map(([sym, v]) => `${esc(sym)} ${v.price != null ? money(v.price) : "—"} ${esc(v.trend)}${v.above_50 && v.above_200 ? ", above 50/200" : v.above_200 ? ", above 200" : ", below 200"}`).join(" · ")}</span>
    <div class="note" style="margin-top:4px">${ix.state === "against"
      ? "The S&amp;P is breaking — below its 200-day or a falling 50-day — so every buy and add on the book is marked down one notch of confidence tonight. A mark-down, not a veto."
      : "The market can override a setup. While the S&amp;P is below its 200-day or a falling 50-day, buys and adds are marked down one notch of confidence; recorded on every call so the replay can measure it. The engine's own weekly call on an index is shown for information only: its weights were fitted on stocks."}</div>
  </div>`;
}

// What the outlook could NOT compute, said where the missing thing would have
// appeared. The payload carries `problems` ({wash: "…", sector: "…"}) when a
// part of the engine failed, and the sentiment reading carries `stale` when
// the nightly fetch has been failing. Neither existed in older servers, so
// every field is optional and an absent one renders nothing.
function problemsHTML(){
  const pr = (OUTLOOK && OUTLOOK.problems) || {};
  const names = {wash: "Wash-sale checks", sector: "Sector strength"};
  const lines = Object.entries(pr).filter(([, why]) => why).map(([k, why]) =>
    `<div class="warn" style="margin-top:8px"><b>${esc(names[k] || k)} could not be computed:</b> ${esc(why)}</div>`);
  return lines.join("");
}

function staleMoodHTML(m){
  if(!m || !m.stale) return "";
  const n = m.age_days;
  return `<div class="warn" style="margin-top:8px"><b>Fear &amp; greed reading is ${n == null ? "old" : `${n} day${n === 1 ? "" : "s"} old`}</b>${m.as_of ? ` (as of ${esc(m.as_of)})` : ""} — the nightly fetch has been failing. A stale reading is not weighed in today's verdicts.</div>`;
}

function renderMood(){
  const el = $("#mktmood");
  if(!el) return;
  const m = OUTLOOK && OUTLOOK.market;
  if(!m || m.score == null){ el.innerHTML = `<div class="note">Market fear and greed unavailable —
    it is fetched nightly by <code>./update.sh</code>.</div>` + staleMoodHTML(m) + problemsHTML() + regimeHTML(OUTLOOK && OUTLOOK.regime); return; }
  // Fear reads red and greed reads green, which is how everybody publishes
  // this index. The contrarian ARGUMENT is the opposite — fear is when you buy
  // — and that belongs in the sentence below, not in the colour, where it would
  // just look like a bug.
  // Colour follows the LABEL, not just the extremes. At 31 the index reads
  // "fear" and was painted amber, because only sub-25 counted as red — so a
  // fearful market did not look fearful.
  const tone = m.score < 45 ? "var(--down)" : m.score > 55 ? "var(--up)"
             : "var(--muted)";
  const arg = m.stance === "bull"
    ? "Extreme fear. Contrarian argument for <b>buying</b>, and it is adding weight to every holding's verdict today."
    : m.stance === "extended"
    ? "Extreme greed. Contrarian argument for <b>taking something off</b>, and it is adding weight to every holding's verdict today."
    : "Mid-range, so it argues nothing either way and carries no weight in any verdict today. It only counts below 25 or above 75.";
  const move = (label, val) => val == null ? "" :
    `<span class="note" style="margin-right:12px">${label} <b>${val.toFixed(0)}</b></span>`;
  el.innerHTML = `
    <div style="display:flex;gap:18px;align-items:center;flex-wrap:wrap">
      <div style="flex:0 0 auto">
        <div class="k">Fear &amp; greed</div>
        <div style="font-size:30px;font-weight:700;color:${tone};line-height:1.1">
          ${m.score.toFixed(0)}</div>
        <div class="note" style="text-transform:uppercase;letter-spacing:.06em">${esc(m.rating)}</div>
      </div>
      <div style="flex:1 1 260px;min-width:200px">
        <div style="position:relative;height:10px;border-radius:5px;
             background:linear-gradient(90deg,var(--down-strong),var(--warn-strong),var(--line-strong),var(--warn-strong),var(--up-strong))">
          <span style="position:absolute;left:${Math.max(0,Math.min(100,m.score))}%;top:-5px;
                margin-left:-3px;width:6px;height:20px;background:var(--text);border:2px solid var(--bg-1);border-radius:3px;box-shadow:0 0 0 1px var(--line-strong)"></span>
        </div>
        <div class="note" style="display:flex;justify-content:space-between;margin-top:3px">
          <span>0 extreme fear</span><span>50</span><span>extreme greed 100</span></div>
        <div style="margin-top:8px">${move("yesterday", m.previous)}${move("a month ago", m.month_ago)}
          <span class="note">as of ${esc(m.as_of)}</span></div>
      </div>
    </div>
    <div class="note" style="margin-top:10px">${arg}</div>
    <div class="note" style="margin-top:6px">Seven measures of breadth, volatility
      and demand for safety, combined by CNN into one score. It says the same
      thing about every holding, and its record at calling turns is mixed — so
      it can add to a case the chart is already making and never makes one on
      its own.</div>` + staleMoodHTML(m) + problemsHTML() + regimeHTML(OUTLOOK && OUTLOOK.regime);
}

// ------------------------------------------------------------ attention ----
// The app can now say a great many true things across thirteen tabs, which is a
// different problem from saying nothing: the answer to "where do I start today"
// was spread over at least five of them and ranked nowhere. This is one list,
// ordered by how much money the fact is about.
//
// Every row is a RULE over data already computed elsewhere, and names the tab
// that holds the working. Nothing here is a recommendation — each line states
// something measured and says where to go and see it.
const ATTN = [];

// Buy plans for the next session. The user's rule in numbers: buy at or
// below a price, and if the name gaps up at the open past a percentage, wait
// for a pullback under the open instead of chasing. The poll does the
// watching and alerts; nothing is ordered.
function planForm(sym, v){
  const w = v.watch || {};
  const suggest = w.buy_at && w.buy_pct != null && w.buy_pct <= 0 ? w.buy_at : (v.price || "");
  return `<div class="note" style="margin:6px 0 8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center">
    <span>Plan a buy for the next session<span class="minetag">yours</span>:</span>
    <span>at or below</span><input id="planmax" type="number" step="0.01" value="${suggest ? Number(suggest).toFixed(2) : ""}" style="width:96px" title="The most you will pay">
    <span>· wait if it gaps up more than</span><input id="plangap" type="number" step="0.5" value="2" style="width:56px">%
    <button class="attngo" data-planadd="${esc(sym)}">set plan</button><span id="planmsg"></span></div>
    <div class="note">The poll runs every 15 minutes while the market is open and alerts once per condition per day: "at level" when there was no gap and price is at or below your number; "gapped" when the open was over the rule; "pulled back" when a gapped name comes back under its open and to your number.</div>`;
}

// The plans, kept so the Today list and the symbol page read one copy.
let PLANS = null;

async function loadPlans(){
  const el = $("#buyplans");
  let d;
  try{ d = await (await fetch("/api/plans")).json(); }catch(e){ if(el) el.innerHTML = `<div class="note">Plans unavailable.</div>`; PLANS = PLANS || []; renderTodo(); return; }
  const rows = d.plans || [];
  PLANS = rows;
  if(el) el.innerHTML = !rows.length ? `<div class="note">No plan set. On a name's page, under Plan &amp; levels: "Plan a buy for the next session" — a price to buy at or below, and the gap past which you wait.</div>` :
    `<table><tr><th scope=col>Name</th><th class=num scope=col>Buy at or below</th><th class=num scope=col>Gap rule</th><th scope=col>Set</th><th scope=col>Today</th><th scope=col></th></tr>
    ${rows.map(p => `<tr><td><b>${esc(p.symbol)}</b>${p.note ? `<div class="note">${esc(p.note)}</div>` : ""}</td><td class=num>${money(p.max_price)}</td><td class=num>wait if open is up ${p.gap_pct}%+</td><td class="note date">${esc(p.created)}</td>
      <td class="note">${Object.keys(p.today || {}).length ? Object.entries(p.today).map(([k, px]) => `${esc(k.replace("_", " "))} at ${money(px)}`).join(" · ") : "nothing yet"}</td>
      <td><button class="attngo" data-planrm="${p.id}">done</button></td></tr>`).join("")}</table>`;
  renderTodo();
  repaintSymbol();
}

// "done" on a plan, wherever the plan is listed (the Today list, the symbol
// page's ladder, the hidden plans table): one listener.
document.addEventListener("click", async ev => {
  const b = ev.target.closest("[data-planrm]"); if(!b) return;
  ev.preventDefault(); ev.stopPropagation();
  b.disabled = true;
  await fetch("/api/plans?" + new URLSearchParams({action: "remove", id: b.dataset.planrm}));
  loadPlans();
});

document.addEventListener("click", async ev => {
  const b = ev.target.closest("[data-planadd]"); if(!b) return;
  ev.preventDefault(); ev.stopPropagation();
  const msg = $("#planmsg"); if(msg) msg.textContent = "saving…";
  const r = await (await fetch("/api/plans?" + new URLSearchParams({action: "add", symbol: b.dataset.planadd, max_price: $("#planmax").value, gap_pct: $("#plangap").value}))).json();
  if(msg) msg.textContent = r.error ? r.error : `set — the poll watches ${b.dataset.planadd} tomorrow`;
  loadPlans();
});

// The kind of alert, in a word a person would use. The severity word alone
// ("act") said nothing about what the alert was.
const ALERT_KIND = {level: "your level", intraday: "your level", verdict: "call changed", first: "first reading", floor: "floor", ladder: "ladder rung",
                    wash: "wash sale", earnings: "earnings", regime: "market", sentiment: "fear & greed", tier: "DCA tier", plan: "your plan",
                    statement: "export due"};

const alertMine = a => /(^|:)mylevel:/.test(a.key || "");

const alertKindWord = a => (a.kind === "level" || a.kind === "intraday") && !alertMine(a) ? "app level" : (ALERT_KIND[a.kind] || a.kind || a.level || "alert");

// One row per name, kind and day, the newest state only: three intraday
// alerts on IREN on one morning are one fact. Shared by the log and the
// Today list, so both dedupe the same way.
function dedupeAlerts(list){
  const seen = new Set();
  return (list || []).filter(a => { const k = `${a.kind}|${a.symbol}|${a.day}`; if(seen.has(k)) return false; seen.add(k); return true; });
}

const alertLookKey = a => lookKey(`${a.kind} ${a.symbol} ${a.day}`);

// What to DO about an alert, in plain words. An alert is a fact; this is the
// action it asks for, or the statement that it asks for none.
function alertTodo(a){
  switch(a.kind){
    case "level": case "intraday": return alertMine(a)
      ? "A level you set on the chart, not the app's call: whatever you planned for it is the action. The app's own read is on the name's page."
      : "A level the app named on this name — its buy-at, sell-into or wrong-below. Open the page for the read and the next levels before acting.";
    case "verdict": return "The app's call on this name changed. Read why on its page before acting on it.";
    case "first": return "A first reading. Nothing to do until it has a record.";
    case "floor": return "A buy-back reading is in place. Compare it with your own last sale on the name's page before buying.";
    case "ladder": return "A sell rung fired. Decide whether to sell that rung's share; the ladder is on the name's page.";
    case "wash": return "Buying this back inside the window disallows the loss for tax. Wait it out, or accept that.";
    case "earnings": return "Nothing to decide from the chart until the report is out; size for the gap either way.";
    case "regime": return "The market's reading changed. Buys and adds are marked down a notch while it lasts; nothing to do on its own.";
    case "sentiment": return "Fear and greed reached an extreme. It adds weight to every call; nothing to do on its own.";
    case "tier": return "Your DCA tier changed. Size the next scheduled buy to it.";
    case "plan": return "Your buy plan's condition was met. Check the fill price against your number and act, or tick this off.";
    case "statement": return "This one cannot pull itself. Export it from the site (SETUP.md, Monthly statement pull — Claude can drive most of them in Chrome), drop the file in the folder named, run the import. It comes back weekly until the file lands.";
    default: return a.detail ? esc(a.detail) : "Read it, then tick it off.";
  }
}

function renderAlerts(d){
  TODO_DATA = d;
  const el = $("#alerts");
  if(!el){ renderTodo(); return; }
  const ch = d.alert_channels || {};
  const where = [ch.ntfy_topic ? "your phone (ntfy)" : null, ch.macos ? "this Mac" : null].filter(Boolean);
  const chan = `<div class="note" style="margin-bottom:8px">${
    where.length ? `Delivered to ${where.join(" and ")}.` :
    `Not delivered anywhere yet: set <code>alerts.ntfy_topic</code> in config.json to reach your phone — see SETUP.md.`}
    Nightly after the close, and every 15 minutes during the session for a price through a stop or a trim level. Today's are ranked under <b>What to do</b>; this is the whole week.</div>`;
  const all = dedupeAlerts(d.alerts);
  const seenLook = looked("alerts");
  const lk = alertLookKey;
  const hiddenN = all.filter(a => seenLook[lk(a)]).length;
  const rows = SHOW_LOOKED.alerts ? all : all.filter(a => !seenLook[lk(a)]);
  if(!all.length){ el.innerHTML = chan + `<div class="note">Nothing in the last week.</div>`; renderTodo(); return; }
  const tone = {act: "var(--down)", warn: "var(--warn)", info: "var(--muted)"};
  el.innerHTML = chan + `<div class="note" style="margin-bottom:6px">The word is the kind of alert; red ones need a decision. Each row says what to do; "open" is the name's page.</div>
    <table style="width:100%">${rows.slice(0, 60).map((a, i) => `<tr class="alertrow" data-i="${i}" data-key="${esc(`${a.kind}|${a.symbol}|${a.day}`)}" style="${a.detail ? "cursor:pointer" : ""}">
      <td><label class="cb" title="Tick when dealt with"><input type="checkbox" data-look="${esc(lk(a))}" ${seenLook[lk(a)] ? "checked" : ""}></label></td>
      <td class="note" style="white-space:nowrap">${esc(a.day)}</td>
      <td><span class="pill" style="color:${tone[a.level] || "inherit"}" title="${esc(a.level)}">${esc(alertKindWord(a))}</span></td>
      <td>${esc(a.message)}<div class="note" style="margin-top:3px">${alertTodo(a)}${a.symbol ? ` <button class="attngo" data-open="${esc(a.symbol)}" style="margin-left:6px;min-height:28px">open ${esc(a.symbol)} →</button>` : ""}</div>${a.detail ? `<div class="note alertdetail" ${a.level === "act" && window.innerWidth > 640 ? "" : "hidden"} style="margin-top:4px;line-height:1.45">${esc(a.detail)}</div>` : ""}</td>
      <td class="note" style="white-space:nowrap">${a.sent_at ? "sent · " + esc(a.channel || "") : "stored"}</td>
    </tr>`).join("")}</table>`;
  el.insertAdjacentHTML("beforeend", hiddenN ? `<div class="note" style="margin-top:6px">${hiddenN} dealt with · <a href="#" data-showlooked="alerts">${SHOW_LOOKED.alerts ? "hide them" : "show them"}</a></div>` : "");
  el.querySelectorAll("tr.alertrow").forEach(tr => tr.addEventListener("click", ev => {
    if(ev.target.closest("label, input, button")) return;
    const dd = tr.querySelector(".alertdetail"); if(dd) dd.hidden = !dd.hidden;
  }));
  wireLooked(el, "alerts", () => renderAlerts(d));
  renderTodo();
}

// "open X →" on an alert row, wherever it is rendered.
document.addEventListener("click", ev => {
  const b = ev.target.closest("[data-open]"); if(!b) return;
  ev.preventDefault(); ev.stopPropagation();
  openSymbol(b.dataset.open, "read");
});

// `extra`: {sym, todo} — the one name the row is about, when it is about one
// (the row then opens its page), and what to do about it in a sentence.
function attn(dollars, text, tab, detail, extra){
  ATTN.push(Object.assign({dollars: dollars || 0, text, tab, detail: detail || ""}, extra || {}));
}

// Where a "go" lands, in the section's own name.
const GO_LABEL = {risk: "Money → Risk", outlook: "Stocks → Holdings calls", holdings: "Money → Holdings", budget: "Budget", trades: "Money → Trades"};

function renderAttention(){
  const el = $("#attention");
  if(!el){ renderTodo(); return; }
  if(!ATTN.length){
    el.innerHTML = `<div class="note">Nothing is far enough out of the ordinary to
      call out. That is a statement about thresholds, not a clean bill of health.</div>`;
    renderTodo();
    return;
  }
  // Biggest consequence first. A 68% give-back on a $37k position outranks a
  // 35% one on $2k, and sorting by percentage would put them the other way up.
  // Eight is the point past which a list of priorities stops being one.
  const rows = [...ATTN].sort((a,b)=> b.dollars - a.dollars).slice(0, 8);
  const seen = looked("attn");
  const key = r => lookKey(r.text);
  const hidden = rows.filter(r => seen[key(r)]);
  const show = SHOW_LOOKED.attn ? rows : rows.filter(r => !seen[key(r)]);
  el.innerHTML = show.map(r=>`
    <div class="attnrow" style="${seen[key(r)] ? "opacity:.55" : ""}">
      <label class="cb" title="Tick when you have looked into it. It stays hidden for two weeks or until the item changes." style="flex:none;padding-top:2px"><input type="checkbox" data-look="${esc(key(r))}" ${seen[key(r)] ? "checked" : ""}></label>
      <div class="attnamt">${r.dollars ? money(r.dollars) : ""}</div>
      <div class="attntext">${r.text}${r.detail
        ? `<div class="note">${r.detail}</div>` : ""}${r.todo ? `<div class="note">${r.todo}</div>` : ""}</div>
      ${r.sym ? `<button class="attngo" data-open="${esc(r.sym)}">${esc(r.sym)} →</button>` : `<button class="attngo" data-goto="${esc(r.tab)}">${esc(GO_LABEL[r.tab] || r.tab)} →</button>`}
    </div>`).join("") + (hidden.length ? `<div class="note" style="margin-top:6px">${hidden.length} looked into · <a href="#" data-showlooked="attn">${SHOW_LOOKED.attn ? "hide them" : "show them"}</a></div>` : "");
  el.querySelectorAll("[data-goto]").forEach(b =>
    b.addEventListener("click", ()=> showTab(b.dataset.goto)));
  wireLooked(el, "attn", renderAttention);
  renderTodo();
}

// ------------------------------------------------------------ what to do ----
// ONE ranked list, Phase 2 commit 3. The four things that used to stack on
// the Overview — tomorrow's buy plans, the "worth a look" rows, the day's
// alerts and the Diagnose findings — each answer "what needs me", and each
// keeps its own render function above; this reads the same data and puts
// every item on one row: a tick, the dollars it is about, what it is in
// bold, what to do, and where to go. Ranked the way attn() already ranked —
// by dollars at stake, since a fact about a $37k position outranks the same
// fact about $2k — then by kind. A buy plan whose condition was met today
// goes first whatever its size: it is the one thing the day was set up for.
let TODO_DATA = null;                 // the performance payload (alerts, channels)

let DX = null, DX_STATE = "";          // the Diagnose findings, and whether they are in

const TODO_CAP = 12;

const KIND_RANK = {plan: 0, alert: 1, finding: 2, attn: 3};

function todoItems(){
  const items = [];
  const heldValue = s => (OUTLOOK && OUTLOOK.verdicts && OUTLOOK.verdicts[s] && OUTLOOK.verdicts[s].value) || 0;
  const one = s => ({label: s, sym: s});
  (PLANS || []).forEach(p => {
    const today = Object.entries(p.today || {});
    items.push({kind: "plan", kindWord: "your plan", dollars: heldValue(p.symbol), urgent: today.length > 0,
      lookKind: "plans", lookKey: lookKey(`plan ${p.symbol} ${today.map(t => t[0]).join(" ")}`),
      what: `Buy <b>${esc(p.symbol)}</b> at or below ${money(p.max_price)}${today.length ? ` — <span style="color:var(--up)">${today.map(([k, px]) => `${esc(k.replace("_", " "))} at ${money(px)}`).join(", ")} today</span>` : ""}`,
      todo: today.length ? `Your plan's condition was met. Check the fill price against ${money(p.max_price)} and act, or tick this off.`
                         : `Your plan, set ${esc(p.created)}: wait if it opens up more than ${p.gap_pct}%; the 15-minute poll alerts when price gets there.${p.note ? ` Your note: ${esc(p.note)}.` : ""}`,
      go: Object.assign(one(p.symbol), {sub: "plan"})});
  });
  // The newest session's alerts, every level. Older ones are the week's log
  // under All alerts — carrying them here too made the list seventy rows,
  // which is not a list of what to do today.
  const alerts = dedupeAlerts((TODO_DATA || {}).alerts);
  const newest = alerts.reduce((m, a) => a.day > m ? a.day : m, "");
  alerts.filter(a => a.day === newest).forEach(a => {
    // A plan alert IS the plan row above, fired: one item, not two.
    if(a.kind === "plan" && (PLANS || []).some(p => p.symbol === a.symbol)) return;
    items.push({kind: "alert", kindWord: alertKindWord(a), dollars: heldValue(a.symbol), urgent: false,
      lookKind: "alerts", lookKey: alertLookKey(a),
      what: `${esc(a.message)}${a.day !== newest ? ` <span class="note">(${esc(a.day)})</span>` : ""}`,
      todo: alertTodo(a),
      go: a.symbol ? one(a.symbol) : {label: "Today → Market", view: "today/market"}});
  });
  const dxLabel = {critical: "needs attention", warning: "worth knowing", note: "context"};
  (DX || []).forEach(f => {
    const syms = f.symbols || [];
    const dollars = syms.reduce((t, s2) => t + heldValue(s2), 0);
    const view = syms.length === 1 ? null : /concentrat|equal positions|correlat|% of the portfolio/i.test(f.headline + " " + f.detail) ? "money/risk" : "stocks/calls";
    items.push({kind: "finding", kindWord: dxLabel[f.severity] || f.severity, dollars, urgent: false,
      lookKind: "dx", lookKey: lookKey(f.headline + " " + syms.join(" ")),
      what: `${f.headline}${syms.length ? ` <span class="note">${syms.map(esc).join(", ")}</span>` : ""}`,
      todo: f.action ? esc(f.action) : f.why ? esc(f.why) : f.detail,
      go: syms.length === 1 ? one(syms[0]) : {label: GO_LABEL[view === "money/risk" ? "risk" : "outlook"], view}});
  });
  ATTN.forEach(r => items.push({kind: "attn", kindWord: "worth a look", dollars: r.dollars, urgent: false,
    lookKind: "attn", lookKey: lookKey(r.text),
    what: r.text, todo: [r.detail, r.todo].filter(Boolean).map(t => /[.!?]\s*$/.test(t.replace(/<[^>]+>/g, "")) ? t : t + ".").join(" "),
    go: r.sym ? one(r.sym) : {label: GO_LABEL[r.tab] || r.tab, view: r.tab}}));
  return items.sort((a, b) => (b.urgent ? 1 : 0) - (a.urgent ? 1 : 0) || b.dollars - a.dollars
    || KIND_RANK[a.kind] - KIND_RANK[b.kind] || a.what.localeCompare(b.what));
}

function renderTodo(){
  const el = $("#todo"); if(!el) return;
  if(!TODO_DATA){ el.innerHTML = loadingHTML("Reading what needs you today…"); return; }
  const items = todoItems();
  const looks = {attn: looked("attn"), dx: looked("dx"), alerts: looked("alerts"), plans: looked("plans")};
  const isLooked = it => !!looks[it.lookKind][it.lookKey];
  const live = items.filter(it => !isLooked(it)), done = items.filter(isLooked);
  const shown = SHOW_LOOKED.todo ? items : live;
  const row = it => `<div class="attnrow${isLooked(it) ? " looked" : ""}" data-kind="${it.kind}">
    <label class="cb" title="Tick when dealt with. It stays hidden for two weeks, or until the item changes." style="flex:none;padding-top:2px"><input type="checkbox" data-look="${esc(it.lookKey)}" data-lookkind="${it.lookKind}" ${isLooked(it) ? "checked" : ""}></label>
    <div class="attnamt">${it.dollars ? money(it.dollars) : ""}</div>
    <div class="attntext"><div class="todo1"><span class="todokind">${esc(it.kindWord)}</span>${it.what}</div><div class="todo2">${it.todo}</div></div>
    ${it.go.sym ? `<button class="attngo" data-open="${esc(it.go.sym)}"${it.go.sub ? ` data-opensub="${it.go.sub}"` : ""}>${esc(it.go.label)} →</button>`
                : `<button class="attngo" data-goto="${esc(it.go.view)}">${esc(it.go.label)} →</button>`}</div>`;
  const head = shown.slice(0, TODO_CAP), tail = shown.slice(TODO_CAP);
  const still = DX_STATE === "loading" ? `<div class="note" style="margin-top:6px">Still reading the book for findings — they join the list when they land.</div>` : "";
  el.innerHTML = (!shown.length
      ? `<div class="note"><b>Nothing needs you today.</b>${done.length ? ` ${done.length} dealt with.` : ""}</div>`
      : `<div class="note" style="margin-bottom:4px">${live.length} thing${live.length === 1 ? "" : "s"}, biggest first: what it is, what to do, and where to go.</div>`
        + head.map(row).join("")
        + (tail.length ? `<details style="margin-top:6px"><summary class="note" style="cursor:pointer;min-height:32px;display:flex;align-items:center">show all ${shown.length}</summary>${tail.map(row).join("")}</details>` : ""))
    + (done.length ? `<div class="note" style="margin-top:6px">${done.length} dealt with · <a href="#" data-showlooked="todo">${SHOW_LOOKED.todo ? "hide them" : "show them"}</a></div>` : "")
    + still;
  el.querySelectorAll("[data-goto]").forEach(b => b.addEventListener("click", () => showTab(b.dataset.goto)));
  el.querySelectorAll("[data-opensub]").forEach(b => b.addEventListener("click", ev => { ev.stopPropagation(); openSymbol(b.dataset.open, b.dataset.opensub); }));
  // A tick here is the same tick as on the source panel: same key, same
  // fortnight, so the log and the findings stay in step with this list.
  wireLooked(el, "todo", () => { renderTodo(); if(TODO_DATA && $("#alerts")) renderAlerts(TODO_DATA); renderAttention(); renderDxFindings(); });
}

// "Looked into it" — a box on each Worth-a-look row, each Diagnose finding,
// each alert and each Today row. Ticked items drop out of the list for two
// weeks, keyed by the item's words with the numbers stripped, so the same
// item with today's figures stays hidden and a genuinely new one does not.
// Per browser (localStorage). A box carries data-lookkind when the list it
// sits in mixes kinds (the Today list).
const SHOW_LOOKED = {attn: false, dx: false, alerts: false, plans: false, todo: false};

function lookKey(text){
  return String(text || "").replace(/<[^>]+>/g, "").replace(/[\d.,%$+−-]+/g, "").replace(/\s+/g, " ").trim().toLowerCase().slice(0, 120);
}

function looked(kind){
  try{
    const all = JSON.parse(localStorage.getItem("invest.looked." + kind) || "{}") || {};
    const cutoff = Date.now() - 14 * 86400 * 1000;
    const live = {};
    Object.entries(all).forEach(([k, t]) => { if(t > cutoff) live[k] = t; });
    return live;
  }catch(e){ return {}; }
}

function wireLooked(el, kind, rerender){
  el.querySelectorAll("[data-look]").forEach(cb => cb.addEventListener("change", () => {
    const k = cb.dataset.lookkind || kind;
    try{
      const all = looked(k);
      if(cb.checked) all[cb.dataset.look] = Date.now(); else delete all[cb.dataset.look];
      localStorage.setItem("invest.looked." + k, JSON.stringify(all));
    }catch(e){}
    rerender();
    if(kind !== "todo") renderTodo();
  }));
  el.querySelectorAll("[data-showlooked]").forEach(a => a.addEventListener("click", ev => {
    ev.preventDefault(); SHOW_LOOKED[kind] = !SHOW_LOOKED[kind]; rerender();
  }));
}

// From the performance payload, which Overview already has in hand.
function buildAttention(d){
  ATTN.length = 0;
  const r = d.risk || {};

  if(r.current_drawdown != null && r.current_drawdown <= -0.10){
    const peak = (d.summary && d.summary.end_value) || 0;
    attn(Math.abs(r.current_drawdown) * peak / (1 + r.current_drawdown),
      `The whole portfolio is <b>${pct0(Math.abs(r.current_drawdown))}</b> below its own peak`,
      "risk", `Worst it has been is ${pct0(Math.abs(r.max_drawdown||0))}.`,
      {todo: "Look at which names are giving the most back under Money → Risk, and whether each still has its reason to be held."});
  }

  // Only what is EXCEPTIONAL gets its own line. Listing every holding that is
  // 25% below its high put ten near-identical rows here and simply reprinted
  // the Risk table one tab earlier, which is the overload this panel exists to
  // cure. A position earns a line by doing something beyond drifting down:
  // moving hard in the last month, or turning up out of a deep hole. The plain
  // give-backs collapse into a single row that points at the table.
  const moves = (d.position_moves || []).filter(p=>p.notable);
  const special = moves.filter(p => (p.notes||[]).length > 1);
  // "Well below its high" means exactly that; a name flagged only for a
  // surge (TEM +40% in a month, ASST at its held peak) is not a give-back.
  const routine = moves.filter(p => (p.notes||[]).length <= 1 && (p.from_peak || 0) <= -0.25);
  const surges = moves.filter(p => (p.notes||[]).length <= 1 && (p.from_peak || 0) > -0.25 && (p.notes||[]).some(n => /\+\d+% in a month/.test(n)));
  if(surges.length){
    attn(surges.reduce((a,p)=> a + (p.value || 0), 0),
      `<b>${surges.map(p => esc(p.symbol)).join(", ")}</b> ${surges.length > 1 ? "have" : "has"} run hard this month`,
      "outlook", `${surges.map(p => `${esc(p.symbol)} ${esc((p.notes||[])[0] || "")}`).join("; ")}.`,
      {sym: surges.length === 1 ? surges[0].symbol : null,
       todo: "Check the sell-into level on the name's page (Plan & levels) — a run into a level tested before is where a trim is taken, never on the way down."});
  }

  special.slice(0, 3).forEach(p=>{
    // Valued by how much of THIS position the move is about, so ordering
    // reflects dollars at stake rather than percentages: a 68% give-back on a
    // $37k position outranks a 90% one on $2k.
    attn(Math.abs(p.given_back_usd != null ? p.given_back_usd : (p.value || 0) * (p.from_peak || 0)),
      `<b>${esc(p.symbol)}</b> ${esc((p.notes||[]).slice(1).join(" · "))}`,
      "risk", esc((p.notes||[])[0] || ""),
      {sym: p.symbol, todo: "Re-read the thesis on the name's page: is the wrong-below level still above the price you would give up at?"});
  });

  if(routine.length){
    const worst = routine.slice().sort((a, b) => Math.abs(b.from_peak || 0) - Math.abs(a.from_peak || 0))[0];
    attn(routine.reduce((a,p)=> a + Math.abs(p.given_back_usd != null ? p.given_back_usd : (p.value||0)*(p.from_peak||0)), 0),
      `<b>${routine.length}</b> other holding${routine.length>1?"s are":" is"} well below
       ${routine.length>1?"their":"its"} high since you bought`,
      "risk", `Deepest is ${esc(worst.symbol)} at ${pct0(Math.abs(worst.from_peak))}.`,
      {sym: routine.length === 1 ? routine[0].symbol : null, todo: "The list is under Money → Risk. Nothing to do unless one of them has broken its wrong-below level."});
  }

  const biggest = (d.concentration && d.concentration.rows || d.holdings || [])
    .slice().sort((a,b)=>(b.weight||0)-(a.weight||0))[0];
  if(biggest && (biggest.weight||0) >= 0.25){
    attn(biggest.value || 0,
      `<b>${esc(biggest.symbol)}</b> is <b>${pct0(biggest.weight)}</b> of the book`,
      "risk", "One position moving decides the month.",
      {sym: biggest.symbol, todo: "Decide whether that weight is intended. If not, the trim goes into strength at its sell-into level, not on a drawdown."});
  }
  renderAttention();
}

async function augmentAttention(){
  let b;
  try{ b = await fetchBudget(); }catch(e){ return; }
  if(!b || b.error) return;
  const i = b.insights || {};
  if(i.deferral_remaining > 0){
    attn(i.deferral_remaining,
      `of 401(k) deferral is still available this year`,
      "budget", `Limit ${money(i.deferral_limit)}, ${money(i.deferral_contributed)} in — ${esc(i.deferral_basis||"")}.`,
      {todo: "Raise the payroll deferral if you want it used before the year ends; Budget → Taxes has the projection."});
  }
  if(i.roth_remaining > 0){
    attn(i.roth_remaining, `of Roth IRA room is unused`,
      "budget", `Allowed ${money(i.roth.allowed)} at this income.`,
      {todo: "Contribute before the filing deadline if the income projection under Budget → Taxes still allows it."});
  }
  if(i.withholding_gap != null && i.withholding_gap < 0){
    attn(Math.abs(i.withholding_gap),
      `of federal withholding behind the computed floor`,
      "budget", "Business income has nothing withheld against it.",
      {todo: "Make an estimated payment or raise withholding; the gap is under Budget → Taxes."});
  }
  if(b.card_blind_spot > 0){
    attn(b.card_blind_spot,
      `of card spending is still unaccounted for`,
      "budget", "A card's own transactions are not imported yet.",
      {todo: "Export that card's transactions and drop the file in data/; the Budget tab fills in from it."});
  }
  if(b.unmatched_out > 500){
    attn(b.unmatched_out,
      `of spending is uncategorised`,
      "budget", `${b.unmatched_count} transactions across ${(b.unmatched_groups||[]).length} merchants.`,
      {todo: "Categorise the biggest merchants under Budget → Loose ends; each rule you add applies to every future import."});
  }
  renderAttention();
}

async function loadDiagnose(){
  const q = new URLSearchParams({from:$("#from").value, to:$("#to").value, scope:$("#scope").value});
  // The findings take anywhere from one to twenty-five seconds cold, and the
  // panel was empty for all of it — which reads as "nothing to report". The
  // Today list says it is still reading until they land.
  DX_STATE = "loading"; renderTodo();
  $("#dxfindings").innerHTML = `<div class="note" aria-live="polite">Reading the book for findings… this takes up to half a minute the first time.</div>`;
  let d;
  try{ d = await (await fetch("/api/diagnose?"+q)).json(); }
  catch(e){ DX_STATE = "failed"; renderTodo(); throw e; }
  if(d.error){ DX_STATE = "failed"; renderTodo(); $("#dxfindings").innerHTML = `<div class="warn">${esc(d.error)}</div>`; return; }

  // Regime is context for reading the findings, not a finding itself — and its
  // own caveats travel with it rather than being summarised away.
  // No header cards: value and return are on the Overview, drawdown and
  // volatility on Risk, and a count of findings is not information.
  DX = d.findings || []; DX_STATE = "ready";
  renderDxFindings();

  $("#dxlevels").innerHTML =
    `<tr><th scope=col>Symbol</th><th class=num scope=col>Weight</th><th class=num scope=col>Close</th>
      <th class=num scope=col>20-month MA</th><th class=num scope=col>Lower band</th><th class=num scope=col>Kijun</th></tr>` +
    d.levels.map(l=>{
      const cell = (v, p2) => v==null
        ? `<td class=num class="note">—</td>`
        : `<td class=num>${money(v)}<br><span style="${col(p2)};font-size:12px">${pct(p2)}</span></td>`;
      return `<tr class="clickable" data-sym="${l.symbol}">
        <td><b>${l.symbol}</b></td><td class=num>${pct(l.weight)}</td>
        <td class=num>${money(l.close)}</td>
        ${cell(l.ma20, l.to_ma20)}${cell(l.lower_band, l.to_lower_band)}${cell(l.kijun, l.to_kijun)}</tr>`;
    }).join("");
  // The chart on the MONTHLY, since these are monthly levels: the timeframe
  // is set before the page opens, and the redraw forced in case the same name
  // is already up on the daily. stopPropagation keeps the document-wide
  // [data-sym] delegate from opening it a second time.
  document.querySelectorAll("#dxlevels [data-sym]").forEach(el =>
    el.addEventListener("click", ev => { ev.stopPropagation(); $("#tf").value="M"; openSymbol(el.dataset.sym, "chart", {reload: true}); }));

  const suppressed = d.levels.filter(l=>!l.lower_band).map(l=>l.symbol);
  $("#dxnote").innerHTML =
    `These are the levels the encoded methods actually wait at — the 20-month average, the lower
     monthly band and the kijun — not targets invented for the purpose. Percentages are distance
     from today's price.` +
    (suppressed.length ? ` Lower band omitted for ${suppressed.join(", ")}: monthly volatility
     exceeds the mean there, so the band sits below zero and is not a price anything can reach.` : "") +
    ` <b>These are observations, not advice.</b> Nothing here sizes a trade or tells you to make one.`;
}

// The findings as their own panel (hidden under Today → What to do, where
// the ranked list carries them); kept so the Diagnose rendering still exists
// in full and the tick state is shared with the list.
function renderDxFindings(){
  const el = $("#dxfindings");
  if(!el || !DX) return;
  const label = {critical:"needs attention", warning:"worth knowing", note:"context"};
  const seen = looked("dx");
  const key = f => lookKey(f.headline + " " + (f.symbols || []).join(" "));
  const hidden = DX.filter(f => seen[key(f)]);
  const show = SHOW_LOOKED.dx ? DX : DX.filter(f => !seen[key(f)]);
  el.innerHTML = show.map(f=>`
    <div class="finding ${f.severity}" style="${seen[key(f)] ? "opacity:.55" : ""}">
      <h4><label class="cb" title="Tick when you have looked into it. It stays hidden for two weeks or until the finding changes." style="margin-right:6px"><input type="checkbox" data-look="${esc(key(f))}" ${seen[key(f)] ? "checked" : ""}></label>${f.headline}
        <span class="pill">${label[f.severity]||f.severity}</span>
        ${f.symbols.length?`<span class="note">${f.symbols.join(", ")}</span>`:""}</h4>
      <p>${f.detail}</p>
      ${f.why ? `<p class="note" style="margin:6px 0 0"><b>What it means:</b> ${esc(f.why)}</p>` : ""}
      ${f.action ? `<p class="note" style="margin:4px 0 0"><b>What you could do:</b> ${esc(f.action)}</p>` : ""}
    </div>`).join("") + (hidden.length ? `<div class="note" style="margin:6px 0">${hidden.length} looked into · <a href="#" data-showlooked="dx">${SHOW_LOOKED.dx ? "hide them" : "show them"}</a></div>` : "");
  wireLooked(el, "dx", renderDxFindings);
  renderTodo();
}
