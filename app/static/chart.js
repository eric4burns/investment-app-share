// The chart: loadChart, panes, indicators, structure, style, the fills overlay, the as-of view.
// One of the dashboard's scripts (see dashboard.html): a classic script sharing the page's
// global scope with the others, loaded in the order the tags there give.

// The cloud is the area BETWEEN the two spans, and nothing else.
//
// Two earlier attempts got this wrong in opposite directions. Plain line series
// drew no band at all. Area series then shaded everything BENEATH each span
// down to the floor of the pane — 111,905 of 142,236 drawn pixels — because an
// area series fills to the bottom, not to another series. Lightweight Charts
// has no between-series fill, so the band is drawn on a canvas above the chart,
// which is the same approach drawings.js already uses for annotations: it
// cannot disturb the price scale, and coordinates come from the chart itself so
// it stays correct through pan and zoom.
function drawCloudBand(chart, series, host, ich, fromTime, th, onRO){
  const cv = document.createElement("canvas");
  // Named, so a test can address THIS canvas rather than "the last one in the
  // container". Selecting by position passed for the wrong reason when the
  // overlay was absent: it fell through to the price-scale canvas and reported
  // a 26px-tall element with one lit pixel.
  cv.className = "cloudband";
  cv.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:2";
  if(getComputedStyle(host).position === "static") host.style.position = "relative";
  host.appendChild(cv);
  const byTime = new Map();
  (ich.span_a || []).forEach(p => { if(p.time >= fromTime && p.value != null)
    byTime.set(p.time, {a: p.value}); });
  (ich.span_b || []).forEach(p => { if(p.time >= fromTime && p.value != null){
    const e = byTime.get(p.time); if(e) e.b = p.value; } });
  const pts = [...byTime.entries()].filter(([, v]) => v.b != null)
    .map(([time, v]) => ({time, a: v.a, b: v.b}));

  const paint = () => {
    const dpr = window.devicePixelRatio || 1;
    const w = host.clientWidth, h = host.clientHeight;
    if(!w || !h) return;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    cv.style.width = w + "px"; cv.style.height = h + "px";
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const ts = chart.timeScale();
    // One quad per adjacent pair, coloured by which span is on top there — the
    // cloud flips colour mid-run and a single fill would lose that.
    for(let i = 1; i < pts.length; i++){
      const p0 = pts[i - 1], p1 = pts[i];
      const x0 = ts.timeToCoordinate(p0.time), x1 = ts.timeToCoordinate(p1.time);
      if(x0 == null || x1 == null) continue;
      const a0 = series.priceToCoordinate(p0.a), b0 = series.priceToCoordinate(p0.b);
      const a1 = series.priceToCoordinate(p1.a), b1 = series.priceToCoordinate(p1.b);
      if([a0, b0, a1, b1].some(v => v == null)) continue;
      const rising = (p0.a + p1.a) / 2 <= (p0.b + p1.b) / 2;   // y grows downward
      ctx.fillStyle = rgba(rising ? th.up : th.down, 0.22);
      ctx.beginPath();
      ctx.moveTo(x0, a0); ctx.lineTo(x1, a1); ctx.lineTo(x1, b1); ctx.lineTo(x0, b0);
      ctx.closePath(); ctx.fill();
    }
    // The edges, so the band reads as bounded rather than as a smudge.
    [["a", th.up], ["b", th.down]].forEach(([k, col])=>{
      ctx.strokeStyle = rgba(col, 0.9); ctx.lineWidth = 1.5;
      ctx.beginPath();
      let started = false;
      for(const p of pts){
        const x = ts.timeToCoordinate(p.time), y = series.priceToCoordinate(p[k]);
        if(x == null || y == null){ started = false; continue; }
        if(started) ctx.lineTo(x, y); else { ctx.moveTo(x, y); started = true; }
      }
      ctx.stroke();
    });
  };

  paint();
  // Redrawn on every pan, zoom and resize, or the band detaches from the price.
  chart.timeScale().subscribeVisibleLogicalRangeChange(paint);
  if(window.ResizeObserver){
    const ro = new ResizeObserver(paint);
    ro.observe(host);
    if(onRO) onRO(ro);
  }
  return cv;
}

let CLOUD_RO = null, VPROF_RO = null, FILL_RO = null;

// The user's fills as haloed arrows (or circles, or squares) on an overlay
// canvas over the price pane. Sized the way the library sizes its own markers
// — from the bar spacing, between 12 and 30px, times the chosen size — so
// they grow and shrink with the candles they belong to.
function drawFillMarks(chart, series, host, marks, bars, style, th, labelled, onRO){
  const cv = document.createElement("canvas");
  cv.className = "fillmarks";
  cv.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:2";
  if(getComputedStyle(host).position === "static") host.style.position = "relative";
  host.appendChild(cv);
  const barByTime = new Map(bars.map(b => [b.time, b]));
  const halo = th.bg || (th.dark ? "#1B1F2B" : "#FFFFFF");
  const mult = Math.max(0, Math.min(4, Number(style.size) || 0));
  const paint = () => {
    const dpr = window.devicePixelRatio || 1;
    const w = host.clientWidth, h = host.clientHeight;
    if(!w || !h) return;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    cv.style.width = w + "px"; cv.style.height = h + "px";
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if(!mult) return;
    const ts = chart.timeScale();
    // Only the pane: never over the price axis or the time axis.
    let paneW = w, paneH = h;
    try{ paneW = w - chart.priceScale("right").width(); }catch(e){}
    try{ paneH = h - ts.height(); }catch(e){}
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, paneW, paneH); ctx.clip();
    let spacing = 6;
    try{ const o = ts.options(); spacing = o.barSpacing || spacing; }catch(e){}
    const base = Math.min(Math.max(spacing, 12), 30);
    const size = Math.round(base * mult * 0.7);       // the arrow's height
    ctx.font = "600 11px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.lineJoin = "round";
    for(const m of marks){
      const b = barByTime.get(m.date);
      if(!b) continue;
      const x = ts.timeToCoordinate(m.date);
      if(x == null || x < 0 || x > paneW) continue;
      const buy = m.side === "buy";
      const anchor = series.priceToCoordinate(buy ? b.low : b.high);
      if(anchor == null) continue;
      const colour = buy ? style.buy : style.sell;
      // Buys sit under the bar pointing up at it, sells over it pointing down.
      const gap = 3;
      const tip = buy ? anchor + gap : anchor - gap;
      const dir = buy ? 1 : -1;                 // which way the shape extends
      ctx.beginPath();
      if(style.shape === "circle"){
        const r = size / 2;
        ctx.arc(x, tip + dir * r, r, 0, Math.PI * 2);
      } else if(style.shape === "square"){
        const r = size / 2;
        ctx.rect(x - r, Math.min(tip, tip + dir * size), size, size);
      } else {
        const half = size * 0.5, stem = size * 0.18, head = size * 0.55;
        ctx.moveTo(x, tip);
        ctx.lineTo(x - half, tip + dir * head);
        ctx.lineTo(x - stem, tip + dir * head);
        ctx.lineTo(x - stem, tip + dir * size);
        ctx.lineTo(x + stem, tip + dir * size);
        ctx.lineTo(x + stem, tip + dir * head);
        ctx.lineTo(x + half, tip + dir * head);
        ctx.closePath();
      }
      ctx.lineWidth = 2; ctx.strokeStyle = halo; ctx.stroke();   // 1px shows outside the fill
      ctx.fillStyle = colour; ctx.fill();
      if(style.labels && labelled){
        const text = `${buy ? "BUY" : "SELL"} ${m.qty.toLocaleString(undefined, {maximumFractionDigits: 2})}`;
        const ty = buy ? tip + size + 12 : tip - size - 4;
        ctx.lineWidth = 3; ctx.strokeStyle = halo; ctx.strokeText(text, x, ty);
        ctx.fillStyle = colour; ctx.fillText(text, x, ty);
      }
    }
    ctx.restore();
  };
  paint();
  chart.timeScale().subscribeVisibleLogicalRangeChange(paint);
  // The price scale settles a frame after the range is set; paint once more
  // so the first frame is not drawn against the scale before autoscale ran.
  requestAnimationFrame(paint);
  if(window.ResizeObserver){
    const ro = new ResizeObserver(paint);
    ro.observe(host);
    if(onRO) onRO(ro);
  }
  return cv;
}

// Volume by PRICE, drawn down the right edge of the price pane the way
// SteveUrkeldude's IREN chart shows it: one horizontal bar per price bin, its
// length the share of the window's volume that traded there, the heaviest
// bin (the point of control) marked. Same overlay-canvas approach as the
// cloud band, so it follows the price scale through pan, zoom and resize and
// never touches the scale itself. Nothing here is a level: it answers "how
// much traded here", which is a different question from "where did price
// turn" — a thick node under price is support only in the sense that many
// holders are at a profit there.
function drawVolumeProfile(chart, series, host, profile, th, onRO){
  if(!profile || !profile.bins || !profile.bins.length) return;
  const cv = document.createElement("canvas");
  cv.className = "vprofile";
  cv.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:2";
  if(getComputedStyle(host).position === "static") host.style.position = "relative";
  host.appendChild(cv);
  const maxShare = Math.max(...profile.bins.map(b => b.share)) || 1;
  const paint = () => {
    const dpr = window.devicePixelRatio || 1;
    const w = host.clientWidth, h = host.clientHeight;
    if(!w || !h) return;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    cv.style.width = w + "px"; cv.style.height = h + "px";
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    // The price scale sits at the right; the bars grow leftward from just
    // inside it. A fifth of the pane at most, so the candles stay the chart.
    const scaleW = (chart.priceScale("right") && chart.priceScale("right").width && chart.priceScale("right").width()) || 60;
    const right = w - scaleW - 2;
    const maxLen = Math.max(40, w * 0.18);
    profile.bins.forEach(b => {
      const y0 = series.priceToCoordinate(b.high), y1 = series.priceToCoordinate(b.low);
      if(y0 == null || y1 == null) return;
      const len = maxLen * (b.share / maxShare);
      const poc = b.low === profile.poc.low;
      ctx.fillStyle = rgba(poc ? th.flag || th.up : th.text, poc ? 0.42 : 0.16);
      const hgt = Math.max(1, Math.abs(y1 - y0) - 1);
      ctx.fillRect(right - len, Math.min(y0, y1) + 0.5, len, hgt);
    });
  };
  paint();
  chart.timeScale().subscribeVisibleLogicalRangeChange(paint);
  if(window.ResizeObserver){
    const ro = new ResizeObserver(paint);
    ro.observe(host);
    if(onRO) onRO(ro);
  }
}

