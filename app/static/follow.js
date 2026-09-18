// Who I follow: research artifacts, the graded accounts, the record form, the Substack and VT charts.
// One of the dashboard's scripts (see dashboard.html): a classic script sharing the page's
// global scope with the others, loaded in the order the tags there give.

// The four artifact kinds are deliberately not merged into one list. A thesis
// and a setup answer different questions, and a reader who cannot tell them
// apart will end up trading a supply-chain argument on a weekly candle.
let RESEARCH = null;

const RES_TF = {D:"daily", W:"weekly", M:"monthly", Q:"quarterly"};

function resList(kind){
  const map = {setup:"setups", framework:"frameworks",
               intermarket:"intermarket", macro:"macro", thesis:"theses"};
  return (RESEARCH && RESEARCH[map[kind]]) || [];
}

function resBullets(title, items){
  if(!items || !items.length) return "";
  return `<p style="margin:12px 0 4px"><b>${title}</b></p>
    <ul style="margin:0;padding-left:18px;display:flex;flex-direction:column;gap:5px;font-size:14px">
      ${items.map(i=>`<li>${esc(i)}</li>`).join("")}</ul>`;
}

// Their charts: one grid over three sources — the charts the followed
// accounts post on X (saved nightly by account, xcharts.py), StonkChris's
// Substack charts, and the Value Trader's Patreon charts — filtered by who,
// which name and when. "Side by side by name" groups them by ticker so two
// people's charts of the same name sit next to each other, which is what the
// user asked for on 2026-09-13: pull the charts in by account, then compare.
const VT_AUTHOR = "The Value Trader";
let CHARTS = null;             // every chart from every source, newest first
let CHART_NOTES = {};          // per-source notes for the header line

function chartFilters(){
  const v = id => { const el = $(id); return el ? el.value : ""; };
  return {author: v("#scauthor"), sym: v("#scsym"), from: v("#scfrom"), to: v("#scto"),
          hide: !!($("#schide") && $("#schide").checked), byName: !!($("#scbyname") && $("#scbyname").checked)};
}

function inDateRange(f, day){
  return (!f.from || (day || "") >= f.from) && (!f.to || (day || "").slice(0, 10) <= f.to);
}

function fillChartFilters(){
  const a = $("#scauthor"), sy = $("#scsym");
  if(!a || !sy || !CHARTS) return;
  const keepA = a.value, keepS = sy.value;
  const names = [...new Set(CHARTS.map(r => r.author).filter(Boolean))].sort();
  a.innerHTML = `<option value="">everyone</option>` + names.map(n => `<option>${esc(n)}</option>`).join("");
  a.value = keepA;
  const syms = [...new Set(CHARTS.flatMap(r => r.symbols))].sort();
  sy.innerHTML = `<option value="">every name</option>` + syms.map(n => `<option>${esc(n)}</option>`).join("");
  sy.value = keepS;
}

function wireChartFilters(){
  ["#scauthor", "#scsym", "#scfrom", "#scto", "#schide", "#scbyname"].forEach(id => {
    const el = $(id);
    if(el && !el.dataset.wired){ el.dataset.wired = "1"; el.addEventListener("change", drawCharts); }
  });
  const c = $("#scclear");
  if(c && !c.dataset.wired){
    c.dataset.wired = "1";
    c.addEventListener("click", () => {
      ["#scauthor", "#scsym", "#scfrom", "#scto"].forEach(id => { const el = $(id); if(el) el.value = ""; });
      ["#schide", "#scbyname"].forEach(id => { const el = $(id); if(el) el.checked = false; });
      drawCharts();
    });
  }
}

