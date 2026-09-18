// My Money: init() and load(), the overview cards and SVG charts, holdings, trades, risk, sectors, net worth.
// One of the dashboard's scripts (see dashboard.html): a classic script sharing the page's
// global scope with the others, loaded in the order the tags there give.

let OV_MODE = "value";
try{ OV_MODE = localStorage.getItem("invest.overview.mode") || "value"; }catch(e){}

let OV_DATA = null;

function setOverviewMode(m){
  OV_MODE = m;
  try{ localStorage.setItem("invest.overview.mode", m); }catch(e){}
  if(OV_DATA) draw(OV_DATA);
}

function draw(data){
  OV_DATA = data;
  const narrow = ($("#chart") && $("#chart").clientWidth || 900) < 600;
  const W = narrow ? 480 : 900, H = narrow ? 300 : 260, PAD = 34;
  const growth = OV_MODE === "growth";
  // Value is dollars, so it rises when money is deposited as well as when the
  // holdings rise. Growth is the time-weighted return alone: what $100 at the
  // start became, deposits taken out — the line that answers "did the
  // investing work", which the value line cannot.
  const mine = growth ? data.series.map(p => p.twr == null ? null : 100 * (1 + p.twr)) : data.series.map(p=>p.value);
  // Percentages travel alongside the values so the readout can show both.
  // The portfolio's is TIME-WEIGHTED and the benchmark's is the index's own
  // return, which is the only pairing that compares like with like — the
  // benchmark line is a same-deposits replay, so its VALUE contains the same
  // contributions yours does and dividing it by its own start would measure
  // the deposits rather than the market.
  const sets = [{name:"Your portfolio", pts:mine,
                 pcts:data.series.map(p=>p.twr), color:"var(--accent)", dash:false}];
  (data.benchmarks||[]).forEach((b,i)=>{
    const usable = b.points.filter(p=>p.value != null);
    if(usable.length === mine.length)
      sets.push({name: growth ? b.label : b.label+" (same deposits)", pts: growth ? usable.map(p => p.ret == null ? null : 100 * (1 + p.ret)) : usable.map(p=>p.value),
                 pcts:usable.map(p=>p.ret), color:i?"var(--s4)":"var(--muted)", dash:true});
  });
  const all = sets.flatMap(s=>s.pts).filter(v => v != null);
  const min = Math.min(...all), max = Math.max(...all);
  const inner = W - PAD*2, ih = H - PAD*2;
  let g = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Portfolio value over time versus benchmarks">`;
  // Axis labels are HTML laid over the SVG (axisLabels), never <text> inside
  // it: the SVG scales to its box and the labels came out at 6px on a phone.
  const labels = [];
  for(let i=0;i<=4;i++){
    const y = PAD + (ih/4)*i, v = max - ((max-min)/4)*i;
    g += `<line x1="${PAD}" y1="${y}" x2="${W-PAD}" y2="${y}" stroke="var(--grid)" stroke-width="1"/>`;
    labels.push({x:4, y, text: growth ? `${v.toFixed(0)}` : `$${Math.round(v/1000)}k`});
  }
  g += `<g transform="translate(${PAD},${PAD})">`;
  sets.forEach(s=> g += line(s.pts, inner, ih, min, max, s.color, s.dash));
  g += `</g>`;
  // An empty ledger opened on a weekend has no series points at all; the
  // axis labels are simply blank rather than a TypeError that stops init().
  const d0 = data.series.length ? data.series[0].date : "", d1 = data.series.length ? data.series[data.series.length-1].date : "";
  labels.push({x:PAD, y:H-16, text:d0, bottom:true}, {x:W-PAD, y:H-16, text:d1, bottom:true, end:true});
  // Crosshair, hidden until pointed at. Inside the SVG so it scales with the
  // viewBox rather than needing its own coordinate maths.
  g += `<g id="ovhair" style="display:none;pointer-events:none">
          <line y1="${PAD}" y2="${H-PAD}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>
          ${sets.map((s,i)=>`<circle r="4" fill="var(--bg-1)" stroke="${s.color}" stroke-width="2" data-dot="${i}"/>`).join("")}
        </g></svg>`;
  $("#chart").innerHTML = g;
  axisLabels($("#chart"), W, H, labels);
  $("#legend").innerHTML = sets.map(s=>`<span><i style="background:${s.color}"></i>${s.name}</span>`).join("") +
    `<span style="margin-left:auto" class="note">${growth
      ? `growth of $100, deposits taken out · <a href="#" data-ovmode="value">show value</a>`
      : `dollars — rises with deposits too · <a href="#" data-ovmode="growth">show growth of $100</a>`}</span>`;
  $("#legend").querySelectorAll("[data-ovmode]").forEach(a => a.addEventListener("click", ev => { ev.preventDefault(); setOverviewMode(a.dataset.ovmode); }));

  // The readout is shared with the net-worth chart below, since a value curve
  // you cannot interrogate is decoration in both places.
  attachReadout($("#chart"), {
    W, H, PAD, inner, ih, min, max, hairId: "ovhair", tipId: "ovtip",
    dates: data.series.map(p=>p.date), sets,
    // Against the benchmark, and against where the period started. Both are
    // questions you would otherwise answer by squinting at two lines.
    footer: (i, s) => {
      let out = growth
        ? `${s[0].pts[i] == null ? "—" : (s[0].pts[i] - 100).toFixed(1) + "%"} since ${esc((data.series[0]||{}).date || "")}, deposits taken out`
        : `${money(s[0].pts[i] - s[0].pts[0])} since ${esc((data.series[0]||{}).date || "")}`;
      if(s[1] && s[1].pts[i] != null){
        const gap = s[0].pts[i] - s[1].pts[i];
        // Percentage POINTS, not a ratio of percentages: "18 points ahead of
        // the S&P" is a statement anyone can check, "1.4x its return" is not.
        const pp = (s[0].pcts && s[1].pcts && s[0].pcts[i] != null && s[1].pcts[i] != null)
          ? ` (${((s[0].pcts[i] - s[1].pcts[i])*100).toFixed(1)} pts)` : "";
        out += ` · <b style="color:${gap>=0?'var(--up)':'var(--down)'}">`
             + `${growth ? (pp ? pp.replace(/[()]/g, "").trim() : "") : `${gap>=0?'+':''}${money(gap)}${pp}`} vs ${esc(s[1].name.split(" (")[0])}</b>`;
      }
      return out;
    },
  });
}