// ------------------------------------------------------ remembered view ----
// Where you had the chart scrolled and how far in you were zoomed. Three
// separate places used to call fitContent — loading a symbol, switching to the
// chart tab, and going fullscreen — so any one of them threw the view away and
// the chart snapped back to the whole history.
//
// Stored as a TIME range rather than a bar range. Bar indices shift by one
// every time a new day of data arrives, so a logical range slides a little
// further off every day; a pair of dates means the same thing tomorrow.
const VIEW_KEY = "invest.chartview.v1";

const VIEW_LIMIT = 60;

// History length is part of the key. A range saved while looking at fifteen
// years is not a view that exists at all under "1 year".
function viewKey(){
  return [CHART_SYMBOL, $("#tf").value, $("#hist").value, $("#scale").value].join("|");
}

function loadViews(){
  try{ return JSON.parse(localStorage.getItem(VIEW_KEY) || "{}") || {}; }
  catch(e){ return {}; }
}

function rememberView(){
  if(!CHART || !CHART_SYMBOL) return;
  let r = null;
  try{ r = CHART.timeScale().getVisibleRange(); }catch(e){ return; }
  if(!r || !r.from || !r.to) return;
  try{
    const views = loadViews();
    // `v` marks a view saved since the chart opened on the last year; an
    // older entry is every bar there was, which is exactly the view the
    // default replaces, so restoreView ignores those once and they are
    // rewritten here. Same key, one field added.
    views[viewKey()] = {from:r.from, to:r.to, t:Date.now(), v:2};
    // One entry per symbol, timeframe, history and scale is a lot of keys over
    // time, and localStorage is a small fixed budget shared with everything
    // else the page stores. Keep the ones used most recently.
    const keys = Object.keys(views);
    if(keys.length > VIEW_LIMIT){
      keys.sort((a,b)=>(views[b].t||0)-(views[a].t||0))
          .slice(VIEW_LIMIT).forEach(k=> delete views[k]);
    }
    localStorage.setItem(VIEW_KEY, JSON.stringify(views));
  }catch(e){ /* private window, or storage full — the chart still works */ }
}

// The 1Y / All toggle. "1y" is a year of bars for the timeframe on screen —
// 250 daily, 52 weekly, 12 monthly; the intraday frames get the last few
// sessions, since a year of five-minute bars is not a chart anyone reads.
// Quarterly gets five years: four bars is not a chart either.
let CHART_RANGE = "1y";

const YEAR_BARS = {D: 250, W: 52, M: 12, Q: 20, "5m": 390, "15m": 260, "1h": 210};

function yearBars(){ return YEAR_BARS[$("#tf").value] || 250; }

// Show the last N bars, with the same right-hand gap fitContent leaves.
function showLastBars(n){
  if(!CHART || !CANDLES) return false;
  const len = CANDLES.data().length;
  if(!len) return false;
  if(n >= len){ try{ CHART.timeScale().fitContent(); }catch(e){} return true; }
  try{ CHART.timeScale().setVisibleLogicalRange({from: len - n - 0.5, to: len - 0.5 + 4}); return true; }
  catch(e){ return false; }
}

function setRangeChoice(choice, apply){
  CHART_RANGE = choice === "all" ? "all" : "1y";
  document.querySelectorAll("#rangetoggle button").forEach(b => {
    const on = b.dataset.range === CHART_RANGE;
    b.classList.toggle("on", on); b.setAttribute("aria-pressed", on ? "true" : "false");
  });
  if(!apply) return;
  saveSettings();
  if(CHART_RANGE === "all"){ try{ CHART && CHART.timeScale().fitContent(); }catch(e){} }
  else showLastBars(yearBars());
  syncPanesToChart();
  rememberView();          // so a reload lands on the choice, not the view before it
}

function syncPanesToChart(){
  let r = null;
  try{ r = CHART && CHART.timeScale().getVisibleLogicalRange(); }catch(e){}
  if(r) PANES.forEach(p=>{ try{ p.timeScale().setVisibleLogicalRange(r); }catch(e){} });
}

// Restore, or open on the last year if there is nothing sensible to restore.
// Returning to the saved view is only right if it still overlaps the data
// actually loaded; otherwise you get an empty pane, which reads as a broken
// chart. Every redraw — an indicator added, the theme flipped, a colour
// changed — comes back through here, and finds the view it left.
function restoreView(){
  if(!CHART || !CANDLES) return;
  const v = loadViews()[viewKey()];
  let ok = false;
  if(v && v.from && v.to && v.v >= 2){
    const bars = CANDLES.data();
    const first = bars.length ? bars[0].time : null;
    const last = bars.length ? bars[bars.length-1].time : null;
    if(first && last && v.from <= last && v.to >= first){
      // A view saved weeks ago ends where the data ended then; restoring it
      // as-is shows the old bars and none of the new ones, which reads as
      // "the chart stops in July". Keep the zoom, slide the window to today.
      let from = v.from, to = v.to;
      if(to < last){
        const span = (new Date(to) - new Date(from)) || 0;
        to = last; from = new Date(new Date(last) - span).toISOString().slice(0, 10);
      }
      try{ CHART.timeScale().setVisibleRange({from, to}); ok = true; }
      catch(e){ ok = false; }
    }
  }
  if(!ok){
    if(CHART_RANGE === "all" || !showLastBars(yearBars())){ try{ CHART.timeScale().fitContent(); }catch(e){} }
  }
  // The lower panes follow the price pane through the same logical range the
  // sync handler uses, so they cannot end up showing a different window.
  syncPanesToChart();
}

// Which of the chart's two folds (Tools, Levels & structure) were left open.
const FOLD_KEY = "investment-app.chartfolds.v1";

function foldOpen(name){
  try{ return !!(JSON.parse(localStorage.getItem(FOLD_KEY) || "{}") || {})[name]; }
  catch(e){ return false; }
}

function rememberFold(name, open){
  try{
    const all = JSON.parse(localStorage.getItem(FOLD_KEY) || "{}") || {};
    all[name] = !!open;
    localStorage.setItem(FOLD_KEY, JSON.stringify(all));
  }catch(e){ /* private window — the fold still opens, it just will not persist */ }
}

let VIEW_TIMER = null;

function scheduleRememberView(){
  clearTimeout(VIEW_TIMER);
  // Debounced: a single pan fires this continuously, and writing to
  // localStorage on every frame of a drag is how a scroll turns janky.
  VIEW_TIMER = setTimeout(rememberView, 400);
}

// Active indicators, each with its own parameters. Held as objects rather than
// a checkbox list because every period is adjustable — an indicator whose
// period you cannot change is barely an indicator.
let SETUPS = [];

// Applying a setup swaps the whole chart configuration — timeframe and every
// indicator at that analyst's settings — so a ticker can be opened the way they
// look at it. This is the half of "following someone" that is actually
// transferable, and it needs far less sourcing than a full trading method.
// One drawing routine for every pane. A trendline on Williams %R is the same
// object as a trendline on price — which is the whole argument for computing
// structure server-side rather than twice in here.
// Auto-drawn lines you did not ask for and cannot remove are worse than no
// lines. Dismissals are kept per symbol AND timeframe, since the same name on
// a weekly chart is a different drawing.
const HIDDEN_KEY = "investment-app.hiddenlines.v1";

function hiddenKey(){ return `${CHART_SYMBOL}|${$("#tf").value}`; }

// ------------------------------------------------------- hand drawings ----
// The overlay itself lives in /static/drawings.js and knows nothing about this
// page. Everything here is the parts a chart page has to own: when to build and
// tear it down, and how to show what has been drawn so far.

const DRAW_LABEL = {trend:"Trendline", ray:"Ray", level:"Level",
                    channel:"Channel", fib:"Fib"};

const DRAW_HINT = {
  cursor:  "Click a drawing to select it. Drag it to move, drag a square to reshape, Del to delete.",
  trend:   "Click one end, then click the other. Dragging works too.",
  ray:     "Click one end, then click the other. The line continues to the right edge.",
  level:   "Click where you want the line.",
  channel: "Click each end of the base line, then click again to set the width.",
  fib:     "Click each end of the move you want to retrace, low to high or high to low.",
};

// What a drawing is, in words, so the list is readable without the chart. A row
// saying only "Channel" is no better than the menu that stayed empty.
function drawSummary(d){
  const p = d.points || [];
  const money = v => "$" + Number(v).toFixed(2);
  if(d.kind === "level") return `${money(p[0][1])}`;
  if(d.kind === "channel")
    return `${p[0][0]} → ${p[1][0]}, ${money(p[0][1])} → ${money(p[1][1])}`;
  if(!p[1]) return "";
  const dir = p[1][1] >= p[0][1] ? "↗" : "↘";
  return `${p[0][0]} ${money(p[0][1])} ${dir} ${p[1][0]} ${money(p[1][1])}`;
}

function renderDrawList(items, selected){
  const el = $("#drawlist");
  if(!el) return;
  $("#dDelete").disabled = selected == null;
  $("#dHint").textContent = DRAW_HINT[DRAW ? DRAW.tool : "cursor"] || "";
  document.querySelectorAll(".dtool").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.tool === (DRAW ? DRAW.tool : "cursor"))));

  if(!items || !items.length){
    el.innerHTML = `<span class="note">Nothing drawn on this chart yet.</span>`;
    return;
  }
  el.innerHTML = items.map(d => `
    <span class="chip2 drawrow${d.id === selected ? " on" : ""}" data-id="${esc(d.id)}"
          role="button" tabindex="0" title="Select this drawing">
      <span style="display:inline-block;width:9px;height:9px;border-radius:2px;
                   background:${esc(d.colour || chartTheme().mineLevel)}"></span>
      <b>${esc(DRAW_LABEL[d.kind] || d.kind)}</b>
      <span class="note">${esc(drawSummary(d))}</span>
      <button class="drawdel" data-id="${esc(d.id)}" aria-label="Delete this drawing"
              title="Delete">×</button>
    </span>`).join("");

  el.querySelectorAll(".drawrow").forEach(row => {
    row.addEventListener("click", e => {
      if(e.target.classList.contains("drawdel")) return;
      if(DRAW) DRAW.select(Number(row.dataset.id));
    });
    row.addEventListener("keydown", e => {
      if(e.key === "Enter" || e.key === " "){ e.preventDefault(); row.click(); }
    });
  });
  el.querySelectorAll(".drawdel").forEach(b =>
    b.addEventListener("click", e => {
      e.stopPropagation();
      if(DRAW) DRAW.remove(Number(b.dataset.id));
    }));
}