// Every source into one shape: {source, author, date, symbols, timeframe,
// image, text, post_url, tag}. A chart with no cashtag keeps its account and
// no name, and shows when that account is chosen.
async function loadSubstackCharts(){
  const note = $("#scnote"), box = $("#sccharts");
  if(!box) return;
  const rows = [];
  const notes = {};
  const get = async (url) => { try{ return await (await fetch(url)).json(); }catch(e){ return {error: String(e)}; } };
  const [x, sc, vt] = await Promise.all([get("/api/x-charts"), get("/api/substack-charts"), get("/api/valuetrader")]);
  // One person is one entry in the Who list whichever place they posted. The
  // X rows name the author "StonkChris (@StonkChris)" and the Substack rows
  // "StonkChris", and until 2026-09-17 those were two people in the filter:
  // picking the natural one showed his Substack charts only, so his X chart
  // of FPS from that week was "not in the app" however the user filtered
  // (D134). The handle is kept for the card's own use.
  (x.charts || []).forEach(r => rows.push({source: "X", author: (r.author || r.handle || "").split(" (")[0], handle: r.handle, date: r.date, symbols: r.symbols || [],
    timeframe: "", image: r.images[0], text: r.text || "", post_url: r.post_url, tag: null}));
  notes.x = x.error ? "X charts could not be read." : `${(x.charts || []).length} from X`;
  (sc.charts || []).forEach(r => rows.push({source: "Substack", author: r.author || "StonkChris", date: r.date, symbols: [r.symbol],
    timeframe: r.timeframe, image: r.images[0], text: r.text || "", post_url: r.post_url, tag: null}));
  notes.sc = sc.error ? "Substack charts could not be read." : `${(sc.charts || []).length} from the Substack`;
  if(vt.configured === false || vt.error) notes.vt = vt.note || vt.error || "Gmail is not connected.";
  else {
    (vt.posts || []).filter(p => p.has_image).forEach(p => rows.push({source: "Patreon", author: VT_AUTHOR, date: p.email_date, symbols: p.symbols || [],
      timeframe: "", image: `/chart-image?id=${p.post_id}`, text: `${p.subject || ""} — ${p.teaser || ""}`, post_url: p.post_url, tag: p.action || null}));
    notes.vt = `${(vt.posts || []).filter(p => p.has_image).length} from the Value Trader's Patreon`;
  }
  rows.sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  CHARTS = rows; CHART_NOTES = notes;
  if(!rows.length){
    note.innerHTML = `No charts saved yet: the X pull saves them nightly from 2026-09-14; the Substack pull needs its session (<code>./substack-setup.sh</code>).`;
    return;
  }
  fillChartFilters();
  wireChartFilters();
  drawCharts();
}

function loadValueTrader(){ return Promise.resolve(); }   // folded into loadSubstackCharts

function chartCard(r, held){
  return `<div class="panel" style="padding:8px">
    <a href="${esc(safeUrl(r.image))}" target="_blank" rel="noopener">
      <img src="${esc(safeUrl(r.image))}" alt="" loading="lazy" decoding="async" style="width:100%;height:auto;border-radius:6px"></a>
    <div style="margin-top:6px">
      ${r.symbols.map(s => `<span class="clickable" data-sym="${esc(s)}" style="color:var(--accent);font-weight:600;margin-right:6px">${esc(s)}</span>`).join("")}
      <span class="note">${esc(r.author.split(" (")[0])} · ${esc(r.source)}${r.timeframe ? " · " + esc(r.timeframe) : ""} · ${esc(r.date)}</span>
      ${r.tag ? ` <span class="vd vd-${r.tag === "sell" ? "sell" : "buy"}">${esc(r.tag)}</span>` : ""}
      ${r.symbols.some(s => held.has(s)) ? `<span class="vd vd-none">held</span>` : ""}
    </div>
    <div class="note" style="font-size:13px;margin-top:4px">${esc(r.text.slice(0, 260))}${r.text.length > 260 ? "…" : ""}</div>
    ${r.post_url ? `<a href="${esc(safeUrl(r.post_url))}" target="_blank" rel="noopener" class="note">the post</a>` : ""}
  </div>`;
}