// A crosshair and a value readout for any SVG line chart drawn by `line()`.
// Both overview charts use it, so the behaviour — snapping to the nearest
// sample, flipping the tip away from the right edge, arrow-key stepping — is
// written once and identical in both.
function attachReadout(host, cfg){
  const {W, H, PAD, inner, ih, min, max, dates, sets, hairId, tipId} = cfg;
  host.style.position = "relative";
  let tip = document.getElementById(tipId);
  if(!tip){
    tip = document.createElement("div");
    tip.id = tipId; tip.className = "ovtip";
    host.appendChild(tip);
  }
  const svg = host.querySelector("svg");
  const hair = host.querySelector("#" + hairId);
  if(!svg || !hair) return;
  const n = dates.length;
  const xAt = i => PAD + (i/(n-1))*inner;
  const yAt = v => PAD + (ih - ((v-min)/((max-min)||1))*ih);

  function at(clientX){
    const r = svg.getBoundingClientRect();
    if(!r.width) return null;
    const t = ((clientX - r.left) / r.width * W - PAD) / inner;
    return Math.max(0, Math.min(n-1, Math.round(t*(n-1))));
  }
  function show(clientX){
    const i = at(clientX);
    if(i == null) return;
    hair.style.display = "";
    const ln = hair.querySelector("line");
    ln.setAttribute("x1", xAt(i)); ln.setAttribute("x2", xAt(i));
    sets.forEach((s,k)=>{
      const dot = hair.querySelector(`[data-dot="${k}"]`);
      if(!dot) return;
      const v = s.pts[i];
      if(v == null){ dot.style.display = "none"; return; }
      dot.style.display = "";
      dot.setAttribute("cx", xAt(i)); dot.setAttribute("cy", yAt(v));
    });
    const rows = sets.map(s=>{
      const pcv = s.pcts ? s.pcts[i] : null;
      const tag = pcv == null ? "" :
        `<em style="color:${pcv>=0?'var(--up)':'var(--down)'}">${pcv>=0?"+":""}${(pcv*100).toFixed(1)}%</em>`;
      return `<div class="ovrow"><i style="background:${s.color}"></i>
        <span>${esc(s.name)}</span><b>${money(s.pts[i])}</b>${tag}</div>`;
    }).join("");
    const foot = cfg.footer ? `<div class="ovrow2">${cfg.footer(i, sets)}</div>` : "";
    tip.innerHTML = `<div class="ovdate">${esc(dates[i])}</div>${rows}${foot}`;
    tip.style.display = "block";
    const r = svg.getBoundingClientRect();
    const px = (xAt(i)/W) * r.width;
    tip.style.left = (px > r.width*0.6 ? px - tip.offsetWidth - 14 : px + 14) + "px";
  }
  function hide(){ hair.style.display = "none"; tip.style.display = "none"; }
  svg.style.touchAction = "pan-y";       // a phone must still scroll the page
  svg.addEventListener("pointermove", e => show(e.clientX));
  svg.addEventListener("pointerdown", e => show(e.clientX));
  svg.addEventListener("pointerleave", hide);
  let kb = n - 1;
  svg.tabIndex = 0;
  svg.addEventListener("keydown", e => {
    if(e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    kb = Math.max(0, Math.min(n-1, kb + (e.key === "ArrowRight" ? 1 : -1)));
    const r = svg.getBoundingClientRect();
    show(r.left + (xAt(kb)/W)*r.width);
  });
  svg.addEventListener("blur", hide);
}

// A picker, grouped so the names you own are not buried among ninety-nine
// tickers. Defined at module scope on purpose: load() runs before init finishes
// wiring listeners, so a function declared down there does not exist yet when
// the first render calls it, and the dropdown comes up empty.
function fillSymbolPicker(data){
  const sel = $("#sympick");
  if(!sel) return;
  // Money-market sweeps, the synthetic cash row and plan options are holdings
  // but not charts: FDRXX has no candles, and stepping onto it with ] is a dead
  // end rather than a symbol.
  const held = (data.holdings || []).map(h=>h.symbol)
    .filter(x => x && !/^(CASH|PLAN:)/.test(x)
                 && !["FDRXX","SPAXX","FZFXX","SPRXX"].includes(x));
  const all = (data.symbols || []).slice().sort();
  const rest = all.filter(x => !held.includes(x));
  const group = (label, syms) => syms.length
    ? `<optgroup label="${esc(label)}">` +
      syms.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join("") + `</optgroup>`
    : "";
  sel.innerHTML = `<option value="">Jump to…</option>`
    + group(`Held (${held.length})`, held)
    + group(`Everything else (${rest.length})`, rest);
}

function renderEmailTrades(rows){
  const el = $("#emailtrades");
  if(!el) return;
  if(!rows){ el.innerHTML = `<div class="note">Not read.</div>`; return; }
  if(!rows.length){
    el.innerHTML = `<div class="note">No trade confirmations in the last 60 days of mail. Fidelity emails one the morning after a fill;
      the nightly update reads it and the trade appears here, and in the journal, before the statement arrives.</div>`;
    return;
  }
  el.innerHTML = `
    <div class="note" style="margin-bottom:8px">Fidelity's confirmation emails, the morning after each fill. The email carries the
      action and the price, not the shares; a row is <b>pending</b> until the statement's transaction lands in the ledger.</div>
    <div class="tscroll"><table>
      <tr><th scope=col>Traded</th><th scope=col>Action</th><th scope=col>Symbol</th><th class=num scope=col>Price</th><th scope=col>Security</th><th scope=col>Account</th><th scope=col>Status</th></tr>
      ${rows.map(r => `<tr>
        <td>${esc(r.trade_date)}</td>
        <td><span class="vd vd-${r.action === "sell" ? "sell" : "buy"}">${esc(r.action)}</span></td>
        <td><b>${esc(r.symbol || "?")}</b></td>
        <td class=num>${money(r.price)}</td>
        <td class="note">${esc(r.security_name)}</td>
        <td class="note">${r.account ? "…" + esc(r.account) : ""}</td>
        <td class="note">${r.confirmed ? `confirmed by the statement${r.quantity ? `, ${Math.abs(r.quantity)} shares` : ""}` : "pending the statement"}</td></tr>`).join("")}
    </table></div>`;
}

function renderWash(w){
  const el = $("#washsales");
  if(!el) return;
  if(!w){ el.innerHTML = `<div class="note">Not computed.</div>`; return; }
  const win = w.windows || {};
  const rows = [];
  (win.do_not_rebuy || []).forEach(r => rows.push(`<tr><td><b>${esc(r.symbol)}</b></td>
    <td>Sold at a loss ${esc(r.date)} (${money(r.loss)}). <b>Do not buy back before ${esc(r.window_closes)}</b> — ${r.days_left} day${r.days_left === 1 ? "" : "s"} left — or the loss is disallowed this year.</td></tr>`));
  (win.underwater_recent_buys || []).forEach(r => rows.push(`<tr><td><b>${esc(r.symbol)}</b></td>
    <td>Bought ${esc(r.date)} at ${money(r.price)}, now ${money(r.now)} (${money(r.unrealised)}). Selling it at a loss and buying back before ${esc(r.window_closes)} would be a wash.</td></tr>`));
  const past = (w.past || []).slice(0, 12);
  el.innerHTML = `
    <div class="note" style="margin-bottom:8px">A loss is disallowed for tax when the same name is bought within 30 days before or after the sale;
      the loss moves into the new shares' basis instead. ${esc(win.note || "")}</div>
    ${rows.length ? `<h3 style="margin:6px 0">Live windows</h3><div class="tscroll"><table>${rows.join("")}</table></div>`
                  : `<div class="note">No live windows: nothing sold at a loss in the last 30 days, and no recent buy is underwater.</div>`}
    <h3 style="margin:12px 0 6px">Past wash sales <span class="note">${w.past && w.past.length ? `${w.past.length}, ${money(w.disallowed_total)} disallowed in all` : "none found"}</span></h3>
    ${past.length ? `<div class="tscroll"><table>
      <tr><th scope=col>Sold</th><th scope=col>Symbol</th><th class=num scope=col>Loss</th><th class=num scope=col>Disallowed</th><th scope=col>Replacement bought</th></tr>
      ${past.map(r => `<tr><td>${esc(r.date)}</td><td><b>${esc(r.symbol)}</b></td><td class=num>${money(r.loss)}</td>
        <td class=num>${money(r.disallowed)}${r.partial ? ` <span class="note">partial</span>` : ""}</td><td class="note">${esc(r.replacement_dates.join(", "))}</td></tr>`).join("")}
    </table></div>` : ""}`;
}

var LAST_PERF = null;

// The holdings table, with what this trader trades on: how far each name is
// below its held peak, the app's call, and the next ladder rung as a price.
// The call comes from the Outlook payload, fetched once if the tab is opened
// first.
function renderHoldingsTable(data){
  const moves = {}; (data.position_moves || []).forEach(p => { moves[p.symbol] = p; });
  const rungCell = sym => `<span data-rung="${esc(sym)}">${rungText(sym)}</span>`;
  $("#holdings").innerHTML =
    `<tr><th scope=col>Symbol</th><th class=num scope=col>Shares</th><th class=num scope=col>Avg cost</th><th class=num scope=col>Price</th>
      <th class=num scope=col>Value</th><th class=num scope=col>Unrealised</th><th class=num scope=col>%</th><th class=num scope=col>Weight</th>
      <th class=num scope=col title="Below the highest price it has traded at since you first bought it — the same peak the broker's gain showed at the time">From peak</th>
      <th class=num scope=col title="The sell ladder's next rung as a price (rung 1 is 60% above the 50-day); later rungs are weekly RSI readings">Next rung</th>
      <th title="RonnieV's DCA ladder: how much of a SCHEDULED contribution to make this week, by how oversold the weekly is (1x normal, up to 4x at the floor). It sizes a buy you were making anyway; it is not a call, and it can read 3x on a name whose chart still reads hold. Approximation — his candle colours come from a tool he does not disclose" scope=col>DCA</th></tr>` +
    (data.holdings||[]).map(h=>`<tr class="clickable" data-sym="${esc(h.symbol)}">
      <td>${esc(h.symbol)}${h.price_basis!=="market"?` <span class="pill">${h.price_basis}</span>`:""}</td>
      <td class=num>${h.quantity.toLocaleString(undefined,{maximumFractionDigits:2})}</td>
      <td class=num>${money(h.avg_cost)}${basisPill(h)}</td>
      <td class=num>${money(h.price)}</td>
      <td class=num>${money(h.value)}</td>
      <td class=num style="${col(h.unrealised)}">${h.unrealised==null?"—":sign(h.unrealised)+money(Math.abs(h.unrealised)).slice(1)}</td>
      <td class=num style="${col(h.unrealised_pct)}">${pct(h.unrealised_pct)}</td>
      <td class=num>${(h.weight*100).toFixed(1)}%</td>
      <td class=num style="${moves[h.symbol] && moves[h.symbol].from_peak < -0.25 ? "color:var(--down)" : ""}">${moves[h.symbol] && moves[h.symbol].from_peak != null ? pct(moves[h.symbol].from_peak) : "—"}</td>
      <td class=num>${rungCell(h.symbol)}</td>
      <td>${h.dca ? `<span class="pill dca dca-${h.dca.multiplier}" title="Weekly Williams %R ${h.dca.williams_r != null ? Number(h.dca.williams_r).toFixed(0) : ""}: ${esc(h.dca.why)}. Sizes a scheduled contribution; not a call — approximation, not his signal">${h.dca.multiplier}x ${esc(h.dca.tier)}</span>` : "—"}</td></tr>`).join("") +
    `<tr><td><b>Total</b></td><td colspan=3></td><td class=num><b>${money(data.holdings_total)}</b></td><td colspan=6></td></tr>`;
}

// Where the cost came from. The payload has carried basis_source since the
// broker's basis was imported (broker_basis.py) and the page never said which
// figure it was showing — a number that silently changes meaning is worse than
// one that is merely wrong. Stale means the broker's share count no longer
// matches the ledger's, so FIFO is shown and the pill says why.
function basisPill(h){
  if(h.basis_source === "broker")
    return ` <span class="pill prov" title="Cost basis imported from the broker's statement, not FIFO">broker · as of ${esc(h.basis_as_of || "?")}</span>`;
  const st = h.basis_stale;
  if(st)
    return ` <span class="pill prov" style="color:var(--down)" title="The broker's basis as of ${esc(st.as_of || "?")} is for a different share count, so the FIFO figure is shown">FIFO — broker count ${Number(st.broker_qty).toLocaleString(undefined,{maximumFractionDigits:2})} ≠ ledger ${Number(st.ledger_qty).toLocaleString(undefined,{maximumFractionDigits:2})}</span>`;
  return "";
}

// The next rung as text, from the Outlook payload; "…" until it has loaded,
// then filled in place by paintVerdicts so the verdict column it appends is
// never wiped by a re-render.
function rungText(sym){
  const v = OUTLOOK && OUTLOOK.verdicts && OUTLOOK.verdicts[sym];
  const L = v && v.ladder; if(!L) return `<span class="note">${OUTLOOK ? "—" : "…"}</span>`;
  const r1 = L.rungs[0];
  if(L.stage === 0 && r1.level) return `${money(r1.level)} <span class="note">${r1.distance > 0 ? "+" : ""}${(r1.distance*100).toFixed(0)}%</span>`;
  const nxt = L.rungs.find(r => !r.fired);
  return nxt ? `<span class="note">rung ${nxt.n}: ${esc(nxt.name.replace("weekly RSI back under 70 after 80+", "RSI back under 70"))}</span>` : `<span class="note">ladder done</span>`;
}

function fillRungs(){
  document.querySelectorAll("#holdings [data-rung]").forEach(el => { el.innerHTML = rungText(el.dataset.rung); });
  applyPhoneColumns();   // the column may have just become all dashes, or stopped being
}

// What a ratio is actually saying. A number with no scale beside it is a number
// nobody can act on — 0.64 means nothing until you know that 1 is the usual bar.
// Bands are the conventional readings, not targets this app invented, and the
// verdict names where THIS book sits rather than where it ought to.
const RATIO_BANDS = {
  sharpe: {label:"Sharpe", bands:[[0,"below cash"],[1,"modest"],[2,"good"],[3,"very good"],[99,"exceptional"]],
    note:"Return above cash per unit of total volatility. Concentrated books usually sit under 1."},
  sortino: {label:"Sortino", bands:[[0,"below cash"],[1,"modest"],[2,"good"],[99,"very good"]],
    note:"Like Sharpe but only counts downside moves, so it is always the kinder of the two."},
  calmar: {label:"Calmar", bands:[[0.5,"weak"],[1,"fair"],[3,"good"],[99,"strong"]],
    note:"Growth per unit of worst drawdown. 1 means a year of gain matches the deepest fall."},
};

function bandFor(key, v){
  if(v == null) return null;
  const spec = RATIO_BANDS[key];
  for(const [ceil, word] of spec.bands) if(v < ceil) return word;
  return spec.bands[spec.bands.length-1][1];
}

function drawRatioGuide(r){
  if(!r) return;
  const rows = Object.keys(RATIO_BANDS).map(k=>{
    const v = r[k];
    const scale = RATIO_BANDS[k].bands.map(([c,w])=>w).join(" · ");
    return `<tr><td>${RATIO_BANDS[k].label}</td>
      <td class=num><b>${v==null?"—":v.toFixed(2)}</b></td>
      <td>${bandFor(k,v) || "—"}</td>
      <td class="note">${scale}</td></tr>`;
  }).join("");
  const b = r.benchmark || {};
  $("#ratioguide").innerHTML = `<div class="panel">
    <table><tr><th scope=col>Ratio</th><th class=num scope=col>You</th>
      <th scope=col>Reads as</th><th scope=col>Scale, low to high</th></tr>${rows}</table>
    <div class="note" style="margin-top:10px">
      Volatility <b>${pct(r.volatility)}</b> against the benchmark's
      <b>${pct(b.volatility)}</b>${b.beta!=null?`, beta <b>${b.beta.toFixed(2)}</b>`:""}.
      ${b.up_capture!=null && b.down_capture!=null ? `You capture
      <b>${b.up_capture.toFixed(2)}×</b> of up moves against
      <b>${b.down_capture.toFixed(2)}×</b> of down ones — the ratio between those two,
      <b>${(b.up_capture/b.down_capture).toFixed(2)}</b>, is the part that is not
      explained by simply taking more risk.` : ""}
    </div></div>`;
}

// Per holding: what it has handed back from its own high, which is a different
// question from unrealised P/L and the one the app could not previously answer.
function drawPositionMoves(rows){
  const el = $("#posmoves");
  if(!el) return;
  if(!rows || !rows.length){ el.innerHTML = `<div class="note">No price history to measure.</div>`; return; }
  const sign = v => v == null ? "—"
    : `<span style="color:${v>=0?'var(--up)':'var(--down)'}">${(v*100).toFixed(0)}%</span>`;
  const usd = v => v == null ? "—"
    : `<span style="color:${v<=0?'var(--up)':'var(--down)'}">${v<=0?"":"−"}${money(Math.abs(v))}</span>`;
  el.innerHTML = `<div class="note" style="margin-bottom:10px">
      <b>Peak</b> is the highest price the name has traded at since you first
      bought it — the intraday high, the figure the broker's gain showed at the
      time — not the highest in its history, which for several names here is
      years before you owned it. <b>From peak</b> is the price fall since then. <b>At peak</b> and
      <b>Now</b> are the gain on cost at that high and today, so the two together
      say what was handed back; <b>Given back</b> is the same in dollars on the
      shares you hold. Hover a peak to see the all-history high.</div>
    <table><tr><th scope=col>Symbol</th><th class=num scope=col>Price</th>
      <th class=num scope=col>Peak</th><th scope=col class="date">Peak on</th>
      <th class=num scope=col>From peak</th>
      <th class=num scope=col title="Gain on cost at the peak">At peak</th>
      <th class=num scope=col title="Gain on cost today">Now</th>
      <th class=num scope=col>Given back</th>
      <th class=num scope=col>1m</th><th class=num scope=col>3m</th>
      <th scope=col class="prose">Worth a look</th></tr>` +
    rows.map(r=>`<tr${r.notable?"":' class="dim"'}>
      <td>${esc(r.symbol)}</td>
      <td class=num>${money(r.price)}</td>
      <td class=num title="All-history high ${money(r.all_time_high)} on ${esc(r.all_time_high_date||"")}${
        r.held_since ? `; held since ${esc(r.held_since)}` : ""}">${money(r.peak)}</td>
      <td class="note date">${esc(r.peak_date||"")}</td>
      <td class=num>${sign(r.from_peak)}</td>
      <td class=num>${sign(r.gain_at_peak_pct)}</td>
      <td class=num>${sign(r.unrealised_pct)}</td>
      <td class=num>${usd(r.given_back_usd)}</td>
      <td class=num>${sign(r["1m"])}</td>
      <td class=num>${sign(r["3m"])}</td>
      <td class="note prose">${esc((r.notes||[]).join(" · "))}</td></tr>`).join("") + `</table>`;
}

// Mechanical exit rules replayed over real history with no lookahead. The
// caveats are rendered as prominently as the numbers, because this is the panel
// most able to talk somebody into a false conclusion.
// drawExitRules was removed 2026-09-06: it replayed each rule's first fire only and the
// sell ladder (Outlook, D72) replaced it.

function drawRisk(data){
  const k = data.risk || {};
  // Clear everything this function owns before deciding whether it can fill it.
  // drawRisk used to return early on insufficient data having written only
  // #riskcards, leaving the drawdown chart, risk table, concentration cards and
  // account table showing the PREVIOUS period directly beneath a "not enough
  // periods in this range" message.
  ["#ddchart","#ddinfo","#risktable","#riskcards","#conccards","#conctable",
   "#concnote","#acctrisk","#corrcards","#corrgrid","#corrnote"]
    .forEach(id => { const el = $(id); if(el) el.innerHTML = ""; });
  if(k.insufficient_data || !k.curve){ $("#riskcards").innerHTML =
    `<div class="card"><div class="k">Risk</div><div class="v">—</div>
     <div class="k">not enough periods in this range</div></div>`; return; }

  const w = k.worst_episode || {};
  $("#riskcards").innerHTML = `
    <div class="card"><div class="k">Max drawdown</div><div class="v down">${pct(k.max_drawdown)}</div>
      <div class="k" style="margin-top:4px">${w.peak_date||""} → ${w.trough_date||""}</div></div>
    <div class="card"><div class="k">Current drawdown</div>
      <div class="v ${k.current_drawdown < -0.01 ? "down":""}">${pct(k.current_drawdown)}</div>
      <div class="k" style="margin-top:4px">below the previous peak</div></div>
    <div class="card"><div class="k">Volatility</div><div class="v">${pct(k.volatility)}</div>
      <div class="k" style="margin-top:4px">annualised</div></div>
    <div class="card"><div class="k">Sharpe</div><div class="v ${k.sharpe>1?"up":""}">${k.sharpe==null?"—":k.sharpe.toFixed(2)}</div>
      <div class="k" style="margin-top:4px">vs ${pct(k.risk_free)} risk-free</div></div>
    <div class="card"><div class="k">Sortino</div><div class="v ${k.sortino>1?"up":""}">${k.sortino==null?"—":k.sortino.toFixed(2)}</div>
      <div class="k" style="margin-top:4px">downside risk only</div></div>
    <div class="card"><div class="k">Calmar</div><div class="v">${k.calmar==null?"—":k.calmar.toFixed(2)}</div>
      <div class="k" style="margin-top:4px">CAGR ÷ max drawdown</div></div>`;

  // Underwater curve: 0% at the top, so depth reads downward the way it feels.
  const el = $("#ddchart"); el.innerHTML = "";
  el.style.height = "160px";
  const th = chartTheme();
  // autoSize attaches a ResizeObserver, so clearing innerHTML leaves the chart
  // object and its observer alive on a detached node. Every Update leaked one.
  if(DD_CHART){ try{ DD_CHART.remove(); }catch(e){} DD_CHART = null; }
  const dc = DD_CHART = LightweightCharts.createChart(el, {
    height:160, autoSize:true,
    layout:{background:{color:"transparent"}, textColor:th.text, fontSize:11},
    grid:{vertLines:{color:"transparent"}, horzLines:{color:th.grid}},
    rightPriceScale:{borderColor:th.grid},
    timeScale:{borderColor:th.grid},
  });
  // Drawdown is the down-strong line with its fill fading from .25 at the
  // zero line to .05 at depth — the drawn shape is the depth, not a block.
  const area = dc.addAreaSeries({lineColor:th.downStrong, topColor:rgba(th.downStrong, .25),
    bottomColor:rgba(th.downStrong, .05), lineWidth:2, priceLineVisible:false,
    priceFormat:{type:"percent"}});
  area.setData(k.curve.map(p=>({time:p.date, value: p.drawdown*100})));
  dc.timeScale().fitContent();

  const rec = w.recovered_date
    ? `recovered ${w.recovered_date} after ${w.recovery_days} days`
    : `<b>not yet recovered</b>`;
  $("#ddinfo").innerHTML = `Worst episode ${pct(w.depth)} over ${w.days} days (${w.peak_date} → ${w.trough_date}), ${rec}.
    ${(k.positive_periods*100).toFixed(0)}% of weeks positive.
    Best week ${pct(k.best_period[1])} (${k.best_period[0]}), worst ${pct(k.worst_period[1])} (${k.worst_period[0]}).`;

  // ---- concentration ----
  const cc = data.concentration || {};
  if(cc.positions){
    $("#conccards").innerHTML = `
      <div class="card"><div class="k">Effective holdings</div><div class="v">${cc.effective_holdings}</div>
        <div class="k" style="margin-top:4px">of ${cc.positions} positions</div></div>
      <div class="card"><div class="k">Largest position</div><div class="v">${pct(cc.top1)}</div></div>
      <div class="card"><div class="k">Top 3</div><div class="v">${pct(cc.top3)}</div></div>
      <div class="card"><div class="k">Top 5</div><div class="v">${pct(cc.top5)}</div></div>`;
    $("#conctable").innerHTML =
      `<tr><th scope=col>Symbol</th><th class=num scope=col>Weight</th><th class=num scope=col>Share of risk</th>
        <th class=num scope=col>Risk ÷ weight</th><th class=num scope=col>Volatility (held)</th><th scope=col>Held since</th></tr>` +
      cc.rows.slice(0,12).map(r=>{
        const rw = r.risk_vs_weight;
        return `<tr class="clickable" data-sym="${esc(r.symbol)}">
          <td>${esc(r.symbol)}${r.history_predates_holding?' <span class="pill" title="Full-history volatility differs from the period you actually held it">short history</span>':''}</td>
          <td class=num>${pct(r.weight)}</td>
          <td class=num><b>${pct(r.risk_share)}</b></td>
          <td class=num style="${rw>1.5?"color:var(--down)":""}">${rw==null?"—":rw.toFixed(2)}×</td>
          <td class=num>${pct(r.volatility_held ?? r.volatility)}</td>
          <td class="note">${r.held_since||""}</td></tr>`;
      }).join("");
    const worst = cc.rows.filter(r=>r.risk_vs_weight>1.5).map(r=>r.symbol);
    const win = cc.window_periods && cc.range_periods && cc.window_periods < cc.range_periods
      ? ` Measured over the last ${cc.window_periods} sessions (from ${esc(cc.window_from || "")}), the stretch every holding here has prices for; a name with a short listing shortens the window for all of them.`
      : "";
    $("#concnote").innerHTML = win +
      `This portfolio behaves like <b>${cc.effective_holdings} equally-sized positions</b>, not ${cc.positions}.
       Share of risk accounts for each holding's volatility and its correlation with everything else, so it
       sums to 100% — weight alone understates a small, wild position.` +
      (worst.length ? ` <b>${worst.join(", ")}</b> carr${worst.length>1?"y":"ies"} well over ${worst.length>1?"their":"its"} weight in risk.` : "") +
      // What the shares do NOT cover. A holding with no price feed cannot have
      // a risk contribution computed, and giving it a fabricated 0% would rank
      // it as the safest thing you own.
      ((cc.unmeasured || []).length
        ? ` <b>${(cc.unmeasured_weight*100).toFixed(1)}% of the book is not in these figures</b> —
            ${cc.unmeasured.map(u=>`${esc(u.symbol)} (${(u.weight*100).toFixed(1)}%)`).join(", ")}
            ${cc.unmeasured.length>1?"have":"has"} no usable price history, so no risk share can be
            computed. The percentages above are shares of the measured book.`
        : "");
  }

  // ---- per-account risk ----
  $("#acctrisk").innerHTML =
    `<tr><th scope=col>Account</th><th class=num scope=col>Value</th><th class=num scope=col>Max drawdown</th>
      <th class=num scope=col>Now</th><th class=num scope=col>Volatility</th><th class=num scope=col>CAGR</th></tr>` +
    (data.account_risk||[]).map(a=>`<tr>
      <td>${esc(a.account)}${a.at_cost?` <span class="pill" title="${esc(a.note||"")}">at cost</span>`:""}</td>
      <td class=num>${money(a.value)}</td>
      <td class=num style="color:var(--down)">${pct(a.max_drawdown)}</td>
      <td class=num style="${col(a.current_drawdown)}">${pct(a.current_drawdown)}</td>
      <td class=num>${a.volatility==null?"—":pct(a.volatility)}</td>
      <td class=num style="${col(a.cagr)}">${a.cagr==null?"—":pct(a.cagr)}</td></tr>`).join("") +
    // An account valued at contributions never moves with the market, so its
    // volatility collapses and Sharpe explodes. Say why the cells are blank.
    ((data.account_risk||[]).some(a=>a.at_cost)
      ? `<tr><td colspan=6 class="note">An account marked <b>at cost</b> reports no
         tickers, so its value is contributions rather than market value. Risk
         figures are withheld for it — they would describe the contribution
         schedule, not the investments.</td></tr>` : "");

  const b = k.benchmark;
  $("#risktable").innerHTML = b ? `
    <tr><th scope=col>Versus ${b.label}</th><th class=num scope=col>You</th><th class=num scope=col>${b.symbol}</th><th scope=col>Reading</th></tr>
    <tr><td>Volatility (annualised)</td><td class=num>${pct(k.volatility)}</td><td class=num>${pct(b.volatility)}</td>
        <td class="note">${(k.volatility/b.volatility).toFixed(1)}× as volatile</td></tr>
    <tr><td>Beta</td><td class=num colspan=2>${b.beta==null?"—":b.beta.toFixed(2)}</td>
        <td class="note">${b.beta>1?"moves more than":"moves less than"} the index</td></tr>
    <tr><td>Alpha (annualised)</td><td class=num colspan=2 style="${col(b.alpha)}">${pct(b.alpha)}</td>
        <td class="note">return beyond what beta alone predicts</td></tr>
    <tr><td>Up capture</td><td class=num colspan=2>${b.up_capture==null?"—":b.up_capture.toFixed(2)}</td>
        <td class="note">share of the index's gains you caught</td></tr>
    <tr><td>Down capture</td><td class=num colspan=2>${b.down_capture==null?"—":b.down_capture.toFixed(2)}</td>
        <td class="note">share of its losses you took — lower is better</td></tr>` : "";
}

// The performance request as load() would send it. One place, so init can
// tell whether the payload it fetched at boot is the one load() is about to
// ask for again.
function perfQuery(){
  const bm = [...$("#bm").selectedOptions].map(o=>o.value).join(",") || "SPY";
  return new URLSearchParams({from:$("#from").value, to:$("#to").value, scope:$("#scope").value, benchmarks:bm});
}

// {key, promise}: a /api/performance response already in flight at boot.
let PERF_BOOT = null;

async function load(){
  // Changing period, scope or benchmark invalidates every derived tab. Clearing
  // the set alone was not enough: ensureTab only fires from showTab, so the tab
  // you were LOOKING AT kept the previous period's numbers — a "not enough data
  // in this range" card sitting directly above a full drawdown chart for the
  // whole history, with nothing to distinguish them.
  TAB_LOADED.clear();
  $("#go").disabled = true; $("#go").textContent = "Loading…";
  const q = perfQuery();
  try{
    // Boot may already hold this exact payload (see init): the bare request it
    // made for bounds and symbols IS the all-time default, and a saved custom
    // range was fired alongside it. Used once, then forgotten, so Update
    // always fetches.
    const cached = PERF_BOOT && PERF_BOOT.key === q.toString() ? PERF_BOOT.promise : null;
    PERF_BOOT = null;
    const data = await (cached || fetch("/api/performance?"+q).then(r => r.json()));
    if(data.error){ $("#alert").innerHTML = `<div class="warn">${esc(data.error)}</div>`; return; }
    const s = data.summary;

    // An empty ledger renders a dashboard of zeroes, which is accurate and
    // tells a new user nothing. This is the first screen after a fresh clone,
    // so it has to say what is missing and what to do about it.
    if(!s.transactions){
      $("#alert").innerHTML = `<div class="warn"><b>No data yet.</b>
        This is a working install with an empty ledger — every figure below is zero because nothing has been imported.
        Use <b>Get started</b> below: export your activity from your broker, bank or card issuer, drop the files in, add a free price key, reload.
        The command-line route is in <b>SETUP.md</b>: files go in <code>data/</code>, then <code>./update.sh</code>.</div>`;
      openGetStarted(true);
      // Deliberately NOT an early return. Returning here skipped every
      // remaining render, which left the Trades tab with literally zero
      // characters in it — swapping one confusing empty screen for another.
      // Everything below renders honest zeroes and its own empty state.
    } else

    $("#alert").innerHTML = s.complete ? "" : `<div class="warn"><b>Returns withheld.</b> ${
      s.anchored ? `Only ${s.priced_securities} of ${s.held_securities} holdings could be priced — an unpriced holding counts as zero, which would make these figures wrong rather than merely rough.`
                 : `The opening portfolio is unknown: this range starts before the first transaction on record (${s.first_transaction}).`}</div>`;

    // Appended AFTER the assignment above, which would otherwise overwrite it.
    // An unclassified row carrying cash is not cosmetic: "other" is not an
    // external flow, so the money is never stripped out and reads as
    // investment performance.
    if(s.unclassified_rows){
      $("#alert").insertAdjacentHTML("beforeend",
        `<div class="warn"><b>${s.unclassified_rows} rows carrying
         ${money(s.unclassified_cash)} could not be classified.</b> Unclassified
         cash is not stripped out as a deposit or withdrawal, so it reads as
         investment performance. Seen: ${esc((s.unclassified_actions||[]).join("; "))}</div>`);
    }

    renderNetWorth(data.networth);
    // The day change and the dollar gain sit under the figures they qualify.
    // A value with no "since yesterday" and a return with no dollar figure
    // were the first two things the September review asked for.
    const day = s.day || {};
    const dayLine = day.change_usd == null ? "" :
      `<div class="k" style="margin-top:4px"><span style="color:${day.change_usd>=0?'var(--up)':'var(--down)'}">${
        day.change_usd>=0?"+":"−"}${money(Math.abs(day.change_usd))}${
        day.change_pct!=null ? ` (${day.change_pct>=0?"+":""}${(day.change_pct*100).toFixed(2)}%)` : ""}</span> on ${esc(day.date||"")}${
        day.flow ? ` · ${money(Math.abs(day.flow))} ${day.flow>0?"deposited":"withdrawn"} that day, excluded` : ""}</div>`;
    const gainLine = (s.complete && s.gain_usd != null) ?
      `<div class="k" style="margin-top:4px">${s.gain_usd>=0?"+":"−"}${money(Math.abs(s.gain_usd))} earned over the range — value, less what you put in</div>` : "";
    $("#cards").innerHTML = `
      <div class="card"><div class="k">Value</div><div class="v">${money(s.end_value)}</div>${dayLine}</div>
      <div class="card"><div class="k">Net deposits</div><div class="v">${money(s.net_external_flow)}</div></div>
      <div class="card" title="How the investing did, with the timing of your deposits taken out. The number to compare with an index or with another investor."><div class="k">Time-weighted return</div><div class="v ${s.complete&&s.twr>0?"up":s.complete?"down":""}">${s.complete?pct(s.twr):"—"}</div>${gainLine}<div class="k" style="margin-top:4px">the investing, deposit timing taken out — compare this with the index</div></div>
      <div class="card" title="Your own experience: the return on the dollars you actually had in, when you had them in. Modified Dietz approximation. Lower than time-weighted when money went in before a fall or after a rise."><div class="k">Money-weighted return</div><div class="v ${s.complete&&s.modified_dietz>0?"up":s.complete?"down":""}">${s.complete?pct(s.modified_dietz):"—"}</div><div class="k" style="margin-top:4px">your dollars, when you had them in (Modified Dietz) — what you actually earned</div></div>`;

    draw(data);
    drawRisk(data);
    drawRatioGuide(data.risk);
    drawPositionMoves(data.position_moves);
    fillSymbolPicker(data);
    buildAttention(data);
    augmentAttention();
    renderAlerts(data);
    loadPlans();
    // Fire and forget: the verdict layer is the slow payload here and the
    // rest of the page must not wait on it.
    loadOutlook();
    drawCorrelation(data);
    loadSectors(data);
    const fr = s.freshness || {};
    const scoredAt = fr.scored_at ? fr.scored_at.replace("T", " ").slice(0, 16) : null;
    $("#asof").textContent = `${s.start} → ${s.end} · ${s.transactions.toLocaleString()} transactions`
      + (fr.prices_to ? ` · prices to ${fr.prices_to}` : "")
      + (fr.scored_for ? ` · last scored ${fr.scored_for}${scoredAt ? ` at ${scoredAt}` : ""}` : "");
    // Verdicts older than the prices is the one freshness gap worth a banner:
    // the page carries today's date while every call on it is from before.
    if(fr.prices_to && fr.scored_for && fr.scored_for < fr.prices_to){
      $("#alert").insertAdjacentHTML("beforeend",
        `<div class="warn"><b>The nightly scoring has not run for ${esc(fr.prices_to)}.</b>
         Prices are current to that date, but every verdict on the Outlook tab is from
         ${esc(fr.scored_for)}. It runs at 18:30 after the close; <code>./update.sh</code> runs it now.</div>`);
    }

    $("#bench").innerHTML =
      `<tr><th scope=col>Benchmark</th><th scope=col></th><th class=num scope=col>Index</th><th class=num scope=col>You</th>
        <th class=num scope=col>Difference</th><th class=num scope=col>In dollars</th></tr>` +
      (s.benchmarks||[]).map(b=>{
        if(b.error) return `<tr><td>${b.symbol}</td><td colspan=5>${b.error}</td></tr>`;
        const f = b.same_cashflow ? b.same_cashflow.final_value : null;
        return `
        <tr><td rowspan="2">${b.label}${b.timing_disagrees?' <span class="pill">timing</span>':''}</td>
            <td><span class="pill">time-weighted</span><br><span style="font-size:11px;color:var(--muted)">ignores when you added money</span></td>
            <td class=num>${pct(b.return)}</td><td class=num>${pct(s.twr)}</td>
            <td class=num style="${col(b.tw_delta)}">${pct(b.tw_delta)}</td><td class=num>—</td></tr>
        <tr><td><span class="pill">money-weighted</span><br><span style="font-size:11px;color:var(--muted)">accounts for when you added money</span></td>
            <td class=num>${pct(b.mw_benchmark)}</td><td class=num>${pct(b.mw_you)}</td>
            <td class=num style="${col(b.mw_delta)}">${pct(b.mw_delta)}</td>
            <td class=num style="${col(b.dollar_delta)}">${money(f)}<br>
              <span style="font-size:12px">${b.dollar_delta==null?"":(b.dollar_delta>0?"+":"−")+money(Math.abs(b.dollar_delta)).slice(1)}</span></td></tr>`;
      }).join("");
    const disagree = (s.benchmarks||[]).filter(b=>b.timing_disagrees).map(b=>b.symbol);
    $("#timing").innerHTML = disagree.length
      ? `<b>The two rows disagree for ${disagree.join(", ")}.</b> Time-weighted says your picks beat
         the index over the same days. Money-weighted says the index would have ended with more
         dollars, because more of your money was invested during the weaker stretch.
         Selection worked; timing did not.` : "";
    // Cash is derived from the flows, not read from a position: the core fund
    // sweep is never exported, so the share count is only the reinvested
    // interest. An unanchored figure is only as complete as the imported
    // history, which is worth saying rather than presenting as fact.
    $("#accts").innerHTML = `<tr><th scope=col>Account</th><th scope=col>Tax</th>
        <th class=num scope=col title="Core money-market balance, derived from cash flows">Cash</th>
        <th class=num scope=col>Value</th></tr>` +
      (data.per_account||[]).map(a=>{
        const note = a.cash_impossible
          ? ` <span class="pill" title="A cash balance cannot be negative. The imported history does not reach back to when this account was funded, so this is a floor, not a balance.">incomplete</span>`
          : (a.cash_anchored ? ` <span class="pill" title="Anchored to a statement balance you entered.">anchored</span>` : "");
        return `<tr><td>${esc(a.name)}</td><td><span class="pill">${esc(a.tax_status)}</span></td>
        <td class=num>${money(a.cash)}${note}</td>
        <td class=num>${money(a.value)}</td></tr>`;
      }).join("");

    LAST_PERF = data;
    renderHoldingsTable(data);

    // The tier is this app's stand-in, not his signal, and the table must say so
    // where it is read rather than only in the Research tab.
    if((data.holdings||[]).some(h=>h.dca))
      $("#holdings").insertAdjacentHTML("afterend",
        `<div class="note" style="margin-top:6px"><b>Call and DCA answer different questions.</b> The call is
         what the chart says to do at this price; the DCA tier is how much of a contribution you were
         already going to make this week (RonnieV's ladder: 1x white, 2x amber, 3x lime green, 4x purple, by how
         oversold the weekly Williams %R is). A name can read <b>hold</b> with a <b>3x</b> tier: the
         short-term chart is weak, and that weakness is exactly when the ladder scales a scheduled buy up.
         What colours his candles is proprietary, so the tier here is derived from Williams %R at his settings —
         an approximation, not his signal.</div>`);

    const att = (data.attribution||{});
    $("#attrib").innerHTML =
      `<tr><th scope=col>Symbol</th><th class=num scope=col>Unrealised change</th><th class=num scope=col>Realised</th><th class=num scope=col>Contribution</th></tr>` +
      [...(att.top||[]), ...(att.bottom||[])].map(a=>`<tr>
        <td>${a.symbol}</td>
        <td class=num>${money(a.unrealised_change)}</td>
        <td class=num>${money(a.realised)}</td>
        <td class=num style="${col(a.contribution)}"><b>${sign(a.contribution)+money(Math.abs(a.contribution)).slice(1)}</b></td></tr>`).join("");

    // ---- trade record ----
    // The Trades tab rendered literally zero characters on an empty ledger.
  // "A tab that toggles but renders nothing" is the exact failure the browser
  // test exists to catch, and it only ever ran against a ledger with data.
  if(!((data.trades||{}).closed||[]).length && !((data.trades||{}).open||[]).length){
    $("#tradecount").innerHTML = `No closed trades yet. Round trips appear here
      once a position has been both opened and closed in the imported history.`;
  }
  renderWash(data.wash);
  renderEmailTrades(data.email_trades);
  const ts = (data.trades||{}).stats || {};
    if(ts.count){
      $("#tradecards").innerHTML = `
        <div class="card"><div class="k">Win rate</div><div class="v">${(ts.win_rate*100).toFixed(1)}%</div>
          <div class="k" style="margin-top:4px">${ts.wins}W / ${ts.losses}L</div></div>
        <div class="card"><div class="k">Profit factor</div><div class="v ${ts.profit_factor>1?"up":"down"}">${ts.profit_factor?ts.profit_factor.toFixed(2):"—"}</div>
          <div class="k" style="margin-top:4px">won per $1 lost</div></div>
        <div class="card"><div class="k">Expectancy</div><div class="v ${ts.expectancy>0?"up":"down"}">${money(ts.expectancy)}</div>
          <div class="k" style="margin-top:4px">per trade</div></div>
        <div class="card"><div class="k">Payoff ratio</div><div class="v">${ts.payoff_ratio?ts.payoff_ratio.toFixed(2):"—"}</div>
          <div class="k" style="margin-top:4px">avg win ${money(ts.avg_win)} / loss ${money(ts.avg_loss)}</div></div>
        <div class="card"><div class="k">Net realised</div><div class="v ${ts.net>0?"up":"down"}">${money(ts.net)}</div>
          <div class="k" style="margin-top:4px">${ts.count} closed trades</div></div>`;
      const allTrades = data.trades.recent || [];
      // The result says where a trade ended; Worst and Best say what it did on
      // the way, which is what decides whether you could sit through it.
      const rough = allTrades.filter(t => t.win && t.mae_pct != null && t.mae_pct < -0.2).length;
      const wins = allTrades.filter(t => t.win).length;
      $("#tradecount").innerHTML = !allTrades.length ? "" :
        `${allTrades.length} closed round trips, newest first.` +
        (rough ? ` <b>${rough} of your ${wins} winners were once more than 20% underwater</b> —
          Worst and Best are measured from your average entry, against split-adjusted prices.` : "");
      $("#trades").innerHTML =
        `<tr><th scope=col>Exited</th><th scope=col>Symbol</th><th scope=col></th><th class=num scope=col>P/L</th><th class=num scope=col>%</th>
          <th class=num title="Furthest this trade went AGAINST you while open, from your average entry" scope=col>Worst</th>
          <th class=num title="Furthest it went FOR you while open — the part you left on the table" scope=col>Best</th>
          <th class=num scope=col>Held</th><th class=num scope=col>Fills</th></tr>` +
        (data.trades.recent||[]).map((t,i)=>`<tr class="clickable" data-sym="${t.symbol}" data-trade="${i}">
          <td>${t.exit_date}</td><td>${t.symbol} <span style="color:var(--muted)">▸</span></td>
          <td><span class="pill" style="color:${t.win?"var(--up)":"var(--down)"}">${t.win?"win":"loss"}</span></td>
          <td class=num style="${col(t.pnl)}">${sign(t.pnl)+money(Math.abs(t.pnl)).slice(1)}</td>
          <td class=num style="${col(t.pnl)}">${pct(t.pnl_pct)}</td>
          <td class=num style="${col(t.mae_pct)}" title="${t.mae==null?"":"$"+money(Math.abs(t.mae)).slice(1)+" at its worst"}">${t.mae_pct==null?"—":pct(t.mae_pct)}</td>
          <td class=num style="${col(t.mfe_pct)}" title="${t.mfe==null?"":"$"+money(Math.abs(t.mfe)).slice(1)+" at its best"}">${t.mfe_pct==null?"—":pct(t.mfe_pct)}</td>
          <td class=num>${t.held_days}d</td><td class=num>${t.fills}</td></tr>`).join("");
    }

    TRADES = data.trades.recent || [];
    LAST_HOLDINGS = data.holdings || [];

    const stale = s.stale_valued || {};
    const keys = Object.keys(stale);
    $("#note").innerHTML = [
      keys.length ? `${keys.join(", ")} have no market feed and are valued at the price you last traded them (${money(s.stale_value_total)}, ${(s.stale_share_of_value*100).toFixed(1)}% of the portfolio).` : "",
      (s.merged_subperiods ? `${s.merged_subperiods} early sub-periods merged — the account was too small next to incoming deposits to divide by safely.` : ""),
      `Benchmarks are price indices and exclude dividends, so they understate the real index by roughly the dividend yield.`
    ].filter(Boolean).join(" ");
  }catch(e){ $("#alert").innerHTML = `<div class="warn">${e}</div>`; }
  finally{
    $("#go").disabled = false; $("#go").textContent = "Update";
    // Re-run the loader for the view actually on screen. TAB_LOADED.clear()
    // above only marks the others dirty for the next visit; without this the
    // panel you are looking at keeps the previous period's numbers.
    ensureTab(curView());
  }
}

function drawCorrelation(data){
  // Same early-return trap as drawRisk: clearing only the cards left the old
  // heatmap and its explanation sitting under the new "not enough data".
  ["#corrgrid","#corrnote"].forEach(id => { const el = $(id); if(el) el.innerHTML = ""; });
  const c = data.correlation || {};
  if(!c.symbols || c.symbols.length < 2){ $("#corrcards").innerHTML = ""; return; }
  const n = c.symbols.length;
  $("#corrcards").innerHTML = `
    <div class="card"><div class="k">Average correlation</div><div class="v">${c.average.toFixed(2)}</div>
      <div class="k" style="margin-top:4px">across ${n} largest holdings</div></div>
    <div class="card"><div class="k">Value-weighted</div><div class="v">${c.weighted_average.toFixed(2)}</div>
      <div class="k" style="margin-top:4px">what your money actually experiences</div></div>
    <div class="card"><div class="k">Correlated groups</div><div class="v">${c.clusters.length}</div>
      <div class="k" style="margin-top:4px">at r ≥ ${c.threshold}</div></div>`;

  // Heatmap. Red = moves together, blue = moves apart; the diagonal is dropped
  // because a thing correlating with itself carries no information.
  // Stepped rather than a single hue at varying transparency, which read as
  // one shade of pink across the whole grid. Five bands, and the text colour
  // follows the band so the number is always legible.
  const shade = r => r == null ? ["var(--bg-2)", "var(--muted)"]
    : r >= 0.8 ? ["var(--down-strong)", "#fff"]
    : r >= 0.6 ? ["rgba(242,54,69,.55)", "var(--text)"]
    : r >= 0.3 ? ["rgba(242,54,69,.22)", "var(--text)"]
    : r > -0.3 ? ["var(--bg-2)", "var(--muted)"]
    : r > -0.6 ? ["rgba(41,98,255,.22)", "var(--text)"]
    : ["var(--accent-fill)", "#fff"];
  let html = `<div class="cgrid" style="grid-template-columns:64px repeat(${n},minmax(26px,1fr))">`;
  html += `<div></div>` + c.symbols.map(s2=>`<div class="chead">${s2}</div>`).join("");
  c.symbols.forEach((row,i)=>{
    html += `<div class="rhead">${row}</div>`;
    c.symbols.forEach((colS,j)=>{
      const r = i===j ? null : c.matrix[i][j];
      const [bg, fg] = shade(r);
      html += `<div class="cell" title="${row} / ${colS}: ${r==null?"—":r.toFixed(2)}"
        style="background:${bg};color:${fg}">${r==null?"":(r>=0?"":"−")+Math.abs(r).toFixed(1).slice(1)}</div>`;
    });
  });
  $("#corrgrid").innerHTML = html + "</div>" + `<div class="legend" style="margin-top:8px">
    <span><i style="background:var(--down-strong)"></i>0.8 and up: move as one</span>
    <span><i style="background:rgba(242,54,69,.55)"></i>0.6 to 0.8: move together</span>
    <span><i style="background:rgba(242,54,69,.22)"></i>0.3 to 0.6: lean together</span>
    <span><i style="background:var(--bg-2);border:1px solid var(--line)"></i>−0.3 to 0.3: unrelated</span>
    <span><i style="background:rgba(41,98,255,.22)"></i>below −0.3: move apart</span></div>`;

  const topPair = (c.most_correlated||[])[0];
  const multi = (c.clusters||[]).filter(x=>x.members.length>1);
  $("#corrnote").innerHTML =
    `Average pairwise correlation is <b>${c.average.toFixed(2)}</b> over ${c.periods} weekly periods. ` +
    (multi.length
      ? `These move together and are effectively one bet: ` +
        multi.map(x=>`<b>${x.members.join(" + ")}</b> (${pct(x.weight)})`).join("; ") + "."
      : `Nothing pairs above r ≥ ${c.threshold}, so the holdings are genuinely distinct bets — ` +
        `the low effective-holdings figure comes from <b>position size</b>, not from names moving together.`) +
    (topPair ? ` Most correlated pair: ${topPair.a} / ${topPair.b} at ${topPair.r.toFixed(2)}.` : "");
}

// Expand one round trip into the individual fills that made it up. A single
// row saying "LMND +$14,570 over 56 fills" hides the decisions inside it; this
// shows whether the position was built well or averaged down into.
let FILL_REQUEST = 0;

async function showFills(trade){
  if(!trade) return;
  const panel = $("#fillpanel");
  panel.style.display = "";
  panel.innerHTML = loadingHTML(`Loading fills for ${trade.symbol}…`);
  const q = new URLSearchParams({symbol:trade.symbol, scope:$("#scope").value,
                                 from:trade.entry_date, to:trade.exit_date||$("#to").value,
                                 indicators:""});
  // showFills has the same overtaking problem as loadChart: click two trades
  // quickly and the slower response paints into a panel already showing the
  // other one. Its own token.
  const fillToken = ++FILL_REQUEST;
  const res = await fetch("/api/chart?" + q);
  if(fillToken !== FILL_REQUEST) return;
  const d = await res.json();
  if(fillToken !== FILL_REQUEST) return;
  const fills = (d.marks||[]).filter(m => m.date >= trade.entry_date &&
                                          m.date <= (trade.exit_date||"9999"));
  let runQty = 0, runCost = 0;
  const rows = fills.map(f=>{
    if(f.side === "buy"){ runQty += f.qty; runCost += f.value; }
    else { const avg = runQty ? runCost/runQty : 0; runCost -= avg*f.qty; runQty -= f.qty; }
    const avg = runQty > 1e-9 ? runCost/runQty : null;
    return `<tr><td>${f.date}</td>
      <td><span class="pill" style="color:${f.side==="buy"?"var(--up)":"var(--down)"}">${f.side}</span></td>
      <td class=num>${f.qty.toLocaleString()}</td>
      <td class=num>${money(f.price)}</td>
      <td class=num>${money(f.value)}</td>
      <td class=num>${runQty>1e-9?runQty.toLocaleString(undefined,{maximumFractionDigits:2}):"flat"}</td>
      <td class=num>${avg?money(avg):"—"}</td></tr>`;
  }).join("");
  panel.innerHTML = `
    <div style="display:flex;flex-wrap:wrap;gap:16px;align-items:baseline;margin-bottom:10px">
      <b>${trade.symbol}</b>
      <span class="pill" style="color:${trade.win?"var(--up)":"var(--down)"}">${trade.win?"win":"loss"}</span>
      <span class="note">${trade.entry_date} → ${trade.exit_date||"open"} · ${trade.held_days}d ·
      bought ${money(trade.bought)} · sold ${money(trade.sold)} ·
      <b style="${col(trade.pnl)}">${moneyDelta(trade.pnl)} (${pct(trade.pnl_pct)})</b></span>
    </div>
    <div class="tscroll"><table>
      <tr><th scope=col>Date</th><th scope=col>Side</th><th class=num scope=col>Qty</th><th class=num scope=col>Price</th>
          <th class=num scope=col>Value</th><th class=num scope=col>Position after</th><th class=num scope=col>Avg cost</th></tr>
      ${rows}</table></div>`;
}

// Net worth: what you own minus what you owe. Both halves of this app finally
// in one number — investments, bank cash, and card debt, which only became
// knowable once the card exports were imported.
function renderNetWorth(n){
  const el = $("#networth");
  if(!el) return;
  if(!n || n.error || !n.points || !n.points.length){
    el.innerHTML = `<div class="panel note">${esc((n && n.error) || "Not enough data yet.")}</div>`;
    return;
  }
  const last = n.latest, pts = n.points;
  const s12 = n.savings_12m || n.savings || {};
  const rate = s12.rate == null ? "—" : (s12.rate * 100).toFixed(0) + "%";

  // Same geometry as the portfolio chart above it: padded, gridded, and tall
  // enough to read. It used to be a 900x150 viewBox stretched to full width
  // with preserveAspectRatio="none", which squashed two years into a 6:1 strip
  // where a $17k month and a $170k one looked much the same.
  const vals = pts.map(p => p.net);
  const lo = Math.min(...vals, 0), hi = Math.max(...vals);
  const narrowNw = ($("#nwchart") && $("#nwchart").clientWidth || 900) < 600;
  const W = narrowNw ? 480 : 900, H = narrowNw ? 280 : 240, PAD = 34;
  const inner = W - PAD*2, ih = H - PAD*2;
  const nwSets = [{name:"Net worth", pts:vals, color:"var(--accent)", dash:false}];
  let grid = "";
  const nwLabels = [];
  for(let i=0;i<=4;i++){
    const y = PAD + (ih/4)*i, v = hi - ((hi-lo)/4)*i;
    grid += `<line x1="${PAD}" y1="${y}" x2="${W-PAD}" y2="${y}" stroke="var(--grid)" stroke-width="1"/>`;
    nwLabels.push({x:4, y, text:`$${Math.round(v/1000)}k`});
  }
  nwLabels.push({x:PAD, y:H-16, text:pts[0].date, bottom:true}, {x:W-PAD, y:H-16, text:last.date, bottom:true, end:true});
  const zeroY = PAD + (ih - ((0 - lo) / ((hi - lo) || 1)) * ih);

  el.innerHTML = `
  <div class="cards">
    <div class="card"><div class="k">Net worth</div><div class="v">${money(last.net)}</div>
      <div class="note">${n.change != null
        ? `${n.change >= 0 ? "up" : "down"} ${money(Math.abs(n.change))} since ${esc(pts[0].date)}`
        : ""}</div></div>
    <div class="card"><div class="k">Investments</div><div class="v">${money(last.investments)}</div>
      <div class="note">positions and cash held at the brokers</div></div>
    <div class="card"><div class="k">Bank cash</div><div class="v">${money(last.cash)}</div>
      <div class="note">${n.understated_by > 0
        ? "a floor — see below" : "checking and savings"}</div></div>
    <div class="card"><div class="k">Card debt</div><div class="v">${money(last.debt)}</div>
      <div class="note">charged and not yet paid</div></div>
    <div class="card"><div class="k">Saved</div><div class="v">${rate}</div>
      <div class="note">of income, last 12 months${s12.saved != null
        ? ` · ${money(s12.saved)}` : ""}</div></div>
  </div>

  <div class="panel" id="nwchart">
    <div class="svgbox"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Net worth over time">
      ${grid}
      ${lo < 0 ? `<line x1="${PAD}" y1="${zeroY.toFixed(1)}" x2="${W-PAD}" y2="${zeroY.toFixed(1)}"
        stroke="var(--down)" stroke-width="1" stroke-dasharray="4 4"/>` : ""}
      <g transform="translate(${PAD},${PAD})">${line(vals, inner, ih, lo, hi, "var(--accent)")}</g>
      <g id="nwhair" style="display:none;pointer-events:none">
        <line y1="${PAD}" y2="${H-PAD}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>
        <circle r="4" fill="var(--bg-1)" stroke="var(--accent)" stroke-width="2" data-dot="0"/>
      </g>
    </svg></div>
  </div>

  ${n.understated_by > 0 ? `
  <div class="panel" style="border-left:3px solid var(--warn)">
    <b>The real figure is at least ${money(n.understated_by)} higher than this.</b>
    <div class="note">
      ${n.understated_accounts.map(a =>
        `<b>${esc(a.account)}</b> derives a balance below zero, which no account can
         hold — its imported history does not reach back to when it was funded, so
         its opening balance is missing and every figure above is short by at least
         ${money(a.short_by)}.`).join(" ")}
      Entering that account's balance from a statement, on a date, would fix every
      number here at once.
    </div>
  </div>` : ""}

  ${n.card_history_from ? `<div class="note">Card debt is a running total of charges
    minus payments, so it is only as complete as the exports behind it — card history
    here begins ${esc(n.card_history_from)}, and anything owed before that reads as
    zero.</div>` : ""}`;

  // The same crosshair as the portfolio chart. Net worth is the number this
  // whole app exists to produce, and "what was it worth in March" was
  // unanswerable from a picture of it.
  axisLabels($("#nwchart .svgbox"), W, H, nwLabels);
  attachReadout($("#nwchart"), {
    W, H, PAD, inner, ih, min: lo, max: hi,
    hairId: "nwhair", tipId: "nwtip",
    dates: pts.map(p => p.date), sets: nwSets,
    footer: (i) => {
      const p0 = pts[i];
      return `investments ${money(p0.investments)} · cash ${money(p0.cash)}`
           + (p0.debt ? ` · card debt ${money(p0.debt)}` : "")
           + (p0.partial ? " · partial" : "");
    },
  });
}

// Exposure and rotation on the SAME row. Three panels — themes, sectors, and
// a separate rotation table — was the "too much on the page" the September
// review named; what anyone wants to read is one line per theme saying how
// much of the book is in it and whether it is leading or lagging the market.
let ROTATION = null, SECTOR_DATA = null;

async function loadSectors(data){
  SECTOR_DATA = data;
  const th = (data && data.theme_exposure) || [];
  const exp = (data && data.sector_exposure) || [];
  if(!ROTATION){
    try{ ROTATION = await (await fetch("/api/rotation")).json(); }
    catch(e){ ROTATION = {error: "rotation unavailable"}; }
  }
  const r = ROTATION || {};
  const w = r.windows || [];
  const names = {21:"1M", 63:"3M", 126:"6M", 252:"12M"};
  const rsHead = w.map(x=>`<th class=num scope=col title="Return against the market over this window">${names[x]||x+"d"}</th>`).join("")
    + `<th class=num scope=col title="Average of the windows">Avg</th><th scope=col></th>`;
  const rsCells = row => !row ? `<td class=num colspan="${w.length+2}" class="note">—</td>`
    : w.map(x=>`<td class=num style="${col(row.relative[x])}">${pct(row.relative[x])}</td>`).join("")
      + `<td class=num style="${col(row.score)}"><b>${pct(row.score)}</b></td>
         <td>${row.persistent?`<span class="pill" style="color:var(--up)">leading</span>`:""}</td>`;

  // Themes: every theme with money in it, plus every theme that has a fund
  // even if nothing is held — a theme leading the market that you own none
  // of is worth a row.
  const byTheme = {};
  (r.themes || []).forEach(t => { byTheme[t.key] = t; });
  const held = new Set(th.map(t=>t.theme));
  const rows = th.map(t => ({...t, rs: byTheme[t.theme]}))
    .concat((r.themes || []).filter(t => !held.has(t.key))
      .map(t => ({theme: t.key, label: t.theme, weight: 0, value: 0, symbols: [], rs: t})));
  $("#themeexp").innerHTML =
    `<tr><th scope=col>Theme</th><th class=num scope=col>Weight</th><th scope=col>Holdings</th>
      <th scope=col title="The fund the theme is measured by">Fund</th>${rsHead}</tr>` +
    rows.map(t=>`<tr${t.weight ? "" : ' class="dim"'}><td>${esc(t.label)}</td>
      <td class=num>${t.weight ? `<b>${pct(t.weight)}</b>` : "—"}</td>
      <td class="note">${t.symbols.join(", ") || (t.via_funds && t.via_funds.length ? "" : "none held")}${t.via_funds && t.via_funds.length ? `${t.symbols.length ? ", " : ""}<span title="${esc(t.lookthrough_note || "")}">via ${esc(t.via_funds.join(", "))}</span>` : ""}</td>
      <td class="note">${t.rs ? esc(t.rs.symbol) : "—"}</td>${rsCells(t.rs)}</tr>`).join("");
  const topTheme = th[0];
  const leadThemes = (r.themes || []).filter(t=>t.persistent).map(t=>t.theme);
  $("#themenote").innerHTML =
    (topTheme ? `<b>${pct(topTheme.weight)} of the portfolio is ${esc(topTheme.label.toLowerCase())}.</b> ` : "") +
    (leadThemes.length ? `<b>${leadThemes.join(", ")}</b> lead${leadThemes.length>1?"":"s"} the market over every window. ` : "") +
    `Weights sum to more than 100% because a name can carry two themes and both are true.
     Relative strength is the theme's fund against ${esc(r.market || "SPY")}, as of ${esc(r.as_of || "—")};
     the funds were chosen by hand and each is one line to change.` +
    ((data.theme_untagged||[]).length ? ` Untagged: ${esc(data.theme_untagged.join(", "))}.` : "");

  // Sectors: the eleven, each with its weight (or none) and its fund's strength.
  const bySector = {};
  (r.sectors || []).forEach(x => { bySector[x.sector] = x; });
  const expBy = {};
  exp.forEach(e => { expBy[e.sector] = e; });
  const sectorNames = Object.keys(bySector).concat(exp.map(e=>e.sector).filter(n=>!bySector[n]));
  $("#sectorexp").innerHTML =
    `<tr><th scope=col>Sector</th><th class=num scope=col>Weight</th><th scope=col>Holdings</th>
      <th scope=col>Fund</th>${rsHead}</tr>` +
    sectorNames.map(n => { const e = expBy[n], x = bySector[n];
      return `<tr${e ? "" : ' class="dim"'}><td>${esc(n)}</td>
        <td class=num>${e ? `<b>${pct(e.weight)}</b>` : "—"}</td>
        <td class="note">${e ? e.symbols.join(", ") : "none held"}</td>
        <td class="note">${x ? esc(x.symbol) : "—"}</td>${rsCells(x)}</tr>`; }).join("");
  const topSector = exp[0];
  const lead = (r.sectors || []).filter(x=>x.persistent).map(x=>x.sector);
  $("#sectornote").innerHTML = (topSector
    ? `<b>${pct(topSector.weight)} of the portfolio sits in ${esc(topSector.sector)}.</b> ` : "") +
    (lead.length
      ? `<b>${lead.join(", ")}</b> lead${lead.length>1?"":"s"} over every window — short-term and long-term strength together is what reads as rotation rather than a bounce. `
      : `No sector leads over every window, so there is no clean rotation to point at right now. `) +
    `Sectors come from SEC filing codes, which are a filing category rather than a business description,
     so a handful are corrected by hand and the reason is recorded.`;
  // Three tables of dashes with no word of why is a blank panel with extra
  // steps. Say what failed, where the strength figures would have been.
  $("#rotnote").innerHTML = r.error ? `<div class="warn">Sector strength could not be computed: ${esc(r.error)}</div>` : "";
}

// Opening the tab re-reads rotation (it is cheap and cached server-side) and
// redraws with the exposure figures already loaded.
async function loadRotation(){ ROTATION = null; if(SECTOR_DATA) await loadSectors(SECTOR_DATA); }

let BOUNDS = null;

function applyPeriod(){
  const p = $("#period").value;
  if(p === "custom" || !BOUNDS || !BOUNDS.last) return;
  // A ledger with no transactions has no first date. `new Date("nullT00:00:00")`
  // is an Invalid Date and .toISOString() on it throws RangeError — inside
  // init(), which aborted the whole startup and left a fresh install sitting on
  // "Loading your portfolio" forever. That is the first thing a new user sees,
  // and no test caught it because every suite here runs against a ledger that
  // already has data.
  const first = BOUNDS.first || BOUNDS.last;
  const last = new Date(BOUNDS.last + "T00:00:00");
  let from = new Date(last);
  if(p === "1w") from.setDate(last.getDate()-7);
  else if(p === "1m") from.setMonth(last.getMonth()-1);
  else if(p === "3m") from.setMonth(last.getMonth()-3);
  else if(p === "6m") from.setMonth(last.getMonth()-6);
  else if(p === "1y") from.setFullYear(last.getFullYear()-1);
  else if(p === "ytd") from = new Date(last.getFullYear(), 0, 1);
  else from = new Date(first + "T00:00:00");
  const iso = dt => isNaN(dt) ? first : dt.toISOString().slice(0,10);
  // Never start before the ledger does — the opening portfolio would be unknown.
  $("#from").value = iso(from) < first ? first : iso(from);
  $("#to").value = BOUNDS.last;
}

async function init(){
  // Say something immediately. The first paint waits on two portfolio requests
  // and can take fifteen seconds on this dataset, and for all of that the page
  // was completely blank — which is indistinguishable from an app that is
  // broken. It is the single most common reason this has been reported as "not
  // working" when it was merely still loading.
  const boot = document.createElement("div");
  boot.id = "boot";
  boot.style.cssText = "padding:14px 4px";
  boot.innerHTML = loadingHTML("Loading your portfolio — reading the ledger and pricing "
                   + "every holding. This takes a few seconds.");
  const shell = document.querySelector('[data-sub-panel="overview"]');
  if (shell) shell.prepend(boot);
  const done = () => { const b = document.querySelector("#boot"); if (b) b.remove(); };

  // Two portfolio requests used to run one after the other: the bare one
  // here, for bounds and the symbol list, and load()'s with the period — 457
  // KB each, 18 s then 25 s cold. The bare request IS the all-time default the
  // page opens on, so that response is handed to load(); a saved custom range
  // is known before this fetch returns, so it goes out at the same time.
  // A saved relative period ("last month") is measured from the ledger's last
  // date, which only the first response knows, so that case stays serial.
  const bare = fetch("/api/performance").then(r => r.json());
  const savedEarly = loadSettings();
  if(savedEarly && savedEarly.period === "custom" && savedEarly.from && savedEarly.to){
    const q = new URLSearchParams({from: savedEarly.from, to: savedEarly.to,
      scope: savedEarly.scope || "investment",
      benchmarks: (savedEarly.benchmarks || []).join(",") || "SPY"});
    PERF_BOOT = {key: q.toString(), promise: fetch("/api/performance?"+q).then(r => r.json())};
    PERF_BOOT.promise.catch(() => {});      // load() reports it; not an unhandled rejection here
  }
  let d;
  try {
    d = await bare;
    if (d.error) throw new Error(d.error);
  } catch (err) {
    boot.innerHTML = `<div class="warn"><b>Could not load the portfolio.</b> ${
      esc(err.message)}<br>The server may not be running: start it with
      <code>python3 -m app.web</code> in ~/Desktop/Projects/investment-app.</div>`;
    return;
  }
  BOUNDS = d.bounds;
  const saved = savedEarly;
  if(!PERF_BOOT){
    // The server's own defaults for a bare request (web.py build_payload):
    // the ledger's first date, its newest priced date, all investment
    // accounts, SPY and QQQ. load() reuses `d` only if it asks for exactly this.
    const q = new URLSearchParams({from: d.bounds.first || new Date().toISOString().slice(0,10),
      to: d.bounds.last, scope: "investment", benchmarks: "SPY,QQQ"});
    PERF_BOOT = {key: q.toString(), promise: Promise.resolve(d)};
  }

  $("#symlist").innerHTML = (d.symbols||[]).map(x=>`<option value="${x}">`).join("");
  $("#from").min = d.bounds.first; $("#to").max = d.bounds.last;
  $("#scope").innerHTML = [`<option value="investment">All investment accounts</option>`,
                           `<option value="taxable">Taxable only</option>`]
    .concat((d.scopes||[]).map(a =>
      `<option value="${esc(a.name)}">${esc(a.name)} (${a.txns})</option>`)).join("");

  // Restore before the first render, so the page opens where it was left
  // rather than showing defaults and then jumping.
  if(saved){
    if(saved.scope && [...$("#scope").options].some(o=>o.value===saved.scope)) $("#scope").value = saved.scope;
    if(saved.period) $("#period").value = saved.period;
    applyPeriod();
    if(saved.period === "custom"){
      if(saved.from) $("#from").value = saved.from;
      if(saved.to)   $("#to").value   = saved.to;
    }
    if(saved.benchmarks) [...$("#bm").options].forEach(o=> o.selected = saved.benchmarks.includes(o.value));
    if(Array.isArray(saved.indicators) && saved.indicators.length && saved.indicators[0].name)
      INDS = saved.indicators;
    if(saved.wlgroup) $("#wlgroup").value = saved.wlgroup;
    if(saved.wlsort) $("#wlsort").value = saved.wlsort;
    if(saved.timeframe) $("#tf").value = saved.timeframe;
    if(saved.scale) $("#scale").value = saved.scale;
    if($("#paneSize")) $("#paneSize").value = (saved.paneSize && PANE_SIZES[saved.paneSize]) ? saved.paneSize
                                              : ((window.innerWidth || 1000) < 700 ? "small" : "normal");
    if(saved.hist) $("#hist").value = saved.hist;
    if(saved.range === "all" || saved.range === "1y") setRangeChoice(saved.range, false);
    if(saved.structure){
      const st = saved.structure;
      $("#stLines").checked = !!st.lines;   $("#stChannel").checked = !!st.channel;
      $("#stFib").checked = !!st.fib;       $("#stLabels").checked = !!st.labels;
      $("#stOsc").checked = !!st.osc;
      if($("#stVprof") && st.vprof != null) $("#stVprof").checked = !!st.vprof;
      if($("#stZonesAll")) $("#stZonesAll").checked = !!st.zonesAll;
      if(st.pivots) $("#stPivots").value = st.pivots;
      if(st.fibback) $("#stFibBack").value = st.fibback;
    }
    if(saved.compare) $("#compare").value = saved.compare;
    if(saved.cmode) $("#cmode").value = saved.cmode;
    if(saved.drawColour) $("#dColour").value = saved.drawColour;
    if(saved.bgStatus) $("#bgStatus").value = saved.bgStatus;
    if(saved.bgAge) $("#bgAge").value = saved.bgAge;
  } else {
    applyPeriod();
  }

  // ONE delegated listener for every [data-sym] row, bound at startup. Binding
  // per element on each load() added another listener to the rows that survive
  // the redraw, so after two Updates a single click fired loadChart twice —
  // once with a timeframe change and once without — and whichever response
  // landed last won. You asked for a monthly chart and got a daily one labelled
  // monthly, nondeterministically.
  // A name click is a chart click: it opens the symbol page on the chart
  // (a pill or an alert opens The read, through the same openSymbol). A
  // trade row is the one exception — it expands its fills in place.
  document.addEventListener("click", e => {
    const el = e.target.closest("[data-sym]");
    if(!el) return;
    if(el.dataset.trade !== undefined){ loadChart(el.dataset.sym); showFills(TRADES[+el.dataset.trade]); }
    else openSymbol(el.dataset.sym, "chart");
  });

  // Tabs first: they must work even if a later fetch fails. The top bar, the
  // phone's bottom bar and its More sheet all name a section; a section opens
  // on the sub-tab it was last on.
  document.querySelectorAll("#tabs button, #phonebar button[data-section], #moresheet button").forEach(b =>
    b.addEventListener("click", ()=> showTab(b.dataset.section)));
  const moreBtn = $("#phonemore");
  if(moreBtn) moreBtn.addEventListener("click", () => $("#moresheet").hidden ? openMore() : closeMore());
  const moreBack = $("#moreback");
  if(moreBack) moreBack.addEventListener("click", closeMore);

  // Sub-tabs, one row per section. Switching goes through showTab so the hash,
  // the remembered choice and the view's loader all follow; a section whose
  // sub-tabs share one payload (Budget) costs nothing on the switch because the
  // loader has already run.
  document.querySelectorAll(".subtabs button").forEach(b =>
    b.addEventListener("click", ()=> showTab(b.closest(".subtabs").dataset.section + "/" + b.dataset.sub)));
  // Arrow keys move between tabs, which is what a tablist is expected to do and
  // the only way to reach them without a mouse once roving tabindex is on.
  $("#tabs").addEventListener("keydown", e => {
    if(!["ArrowLeft","ArrowRight","Home","End"].includes(e.key)) return;
    const bs = [...document.querySelectorAll("#tabs button")];
    const i = bs.findIndex(b => b.dataset.section === TAB);
    const next = e.key === "Home" ? 0 : e.key === "End" ? bs.length - 1
               : e.key === "ArrowLeft" ? (i - 1 + bs.length) % bs.length
               : (i + 1) % bs.length;
    e.preventDefault();
    showTab(bs[next].dataset.section);
    bs[next].focus();
  });
  // Old hashes (#outlook) and new ones (#money/holdings) both resolve; a hash
  // that already names the view on screen is left alone.
  window.addEventListener("hashchange", ()=>{
    const h = location.hash.replace("#","");
    if(!h) return;
    const {section, sub} = resolveView(h);
    if(section + "/" + sub !== curView() || /\?/.test(h)) showTab(h);
  });
  // The symbol page's empty state, before any name is known — its panels
  // must never be blank, on a fresh install least of all.
  paintSymbol(null, null);
  // My Money → Overview is the landing screen, on the desktop and the phone;
  // only a hash — a bookmark, a deep link, an old tab name — opens elsewhere.
  showTab((location.hash || "").replace("#", "") || HOME_VIEW);

  await load();
  done();

  // The symbol has to be known BEFORE the tab loader runs. It was set after,
  // so opening straight onto the Chart tab called the loader with no symbol —
  // it returned without doing anything, the tab was marked loaded, and every
  // later attempt was a no-op. That is why the chart stayed blank until you
  // pressed Load. `d` was also out of scope on this line, which threw whenever
  // no symbol had been saved.
  // A deep link (#chart/read?sym=X) named the page's symbol already; else
  // the last one charted, else the largest holding.
  const first = SYM || (saved && saved.symbol) || (LAST_HOLDINGS[0] || {}).symbol;
  if(first){
    $("#symbol").value = first; CHART_SYMBOL = first;
    // showTab() ran near the top of init and already called ensureTab, which
    // marked the chart loaded while there was no symbol to load. Clearing
    // the mark is what lets the loader actually run now that there is one.
    if(CHART_DRAWN !== first) TAB_LOADED.delete("chart/*");
  } else paintSymbol(null, null);

  ensureTab(curView());                 // whichever view we opened on

  $("#btrun").addEventListener("click", loadBacktest);
  $("#btmethod").addEventListener("change", () => { describeMethod(); showLastBacktest(); });
  if($("#chartdate")){
    $("#chartdate").addEventListener("change", () => { if(CHART_SYMBOL) loadChart(CHART_SYMBOL); });
    $("#asofback").addEventListener("click", () => stepAsOf(-7));
    $("#asoffwd").addEventListener("click", () => stepAsOf(7));
    $("#asofnow").addEventListener("click", () => { $("#chartdate").value = ""; if(CHART_SYMBOL) loadChart(CHART_SYMBOL); });
    document.addEventListener("keydown", ev => {
      if(TAB !== "chart" || ev.target.matches("input, select, textarea")) return;
      if(ev.key === ",") stepAsOf(-7);
      else if(ev.key === ".") stepAsOf(7);
    });
  }
  ["#methodsel","#heldonly","#qualonly"].forEach(id =>
    $(id).addEventListener("change", loadMethods));

  // Changing the kind rebuilds the artifact list; changing the artifact only
  // re-fetches its detail, since the catalogue is already in hand.
  // Scale is a pure redraw, but the structure toggles and pivot sensitivity
  // change what the server computes, so both paths go through loadChart.
  ["#hist","#scale","#stLines","#stChannel","#stZones","#stZonesAll","#stVprof","#stFib","#stFibBack","#stLabels","#stOsc","#stPivots"]
    .forEach(id => $(id).addEventListener("change", ()=>{
      saveSettings();
      if(CHART_SYMBOL) loadChart(CHART_SYMBOL);
    }));
  // 1Y / All: a view choice, applied to the chart in hand and remembered.
  $("#rangetoggle").addEventListener("click", e => {
    const b = e.target.closest("button[data-range]");
    if(b) setRangeChoice(b.dataset.range, true);
  });
  // The two folds remember whether they were open; the chart is the point of
  // the tab, so both start closed.
  document.querySelectorAll("details[data-fold]").forEach(f => {
    f.open = foldOpen(f.dataset.fold);
    f.addEventListener("toggle", () => rememberFold(f.dataset.fold, f.open));
  });

  $("#reskind").addEventListener("change", loadResearch);
  $("#ressel").addEventListener("change", showResearch);

  $("#wladd").addEventListener("click", ()=>{
    const sym = $("#wlsym").value.trim().toUpperCase();
    if(!sym) return;
    loadWatchlist({action:"add", symbol:sym, tags:$("#wltags").value});
    $("#wlsym").value = ""; $("#wltags").value = "";
  });
  $("#wlsym").addEventListener("keydown", e=>{ if(e.key==="Enter") $("#wladd").click(); });
  ["#wlfilter","#wlgroup","#wlsort"].forEach(id =>
    $(id).addEventListener("change", ()=>{ saveSettings(); WATCHLIST ? renderWatchlist() : loadWatchlist(); }));
  // One listener for every row control on the list, however many rows.
  $("#wlgroups").addEventListener("click", async ev => {
    const edit = ev.target.closest("[data-wledit]");
    if(edit){
      ev.preventDefault(); ev.stopPropagation();
      const f = $("#wlgroups").querySelector(`[data-wlform="${edit.dataset.wledit}"]`); if(f) f.hidden = !f.hidden;
      return;
    }
    const save = ev.target.closest("[data-wlsave]");
    if(save){
      ev.preventDefault(); ev.stopPropagation();
      const f = save.closest("[data-wlform]"); const val = k => (f.querySelector(`[data-f="${k}"]`) || {}).value || "";
      save.disabled = true; save.textContent = "saving…";
      await loadWatchlist({action: "note", symbol: save.dataset.wlsave, note: val("note"), target: val("target"), stop: val("stop")});
      return;
    }
    const del = ev.target.closest("[data-del]");
    if(del){ ev.preventDefault(); ev.stopPropagation(); loadWatchlist({action: "remove", symbol: del.dataset.del}); }
  });
  $("#wlexpand").addEventListener("click", ()=>{
    document.querySelectorAll("#wlgroups details").forEach(d=>d.open = true); rememberGroups(); });
  $("#wlcollapse").addEventListener("click", ()=>{
    document.querySelectorAll("#wlgroups details").forEach(d=>d.open = false); rememberGroups(); });

  // Drawing tools. Bound once, here, rather than rebuilt with every chart —
  // rebinding on each load is how a button ends up with four handlers and one
  // click deletes four drawings.
  document.querySelectorAll(".dtool").forEach(b =>
    b.addEventListener("click", ()=>{
      if(DRAW) DRAW.setTool(b.dataset.tool);
      else renderDrawList([], null);
    }));
  $("#dColour").addEventListener("input", ()=>{
    if(DRAW) DRAW.setColour($("#dColour").value);
    saveSettings();
  });
  $("#dDelete").addEventListener("click", ()=>{
    if(DRAW && DRAW.selected != null) DRAW.remove(DRAW.selected);
  });
  $("#dClear").addEventListener("click", ()=>{
    if(!DRAW || !DRAW.items.length) return;
    // There is no undo, so the one destructive button asks first.
    if(confirm(`Delete all ${DRAW.items.length} drawings on ${CHART_SYMBOL} ${$("#tf").value}?`))
      DRAW.clear();
  });

  ["#bgApply","#bgStatus","#bgAge","#bgAccount"].forEach(id =>
    $(id).addEventListener("change", ()=>{ saveSettings(); loadBudget(); }));
  $("#bgApply").addEventListener("click", ()=> loadBudget());
  $("#bgReset").addEventListener("click", ()=>{
    $("#bgFrom").value = ""; $("#bgTo").value = ""; loadBudget();
  });

  // A manual refresh, and an automatic one when the chart is opened during
  // market hours. There is deliberately NO background poller: this is a
  // single-user tool, and a loop that fetches all day to keep a tab nobody is
  // looking at up to date spends the API budget on nothing.
  $("#refresh").addEventListener("click", ()=>{
    if(CHART_SYMBOL) loadChart(CHART_SYMBOL, {refresh:true});
  });

  $("#sympick").addEventListener("change", e=>{
    const v = e.target.value;
    if(!v) return;
    $("#symbol").value = v;
    openSymbol(v, "chart");
  });

  // [ and ] step through the picker, so a run of names can be flicked through
  // without going back to the mouse. Ignored while typing in a field.
  document.addEventListener("keydown", e=>{
    if(e.key !== "[" && e.key !== "]") return;
    if(/^(INPUT|SELECT|TEXTAREA)$/.test((e.target||{}).tagName || "")) return;
    if(TAB !== "chart") return;
    const opts = [...$("#sympick").options].filter(o=>o.value);
    if(!opts.length) return;
    const i = opts.findIndex(o=>o.value === CHART_SYMBOL);
    const next = opts[(i + (e.key === "]" ? 1 : -1) + opts.length) % opts.length];
    if(!next) return;
    e.preventDefault();
    $("#sympick").value = next.value;
    $("#symbol").value = next.value;
    openSymbol(next.value, SUB);
  });

  // Load redraws even the same name: it is the button for "apply what I
  // just changed in the bar".
  $("#loadsym").addEventListener("click", ()=>{
    const v = $("#symbol").value.trim().toUpperCase();
    if(v) openSymbol(v, "chart", {reload: true});
  });
  $("#symbol").addEventListener("keydown", e=>{
    if(e.key === "Enter"){
      const v = e.target.value.trim().toUpperCase();
      if(v) openSymbol(v, "chart", {reload: true});
    }
  });

  $("#setup").addEventListener("change", ()=> applySetup($("#setup").value));
  ["#tf","#cmode"].forEach(id => $(id).addEventListener("change", ()=>{
    saveSettings(); if(CHART_SYMBOL) loadChart(CHART_SYMBOL);
  }));
  $("#compare").addEventListener("change", ()=>{ saveSettings(); if(CHART_SYMBOL) loadChart(CHART_SYMBOL); });

  // Fullscreen: the chart is the thing you stare at, and 420px is not enough.
  $("#fullscreen").addEventListener("click", ()=>{
    const panel = $("#chartpanel");
    panel.classList.toggle("full");
    $("#fullscreen").textContent = panel.classList.contains("full") ? "✕" : "⛶";
    // Charts sized while constrained keep the old width until told otherwise.
    setTimeout(sizeChart, 60);
  });
  addEventListener("resize", ()=>{ clearTimeout(window.__rs);
    window.__rs = setTimeout(sizeChart, 120); });

  // Appearance: colours and marker style repaint the chart, which is cheap
  // because the data is already in hand.
  STYLE = loadStyle(); styleToForm();
  ["#cUp","#cDown","#cRes","#cSup","#cBuy","#cSell","#mShape","#mSize","#mLabel","#mTint"]
    .concat(["#mDots"])
    .forEach(id => $(id).addEventListener("change", ()=>{
      styleFromForm();
      if(CHART_SYMBOL) loadChart(CHART_SYMBOL);
    }));
  $("#styleReset").addEventListener("click", ()=>{
    STYLE = styleDefaults(); saveStyle(); styleToForm();
    if(CHART_SYMBOL) loadChart(CHART_SYMBOL);
  });
  document.addEventListener("keydown", e=>{
    if(e.key === "Escape" && $("#chartpanel").classList.contains("full")) $("#fullscreen").click();
  });
  $("#go").addEventListener("click", load);
  $("#period").addEventListener("change", ()=>{ applyPeriod(); saveSettings(); load(); });
  $("#scope").addEventListener("change", ()=>{ saveSettings(); load(); });
  $("#bm").addEventListener("change", ()=>{ saveSettings(); load(); });
  ["#from","#to"].forEach(id => $(id).addEventListener("change", ()=>{
    $("#period").value = "custom"; saveSettings();
  }));
}