// Built after the chart, torn down before it. The overlay holds window-level
// listeners and an animation frame, so an orphan left behind would keep
// hit-testing against a chart that no longer exists — the same leak that made
// switching scale look like a log-scale bug.
function attachDrawings(d){
  if(DRAW){ try{ DRAW.dispose(); }catch(e){} DRAW = null; }
  if(!CHART || !CANDLES || !window.ChartDrawings) return;
  DRAW = new ChartDrawings({
    chart: CHART, series: CANDLES, host: $("#pricechart"),
    bars: d.bars || [], symbol: CHART_SYMBOL, timeframe: $("#tf").value,
    theme: chartTheme(), colour: $("#dColour").value,
    onChange: renderDrawList,
    onError: msg => { $("#dHint").textContent = "Could not save that drawing: " + msg; },
  });
  DRAW.setItems(d.drawings || []);
}

function hiddenLines(){
  try{ return new Set((JSON.parse(localStorage.getItem(HIDDEN_KEY) || "{}"))[hiddenKey()] || []); }
  catch(e){ return new Set(); }
}

function setHiddenLines(set){
  try{
    const all = JSON.parse(localStorage.getItem(HIDDEN_KEY) || "{}");
    if(set.size) all[hiddenKey()] = [...set]; else delete all[hiddenKey()];
    localStorage.setItem(HIDDEN_KEY, JSON.stringify(all));
  }catch(e){ /* storage disabled — dismissal just will not persist */ }
}

// Identity has to survive a redraw, so it is the line's own anchors rather than
// its position in the list, which shifts as bars arrive.
const lineId = l => `${l.side}:${l.anchors ? l.anchors.join(">") : l.from.time}`;

function structColours(){
  const st = STYLE || loadStyle();
  return {resistance:st.resistance, support:st.support, channel:chartTheme().line};
}

function drawStructure(chart, struct, opts){
  if(!struct || struct.insufficient) return [];
  const drawn = [];
  const seg = (a, b, colour, style, width) => {
    const s2 = chart.addLineSeries({color:colour, lineWidth:width||1, lineStyle:style||0,
      priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false,
      // Excluded from autoscale. A projected line or a 2.0 extension sits far
      // outside the traded range, and letting it stretch the scale squashes the
      // candles to make room for an annotation — which is backwards. Ticking
      // Channels or Fibonacci should not change the price scale at all.
      autoscaleInfoProvider: () => null});
    s2.setData([{time:a.time, value:a.price}, {time:b.time, value:b.price}]);
    drawn.push(s2);
    return s2;
  };

  const STRUCT_COLOURS = structColours();
  const th = chartTheme();
  // Uniform weight, and a hairline: thickness used to encode the touch count,
  // which implied a strength the count does not carry — measured against
  // shuffled versions of the same series, real lines score no better than
  // noise. Furniture is 1px so the user's own 2px marks are the loudest
  // thing on the pane.
  if(opts.lines) (struct.trendlines||[]).forEach(l=>{
    if(opts.hidden && opts.hidden.has(lineId(l))) return;
    seg(l.from, l.to, STRUCT_COLOURS[l.side], 0, 1);
  });
  if(opts.channel) (struct.channels||[]).forEach(c=>
    seg(c.from, c.to, STRUCT_COLOURS.channel, 2, 1));

  // Fib levels run FORWARD from the end of the swing they are measured on,
  // never across the whole pane. createPriceLine draws edge to edge, which laid
  // every retracement back over history that had already happened before the
  // swing existed — a level cannot be support for a bar that predates the move
  // it is derived from. Segments instead, starting where the swing ends.
  if(opts.fib && struct.fib && struct.fib.to && opts.lastTime != null){
    const fibFrom = struct.fib.to.time;
    // Every level is labelled where it starts — the ratio and the price, the
    // way TradingView's tool writes them — because eight unlabelled dashed
    // lines are eight lines the reader has to guess at. A marker with size 0
    // draws no shape, only the text, on the segment's own series.
    const label = (series, ratio, price) => series.setMarkers([{
      time: fibFrom, position: "inBar", shape: "circle", size: 0, color: th.furnitureHex,
      text: `${ratio} · ${Number(price).toFixed(price >= 100 ? 0 : 2)}`}]);
    struct.fib.levels.forEach(l=>{
      if (opts.range && (l.price < opts.range.lo || l.price > opts.range.hi)) return;
      const ext = l.kind === "extension";
      const s2 = seg({time:fibFrom, price:l.price}, {time:opts.lastTime, price:l.price},
          ext ? th.furnitureStrong : th.furniture,
          l.ratio === 0.5 ? 0 : 2, 1);
      label(s2, l.ratio, l.price);
    });
    // The deep-pullback band (0.786–0.887, the "reversal zone" three of the
    // followed accounts buy) as two dotted edges, and the 1.272 / 1.414
    // targets above the leg. Both come from the same swing as the levels.
    const have = new Set(struct.fib.levels.map(l => l.ratio));
    const rz = struct.fib.reversal_zone;
    if(rz && rz.low > 0){
      const ratios = (rz.ratios || []).slice().sort((a, b) => a - b);
      const up = struct.fib.direction === "up";
      [rz.low, rz.high].forEach((price, i) => {
        if (opts.range && (price < opts.range.lo || price > opts.range.hi)) return;
        const s2 = seg({time:fibFrom, price}, {time:opts.lastTime, price}, th.furnitureStrong, 1, 1);
        // On a rising leg the deeper ratio is the LOWER price; on a falling
        // leg it is the higher one.
        const ratio = ratios.length === 2 ? (up ? ratios[1 - i] : ratios[i]) : null;
        // 0.786 is also a retracement level, already drawn and labelled above.
        if(ratio != null && !have.has(ratio)) label(s2, ratio, price);
      });
    }
    (struct.fib.targets || []).forEach(t => {
      if(have.has(t.ratio)) return;
      if (opts.range && (t.price < opts.range.lo || t.price > opts.range.hi)) return;
      const s2 = seg({time:fibFrom, price:t.price}, {time:opts.lastTime, price:t.price}, th.furniture, 1, 1);
      label(s2, t.ratio, t.price);
    });
  }
  // Horizontal support and resistance. Six of these at 2px were most of the
  // ink on the pane, and none of it is the user's. By default only the two
  // that matter for the next trade are drawn — the nearest zone under price
  // and the nearest over it — as 1px dashed price lines whose only label is
  // on the axis (S / R). "Show all S/R" in the Levels fold draws the rest as
  // bands from their first pivot, still 1px dashed, because a zone IS a band:
  // a cluster of pivots spanning a range.
  if(opts.zones && struct.zones && opts.lastTime != null){
    const px = opts.lastClose;
    const zones = struct.zones.filter(z => !(opts.range && (z.high < opts.range.lo || z.low > opts.range.hi)));
    let sup = null, res = null;
    if(px != null){
      zones.forEach(z => {
        if(z.price < px && (!sup || z.price > sup.price)) sup = z;
        if(z.price >= px && (!res || z.price < res.price)) res = z;
      });
    }
    const nearest = [sup, res].filter(Boolean);
    if(opts.host && opts.host.createPriceLine){
      nearest.forEach(z => opts.host.createPriceLine({
        // The edge that faces price: the top of a support zone, the bottom
        // of a resistance zone — the price a bounce or a rejection happens at.
        price: z === sup ? z.high : z.low, color: th.furniture, lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, axisLabelColor: th.furnitureHex, axisLabelTextColor: th.bg,
        title: z === sup ? "S" : "R"}));
    }
    if(opts.zonesAll) zones.forEach(z=>{
      if(nearest.includes(z)) return;
      [z.low, z.high].forEach(price =>
        seg({time:z.first, price}, {time:opts.lastTime, price}, th.furniture, 2, 1));
    });
  }

  return drawn;
}

// Every lower pane is its own chart, and panes are synced by LOGICAL INDEX.
// An indicator series starts after its warm-up, so index 0 is a different date
// on every pane — RSI(14) is 14 bars late, MACD 33 — and hovering a candle
// showed you the oscillator reading of a bar a month and a half earlier. Padding
// each series with leading whitespace points (a time with no value, which draws
// nothing) puts every pane in the same index space so the sync is honest.
function padToBars(bars, data){
  if(!data || !data.length) return data;
  const first = data[0].time;
  const lead = [];
  for(const b of bars){ if(b.time >= first) break; lead.push({time:b.time}); }
  return lead.length ? lead.concat(data) : data;
}

function structureMarkers(struct){
  return (struct && struct.pivots || []).map(p=>({
    time:p.time, position:p.kind === "high" ? "aboveBar" : "belowBar",
    color:chartTheme().muted, shape:"circle", text:p.label,
  }));
}

function structOpts(){
  return {lines:$("#stLines").checked, channel:$("#stChannel").checked,
          zones:$("#stZones") ? $("#stZones").checked : true,
          zonesAll:$("#stZonesAll") ? $("#stZonesAll").checked : false,
          vprof:$("#stVprof") ? $("#stVprof").checked : true,
          fib:$("#stFib").checked, labels:$("#stLabels").checked,
          osc:$("#stOsc").checked};
}

// Open the chart showing the things a verdict was reached from. Going to a bare
// chart and leaving somebody to find the four toggles that reproduce what the
// Outlook tab just told them is most of the reason the verdict felt
// unverifiable — the levels were named in words with no picture of them.
function chartForVerdict(sym){
  [["#stLines", true], ["#stZones", true], ["#stFib", true], ["#stLabels", true]]
    .forEach(([id, on]) => { const el = $(id); if(el) el.checked = on; });
  openSymbol(sym, "chart", {reload: true});
}