function drawCharts(){
  const note = $("#scnote"), box = $("#sccharts");
  if(!box || !CHARTS) return;
  const f = chartFilters();
  const held = new Set(Object.keys((OUTLOOK && OUTLOOK.verdicts) || {}));
  const shown = CHARTS.filter(r => (!f.author || r.author === f.author) && (!f.sym || r.symbols.includes(f.sym))
    && inDateRange(f, r.date) && !(f.hide && r.symbols.length && r.symbols.every(s => held.has(s))));
  const span = shown.length ? ` ${esc(shown[shown.length - 1].date)} to ${esc(shown[0].date)}` : "";
  note.innerHTML = `${shown.length} of ${CHARTS.length} charts (${Object.values(CHART_NOTES).map(esc).join(", ")}), ${new Set(shown.flatMap(r => r.symbols)).size} names${span}, newest first.`;
  const grid = list => `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px">${list.map(r => chartCard(r, held)).join("")}</div>`;
  if(!shown.length){ box.innerHTML = `<div class="note">No saved chart matches these filters.</div>`; return; }
  if(!f.byName){ box.innerHTML = grid(shown.slice(0, 80)) + (shown.length > 80 ? `<div class="note" style="margin-top:6px">${shown.length - 80} older not shown — narrow the dates or pick a name.</div>` : ""); return; }
  // Side by side: one section per name, the newest chart from each person
  // first, names charted by the most people at the top.
  const bySym = {};
  shown.forEach(r => r.symbols.forEach(s => (bySym[s] = bySym[s] || []).push(r)));
  const syms = Object.keys(bySym).sort((a, b) => new Set(bySym[b].map(r => r.author)).size - new Set(bySym[a].map(r => r.author)).size || bySym[b][0].date.localeCompare(bySym[a][0].date));
  box.innerHTML = syms.slice(0, 40).map(s => {
    const list = bySym[s];
    const people = [...new Set(list.map(r => r.author))];
    const newest = people.map(a => list.find(r => r.author === a));
    const rest = list.filter(r => !newest.includes(r));
    return `<details class="group" ${people.length > 1 ? "open" : ""}><summary><b>${esc(s)}</b> <span class="count">${people.length} ${people.length === 1 ? "person" : "people"} · ${list.length} chart${list.length === 1 ? "" : "s"}</span>
        <span class="note" style="margin-left:8px">${people.map(a => esc(a.split(" (")[0])).join(" · ")}</span></summary>
      <div style="padding:8px 0">${grid(newest)}${rest.length ? `<details style="margin-top:6px"><summary class="note">${rest.length} older chart${rest.length === 1 ? "" : "s"} of ${esc(s)}</summary><div style="padding-top:8px">${grid(rest.slice(0, 24))}</div></details>` : ""}</div>
    </details>`;
  }).join("") + (syms.length > 40 ? `<div class="note">${syms.length - 40} more names — narrow the filters.</div>` : "");
}

async function loadResearch(){
  loadValueTrader();
  if(!RESEARCH) RESEARCH = await (await fetch("/api/research")).json();
  if(RESEARCH.error){ $("#resnote").textContent = RESEARCH.error; return; }
  const kind = $("#reskind").value;
  const list = resList(kind);
  $("#ressel").innerHTML = list.map(a=>`<option value="${a.key}">${esc(a.name)}</option>`).join("");
  renderOutside(RESEARCH.outside);
  await showResearch();
}

// The followed accounts' calls, per author, with every call's 5/21/63-day
// grade. Same table shape as the journal so the eye reads it the same way.
function renderOutside(o){
  const el = $("#outsidetable");
  if(!el) return;
  if(!o || !o.authors || !o.authors.length){
    el.innerHTML = `<p class="note">No outside call recorded yet. Record one above from a chart you saved.</p>`;
    $("#oaAuthors").innerHTML = "";
    return;
  }
  $("#oaAuthors").innerHTML = o.authors.map(a=>`<option value="${esc(a.author)}">`).join("");
  const pct = v => v == null ? "—" : `${(v*100).toFixed(1)}%`;
  const pts = v => v == null ? "—" : `${v >= 0 ? "+" : ""}${(v*100).toFixed(2)}`;
  const hcell = (h) => {
    if(!h) return `<td class="note">—</td>`;
    if(h.status !== "scored") return `<td class="note">${h.status === "open" ? "open" : "no price"}</td>`;
    const col = h.right ? "var(--up)" : "var(--down)";
    return `<td style="color:${col}" title="return ${pct(h.return)} vs SPY ${pct(h.benchmark)}">${pts(h.score)}</td>`;
  };
  el.innerHTML = o.authors.map(a=>`
    <details class="panel"${a.n >= (o.min_sample || 20) ? " open" : ""} style="margin-top:10px">
      <summary style="cursor:pointer"><b>${esc(a.author)}</b>
        <span class="note" style="margin-left:8px">${a.recorded} recorded${(() => { const k = a.calls.filter(c => c.confidence === "auto").length; return k ? ` (${k} read nightly from X)` : ""; })()}, ${a.n} graded at ${o.horizon} days${a.n ? `, hit rate ${pct(a.hit_rate)}, mean ${pts(a.mean_score)}% vs SPY` : ""}</span></summary>
      <p class="note" style="margin:8px 0">${esc(a.verdict)}</p>
      <div style="overflow-x:auto"><table style="width:100%">
        <tr><th>Date</th><th>Symbol</th><th>Call</th><th>Price</th><th>Level</th><th>5d</th><th>21d</th><th>63d</th><th>What they said</th><th></th></tr>
        ${a.calls.slice(0, 25).map(c=>`<tr>
          <td>${esc(c.date)}</td><td><b>${esc(c.symbol)}</b></td><td>${esc(c.action)}${c.confidence === "auto" ? ` <span class="pill" title="Read from the words of the post by the nightly X pull, not by a person. The words it matched are in brackets. Wrong? Remove it with the ×.">auto</span>` : ""}</td>
          <td>${c.entry != null ? Number(c.entry).toFixed(2) : "—"}</td>
          <td>${c.flip != null ? Number(c.flip).toFixed(2) : "—"}</td>
          ${hcell(c.horizons[5])}${hcell(c.horizons[21])}${hcell(c.horizons[63])}
          <td class="note">${esc(c.rationale || "")}</td>
          <td><button class="oaDel" data-id="${c.id}" title="Remove this call" style="padding:0 6px">×</button></td>
        </tr>`).join("")}
      </table>${a.calls.length > 25 ? `<div class="note">${a.calls.length - 25} older calls not shown.</div>` : ""}</div>
    </details>`).join("") + `<p class="note" style="margin-top:8px">All followed accounts together: ${esc(o.overall.verdict)}</p>`;
}