function applySetup(key){
  const s2 = SETUPS.find(x=>x.key === key);
  if(!s2){ $("#setupinfo").style.display = "none"; return; }
  $("#tf").value = s2.timeframe;
  INDS = s2.indicators.map(spec=>{
    const [name, ...args] = spec.split(":");
    return {name, args: args.map(Number)};
  });
  // "reported" was missing and fell through to muted, which is the colour of a
  // default attributed to nobody — so second-hand settings from a real person's
  // material read as unsourced. It sits with inferred: better than a guess,
  // short of their own quoted words.
  const badge = {stated:"var(--up)", reported:"var(--warn)",
                 inferred:"var(--warn)", proposed:"var(--muted)"};
  $("#setupinfo").style.display = "";
  $("#setupinfo").innerHTML = `
    <div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:8px">
      <b>${s2.name}</b>
      <span class="pill" style="color:${badge[s2.confidence]||"var(--muted)"}">${s2.confidence}</span>
      <span class="note">${s2.attribution}</span>
    </div>
    <p class="note" style="margin:0 0 8px">${s2.source}</p>
    <ul style="margin:0;padding-left:18px;display:flex;flex-direction:column;gap:6px;font-size:13.5px;color:var(--text-2)">
      ${s2.reading.map(r=>`<li>${r}</li>`).join("")}
    </ul>
    ${s2.quotes && s2.quotes.length ? `<ul class="note" style="margin:8px 0 0;padding-left:18px;display:flex;flex-direction:column;gap:4px">
      ${s2.quotes.map(q=>`<li>${q}</li>`).join("")}</ul>` : ""}
    ${s2.needs && s2.needs.length ? `<p class="note" style="margin:8px 0 0">
      <b>Unconfirmed:</b> ${s2.needs.join("; ")}.</p>` : ""}`;
  saveSettings();
  if(CHART_SYMBOL) loadChart(CHART_SYMBOL);
}

let INDS = [
  {name:"volume", args:[]},
  {name:"sma", args:[20]},
  {name:"sma", args:[50]},
];

let CATALOGUE = [];

let PALETTE = palette();

const specOf = i => i.args.length ? `${i.name}:${i.args.join(":")}` : i.name;

let PANES = [];

// The container each lower pane lives in, so its chart can be sized to match.
let PANE_WRAPS = [];

function renderIndBar(){
  const opts = CATALOGUE.map(c=>`<option value="${c.name}">${c.label}</option>`).join("");
  $("#indbar").innerHTML =
    INDS.map((ind,i)=>{
      const c = CATALOGUE.find(x=>x.name===ind.name) || {params:[],label:ind.name};
      const fields = c.params.map((p,j)=>
        `<input type="number" data-i="${i}" data-j="${j}" value="${ind.args[j] ?? p.default}"
                min="${p.min}" max="${p.max}" step="${Number.isInteger(p.default)?1:0.1}"
                title="${p.name}">`).join("");
      return `<span class="chip2"><i class="sw" style="background:${PALETTE[i%PALETTE.length]}"></i>
        ${c.label} ${fields}<button data-del="${i}" title="Remove">×</button></span>`;
    }).join("") +
    `<span class="chip2"><select id="addind"><option value="">+ add…</option>${opts}</select></span>`;

  $("#indbar").querySelectorAll("input[type=number]").forEach(inp =>
    inp.addEventListener("change", ()=>{
      INDS[+inp.dataset.i].args[+inp.dataset.j] = parseFloat(inp.value);
      saveSettings(); loadChart(CHART_SYMBOL);
    }));
  $("#indbar").querySelectorAll("[data-del]").forEach(btn =>
    btn.addEventListener("click", ()=>{
      INDS.splice(+btn.dataset.del,1); saveSettings(); loadChart(CHART_SYMBOL);
    }));
  const add = $("#addind");
  if(add) add.addEventListener("change", ()=>{
    const c = CATALOGUE.find(x=>x.name===add.value);
    if(c){ INDS.push({name:c.name, args:c.params.map(p=>p.default)}); saveSettings(); loadChart(CHART_SYMBOL); }
  });
}

// Chart appearance is user-owned. Defaults come from the theme, but anything the
// user sets overrides them and is remembered per theme — a colour chosen against
// a dark ground is usually wrong against a light one, so the two are stored
// separately rather than one clobbering the other.
// Versioned: a saved palette silently outranks a changed default, so shipping
// new defaults means nothing until the key moves. Bumping it is the difference
// between "I changed the buy colour" and "I changed the buy colour for anyone
// who has never touched the picker".
// v4: the fills are size-2 arrows with a halo (Phase 2, commit 4). A v3
// palette is carried over minus its marker size, so a colour the user chose
// survives and the new default size shows.
const STYLE_KEY = "investment-app.chartstyle.v4";

const STYLE_KEY_PREV = "investment-app.chartstyle.v3";

let STYLE = null;

function styleDefaults(){
  const t = chartTheme();
  return {up:t.up, down:t.down, resistance:t.furnitureHex, support:t.furnitureHex,
          buy:t.buy, sell:t.sell, dots:true,
          // Size 2: your fills are the one thing on this chart no other tool
          // can draw, and at size 1 they were dots. Dense names stay readable
          // because each arrow carries a halo in the ground colour.
          shape:"arrow", size:2, labels:true, tint:false};
}

function loadStyle(){
  const key = chartTheme().dark ? "dark" : "light";
  let saved = null;
  try{ saved = (JSON.parse(localStorage.getItem(STYLE_KEY) || "{}")[key]) || null; }
  catch(e){ saved = null; }
  if(!saved){
    try{ saved = (JSON.parse(localStorage.getItem(STYLE_KEY_PREV) || "{}")[key]) || {}; }
    catch(e){ saved = {}; }
    saved = {...saved}; delete saved.size;
  }
  return {...styleDefaults(), ...saved};
}

function saveStyle(){
  const key = chartTheme().dark ? "dark" : "light";
  try{
    const all = JSON.parse(localStorage.getItem(STYLE_KEY) || "{}");
    all[key] = STYLE;
    localStorage.setItem(STYLE_KEY, JSON.stringify(all));
  }catch(e){ /* storage disabled — the chart still renders */ }
}

function styleToForm(){
  $("#cUp").value = STYLE.up;       $("#cDown").value = STYLE.down;
  $("#cRes").value = STYLE.resistance; $("#cSup").value = STYLE.support;
  $("#cBuy").value = STYLE.buy;     $("#cSell").value = STYLE.sell;
  $("#mShape").value = STYLE.shape; $("#mSize").value = STYLE.size;
  $("#mLabel").checked = !!STYLE.labels; $("#mTint").checked = !!STYLE.tint;
  $("#mDots").checked = !!STYLE.dots;
}

function styleFromForm(){
  STYLE = {up:$("#cUp").value, down:$("#cDown").value,
           resistance:$("#cRes").value, support:$("#cSup").value,
           buy:$("#cBuy").value, sell:$("#cSell").value,
           shape:$("#mShape").value, size:Math.max(0, Math.min(4, +$("#mSize").value || 0)),
           labels:$("#mLabel").checked, tint:$("#mTint").checked,
           dots:$("#mDots").checked};
  saveStyle();
}

// In fullscreen the price pane takes whatever the other elements leave. The old
// rule reserved a fixed 260px, which cannot know how many indicator panes exist
// — so it left a band of dead space with no lower panes and overflowed with
// several. Flex does the arithmetic instead.
// A lower pane's chart honours its container's height WHEN IT IS CREATED and
// never afterwards. Neither the library's resizing method nor applyOptions with
// an explicit height moves the canvases, and neither raises an error: the
// container grows to 230px and the four canvases inside it stay at 130. So a
// finished drag REBUILDS the chart at the new height rather than pretending to
// resize it. That costs one /api/chart call, which the response cache answers
// in about six milliseconds.
function applyPaneHeights(){
  if(CHART_SYMBOL) loadChart(CHART_SYMBOL);
}

function sizeChart(){
  const panel = $("#chartpanel");
  if(CHART) CHART.applyOptions({autoSize:true});
  if(!panel.classList.contains("full")) return;
  requestAnimationFrame(()=>{
    // Resizing rescales the axis; going fullscreen should give you more of the
    // same chart, not reset it to everything you have ever had data for.
    restoreView();
  });
}

// ------------------------------------------------------------- pane size ----
const PANE_KEY = "portfolio.paneHeights";

function paneHeights(){
  try{ return JSON.parse(localStorage.getItem(PANE_KEY) || "{}") || {}; }
  catch(e){ return {}; }
}

function paneHeight(spec){
  const h = paneHeights()[spec];
  return (typeof h === "number" && h >= 40) ? h : null;
}

// The default height of every lower pane, chosen from the Panes control.
// Small is the point: with two or three oscillators the price chart was
// sharing the screen with them, and on a phone it was half of it. A dragged
// height still wins for that one pane; choosing a size clears the dragged
// heights so the choice actually shows.
// Volume never drops under 90px: at 44 the bars were a fringe along the
// bottom edge and a spike read as a slightly taller fringe.
const PANE_SIZES = {small: {ind: 64, vol: 90}, normal: {ind: 130, vol: 100}, large: {ind: 210, vol: 130}};

function paneSize(){
  const sel = $("#paneSize");
  const v = sel && sel.value;
  if(v && PANE_SIZES[v]) return v;
  // Nothing chosen yet: a narrow screen gets small, everything else normal.
  return (window.innerWidth || 1000) < 700 ? "small" : "normal";
}

function paneDefault(isVol){
  const sz = PANE_SIZES[paneSize()] || PANE_SIZES.normal;
  return isVol ? sz.vol : sz.ind;
}

function rememberPaneHeight(spec, px){
  try{
    const all = paneHeights();
    all[spec] = Math.round(px);
    localStorage.setItem(PANE_KEY, JSON.stringify(all));
  }catch(e){ /* private window; the drag still worked, it just will not persist */ }
}

// The bar you drag to resize the pane below it. Pointer capture is what makes a
// drag survive the pointer leaving the 7px strip — without it the resize stops
// the moment you move faster than the element follows, which feels broken.
function makeGrip(wrap, spec){
  const grip = document.createElement("div");
  grip.className = "panegrip";
  grip.title = "Drag to resize this pane";
  let startY = 0, startH = 0;
  grip.addEventListener("pointerdown", e=>{
    startY = e.clientY;
    startH = wrap.getBoundingClientRect().height;
    grip.setPointerCapture(e.pointerId);
    grip.classList.add("dragging");
    e.preventDefault();
  });
  // Floor at 40px: a pane shorter than its own axis labels is not a smaller
  // chart, it is an unreadable one.
  const applyTo = y => {
    wrap.style.height = Math.max(40, Math.min(600, startH + (y - startY))) + "px";
  };
  // The container follows the pointer live, so the drag has feedback; the chart
  // inside it is rebuilt once, on release.
  grip.addEventListener("pointermove", e=>{
    if(!grip.hasPointerCapture(e.pointerId)) return;
    applyTo(e.clientY);
  });
  const end = e => {
    if(!grip.hasPointerCapture(e.pointerId)) return;
    // Apply the RELEASE position too, not just the moves along the way. A fast
    // drag can go down and up with no pointermove in between, and without this
    // such a drag does nothing at all.
    applyTo(e.clientY);
    grip.releasePointerCapture(e.pointerId);
    grip.classList.remove("dragging");
    rememberPaneHeight(spec, wrap.getBoundingClientRect().height);
    applyPaneHeights();
  };
  grip.addEventListener("pointerup", end);
  grip.addEventListener("pointercancel", end);
  // Double-click restores the default, which is the only way back if a pane has
  // been dragged down to a sliver.
  grip.addEventListener("dblclick", ()=>{
    rememberPaneHeight(spec, spec === "volume" ? 72 : 130);
    applyPaneHeights();
  });
  return grip;
}

let CHART_REQUEST = 0;

// When the latest loadChart started, cleared once its response lands. Bounded
// by time as well, so a request that never returns cannot wedge the tab loader.
let CHART_STARTED = 0;

const chartInFlight = () => CHART_STARTED && Date.now() - CHART_STARTED < 30000;

// What the engine would have said on the replay date, from bars truncated
// to it — the same rule the replay lives by. Shown under the controls so a
// step through history reads the chart and the call together.
let ASOF_REQ = 0;

async function renderAsOfVerdict(symbol, asof){
  const el = $("#chartasof");
  if(!el) return;
  if(!asof){ el.innerHTML = ""; el.hidden = true; ASOF_LEVELS = null; return; }
  const token = ++ASOF_REQ;
  el.hidden = false;
  el.innerHTML = `<span class="note">Reading ${esc(symbol)} as of ${esc(asof)}…</span>`;
  let d;
  try{ d = await (await fetch("/api/outlook?" + new URLSearchParams({symbol, asof}))).json(); }
  catch(e){ if(token === ASOF_REQ) el.innerHTML = `<span class="note">Could not read that date.</span>`; return; }
  if(token !== ASOF_REQ) return;
  const v = d.verdict;
  if(!v){ el.innerHTML = `<span class="note">No bars for ${esc(symbol)} on or before ${esc(asof)}.</span>`; return; }
  const line = (tf, r) => !r || r.insufficient ? "" :
    `<span style="margin-right:14px">${tf} ${vdPill(r.verdict, r.confidence)}${
      r.flip != null ? `<span class="note"> flips ${money(r.flip)}</span>` : ""}</span>`;
  // The three prices as they stood that day, in the chart's colours: the
  // first timeframe with a level worth acting on, the way the page picks one.
  let w = null;
  for(const tf of ["daily", "weekly", "monthly"]){ const x = (v[tf] || {}).watch; if(x && (x.buy_at || x.trim_at || x.stop_at)){ w = x; break; } }
  ASOF_LEVELS = {symbol, asof, watch: w, flip: v.daily && v.daily.flip};
  drawVerdictLines(symbol);
  el.innerHTML = `<b>As of ${esc(asof)}</b> at ${money(v.daily && v.daily.price)} —
    ${line("monthly", v.monthly)}${line("weekly", v.weekly)}${line("daily", v.daily)}
    <span class="note">${esc((v.daily && v.daily.because && v.daily.because[0]) || "")}</span>
    <span class="note" style="margin-left:10px">no sentiment on a past date; scored as ${d.position ? "held" : "unheld"}.</span>
    ${w ? `<div class="threeline" style="margin-top:4px">${threePriceLine(w, v.daily && v.daily.flip)}</div>` : ""}`;
}

function stepAsOf(days){
  const el = $("#chartdate");
  if(!el) return;
  const base = el.value ? new Date(el.value + "T12:00:00") : new Date();
  base.setDate(base.getDate() + days);
  const today = new Date();
  if(base > today){ el.value = ""; }
  else el.value = base.toISOString().slice(0, 10);
  if(CHART_SYMBOL) loadChart(CHART_SYMBOL);
}

let CHART_OWN = false, CHART_OWN_FOR = null;

// Whether the pane is a plain price chart: a ratio or an overlay compare is
// on another scale, and a level in dollars means nothing drawn over it.
let CHART_PLAIN = true;

// Held so the browser check can ask whether they exist: the library gives no
// way to list a series' price lines.
let COST_LINE = null;

let VERDICT_LINES = [];

// The verdict's three prices — buy at / sell into / wrong below — and the
// flip, as labelled 1.5px lines in the ladder's colours. They come from the
// symbol page's payload (SYM_DATA), which loads on its own clock: loadChart
// draws them if that payload is in hand, and paintSymbol() calls this again
// when it lands, so whichever arrives second completes the picture. Replaced
// wholesale each time, since the page can repaint with a fresher row.
function drawVerdictLines(symbol){
  if(!CHART || !CANDLES) return;
  VERDICT_LINES.forEach(l => { try{ CANDLES.removePriceLine(l); }catch(e){} });
  VERDICT_LINES = [];
  if(!CHART_PLAIN || CHART_DRAWN !== symbol) return;
  // Bar replay: the levels as they stood on that day, from the as-of read,
  // never today's drawn over a chart that ends months ago.
  const asof = $("#chartdate") && $("#chartdate").value;
  let w, flip;
  if(asof){
    if(!ASOF_LEVELS || ASOF_LEVELS.symbol !== symbol || ASOF_LEVELS.asof !== asof) return;
    w = ASOF_LEVELS.watch || {}; flip = ASOF_LEVELS.flip;
  } else {
    const D = (SYM === symbol && SYM_DATA) ? SYM_DATA : null;
    const v = D && D.row;
    if(!v) return;
    w = v.watch || {}; flip = v.flip;
  }
  const th = chartTheme();
  const line = (price, color, title) => {
    if(price == null || isNaN(price)) return;
    try{
      VERDICT_LINES.push(CANDLES.createPriceLine({price:Number(price), color, lineWidth:1.5, lineStyle:0,
        axisLabelVisible:true, title}));
    }catch(e){ /* a price the scale has no room for: a ratio chart, or a log scale at zero */ }
  };
  line(w.buy_at, th.buyAt, "buy at");
  line(w.trim_at, th.trimAt, "sell into");
  line(w.stop_at, th.stopAt, "wrong below");
  if(flip != null && ![w.buy_at, w.trim_at, w.stop_at].includes(flip)) line(flip, th.muted, "flips");
}

// The as-of read's levels, kept for drawVerdictLines: {symbol, asof, watch, flip}.
let ASOF_LEVELS = null;