async function recordOutside(){
  const q = new URLSearchParams({action:"outside",
    author: $("#oaAuthor").value.trim(), symbol: $("#oaSymbol").value.trim(),
    date: $("#oaDate").value, price: $("#oaPrice").value, decision: $("#oaCall").value,
    level: $("#oaLevel").value, note: $("#oaNote").value});
  const r = await (await fetch("/api/outlook?" + q.toString())).json();
  if(r.error){ $("#oaStatus").textContent = r.error; return; }
  $("#oaStatus").textContent = `Recorded ${r.author} on ${r.symbol}, ${r.decision}, ${r.date}.`;
  ["#oaSymbol","#oaPrice","#oaLevel","#oaNote"].forEach(id => { $(id).value = ""; });
  if(RESEARCH) RESEARCH.outside = r.outside;
  renderOutside(r.outside);
}

document.addEventListener("change", (e)=>{
  if(e.target && e.target.id === "paneSize"){
    try{ localStorage.removeItem(PANE_KEY); }catch(err){}
    saveSettings();
    if(CHART_SYMBOL) loadChart(CHART_SYMBOL);
  }
});

document.addEventListener("click", async (e)=>{
  const del = e.target.closest && e.target.closest(".oaDel");
  if(del){
    const r = await (await fetch(`/api/outlook?action=outside_delete&id=${encodeURIComponent(del.dataset.id)}`)).json();
    if(r.error){ $("#oaStatus").textContent = r.error; return; }
    if(RESEARCH) RESEARCH.outside = r.outside;
    renderOutside(r.outside);
    return;
  }
  if(e.target.id === "oaRecord") recordOutside();
});