async function loadChart(symbol, how){
  if(!symbol) return;
  CHART_STARTED = Date.now();
  // `how` rather than `opts`: this function already declares a local `opts`
  // for the structure toggles further down, and shadowing it is a
  // SyntaxError that kills the entire script.
  how = how || {};
  // Lightweight Charts measures its container when it is constructed. Building
  // into a panel that is still hidden gives it a zero-size canvas, and the
  // library then throws "Value is null" from inside its own render loop — which
  // happens asynchronously, escapes every try/catch here, and leaves the page
  // half-initialised with no data anywhere.
  const host = $("#pricechart");
  for (let tries = 0; host.clientWidth === 0 && tries < 60; tries++) {
    await new Promise(r => requestAnimationFrame(r));
  }
  if (host.clientWidth === 0){ CHART_STARTED = 0; return; }   // still hidden; the tab loader retries
  // A token per request. An uncached symbol makes the server fetch from the
  // network and take seconds, while a cached one returns in milliseconds — so
  // typing NVDA then AAPL painted NVDA's candles over AAPL's, with the header,
  // the label and the saved setting all still saying AAPL. Only the newest
  // request is allowed to touch the DOM.
  const token = ++CHART_REQUEST;
  CHART_SYMBOL = symbol;
  $("#symbol").value = symbol;
  $("#chartsym").textContent = symbol;
  saveSettings();

  const q = new URLSearchParams({
    symbol, scope:$("#scope").value, years:$("#hist").value,
    timeframe:$("#tf").value, compare:$("#compare").value.trim().toUpperCase(),
    mode:$("#cmode").value, indicators: INDS.map(specOf).join(","),
    pivots: $("#stPivots").value || "3",
    fibback: $("#stFibBack").value || "120",
  });
  // The OTC line itself, once asked for; a new symbol goes back to the home listing.
  if(CHART_OWN && symbol === CHART_OWN_FOR) q.set("own", "1"); else { CHART_OWN = false; }
  CHART_OWN_FOR = symbol;
  // Bar replay: the chart as it stood at the close of the chosen day.
  const asof = $("#chartdate") && $("#chartdate").value;
  if(asof) q.set("to", asof);
  renderAsOfVerdict(symbol, asof);
  // Bypass the response cache on an explicit refresh. Without this the button
  // would return the same cached payload it was pressed to replace, which is a
  // refresh that refreshes nothing.
  if(how.refresh) q.set("_", Date.now());
  let res, d;
  try{
    res = await fetch("/api/chart?" + q, how.refresh ? {cache:"no-store"} : undefined);
    if(token !== CHART_REQUEST) return;        // superseded while in flight
    d = await res.json();
  } finally { if(token === CHART_REQUEST) CHART_STARTED = 0; }
  if(token !== CHART_REQUEST) return;

  if(d.catalogue && !CATALOGUE.length){ CATALOGUE = d.catalogue; }
  if(d.setups && $("#setup").options.length <= 1){
    SETUPS = d.setups;
    $("#setup").innerHTML = `<option value="">Custom</option>` +
      d.setups.map(x=>`<option value="${x.key}">${x.name}</option>`).join("");
  }
  renderIndBar();

  if(d.error || !d.bars || !d.bars.length){
    $("#chartinfo").textContent = d.error || (d.fetch && d.fetch.error) ||
      `No price history for ${symbol}.`;
    CHART_DRAWN = symbol;            // drawn as far as it can be; do not retry on every tab switch
    return;
  }
  CHART_DRAWN = symbol;

  const th = chartTheme();
  // Disposing matters more than clearing. innerHTML alone removes the canvas but
  // leaves the chart object alive with its range-sync subscription still
  // attached — and that handler writes into the CURRENT globals, so every
  // orphan kept shoving its own stale visible range into the new panes. The
  // symptom was a chart squashed into a corner after switching scale, which
  // looked like a log-scale bug and was really a leak.
  if(CHART){ try{ CHART.remove(); }catch(e){} }
  PANES.forEach(p=>{ try{ p.remove(); }catch(e){} });
  CHART = null; CANDLES = null; PANES = []; PANE_WRAPS = [];
  // The cloud overlay's observer watches an element that is about to be
  // replaced. Clearing innerHTML removes the canvas but not the observer, and
  // one is left behind on every redraw otherwise.
  if(CLOUD_RO){ try{ CLOUD_RO.disconnect(); }catch(e){} CLOUD_RO = null; }
  if(FILL_RO){ try{ FILL_RO.disconnect(); }catch(e){} FILL_RO = null; }
  const el = $("#pricechart"); el.innerHTML = "";
  $("#lowerwrap").innerHTML = "";

  // Log matters on anything that has multiplied: on a linear axis a move
  // from 2 to 4 is invisible beside one from 80 to 100, though the first
  // doubled your money and the second did not.
  const scaleMode = Number($("#scale").value || 0);
  const linear = scaleMode === 0;
  CHART = LightweightCharts.createChart(el, {
    autoSize:true,
    layout:{background:{color:"transparent"}, textColor:th.text, fontSize:11},
    grid:{vertLines:{color:th.grid}, horzLines:{color:th.grid}},
    // On a linear scale the bottom margin is applied by linearFloor() below,
    // in price, so it can stop at zero: the library's own 6% went below the
    // axis floor on any name whose range dwarfs its low, and IREN's axis
    // read −5.00.
    rightPriceScale:{borderColor:th.grid, scaleMargins:{top:0.06, bottom: linear ? 0 : 0.06},
      mode: scaleMode},
    timeScale:{borderColor:th.grid, rightOffset:4},
    crosshair:{mode: LightweightCharts.CrosshairMode.Normal,
      vertLine:{color:th.muted, labelBackgroundColor:th.muted},
      horzLine:{color:th.muted, labelBackgroundColor:th.muted}},
  });
  // The 6% the scale used to leave under the lowest bar, in price, floored at
  // zero. Given to every series on the price scale, since the scale takes the
  // union of what its series ask for.
  const linearFloor = baseInfo => {
    const r = baseInfo();
    if(!linear || !r || !r.priceRange) return r;
    const {minValue, maxValue} = r.priceRange;
    const below = (maxValue - minValue) * 0.06 / 0.88;
    const lo = minValue - below;
    return {...r, priceRange:{minValue: (minValue >= 0 && lo < 0) ? 0 : lo, maxValue}};
  };
  const ratio = d.compare && d.compare.mode === "ratio";
  if(!STYLE) STYLE = loadStyle();
  CANDLES = CHART.addCandlestickSeries({
    upColor:STYLE.up, downColor:STYLE.down, borderVisible:false,
    wickUpColor:STYLE.up, wickDownColor:STYLE.down,
    autoscaleInfoProvider: linearFloor,
  });

  // Tinting the candle you traded on is a better answer than a marker where
  // fills are dense: it puts the information on the bar itself instead of
  // stacking arrows above and below the price. A day with both a buy and a sell
  // is tinted as a buy, since that is the entry the level is usually read from.
  // Lightweight Charts wants a business-day STRING for daily bars and a UNIX
  // TIMESTAMP for intraday ones. Handing it "2026-08-28T20:00:00Z" draws an
  // empty pane and reports nothing, so every series is normalised here, once,
  // before anything reaches the library.
  if(d.intraday){
    const toEpoch = t => typeof t === "number" ? t : Math.floor(Date.parse(t) / 1000);
    ["bars","compare"].forEach(k=>{
      const src = k === "bars" ? d.bars : (d.compare && d.compare.bars);
      if(Array.isArray(src)) src.forEach(b => { b.time = toEpoch(b.time); });
    });
    Object.values(d.indicators || {}).forEach(sp=>{
      if(Array.isArray(sp.data)) sp.data.forEach(pt => { pt.time = toEpoch(pt.time); });
      else if(sp.data) Object.values(sp.data).forEach(arr =>
        Array.isArray(arr) && arr.forEach(pt => { pt.time = toEpoch(pt.time); }));
    });
    // STRUCTURE too. Missing it left pivots, trendlines, channels and fib
    // carrying ISO strings while the bars beside them were epoch numbers, so
    // the chart threw "time must be of type BusinessDay" from inside setData
    // the moment any of them was drawn on an intraday chart.
    Object.values(d.structure || {}).forEach(st=>{
      if(!st || typeof st !== "object") return;
      (st.pivots || []).forEach(pt => { pt.time = toEpoch(pt.time); });
      [].concat(st.trendlines || [], st.channels || []).forEach(l => {
        if(l.from) l.from.time = toEpoch(l.from.time);
        if(l.to) l.to.time = toEpoch(l.to.time);
      });
      if(st.fib){
        if(st.fib.from) st.fib.from.time = toEpoch(st.fib.from.time);
        if(st.fib.to) st.fib.to.time = toEpoch(st.fib.to.time);
      }
    });
  }

  const sideByDate = {};
  (d.marks || []).forEach(m=>{ if(!(m.date in sideByDate) || m.side === "buy")
    sideByDate[m.date] = m.side; });
  CANDLES.setData(STYLE.tint && !ratio ? d.bars.map(b=>{
    const side = sideByDate[b.time];
    if(!side) return b;
    const c = side === "buy" ? STYLE.buy : STYLE.sell;
    return {...b, color:c, wickColor:c, borderColor:c};
  }) : d.bars);

  // Comparison as a second line on its own scale — different price levels would
  // otherwise flatten one of them into the axis.
  let cmpSeries = null;
  if(d.compare && !ratio){
    cmpSeries = CHART.addLineSeries({color:th.line, lineWidth:2, priceScaleId:"cmp",
      priceLineVisible:false, lastValueVisible:true});
    cmpSeries.priceScale().applyOptions({scaleMargins:{top:0.08, bottom:0.22}});
    cmpSeries.setData(d.compare.bars.map(b=>({time:b.time, value:b.close})));
  }

  const series = {};
  Object.entries(d.indicators||{}).forEach(([spec, sp], idx)=>{
    const colour = PALETTE[INDS.findIndex(i=>specOf(i)===spec) % PALETTE.length] || chartTheme().muted;
    if(sp.error || !sp.data) return;
    // One indicator must never take the chart down with it. setData() throws on
    // a payload it does not expect, the exception escapes this callback, and
    // everything AFTER the indicator loop — the average-cost line, the trade
    // marks, and the whole structure overlay — silently never runs. That is why
    // turning Ichimoku on made HH/HL stop working: HH/HL was fine, it just never
    // got the chance to draw.
    try{
    if(sp.pane === "price"){
      // Multi-line indicators arrive as an OBJECT of named series, single-line
      // ones as an array. Only Bollinger was ever handled, so Keltner and
      // Ichimoku were handing a plain object to setData() and throwing.
      if(Array.isArray(sp.data)){
        // Moving averages are furniture: a hairline at three-quarter strength,
        // under the candles and well under the user's own marks.
        const s2 = CHART.addLineSeries({color:rgba(colour, .75), lineWidth:1,
          priceLineVisible:false, lastValueVisible:false, autoscaleInfoProvider: linearFloor});
        s2.setData(sp.data); series[spec] = s2;
      } else if(spec.startsWith("ichimoku")){
        // The cloud is the area BETWEEN span A and span B, and nothing else.
        // This drew two AREA series instead, each filling from its own line
        // down to the floor of the pane, because an area series fills to the
        // bottom rather than to another series — so most of the chart came out
        // shaded and only the overlap looked like a band. The mini chart hit
        // exactly this and was fixed with a canvas overlay; the same helper
        // does the job here, and takes its coordinates from the chart so it
        // survives pan and zoom.
        const th2 = chartTheme();
        // Declared before the legend that reads it. It was declared below and
        // used here, which is a temporal dead zone: every draw threw
        // "Cannot access 'wantLag' before initialization" and the whole
        // indicator silently failed to render.
        const wantLag = (sp.args || []).length > 3 && Number(sp.args[3]);
        // Five unlabelled lines is not a chart, it is a puzzle. Each one is
        // named with what it does, so the count stops being the question.
        const key = $("#cloudkey");
        if(key) key.innerHTML =
          `<b>Ichimoku</b> — <span style="color:${rgba(th2.up,1)}">cloud top
           (span A)</span>, <span style="color:${rgba(th2.down,1)}">cloud bottom
           (span B)</span>: the shaded band between them is support when price is
           above it and resistance when below, and it is drawn 26 sessions ahead
           of the bars it comes from.
           <span style="color:${colour}">Conversion</span> is the 9-session
           midpoint and <span style="color:${chartTheme().text}">base</span> the
           26-session one — "reclaiming the base" is the phrase for price winning
           that line back.
           ${wantLag ? "The dashed lagging span is today's close plotted 26 sessions in the PAST."
                     : "The lagging span is hidden; add <code>:1</code> to the indicator to show it."}`;
        if((sp.data.span_a||[]).length && (sp.data.span_b||[]).length){
          if(CLOUD_RO){ try{ CLOUD_RO.disconnect(); }catch(e){} CLOUD_RO = null; }
          const first = (sp.data.span_a[0] || {}).time;
          drawCloudBand(CHART, CANDLES, $("#pricechart"), sp.data, first, th2,
                        ro => { CLOUD_RO = ro; });
        }
        // Conversion and base are the lines a "reclaim the kijun" read uses, so
        // they stay solid and distinguishable; the lagging span is dashed
        // because it is plotted in the past and is easy to misread as current.
        // The lagging span is OFF unless asked for. Ichimoku is five lines and
        // that is a lot of chart; this is the one plotted 26 sessions in the
        // PAST, so it is both the least used and the easiest to misread as
        // current — which the old comment here said outright while drawing it
        // anyway. `ichimoku:9:26:52:1` turns it back on.
        [["conversion", colour, 2, 0], ["base", chartTheme().text, 3, 0]]
          .concat(wantLag ? [["lagging", colour, 2, 2]] : [])
          .forEach(([k, col, w, style])=>{
          if(!(sp.data[k]||[]).length) return;
          const s2 = CHART.addLineSeries({color:col, lineWidth:w, lineStyle:style,
            priceLineVisible:false, lastValueVisible:false});
          s2.setData(sp.data[k]); series[spec+"."+k] = s2;
        });
      } else {
        // Bollinger, Keltner, and any future banded indicator: middle solid,
        // the envelope dashed.
        Object.keys(sp.data).forEach(k=>{
          if(!(sp.data[k]||[]).length) return;
          const s2 = CHART.addLineSeries({color:rgba(colour, .75), lineWidth:1,
            lineStyle:k==="middle"?0:2, priceLineVisible:false, lastValueVisible:false,
            autoscaleInfoProvider: linearFloor});
          s2.setData(sp.data[k]); series[spec+"."+k] = s2;
        });
      }
    }
    }catch(err){
      console.error("[chart] indicator " + spec + " failed to draw:", err);
    }
    // Volume is deliberately NOT overlaid on the price pane. Reserving the
    // bottom fifth of that scale for it is what made the candles small, and on
    // a log scale the reserved margin is taken in log space, which stretched the
    // axis to 1.60-140 for data spanning 5-76 and squashed the candles into a
    // band in the middle.
  });

  // What is YOURS is the only 2px solid ink on the pane: the average cost,
  // with its price filled on the axis; the buy-back floor; your buy plans and
  // the watchlist's target and stop, in the amber reserved for your levels.
  CHART_PLAIN = !ratio && !d.compare;
  COST_LINE = null;
  if(d.position && d.position.avg_cost && CHART_PLAIN){
    COST_LINE = CANDLES.createPriceLine({price:d.position.avg_cost, color:th.mineCost, lineWidth:2,
      lineStyle:0, axisLabelVisible:true, title:"avg cost"});
  }
  // The plan's levels, on the chart the trade is made from: the ladder's
  // sell rung and the buy-back under it (D78). Named levels below are
  // furniture; the chosen buy-back is yours.
  if(d.plan && CHART_PLAIN){
    if(d.plan.sell_at) CANDLES.createPriceLine({price:d.plan.sell_at, color:th.mineLevel, lineWidth:2, lineStyle:0, axisLabelVisible:true, title:"ladder sell"});
    if(d.plan.buy_back) CANDLES.createPriceLine({price:d.plan.buy_back, color:th.upStrong, lineWidth:2, lineStyle:0, axisLabelVisible:true, title:"buy back"});
    (d.plan.named || []).filter(x => x.level !== d.plan.buy_back).slice(0, 3).forEach(x =>
      CANDLES.createPriceLine({price:x.level, color:th.furniture, lineWidth:1, lineStyle:2, axisLabelVisible:false, title:""}));
  }
  if(CHART_PLAIN){
    (PLANS || []).filter(x => x.symbol === symbol && x.max_price).forEach(x =>
      CANDLES.createPriceLine({price:x.max_price, color:th.mineLevel, lineWidth:2, lineStyle:0, axisLabelVisible:true, title:"your buy plan"}));
    const wlr = WATCHLIST && (WATCHLIST.rows || []).find(r => r.symbol === symbol);
    if(wlr && wlr.target) CANDLES.createPriceLine({price:wlr.target, color:th.mineLevel, lineWidth:2, lineStyle:0, axisLabelVisible:true, title:"your target"});
    if(wlr && wlr.stop) CANDLES.createPriceLine({price:wlr.stop, color:th.mineLevel, lineWidth:2, lineStyle:0, axisLabelVisible:true, title:"your stop"});
  }
  // The three prices the read resolves to, and the flip, from the symbol
  // page's payload — drawn now if it is in hand, and by paintSymbol() when it
  // lands after the candles, so the chart and the ladder always agree.
  drawVerdictLines(symbol);

  const marks = d.marks || [];
  const labelled = marks.length <= 25;
  const opts = structOpts();
  const priceStruct = (d.structure||{}).price;
  const hidden = hiddenLines();
  drawStructure(CHART, priceStruct, {...opts, host:CANDLES, hidden,
                                    lastTime: d.bars.length ? d.bars[d.bars.length-1].time : null,
                                    lastClose: d.bars.length ? d.bars[d.bars.length-1].close : null});
  if(VPROF_RO){ try{ VPROF_RO.disconnect(); }catch(e){} VPROF_RO = null; }
  $("#pricechart").querySelectorAll("canvas.vprofile").forEach(c => c.remove());
  if(opts.vprof && d.volume_profile){
    drawVolumeProfile(CHART, CANDLES, $("#pricechart"), d.volume_profile, chartTheme(),
                      ro => { VPROF_RO = ro; });
  }
  attachDrawings(d);

  // One chip per drawn line, each removable. This is the only way to get rid of
  // a line the detector drew and you disagree with.
  const shown = (priceStruct && priceStruct.trendlines || []).filter(l=>!hidden.has(lineId(l)));
  const SC = structColours();          // drawStructure keeps its own copy locally
  const legend = $("#structlegend");
  const fibNote = (opts.fib && priceStruct && priceStruct.fib)
    ? `<span class="note" style="margin-left:6px">Fib measured from the largest
       move in the last ${esc($("#stFibBack").value)} bars:
       <b>${esc(priceStruct.fib.from.time)}</b> $${priceStruct.fib.from.price}
       → <b>${esc(priceStruct.fib.to.time)}</b> $${priceStruct.fib.to.price}
       (${esc(priceStruct.fib.direction)}). That is a guess at which swing you
       mean — change the bar count to point it at a different one.</span>`
    : "";

  legend.innerHTML = fibNote + (!opts.lines ? "" : (
    shown.map(l=>`<span class="chip2">
        <i class="sw" style="background:${SC[l.side]}"></i>
        ${l.side} <span class="note">${l.confirmations} confirming bar${l.confirmations===1?"":"s"}</span>
        <button data-hide="${esc(lineId(l))}" title="Remove this line">×</button></span>`).join("")
    + (hidden.size ? `<span class="chip2"><button data-restore="1">Restore ${hidden.size} hidden</button></span>` : "")
    + (shown.length || hidden.size
        ? `<span class="note" style="margin-left:6px">Lines are drawn from recent pivots.
           Tested against shuffled versions of this same series they score no better than
           chance, so treat them as reference geometry, not as confirmation.</span>` : "")));

  legend.querySelectorAll("[data-hide]").forEach(b =>
    b.addEventListener("click", ()=>{
      const set = hiddenLines(); set.add(b.dataset.hide); setHiddenLines(set);
      loadChart(CHART_SYMBOL);
    }));
  // A data attribute rather than an id, because this button only exists while
  // something is hidden — a dynamic id would look like a missing element to the
  // check that every referenced id is present in the markup.
  const restore = legend.querySelector("[data-restore]");
  if(restore) restore.addEventListener("click", ()=>{
    setHiddenLines(new Set()); loadChart(CHART_SYMBOL);
  });

  // Your own fills are the one thing on this chart no other tool can draw, so
  // they are the loudest marks on it: size-2 arrows in a colour that belongs
  // to nothing else (blue and magenta, outside the candles' red and green —
  // a purchase on a down day painted green would read as an up candle), each
  // with a one-pixel halo in the ground colour so it stays legible over a
  // wick, a grid line or a moving average, on either theme. The library's own
  // markers cannot be outlined, so they are painted on an overlay canvas that
  // follows the chart through pan, zoom and resize — the same mechanism as
  // the Ichimoku cloud. Shape, size and labels are still the user's to set
  // under Appearance, including switching the arrows off entirely, which is
  // the sensible pairing with candle tinting rather than having both shout.
  if(FILL_RO){ try{ FILL_RO.disconnect(); }catch(e){} FILL_RO = null; }
  $("#pricechart").querySelectorAll("canvas.fillmarks").forEach(c => c.remove());
  if(!ratio && STYLE.shape !== "none" && marks.length){
    drawFillMarks(CHART, CANDLES, $("#pricechart"), marks, d.bars, STYLE, th, labelled,
                  ro => { FILL_RO = ro; });
  }
  // A marker can only sit above, below or centred on a bar — it cannot sit at a
  // price. So the fill price gets its own series with the connecting line
  // hidden, which puts a dot exactly where the trade happened inside the
  // candle's range rather than merely on the day it happened. A second series
  // in the ground colour, one pixel wider and drawn first, is the halo.
  if(STYLE.dots && !ratio){
    [["buy", STYLE.buy], ["sell", STYLE.sell]].forEach(([side, colour])=>{
      const pts = marks.filter(m => m.side === side && m.price)
                       .map(m => ({time:m.date, value:m.price}));
      if(!pts.length) return;
      const r = Math.max(2, (STYLE.size || 1) + 1);
      [[th.bg, r + 1], [colour, r]].forEach(([col, radius]) => {
        const dot = CHART.addLineSeries({
          color:col, lineVisible:false, pointMarkersVisible:true,
          pointMarkersRadius: radius,
          priceLineVisible:false, lastValueVisible:false,
          crosshairMarkerVisible:false, autoscaleInfoProvider: linearFloor,
        });
        dot.setData(pts);
      });
    });
  }

  // The structure labels (HH, HL…) keep the library's marker layer to themselves.
  const structMarks = opts.labels ? structureMarkers(priceStruct).map(
    m => ({...m, color: th.text})) : [];
  CANDLES.setMarkers(structMarks.sort((a,b)=> a.time < b.time ? -1 : a.time > b.time ? 1 : 0));

  // Lower panes: one chart each, all panned together with the price. Volume
  // rides here too, in a shorter pane of its own.
  Object.entries(d.indicators||{}).forEach(([spec, sp])=>{
    const isVol = sp.pane === "volume";
    if((sp.pane !== "lower" && !isVol) || sp.error || !sp.data) return;
    const wrap = document.createElement("div");
    // Heights were fixed at 72px and 130px with no way to change them, so an
    // RSI pane was the same size whether it was the only one or one of five.
    // Remembered per indicator, per device, like the rest of the view state.
    wrap.style.height = (paneHeight(spec) || paneDefault(isVol)) + "px";
    wrap.style.marginTop = "0";
    $("#lowerwrap").appendChild(makeGrip(wrap, spec));
    $("#lowerwrap").appendChild(wrap);
    const lc = LightweightCharts.createChart(wrap, {
      // Sized at creation from its container, which is the only moment this
      // chart takes any notice of it — see applyPaneHeights().
      autoSize:false,
      width: wrap.clientWidth, height: wrap.clientHeight,
      // One attribution for the whole chart: the price pane carries it, and
      // every lower pane is the same chart continued, not a second one.
      layout:{background:{color:"transparent"}, textColor:th.text, fontSize:11, attributionLogo:false},
      grid:{vertLines:{color:"transparent"}, horzLines:{color:th.grid}},
      rightPriceScale:{borderColor:th.grid},
      timeScale:{borderColor:th.grid, visible:false},
      crosshair:{vertLine:{color:th.muted, labelBackgroundColor:th.muted},
                 horzLine:{color:th.muted, labelBackgroundColor:th.muted}},
    });
    const colour = PALETTE[INDS.findIndex(i=>specOf(i)===spec) % PALETTE.length] || chartTheme().line;
    if(isVol){
      // Coloured by the candle it belongs to, so a volume spike is immediately
      // readable as buying or selling rather than as a neutral bar.
      const dir = Object.fromEntries(d.bars.map(b=>[b.time, b.close >= b.open]));
      const h = lc.addHistogramSeries({priceFormat:{type:"volume"}, priceLineVisible:false});
      h.setData(padToBars(d.bars, sp.data.map(v=>({time:v.time, value:v.value,
        color: dir[v.time] ? th.volUp : th.volDown}))));
    } else if(spec.startsWith("macd")){
      const h = lc.addHistogramSeries({priceLineVisible:false});
      h.setData(padToBars(d.bars, sp.data.histogram.map(p=>({time:p.time, value:p.value,
        color: p.value>=0 ? rgba(th.upStrong, .5) : rgba(th.downStrong, .5)}))));
      lc.addLineSeries({color:colour, lineWidth:2, priceLineVisible:false})
        .setData(padToBars(d.bars, sp.data.macd));
      lc.addLineSeries({color:th.muted, lineWidth:1, priceLineVisible:false})
        .setData(padToBars(d.bars, sp.data.signal));
    } else if(spec.startsWith("stoch")){
      lc.addLineSeries({color:colour, lineWidth:2, priceLineVisible:false})
        .setData(padToBars(d.bars, sp.data.k));
      lc.addLineSeries({color:th.muted, lineWidth:1, priceLineVisible:false})
        .setData(padToBars(d.bars, sp.data.d));
    } else {
      const ls = lc.addLineSeries({color:colour, lineWidth:2, priceLineVisible:false});
      ls.setData(padToBars(d.bars, sp.data));
      (sp.bounds||[]).forEach(lvl => ls.createPriceLine({price:lvl,
        color:th.furniture, lineWidth:1, lineStyle:2,
        axisLabelVisible:true, title:String(lvl)}));
    }
    // Structure on the oscillator itself. RonnieV, StonkChris and Cantonese Cat
    // all do this by hand; Fibonacci is deliberately left off a lower pane,
    // where it has no accepted meaning.
    const oscStruct = (d.structure||{})[spec];
    let oscNote = "";
    if(opts.osc && oscStruct && !oscStruct.insufficient){
      drawStructure(lc, oscStruct, {lines:opts.lines, channel:opts.channel,
                                    fib:false, hidden});
      const n = (oscStruct.trendlines||[]).length;
      if(n) oscNote = `  · ${n} line${n>1?"s":""}`;
    }

    const tag = document.createElement("div");
    tag.className = "panelabel";
    tag.textContent = (sp.label||spec) + (sp.args && sp.args.length ? " " + sp.args.join(", ") : "") + oscNote;
    wrap.appendChild(tag);
    PANES.push(lc);
    PANE_WRAPS.push(wrap);
  });

  sizeChart();

  // Keep every pane on the same visible range.
  const sync = r => { if(!r) return; PANES.forEach(p => p.timeScale().setVisibleLogicalRange(r)); };
  CHART.timeScale().subscribeVisibleLogicalRangeChange(sync);
  PANES.forEach(p => p.timeScale().subscribeVisibleLogicalRangeChange(r =>
    r && CHART.timeScale().setVisibleLogicalRange(r)));

  // Crosshair readout — OHLC, volume and every indicator value at the cursor.
  // Volume in particular had no way of being read before.
  const fmt = n => n==null ? "—" : (Math.abs(n) >= 1000
    ? n.toLocaleString(undefined,{maximumFractionDigits:0})
    : n.toLocaleString(undefined,{maximumFractionDigits:2}));
  const barByTime = Object.fromEntries(d.bars.map(b=>[b.time,b]));
  function paint(param){
    const t = param && param.time ? param.time : d.bars[d.bars.length-1].time;
    const b = barByTime[t]; if(!b) return;
    const up = b.close >= b.open;
    // Intraday times are UNIX timestamps, which is what the chart library
    // wants and not what a person reads: the legend was showing "1787947200".
    const when = typeof t === "number"
      ? new Date(t * 1000).toLocaleString(undefined,
          {month:"short", day:"numeric", hour:"2-digit", minute:"2-digit"})
      : t;
    let html = `<span><b>${when}</b></span>
      <span>O <b>${fmt(b.open)}</b></span><span>H <b>${fmt(b.high)}</b></span>
      <span>L <b>${fmt(b.low)}</b></span>
      <span>C <b style="color:${up?"var(--up)":"var(--down)"}">${fmt(b.close)}</b></span>
      <span>Vol <b>${fmt(b.volume)}</b></span>`;
    Object.entries(d.indicators||{}).forEach(([spec, sp])=>{
      if(sp.error || !sp.data) return;
      if(spec === "volume") return;      // already shown in the OHLC block
      const pick = arr => { const hit = arr && arr.find(p=>p.time===t); return hit ? hit.value : null; };
      let val;
      if(Array.isArray(sp.data)) val = pick(sp.data);
      else val = Object.entries(sp.data).map(([k,v])=>`${k[0]} ${fmt(pick(v))}`).join(" ");
      if(val === null || val === undefined || val === "") return;
      const lbl = (sp.label||spec) + (sp.args && sp.args.length ? " "+sp.args.join(",") : "");
      html += `<span>${lbl} <b>${typeof val === "number" ? fmt(val) : val}</b></span>`;
    });
    if(d.compare && !ratio){
      const c = d.compare.bars.find(x=>x.time===t);
      if(c) html += `<span>${d.compare.symbol} <b>${fmt(c.close)}</b></span>`;
    }
    $("#readout").innerHTML = html;
  }
  CHART.subscribeCrosshairMove(paint);
  paint(null);

  restoreView();
  CHART.timeScale().subscribeVisibleTimeRangeChange(scheduleRememberView);

  const buys = marks.filter(m=>m.side==="buy").length;
  const p = d.position;
  const tfName = {D:"daily", W:"weekly", M:"monthly", Q:"quarterly",
                  "5m":"5-minute", "15m":"15-minute", "1h":"hourly"}[d.timeframe] || "";
  $("#chartinfo").innerHTML =
    `${d.bars.length} ${tfName} bars` +
    (d.compare ? ` · ${ratio?"ratio vs":"vs"} ${d.compare.symbol}` : "") +
    (marks.length ? ` · ${buys} buy / ${marks.length-buys} sell bars (${(d.fills||[]).length} fills)` : "") +
    (p ? ` · holding ${p.quantity.toLocaleString()} @ ${money(p.avg_cost)}, now ${money(p.price)}
          (<span style="${col(p.unrealised)}">${pct(p.unrealised_pct)}</span>)` : "") +
    (d.proxy ? `<div class="note" style="margin-top:4px">Drawn from <b>${esc(d.proxy.symbol)}</b>, the home listing, rescaled into ${esc(d.symbol)}'s currency (×${d.proxy.factor}) — ${d.proxy.proxy_bars} bars against ${d.proxy.own_bars} on the OTC line. The verdict, the ladder and the buy-back readings use these same bars. <a href="#" id="chartown">Show the OTC line instead</a></div>` : "");
  const ownLink = $("#chartown");
  if(ownLink) ownLink.addEventListener("click", ev => { ev.preventDefault(); CHART_OWN = true; CHART_OWN_FOR = d.symbol; loadChart(d.symbol); });

  renderAnalysis(d.analysis);
}