async function showResearch(){
  const kind = $("#reskind").value, key = $("#ressel").value;
  if(!key){ $("#resdetail").innerHTML = "<p class=\"note\">Nothing recorded yet.</p>"; return; }
  // noscan=1: the "which names satisfy it now" table is the one method
  // scanner under Stocks → New Stocks, fed by /api/methods; the artifact page
  // links to it rather than running the same scan a second time. An older
  // server ignores the flag and the scan it sends back is simply not drawn.
  const d = await (await fetch(`/api/research?kind=${kind}&key=${encodeURIComponent(key)}&noscan=1`)).json();
  const x = d.detail;
  if(!x || x.error){ $("#resdetail").innerHTML = `<p class="note">${esc((x&&x.error)||"not found")}</p>`; return; }

  const meta = resList(kind).find(a=>a.key === key) || {};
  // Confidence is the first thing shown because it changes how much weight the
  // rest deserves: "stated" is quoted from the source, "inferred" is deduced,
  // and "proposed" belongs to nobody but this app.
  const conf = meta.confidence || x.confidence || "";
  let html = `<div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap">
      <b>${esc(x.name || meta.name || key)}</b>
      ${meta.attribution||x.attribution ? `<span class="note">${esc(meta.attribution||x.attribution)}</span>`:""}
      ${conf ? `<span class="pill">${esc(conf)}</span>`:""}
      ${x.timeframe ? `<span class="pill">${RES_TF[x.timeframe]||x.timeframe}</span>`:""}
      ${x.pair ? `<span class="pill">${esc(x.pair)}</span>`:""}
    </div>`;
  if(x.claim)   html += `<p style="margin:10px 0 0;font-size:14px">${esc(x.claim)}</p>`;
  if(x.summary) html += `<p style="margin:10px 0 0;font-size:14px">${esc(x.summary)}</p>`;
  if(x.reading && !Array.isArray(x.reading))
    html += `<p style="margin:10px 0 0;font-size:14px">${esc(x.reading)}</p>`;

  if(x.state){
    html += `<p style="margin:12px 0 0;font-size:14px"><b>Now:</b> ${esc(x.state)}
      as of ${esc(x.as_of)}${x.last_bullish_cross
        ? ` — last bullish cross ${esc(x.last_bullish_cross)}, his window
            ${esc(x.window.opens)} to ${esc(x.window.closes)}` : ""}</p>`;
    if(x.crosses && x.crosses.length)
      html += `<p class="note" style="margin:4px 0 0">Crosses in usable history (from
        ${esc(x.usable_from)}): ${x.crosses.map(c=>`${c.time} ${c.direction}`).join(", ")}</p>`;
  }

  if(Array.isArray(x.reading)) html += resBullets("How it is read", x.reading);
  if(x.mechanism)  html += resBullets("Mechanism", x.mechanism);

  if(x.links){
    html += `<p style="margin:12px 0 4px"><b>Where it touches the book</b></p>
      <table style="font-size:13px"><tr><th scope=col>Symbol</th><th scope=col>Role</th><th scope=col>Exposure</th><th scope=col>Note</th></tr>
      ${x.links.map(l=>`<tr><td>${esc(l.symbol)}</td><td>${esc(l.role)}</td>
        <td>${l.held ? `held${l.weight?` ${l.weight}%`:""}` : (l.watchlist?"watchlist":"—")}</td>
        <td class="note">${esc(l.note)}</td></tr>`).join("")}</table>`;
  }
  if(x.buckets){
    html += x.buckets.map(b=>`<p style="margin:12px 0 4px"><b>${esc(b.name)}</b>
      ${b.share?`<span class="note"> — ${esc(b.share)}</span>`:""}</p>
      <ul style="margin:0;padding-left:18px;font-size:14px">
        ${b.rules.map(r=>`<li>${esc(r)}</li>`).join("")}</ul>`).join("");
  }
  if(x.checks){
    html += `<p style="margin:12px 0 4px"><b>Checked against the ledger</b></p>
      <table style="font-size:13px">${x.checks.map(c=>`<tr>
        <td>${c.holds === null ? `<span class="yn">?</span>` : yesNo(c.holds)}</td>
        <td>${esc(c.rule)}</td><td class="note">${esc(c.detail||"")}</td></tr>`).join("")}</table>`;
  }

  // A scannable setup — one encoded as a method — has its "which names
  // satisfy it now" table under Stocks → New Stocks, By method, which is the
  // one scanner (it used to be drawn here too, from a second run of the same
  // scan). The link opens it with this method chosen.
  if(x.scan){
    html += `<p class="note" style="margin:14px 0 4px">Which names on your lists satisfy it now: <a href="#stocks/newstocks?method=${encodeURIComponent(x.scan)}">Stocks → New Stocks, By method → ${esc(meta.name || key)}</a>.</p>`;
  }

  html += resBullets("In their words", x.quotes);
  html += resBullets("What would make it wrong", x.falsifiers);
  html += resBullets("Caveats", x.caveats);
  if(x.indicators)
    html += `<p class="note" style="margin:12px 0 0">Indicators: ${x.indicators.join(", ")}</p>`;
  $("#resdetail").innerHTML = html;
  $("#resnote").textContent = "";
}

document.addEventListener("DOMContentLoaded", () => {
  const fold = $("#methodsfold");
  if(fold) fold.addEventListener("toggle", () => { if(fold.open && !fold.dataset.loaded){ fold.dataset.loaded = "1"; loadMethods(); } });
  // The fold that borrows another view's loader: the "levels the methods
  // wait at" table is drawn by loadDiagnose, through the same path its own
  // view uses.
  const dl = $("#dxlevelsfold");
  if(dl) dl.addEventListener("toggle", () => { if(dl.open) ensureTab("today/todo"); });
});