// The three prices and the flip as one line, in the colours the chart draws
// them in — used by the Technical read and the as-of line so a level reads
// the same wherever it appears.
function threePriceLine(w, flip){
  w = w || {};
  const cell = (label, px, col) => px == null ? "" :
    `<span style="margin-right:14px;white-space:nowrap"><span class="tlk">${label}</span> <b style="color:${col}">${money(px)}</b></span>`;
  const out = cell("Buy at", w.buy_at, "var(--buy)") + cell("Sell into", w.trim_at, "var(--trim)")
            + cell("Wrong below", w.stop_at, "var(--down)")
            + (flip != null && ![w.buy_at, w.trim_at, w.stop_at].includes(flip) ? cell("Flips", flip, "var(--muted)") : "");
  return out;
}

function renderAnalysis(a){
  if(!a){ $("#tapanel").innerHTML = `<div class="note">Not enough history to analyse.</div>`; return; }
  const tone = b => b.includes("bull") ? "var(--up)" : b.includes("bear") ? "var(--down)" : "var(--muted)";
  // The nearest support and resistance the frame found, in the chart's
  // furniture grey with the same dashed rule the lines are drawn with.
  const srLine = f => {
    const L = f.levels || {};
    const one = (arr, label) => (arr || []).length
      ? `<span style="margin-right:12px">${label} ${arr.slice(0, 2).map(l => `<span class="srlvl">${money(l.price)}</span>`).join(" · ")}</span>` : "";
    const txt = one(L.support, "Support") + one(L.resistance, "Resistance");
    return txt ? `<div class="note" style="margin:4px 0 2px">${txt}</div>` : "";
  };
  const cards = a.frames.map(f=> f.insufficient
    ? `<div class="tfcard"><h4>${f.timeframe}</h4><div class="note">Only ${f.bars} bars — not enough.</div></div>`
    : `<div class="tfcard">
         <h4>${f.timeframe}
           <span class="verdict" style="color:${tone(f.bias)};background:var(--bg-1)">${f.bias}</span></h4>
         <div class="note">${f.trend} · close ${money(f.close)}</div>
         ${srLine(f)}
         <ul>${f.observations.map(o=>`<li>${o}</li>`).join("")}</ul>
       </div>`).join("");
  // The verdict's three prices lead, when the page has them for this name.
  // Not during bar replay: the as-of line above carries that day's levels,
  // and today's would sit over a reading of a different day.
  const replay = $("#chartdate") && $("#chartdate").value;
  const row = (!replay && SYM === a.symbol && SYM_DATA && SYM_DATA.row) ? SYM_DATA.row : null;
  const three = row ? threePriceLine(row.watch, row.flip) : "";
  $("#tapanel").innerHTML =
    (three ? `<div class="threeline" style="margin:0 0 10px">${three}<span class="note">the levels drawn on the chart</span></div>` : "") +
    (a.summary||[]).map(s2=>`<p style="margin:0 0 8px">${s2}</p>`).join("") +
    `<div class="tfgrid">${cards}</div>` +
    `<div class="note" style="margin-top:10px">Observations, not advice — every line names the
      number behind it so you can disagree with it.</div>`;
}
