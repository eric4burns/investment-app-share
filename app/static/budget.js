// Budget: the bank half, Amazon, the Get started screen, category trends.
// One of the dashboard's scripts (see dashboard.html): a classic script sharing the page's
// global scope with the others, loaded in the order the tags there give.

// One tile per category, showing its own twelve-ish months. A single total says
// where money went; it cannot say whether groceries are creeping up or last
// month's travel was a one-off, which is the question people actually bring to
// a budget.
// Per-category spend, month by month. Two things decide whether this is
// readable at all, and the first version got one of them wrong.
//
// SCALE. It originally put every tile on ONE shared scale, reasoning that
// per-tile scaling draws a $40 category and a $2,600 one as the same picture.
// That is a real failure mode, but on this data the opposite one is far worse:
// Taxes peaks near $9,400 and sets the ceiling, which left Utilities' TALLEST
// bar 1.5px high and Subscriptions' 2.2px. Thirteen of nineteen categories were
// flat lines — the chart was unreadable for most of what it drew. So each tile
// now scales to its own peak by default and PRINTS that peak above the bars,
// which keeps the magnitude honest without flattening the shape. Shared scale
// is still one click away for cross-category comparison.
//
// RANGE. Twelve months cannot show a year-over-year pattern: every month has
// exactly one comparison point and a seasonal category looks like a trend. The
// ledger holds 25 months, so the default is 24 and everything is available.
let _catTrend = null;                 // last payload, so the controls re-render

let _catRange = 24;                   // months shown; 0 means everything

let _catScale = "own";                // "own" | "shared"

function smTip(){
  let el = document.getElementById("smtip");
  if(!el){
    el = document.createElement("div");
    el.id = "smtip";
    document.body.appendChild(el);
  }
  return el;
}

// What was left over each month: income minus everything spent. Kept separate
// from the stacked income/spending chart above because a difference between two
// tall bars is the one thing a stacked chart cannot show — the eye cannot
// subtract, and $12,078 against $6,858 does not read as "$5,220 saved".
//
// It has a real zero line rather than bars from the floor. Two months here are
// NEGATIVE (Nov 2024 and Jun 2025, the latter -$4,837), and drawing those the
// same way up as a surplus would invert the meaning of the chart on exactly the
// months worth noticing.
//
// "Saved" is income minus expense, which is not the same as what reached a
// brokerage. Over this ledger the two differ by a lot and the note says so.
function drawSavedMonths(d){
  const el = $("#bgSaved");
  if(!el) return;
  const rows = (d.by_month || []).map(r => {
    const inc = r.income || 0, exp = Math.abs(r.expense || 0);
    return {month: r.month, inc, exp, saved: inc - exp,
            inv: Math.abs(r.investment || 0)};
  });
  if(!rows.length){ el.innerHTML = `<div class="note">No months yet.</div>`; return; }

  const H = 96;
  const hi = Math.max(...rows.map(r => r.saved), 0);
  const lo = Math.min(...rows.map(r => r.saved), 0);
  const span = (hi - lo) || 1;
  const upH = Math.round(H * (hi / span));      // pixels above the zero line

  const totInc = rows.reduce((a, r) => a + r.inc, 0);
  const totSaved = rows.reduce((a, r) => a + r.saved, 0);
  const totInv = rows.reduce((a, r) => a + r.inv, 0);
  const avg = totSaved / rows.length;
  const rate = totInc ? totSaved / totInc * 100 : 0;
  const negs = rows.filter(r => r.saved < 0);

  el.innerHTML = `<div class="note">
      Income minus everything spent, month by month. Averaging
      <b>${money(avg)}</b> a month — a <b>${rate.toFixed(0)}%</b> savings rate
      across ${rows.length} months.${negs.length
        ? ` ${negs.length} month${negs.length>1?"s":""} went the other way:
            ${negs.map(r=>esc(r.month)).join(", ")}.` : ""}
      Hover a column for the month.</div>
    <div class="svchart" style="height:${H}px">
      <div class="svzero" style="top:${upH}px"></div>` +
    rows.map(r => {
      const h = Math.max(2, Math.round(Math.abs(r.saved) / span * H));
      const up = r.saved >= 0;
      // Each column is the full height with the bar pushed to meet the zero
      // line, so every bar starts from the same baseline rather than from
      // wherever its own column happens to end.
      const pad = up ? upH - h : upH;
      return `<div class="svcol" data-m="${esc(r.month)}" data-s="${r.saved}"
                   data-i="${r.inc}" data-e="${r.exp}" data-v="${r.inv}">
          <i style="height:${pad}px;background:transparent;border-radius:0"></i>
          <i class="${up ? "" : "neg"}" style="height:${h}px;
             background:${up ? "var(--up-strong)" : "var(--down-strong)"}"></i>
        </div>`;
    }).join("") + `</div>
    <div class="bgaxis">${rows.map(r=>`<span>${esc(r.month.slice(2))}</span>`).join("")}</div>
    <div class="note" style="margin-top:9px">
      Saved is income minus spending — not what reached a brokerage. Over these
      ${rows.length} months you saved <b>${money(totSaved)}</b> and moved
      <b>${money(totInv)}</b> into investments, so
      ${totInv > totSaved
        ? `<b>${money(totInv - totSaved)}</b> more went in than these months
           earned, which means it came from cash you already held.`
        : `<b>${money(totSaved - totInv)}</b> of it stayed as cash.`}</div>`;

  const chart = el.querySelector(".svchart");
  const tip = smTip();
  let hot = null;
  const clear = () => { if(hot){ hot.classList.remove("hot"); hot = null; }
                        tip.style.display = "none"; };
  chart.addEventListener("mousemove", ev => {
    const col = ev.target.closest(".svcol");
    if(!col){ clear(); return; }
    if(col !== hot){ if(hot) hot.classList.remove("hot");
                     hot = col; hot.classList.add("hot"); }
    const s = +col.dataset.s, inc = +col.dataset.i;
    tip.innerHTML = `<div class="t1">${esc(col.dataset.m)}</div>
      <div class="t2" style="color:${s>=0?"var(--up)":"var(--down)"}">
        ${money(s)}${s>=0?" saved":" over"}</div>
      <div class="t3">in ${money(inc)} · out ${money(+col.dataset.e)}
        · ${inc ? Math.round(s/inc*100) : 0}% rate</div>
      <div class="t3">to investments ${money(+col.dataset.v)}</div>`;
    tip.style.display = "block";
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = (ev.clientX + 14 + w > window.innerWidth
                      ? ev.clientX - w - 14 : ev.clientX + 14) + "px";
    tip.style.top = Math.max(6, ev.clientY - h - 12) + "px";
  });
  chart.addEventListener("mouseleave", clear);
}

function drawCategoryTrends(d){
  if(d) _catTrend = d;
  d = _catTrend;
  const el = $("#bgCatTrend");
  if(!el || !d) return;
  const months = d.category_months || [];
  const rows = (d.by_category_month || []).filter(r => r.total > 0);
  if(!months.length || !rows.length){
    el.innerHTML = `<div class="note">Not enough history to chart.</div>`;
    return;
  }

  const span = _catRange > 0 ? Math.min(_catRange, months.length) : months.length;
  const from = months.length - span;
  const shown = months.slice(from);
  // Only used when the scale is shared; each tile otherwise takes its own.
  const peak = Math.max(...rows.map(r => Math.max(...r.values.slice(from).map(Math.abs))), 1);
  const lastMonth = shown[shown.length-1];
  const lastLabel = new Date(lastMonth + "-01T00:00:00")
    .toLocaleString(undefined, {month: "short"});
  // The newest month is usually STILL RUNNING. Comparing three days of it
  // against a full-month average would print a large negative on every tile at
  // the start of every month and call it a finding. So when the last month is
  // the current one, the average is pro-rated to the days elapsed and the
  // label says "so far" — the comparison stays live all month instead of
  // being either misleading or withheld.
  const now = new Date();
  const curKey = now.getFullYear() + "-" + String(now.getMonth()+1).padStart(2, "0");
  const partial = lastMonth === curKey;
  const daysIn = new Date(now.getFullYear(), now.getMonth()+1, 0).getDate();
  const frac = partial ? Math.min(1, now.getDate() / daysIn) : 1;

  const opt = (v, label, cur) =>
    `<option value="${v}"${v == cur ? " selected" : ""}>${esc(label)}</option>`;

  el.innerHTML = `<div class="smctl">
      <label>Months
        <select id="smrange">
          ${opt(12, "Last 12", _catRange)}${opt(24, "Last 24", _catRange)}
          ${opt(36, "Last 36", _catRange)}${opt(0, `All (${months.length})`, _catRange)}
        </select></label>
      <label>Scale
        <select id="smscale">
          ${opt("own", "Each tile its own", _catScale)}
          ${opt("shared", "Shared across tiles", _catScale)}
        </select></label>
    </div>
    <div class="note" style="margin-bottom:10px">
      ${esc(shown[0])} to ${esc(shown[shown.length-1])}. ${_catScale === "own"
        ? `Each tile scales to its own peak, printed above its bars — so shape is
           comparable between tiles but HEIGHT is not.`
        : `Every tile shares one scale, so a tall bar means more money wherever
           you see it — but small categories will look flat.`}
      The figure beside each category name is the MONTHLY AVERAGE over the window
      shown, counting months with no spend. Below the bars, the latest month is
      given as a percentage against that average — the highlighted bar. Hover any
      bar for its own month and figure.</div>
    <div class="smgrid${span > 14 ? " wide" : ""}">` +
    rows.map(r=>{
      const vals = r.values.slice(from);
      const own = Math.max(...vals.map(Math.abs), 1);
      const ceiling = _catScale === "own" ? own : peak;
      const recent = vals[vals.length-1] || 0;
      // Monthly average across the WHOLE window, zero months included. A month
      // with no spend is a real month you did not spend in, and dropping it
      // answers a different question ("what does this cost when it happens")
      // than the one a budget line asks ("what does this cost me a month").
      // Pets reads $281.74 across all 24 months against $422.62 on the months
      // it actually billed in — a 50% difference from the denominator alone.
      const avg = vals.reduce((a, v) => a + Math.abs(v), 0) / Math.max(1, vals.length);
      const expected = avg * frac;          // what this far into the month buys
      const delta = expected ? (Math.abs(recent) - expected) / expected : null;
      return `<div class="smcell">
        <div class="smhead"><span class="smname">${esc(r.category)}</span>
          <span class="smnum">${money(avg)}/mo</span></div>
        <div class="smbars" data-cat="${esc(r.category)}">
          <span class="smmax">${_catScale === "own" ? "peak " + money(own) : ""}</span>
          ${vals.map((v,i)=>{
            // A month with real spend must never round to nothing, or "small"
            // and "none" become the same picture.
            const h = v ? Math.max(2, Math.round(Math.abs(v) / ceiling * 52)) : 1;
            return `<i class="${i === vals.length-1 ? "last" : ""}"
                       data-m="${esc(shown[i])}" data-v="${v}"
                       style="height:${h}px"></i>`;
          }).join("")}</div>
        <div class="smfoot">${!avg ? "nothing in this window"
          : !recent ? `nothing in ${esc(lastLabel)}${partial ? " yet" : ""}`
          : delta != null && Math.abs(delta) >= 0.25
            ? `${esc(lastLabel)}${partial ? " so far" : ""} <b style="color:${delta>0?"var(--down)":"var(--up)"}">${delta>0?"+":""}${Math.round(delta*100)}%</b> vs avg`
            : `${esc(lastLabel)}${partial ? " so far" : ""} in line with avg`}</div>
      </div>`;
    }).join("") + `</div>`;

  const rerender = () => drawCategoryTrends(null);
  const rs = $("#smrange"), ss = $("#smscale");
  if(rs) rs.onchange = e => { _catRange = +e.target.value; rerender(); };
  if(ss) ss.onchange = e => { _catScale = e.target.value; rerender(); };

  // One delegated listener on the grid rather than one per bar: with 19
  // categories over 25 months that is 475 bars, and 475 listeners is how a
  // hover starts costing more than the render did.
  const grid = el.querySelector(".smgrid");
  const tip = smTip();
  let hot = null;
  const clear = () => {
    if(hot){ hot.classList.remove("hot"); hot = null; }
    tip.style.display = "none";
  };
  grid.addEventListener("mousemove", ev => {
    const bar = ev.target.closest(".smbars > i");
    if(!bar){ clear(); return; }
    if(bar !== hot){
      if(hot) hot.classList.remove("hot");
      hot = bar; hot.classList.add("hot");
    }
    const cat = bar.parentElement.dataset.cat || "";
    const v = +bar.dataset.v || 0;
    tip.innerHTML = `<div class="t1">${esc(bar.dataset.m)}</div>
      <div class="t2">${money(v)}</div>
      <div class="t3">${esc(cat)}</div>`;
    tip.style.display = "block";
    // Flip to the left of the cursor near the right edge, so the tooltip is
    // never clipped by the window on the rightmost tile in a row.
    const w = tip.offsetWidth, h = tip.offsetHeight;
    const x = ev.clientX + 14 + w > window.innerWidth ? ev.clientX - w - 14 : ev.clientX + 14;
    const y = Math.max(6, ev.clientY - h - 12);
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  });
  grid.addEventListener("mouseleave", clear);
}

async function loadAmazon(){
  const el = $("#bgAmazon");
  if(!el) return;
  let d;
  try{ d = await (await fetch("/api/amazon")).json(); }
  catch(e){ el.innerHTML = `<div class="note">Amazon check unavailable.</div>`; return; }
  if(!d.configured){ el.innerHTML = `<div class="note">${esc(d.note)}</div>`; return; }
  if(d.error){ el.innerHTML = `<div class="note">${esc(d.error)}</div>`; return; }
  const row = (o, extra) => `<tr><td>${esc(o.order || "—")}</td><td class=num>${money(o.amount || 0)}</td><td>${extra}</td></tr>`;
  if(!(d.owed || []).length && !(d.open || []).length){
    el.innerHTML = `<div class="note">Amazon: nothing to chase — ${d.emails} return and refund emails in the window, ${d.credits_seen} credits on the cards, all matched.</div>`;
    return;
  }
  el.innerHTML = `
    <div class="note" style="margin-bottom:8px">${d.emails} return and refund emails in the last window, ${d.credits_seen} Amazon credits on the cards.</div>
    <h3 style="margin:6px 0">Refund issued, not yet on a card <span class="note">${d.owed.length ? money(d.owed_total) : "none"}</span></h3>
    ${d.owed.length ? `<div class="tscroll"><table><tr><th scope=col>Order</th><th class=num scope=col>Refund</th><th scope=col>Status</th></tr>
      ${d.owed.map(o => row(o, `Amazon said issued ${esc(o.issued)}, ${o.days_since_issued} days ago${o.late ? ` — <b style="color:var(--down)">late; chase it</b>` : " — a card credit usually takes 3 to 10 days"}`)).join("")}</table></div>` : ""}
    <h3 style="margin:12px 0 6px">Returns started, no refund email yet <span class="note">${d.open.length || "none"}</span></h3>
    ${d.open.length ? `<div class="tscroll"><table><tr><th scope=col>Order</th><th class=num scope=col>Amount</th><th scope=col>Last heard</th></tr>
      ${d.open.map(o => row(o, `${esc((o.events[o.events.length-1].kind || "").replace("_", " "))} on ${esc(o.events[o.events.length-1].date || "?")}`)).join("")}</table></div>` : ""}
    <h3 style="margin:12px 0 6px">Refunds that reached a card <span class="note">${d.matched.length}</span></h3>
    ${d.matched.length ? `<div class="tscroll"><table><tr><th scope=col>Order</th><th class=num scope=col>Refund</th><th scope=col>Credited</th></tr>
      ${d.matched.slice(0, 20).map(o => row(o, `${esc(o.credit_date)} on ${esc(o.account || "")}`)).join("")}</table></div>` : ""}`;
}

// The last week of alerts, sent or not. What was sent says where; what was
// not says why in the channel line, so a silent phone is never a mystery.
// Bills due before the next pay lands, against the cash in the bank.
function renderDue(u){
  const el = $("#bgDue");
  if(!el) return;
  if(!u || u.error){ el.innerHTML = `<div class="note">Bills before payday: ${esc((u && u.error) || "not available")}</div>`; return; }
  const bills = u.bills || [];
  const ok = u.after == null ? null : u.after >= 0;
  el.innerHTML = `<div style="display:flex;gap:18px;flex-wrap:wrap;align-items:baseline">
      <div><span class="k">Due before payday</span> <b>${money(u.total)}</b> <span class="note">${bills.length} bill${bills.length === 1 ? "" : "s"}${u.next_payday ? ` before ${esc(u.next_payday)}` : ""}${u.last_pay ? ` (last pay ${esc(u.last_pay)}, every ${u.pay_step_days} days)` : ""}</span></div>
      <div><span class="k">Bank cash</span> <b>${u.cash == null ? "—" : money(u.cash)}</b></div>
      <div><span class="k">Left after them</span> <b style="color:${ok == null ? "inherit" : ok ? "var(--up)" : "var(--down)"}">${u.after == null ? "—" : money(u.after)}</b></div>
    </div>
    ${bills.length ? `<table style="font-size:13px;margin-top:6px"><tr><th scope=col>Due</th><th scope=col>Bill</th><th class=num scope=col>Usual</th><th scope=col></th></tr>${bills.map(b => `<tr>
      <td class="note">${esc(b.due)}</td><td>${esc(b.merchant || "")}</td><td class=num>${money(b.amount)}</td><td class="note">${b.overdue ? "expected already — not seen yet" : esc(b.cadence || "")}</td></tr>`).join("")}</table>` : `<div class="note" style="margin-top:4px">No recurring bill is expected before the next pay.</div>`}`;
}

// The first-run screen, and the "Import files" door for later exports. A
// friend who downloads the archive never sees data/, never runs an importer,
// never edits config.json: they export from the broker, drop the file here,
// paste a free price key, and the same dashboard fills in.
let GS_STATUS = null;

async function openGetStarted(force){
  const el = $("#getstarted");
  if(!el) return;
  if(!force && !el.hidden){ el.hidden = true; return; }
  el.hidden = false;
  el.innerHTML = loadingHTML("Reading what this install has…");
  try{ GS_STATUS = await (await fetch("/api/setup")).json(); }
  catch(e){ el.innerHTML = `<div class="note">Could not read the setup state.</div>`; return; }
  renderGetStarted();
  el.scrollIntoView({behavior: "smooth", block: "start"});
}

function renderGetStarted(){
  const el = $("#getstarted"), st = GS_STATUS;
  if(!el || !st) return;
  const kinds = st.kinds || {};
  const tick = ok => `<span style="font-weight:700;color:${ok ? "var(--up)" : "var(--muted)"}">${ok ? "✓" : "○"}</span>`;
  const kindRow = k => `<details style="margin:6px 0" ${k === "fidelity" ? "open" : ""}><summary style="cursor:pointer">${tick(st.files[k] > 0)} <b>${esc(kinds[k].label)}</b> <span class="note">${st.files[k] ? `${st.files[k]} file${st.files[k] === 1 ? "" : "s"} in` : "none yet"}</span></summary>
      <ol class="note" style="margin:6px 0 6px 18px;line-height:1.6">${(kinds[k].steps || []).map(x => `<li>${esc(x)}</li>`).join("")}</ol>
      <label class="note">Drop the file: <input type="file" data-gskind="${k}" accept="${kinds[k].ext.join(",")}" multiple></label>
      <div class="note" data-gsresult="${k}"></div></details>`;
  el.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px">
      <h2 style="margin:0">Get started <span class="note" style="font-weight:400">— everything stays on this computer</span></h2>
      <button class="attngo" id="gsclose">close</button></div>
    <div class="note" style="margin:6px 0 10px">${st.transactions ? `${st.transactions.toLocaleString()} transactions in the ledger.` : "The ledger is empty."} Python ${esc(st.python)} on ${esc(st.platform)}.</div>
    ${!st.transactions ? `<div class="panel" style="border-left:3px solid var(--accent);margin-bottom:10px">
      <b>Want to see it working first?</b> <span class="note">Load a made-up year — a brokerage account with a few real tickers, a checking account with pay, rent and bills, and a credit card — so every tab has something on it. Nothing here is anyone's real money; every account is called "Sample". Take it out again with one click when your own exports are ready.</span>
      <div style="margin-top:8px"><button class="attngo primary" id="gssample">Load sample data</button> <span class="note" id="gssamplemsg"></span></div></div>`
    : st.sample ? `<div class="panel" style="border-left:3px solid var(--warn);margin-bottom:10px">
      <b>This is sample data.</b> <span class="note">Every figure in the app is from the made-up year. When your own exports are ready, remove it here first, then drop them in below.</span>
      <div style="margin-top:8px"><button class="attngo" id="gsunsample">Remove sample data</button> <span class="note" id="gssamplemsg"></span></div></div>` : ""}
    <h3 style="margin:10px 0 4px">1. Your exports <span class="note" style="font-weight:400">— a file per account, as far back as the site allows; re-dropping a file is safe, nothing is counted twice</span></h3>
    ${["fidelity", "robinhood", "bank", "cards", "payroll"].map(kindRow).join("")}
    <h3 style="margin:14px 0 4px">2. Share prices <span class="note" style="font-weight:400">— click once after your exports are in; no account needed</span></h3>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:6px">
      <button class="attngo primary" id="gsprices">fetch prices now</button>
      <span class="note" id="gskeymsg"></span></div>
    <details style="margin:4px 0"><summary class="note" style="cursor:pointer">${tick(st.alpaca)} Optional: a free Alpaca key for the better price feed <span class="note">— email only, no SSN, no funding</span></summary>
    <ol class="note" style="margin:4px 0 6px 18px;line-height:1.6">
      <li>Go to <b>app.alpaca.markets/signup</b> and create a free account.</li>
      <li>After signing in, open the <b>Paper Trading</b> dashboard and click <b>View API keys</b>, then <b>Generate</b>.</li>
      <li>Paste the two values here. They are written to a file on this computer only.</li></ol>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <input id="gskey" placeholder="API Key ID" style="width:220px" autocomplete="off">
      <input id="gssecret" placeholder="Secret key" type="password" style="width:260px" autocomplete="off">
      <button class="attngo" id="gssavekey">save key</button></div></details>
    <h3 style="margin:14px 0 4px">3. Tax profile ${tick(st.age)} <span class="note" style="font-weight:400">— sets every bracket and limit on the Budget's Taxes tab</span></h3>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <select id="gsstatus"><option value="single" ${st.filing_status === "single" ? "selected" : ""}>single</option><option value="married_jointly" ${st.filing_status === "married_jointly" ? "selected" : ""}>married, filing jointly</option><option value="head_of_household" ${st.filing_status === "head_of_household" ? "selected" : ""}>head of household</option></select>
      <input id="gsage" type="number" min="18" max="100" placeholder="age" value="${st.age || ""}" style="width:80px">
      <button class="attngo" id="gssaveprofile">save</button><span class="note" id="gsprofilemsg"></span></div>
    <h3 style="margin:14px 0 4px">4. Reload the page</h3>
    <div class="note">Every tab fills in from the imports. The nightly refresh (SETUP.md, "Running it all the time") keeps prices current after that.</div>`;
  $("#gsclose").addEventListener("click", () => { $("#getstarted").hidden = true; });
  el.addEventListener("click", ev => { if(ev.target.closest("[data-gsreload]")) location.reload(); });
  // The sample year in, or out. Both reload the whole page afterwards: every
  // tab reads the ledger, and a stale Overview beside a fresh Get started
  // would look like the load did nothing.
  [["#gssample", "sample", "Loading the sample year and fetching its prices… (about 20 seconds)", "Loaded. Reloading…"],
   ["#gsunsample", "unsample", "Removing…", "Removed. Reloading…"]].forEach(([id, action, busy, done]) => {
    const b = $(id); if(!b) return;
    b.addEventListener("click", async () => {
      const msg = $("#gssamplemsg"); b.disabled = true; msg.textContent = busy;
      try{
        const r = await (await fetch("/api/setup", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action})})).json();
        if(r.error){ msg.innerHTML = `<span style="color:var(--down)">${esc(r.error)}</span>`; b.disabled = false; return; }
        msg.textContent = done; setTimeout(() => location.reload(), 600);
      }catch(e){ msg.textContent = "That did not work: " + String(e).slice(0, 80); b.disabled = false; }
    });
  });
  el.querySelectorAll("input[data-gskind]").forEach(inp => inp.addEventListener("change", async () => {
    const out = el.querySelector(`[data-gsresult="${inp.dataset.gskind}"]`);
    out.textContent = "importing…";
    const fd = new FormData(); fd.append("kind", inp.dataset.gskind);
    [...inp.files].forEach(f => fd.append("file", f, f.name));
    try{
      const r = await (await fetch("/api/upload", {method: "POST", body: fd})).json();
      if(r.error){ out.innerHTML = `<span style="color:var(--down)">${esc(r.error)}</span>`; return; }
      // "Reload the page" was a numbered step in the guide, and a step a
      // person new to this does not know how to take. A button instead.
      const showIt = (r.imported || []).some(x => !x.error && x.inserted)
        ? `<div style="margin-top:6px"><button class="attngo primary" data-gsreload>Show it in the app →</button> <span class="note">or drop the next file first</span></div>` : "";
      out.innerHTML = (r.imported || []).map(x => x.error ? `<div style="color:var(--down)">${esc(x.file)}: ${esc(x.error)}</div>`
        : `<div><b>${esc(x.file)}</b>: ${x.seen} rows read, ${x.inserted} new, ${x.skipped} already there${x.account ? ` · account ${esc(x.account)}` : ""}</div>`).join("");
      GS_STATUS = await (await fetch("/api/setup")).json(); const keep = out.innerHTML; renderGetStarted();
      const again = el.querySelector(`[data-gsresult="${inp.dataset.gskind}"]`); if(again) again.innerHTML = keep;
    }catch(e){ out.textContent = "The upload failed: " + String(e).slice(0, 80); }
  }));
  $("#gssavekey").addEventListener("click", async () => {
    const m = $("#gskeymsg"); m.textContent = "saving…";
    const r = await (await fetch("/api/setup", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: "alpaca", key: $("#gskey").value, secret: $("#gssecret").value})})).json();
    m.textContent = r.error ? r.error : "saved to data/.alpaca — now fetch prices"; if(!r.error){ $("#gsprices").disabled = false; $("#gssecret").value = ""; }
  });
  $("#gsprices").addEventListener("click", async () => {
    const m = $("#gskeymsg"); m.textContent = "fetching prices — a minute or two…"; $("#gsprices").disabled = true;
    const r = await (await fetch("/api/setup", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: "prices"})})).json();
    m.textContent = r.error ? r.error : `SPY ${r.benchmarks.SPY}, QQQ ${r.benchmarks.QQQ}${r.holdings ? `; holdings priced ${r.holdings.priced}${(r.holdings.failed || []).length ? `, no feed for ${r.holdings.failed.join(", ")}` : ""}` : ""}. Reload the page.`;
    $("#gsprices").disabled = false;
  });
  $("#gssaveprofile").addEventListener("click", async () => {
    const m = $("#gsprofilemsg"); m.textContent = "saving…";
    const r = await (await fetch("/api/setup", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: "profile", filing_status: $("#gsstatus").value, age: $("#gsage").value})})).json();
    m.textContent = r.error ? r.error : `saved: ${r.filing_status}, ${r.age || "no age"}`;
  });
}

// The money side arrives separately: Overview does not load /api/budget, and
// waiting on it would delay the first paint for a panel that is mostly about
// the portfolio. So these rows appear a moment later rather than never.
// The budget request as the Budget tab sends it — filing status and age
// included, from the saved settings — so the Overview's early read and the
// tab's own are the same request and one response serves both.
function budgetQuery(){
  const q = new URLSearchParams();
  const v = id => { const el = $(id); return el ? el.value : ""; };
  if(v("#bgFrom")) q.set("from", v("#bgFrom"));
  if(v("#bgTo"))   q.set("to", v("#bgTo"));
  if(v("#bgAccount")) q.set("account", v("#bgAccount"));
  if(v("#bgStatus")) q.set("status", v("#bgStatus"));
  if(v("#bgAge")) q.set("age", v("#bgAge"));
  return q;
}

// Held for ten minutes: the figures only change on an import, and a write
// from this page (dismiss, rule) clears it at once. Long enough that opening
// the tab after reading the Overview never fetches a second time.
let BUDGET_FETCH = null;            // {key, at, promise} — the last read

function fetchBudget(){
  const q = budgetQuery(), key = q.toString();
  if(!BUDGET_FETCH || BUDGET_FETCH.key !== key || Date.now() - BUDGET_FETCH.at > 600000){
    BUDGET_FETCH = {key, at: Date.now(), promise: fetch("/api/budget?" + q).then(r => r.json())};
    BUDGET_FETCH.promise.catch(() => { BUDGET_FETCH = null; });
  }
  return BUDGET_FETCH.promise;
}

// ------------------------------------------------------------- budget ----
// The bank half of the app. The thing that makes this different from the
// portfolio tabs is that most of what lands in a checking account is NOT
// spending — payroll in, transfers to the brokerage, credit-card bills — so
// every number here is grouped by whether the money actually left.
let BUDGET = null;

function bgBar(rows, key, colour){
  const max = Math.max(...rows.map(r => Math.abs(r[key] || 0)), 1);
  return rows.map(r => {
    const v = Math.abs(r[key] || 0);
    const h = Math.max(1, Math.round((v / max) * 74));
    return `<span class="bgbar" title="${esc(r.month)}: ${money(Math.abs(r[key]||0))}">
      <span style="height:${h}px;background:${colour}"></span></span>`;
  }).join("");
}

// One column per month, three segments stacked on a shared baseline. The scale
// is the largest single MONTH total rather than the largest segment, so column
// heights stay comparable to each other — scaling each series to its own max
// would make a $400 month and a $6,000 month draw the same.
const STACK_SERIES = [
  {key:"expense",    label:"Spending",     colour:"var(--s1)"},
  {key:"income",     label:"Income",       colour:"var(--s3)"},
  {key:"investment", label:"To brokerage", colour:"var(--s2)"},
];

function bgStack(rows){
  const total = r => STACK_SERIES.reduce((a,s)=> a + Math.abs(r[s.key] || 0), 0);
  const max = Math.max(...rows.map(total), 1);
  return rows.map(r => {
    const tip = [esc(r.month)].concat(STACK_SERIES
      .filter(s => Math.abs(r[s.key] || 0) > 0)
      .map(s => `${s.label} ${money(Math.abs(r[s.key]))}`)).join(" · ");
    const segs = STACK_SERIES.map(s => {
      const v = Math.abs(r[s.key] || 0);
      if(!v) return "";
      // Floor at 2px: a real but tiny month must still be visible, and a
      // zero-height segment beside a 2px gap reads as a rendering fault.
      return `<i style="height:${Math.max(2, Math.round(v / max * 74))}px;
        background:${s.colour}"></i>`;
    }).join("");
    return `<span class="bgbar" title="${tip}"><span class="stack">${segs}</span></span>`;
  }).join("");
}

// Bracket and limit arithmetic. Everything shown is a FLOOR, and the panel says
// so in its own words rather than in a footnote: a bank ledger records deposits,
// and a payroll deposit is already net of tax and of pre-tax deferrals, so real
// gross income is always higher than what landed. Presenting this as a tax
// position would be wrong in the direction that matters.
function renderTaxInsights(i){
  const el = $("#bgTax");
  if(!el) return;
  if(!i || i.error){ el.innerHTML = `<div class="panel note">${esc((i&&i.error)||"No tax table.")}</div>`; return; }
  const b = i.bracket, r = i.roth, inv = i.investment;
  const pct = v => (v*100).toFixed(0) + "%";
  const signed = v => v == null ? "—" : (v < 0 ? "−" : "+") + money(Math.abs(v));
  const rothNote = {
    full: "Under the phase-out — the full amount is available.",
    partial: "Inside the phase-out range, so the allowance is reduced rather than gone.",
    ineligible: "Above the phase-out. A backdoor Roth is the usual route; ask someone qualified.",
  }[r.state] || "";

  el.innerHTML = `
  <div class="cards">
    <div class="card"><div class="k">Income counted</div><div class="v">${money(i.received)}</div>
      <div class="note">${esc(String(i.year))} wages from the pay stub, other deposits${inv ? ", and the taxable account's trades, dividends and interest" : ""} · a floor</div></div>
    <div class="card"><div class="k">Marginal band</div><div class="v">${pct(b.rate)}</div>
      <div class="note">${b.room != null
        ? `${money(b.room)} of room before ${pct(b.next_rate)}`
        : "top band"}</div></div>
    <div class="card"><div class="k">Roth IRA</div><div class="v">${money(i.roth_remaining)}</div>
      <div class="note">still available of ${money(r.allowed)}</div></div>
    <div class="card"><div class="k">401(k)</div><div class="v">${money(i.deferral_remaining)}</div>
      <div class="note">still available of ${money(i.deferral_limit)}</div></div>
  </div>

  <div class="panel">
    <table>
      <tr><th scope=col>Item</th><th class=num scope=col>Amount</th><th scope=col>What it means</th></tr>
      <tr><td>Deposits counted as income</td><td class=num>${money(i.deposits != null ? i.deposits : i.received)}</td>
        <td class="note">Every categorised inflow in ${esc(String(i.year))}. Transfers between your own
          accounts are excluded.</td></tr>
      ${inv ? `<tr><td>Trades in the taxable account</td><td class=num style="${col(inv.net_gain)}">${signed(inv.net_gain)}</td>
        <td class="note">${inv.trades} lots closed this year, FIFO-matched: ${signed(inv.short_term)} short-term${inv.long_term ? `, ${signed(inv.long_term)} long-term` : ""}${inv.last_sale ? `, last sale ${esc(inv.last_sale)}` : ""}.
          ${inv.wash_disallowed ? `${money(inv.wash_disallowed)} of losses are wash sales and do not count. ` : ""}${inv.loss_carried < 0 ? `A net loss offsets at most $3,000 of income this year; <b>${money(Math.abs(inv.loss_carried))}</b> carries forward. ` : ""}${inv.biggest && inv.biggest.length ? `Largest: ${inv.biggest.slice(0, 4).map(b => `${esc(b.symbol)} ${signed(b.pnl)}`).join(", ")}. ` : ""}The broker chooses lots per sale, so the 1099-B can differ. Roth, 401(k) and HSA sales are not taxable events and are not here.</td></tr>
      <tr><td>Dividends and interest, taxable account</td><td class=num>${money(inv.dividends + inv.interest)}</td>
        <td class="note">${money(inv.dividends)} of dividends (money-market included) and ${money(inv.interest)} of interest, all counted as ordinary income — the ledger cannot tell which dividends were qualified, so this errs high.</td></tr>` : ""}
      <tr><td>Standard deduction</td><td class=num>${money(i.standard_deduction)}</td>
        <td class="note">${esc(i.status.replace(/_/g," "))}, ${esc(String(i.year))}.</td></tr>
      <tr><td>Income counted, in all</td><td class=num>${money(i.received)}</td>
        <td class="note">Wages and deposits${inv ? `, plus what the taxable account earned (a net trading loss subtracts up to $3,000)` : ""}.</td></tr>
      <tr><td>Taxable, at minimum</td><td class=num>${money(i.taxable_floor)}</td>
        <td class="note">Lands in the ${pct(b.rate)} band${b.room != null
          ? `, ${money(b.room)} below the ${pct(b.next_rate)} band` : ""}.</td></tr>
      <tr><td>Federal tax on that</td><td class=num>${money(i.tax_floor)}</td>
        <td class="note">Only the dollars above each threshold pay the higher rate, so crossing
          a band never costs more than the income that crossed it.${inv && inv.long_term_taxed ? ` Includes ${money(inv.ltcg_tax)} on the long-term gain at its own rate.` : ""}</td></tr>
      ${inv ? `<tr><td>${inv.tax_from_investing >= 0 ? "Extra tax from investing" : "Tax saved by investing"}</td><td class=num style="${col(-inv.tax_from_investing)}">${money(Math.abs(inv.tax_from_investing))}</td>
        <td class="note">The floor with the taxable account's year in, less the floor without it: what the trades, dividends and interest above ${inv.tax_from_investing >= 0 ? "add to" : "take off"} the bill.</td></tr>` : ""}
      <tr><td>Roth IRA contributed</td><td class=num>${money(i.roth_contributed)}</td>
        <td class="note">${esc(rothNote)} Phase-out ${money(r.phase_out[0])}–${money(r.phase_out[1])}.</td></tr>
      <tr><td>401(k) deferred</td><td class=num>${money(i.deferral_contributed)}</td>
        <td class="note">Employer plan and its BrokerageLink sleeves share this limit.</td></tr>
      ${i.hsa_contributed ? `<tr><td>HSA contributed</td><td class=num>${money(i.hsa_contributed)}</td>
        <td class="note">${i.hsa_limit ? `Limit ${money(i.hsa_limit)} (${esc(i.hsa_coverage || "family")} coverage, employer and employee together); ${money(Math.max(0, i.hsa_limit - i.hsa_contributed))} left.` : "Its own separate limit."}</td></tr>` : ""}
      ${i.se_tax ? `<tr><td>Self-employment tax</td><td class=num>${money(i.se_tax)}</td>
        <td class="note">15.3% of 92.35% of ${money(i.business_income)} of 1099 income; half of it comes off taxable income. Included in the federal floor above.</td></tr>` : ""}
      ${i.paid_in != null ? `<tr><td>Paid in so far</td><td class=num>${money(i.paid_in)}</td>
        <td class="note">${money(i.federal_withheld || 0)} withheld on the stub${i.estimated_paid ? ` plus ${money(i.estimated_paid)} of estimated payments in the Taxes category` : ""}.</td></tr>
      <tr><td>${i.withholding_gap >= 0 ? "Paid in more than the floor owes" : "Paid in less than the floor owes"}</td><td class=num style="color:${i.withholding_gap >= 0 ? "var(--up)" : "var(--down)"}">${money(Math.abs(i.withholding_gap))}</td>
        <td class="note">${money(i.paid_in)} paid in (withholding plus estimated payments) against ${money(i.tax_floor)} of federal tax the floor says is owed so far.
          ${i.withholding_gap >= 0 ? "More has gone in than the minimum bill — but the real bill is higher than the floor by an unknown amount, so this is a direction, not a refund." : "Less has gone in than even the minimum bill, and the real bill is higher — expect to owe at least this much at filing, or raise withholding."}</td></tr>` : ""}
    </table>
    <div class="note" style="margin-top:10px">
      <b>Every figure here is a floor.</b> A payroll deposit is already net of tax and of
      pre-tax deferrals, so real gross income is higher than what landed in the bank.
      Business receipts are revenue, not profit — deductible expenses come off before any
      of it is taxable. And the Roth phase-out is measured against MAGI, which is neither
      of those. Useful for noticing that a limit is close; not a filing figure, and not advice.
    </div>
  </div>`;
}

// Subscriptions and habits. The distinction is the whole point: a fixed monthly
// charge is something you can cancel, a weekly grocery run is not, and mixing
// them buries the three that matter under twenty that do not.
function renderRecurring(r){
  const el = $("#bgRecur");
  if(!el) return;
  if(!r || !r.subscriptions){ el.innerHTML = ""; return; }
  const live = r.subscriptions.filter(x=>!x.lapsed);
  // The price over time, read off the row: every step it took and when.
  // "$993.50 → $960.50 → $1,109.50 → $1,379.50, +39% since Jan 2025" is
  // the thing the user opens this tab for; the detector had it in the two
  // medians and showed only the second.
  const mon = d => { const dt = new Date(d + "T00:00:00"); return isNaN(dt) ? d : dt.toLocaleDateString(undefined, {month: "short", year: "2-digit"}); };
  const priceCell = x => {
    const h = x.history || [];
    if(h.length <= 1) return `<span class="note">${h.length ? `unchanged since ${mon(h[0].from)}` : "—"}</span>`;
    // A price that billed once — a half-month of rent, a doubled payment —
    // is in the chain but is not the "from" or "to" of the change.
    const settled = h.filter(s => s.charges >= 2);
    const use = settled.length >= 2 ? settled : h;
    const first = use[0].amount, last = use[use.length - 1].amount;
    const chg = first ? (last / first - 1) : 0;
    const tone = Math.abs(chg) < 0.005 ? "inherit" : chg > 0 ? "var(--down)" : "var(--up)";
    const chain = h.length <= 5
      ? h.map((s, i) => `<span title="from ${esc(s.from)}, ${s.charges} charge${s.charges === 1 ? "" : "s"}"${i === h.length - 1 ? ` style="color:${tone};font-weight:600"` : ""}>${money(s.amount)}</span>`).join(" → ")
      : `${money(first)} … <span style="color:${tone};font-weight:600">${money(last)}</span> <span class="note">(varies: ${h.length} changes)</span>`;
    const once = use === h && h[h.length - 1].charges === 1 && h.length > 1 ? " (latest billed once)" : "";
    return `${chain} <span class="note" style="color:${tone}">${chg > 0 ? "+" : ""}${(chg * 100).toFixed(0)}% since ${mon(use[0].from)}${once}</span>`;
  };
  const statusCell = x => x.lapsed
    ? `<span class="pill" title="Expected ${esc(x.next_expected)}, nothing since ${esc(x.last)}">not seen in ${x.days_overdue}d</span>`
    : `<span class="note">next ~${esc(x.next_expected)}</span>`;

  // "Gone quiet" is a list to work through once, not a permanent fixture. Each
  // row states what it was, what it cost and when it last billed — enough to
  // check — and a Dismiss that stops it being asked again.
  const goneQuiet = !(r.lapsed||[]).length ? "" : `
    <h2>Gone quiet — worth checking</h2>
    <div class="panel">
      <div class="note" style="margin-bottom:8px">Each of these billed on a
        cadence and then stopped. Usually a cancellation or an expired card;
        occasionally something that quietly resumed elsewhere. Dismiss one once
        you know which.</div>
      <table class="reclist"><tr><th scope=col>Merchant</th><th scope=col>Was</th>
        <th class=num scope=col>Typical</th><th class=num scope=col>A year</th>
        <th scope=col>Last seen</th><th scope=col></th></tr>` +
      r.lapsed.map(x=>`<tr>
        <td>${esc(x.merchant)}</td>
        <td class="note">${esc(x.cadence)}${x.assumed ? " (assumed — one charge so far, in the Subscriptions category)" : ""}${x.account ? " · " + esc(x.account) : ""}</td>
        <td class=num>${money(x.typical)}</td>
        <td class=num>${money(x.annual)}</td>
        <td class="note">${esc(x.last)} · ${x.days_overdue}d ago</td>
        <td><button class="attngo" data-dismiss="${esc(x.merchant)}">Dismiss</button></td>
      </tr>`).join("") + `</table></div>`;

  el.innerHTML = `
  <div class="cards">
    <div class="card"><div class="k">Subscriptions</div><div class="v">${money(r.monthly_total)}</div>
      <div class="note">per month · ${money(r.annual_total)} a year · ${r.live_count} active</div></div>
    <div class="card"><div class="k">Gone quiet</div><div class="v">${r.lapsed.length}</div>
      <div class="note">billed regularly, then stopped</div></div>
    <div class="card"><div class="k">Price rises</div><div class="v">${r.risen.length}</div>
      <div class="note">${r.risen.length
        ? money(r.risen.reduce((a,x)=>a+x.annual_increase,0)) + " a year more than they were"
        : "nothing has gone up"}</div></div>
  </div>

  ${r.risen.length ? `<div class="panel" style="border-left:3px solid var(--warn)">
    <b>${r.risen.length} recurring charge${r.risen.length>1?"s have":" has"} gone up.</b>
    <div class="note">A rise on something billed monthly arrives as one slightly larger
      number among hundreds, which is exactly why it is worth listing.</div>
    <table style="margin-top:8px">
      <tr><th scope=col>Charge</th><th class=num scope=col>Was</th><th class=num scope=col>Now</th>
        <th class=num scope=col>Extra per year</th></tr>
      ${r.risen.map(x=>`<tr><td>${esc(x.merchant)} <span class="note">${esc(x.cadence)}</span></td>
        <td class=num>${money(x.was)} <span class="note">${mon(x.was_from || "")}</span></td>
        <td class=num style="color:var(--down)">${money(x.now)} <span class="note">since ${mon(x.now_from || "")}</span></td>
        <td class=num>${money(x.annual_increase)}</td></tr>`).join("")}
    </table></div>` : ""}

  <div class="panel">
    <div class="note" style="margin-bottom:6px">Everything that bills you on a schedule — subscriptions, insurance, utilities, rent — with every price it has billed at. Insurance and utilities are here even though the amount moves, because a bill that reprices is the one most worth watching. Groceries and fuel, regular in time and random in amount, are under the fold below.</div>
    <div class="bar" style="margin-bottom:8px;padding:6px 8px">
      <span class="note">Show</span>
      ${[["all", "all"], ["sure", "sure — billed 3+ times on a measured cadence"], ["likely", "likely — one or two charges so far"], ["quiet", "gone quiet"]].map(([k, l]) =>
        `<button data-recfilter="${k}" class="attngo" style="${(RECUR_FILTER === k) ? "border-color:var(--accent);color:var(--accent)" : ""}" title="${esc(l)}">${esc(k)}</button>`).join("")}
      <span class="note" style="margin-left:auto">Sure first, then likely, then gone quiet. Hide anything that is not a subscription; it moves under the fold below with an undo.</span>
    </div>
    <table class="reclist">
      <tr><th scope=col>Charge</th><th scope=col title="sure: billed 3+ times on a measured cadence and current · likely: one or two charges so far · quiet: stopped billing">How sure</th><th scope=col>Every</th><th class=num scope=col>Amount</th>
        <th scope=col title="Every price it has billed at, oldest to newest, and the change from the first to the latest. Red is a rise.">Price over time</th>
        <th class="num phone-hide" scope=col>A year</th><th class="num phone-hide" scope=col>Charges</th>
        <th class="phone-hide" scope=col>Last</th><th scope=col>Status</th><th scope=col></th></tr>
      ${r.subscriptions.filter(x => RECUR_FILTER === "all" || x.confidence === RECUR_FILTER).map(x=>`<tr${x.lapsed?' class="dim"':''}>
        <td>${esc(x.merchant)}</td>
        <td><span class="pill" style="color:${x.confidence === "sure" ? "var(--up)" : x.confidence === "likely" ? "var(--warn)" : "var(--muted)"}">${esc(x.confidence)}</span></td>
        <td>${esc(x.cadence)}${x.assumed ? ` <span class="note" title="Billed ${x.charges} time${x.charges === 1 ? "" : "s"} so far, so the cadence cannot be measured yet; it is in the Subscriptions category, so it is listed here as annual until a second charge says otherwise.">(assumed)</span>` : ""}</td>
        <td class=num>${money(x.typical)}</td>
        <td style="font-size:13px">${priceCell(x)}</td>
        <td class="num phone-hide">${x.annual==null?"—":money(x.annual)}</td>
        <td class="num phone-hide">${x.charges}</td>
        <td class="phone-hide">${esc(x.last)}</td><td>${statusCell(x)}</td>
        <td><button class="attngo" data-dismiss="${esc(x.merchant)}" title="Not a subscription, or gone for good: take it off the list">Hide</button></td></tr>`).join("")}
    </table>
    ${live.length ? `<div class="note" style="margin-top:8px">Cancelling everything above
      that you no longer use would free ${money(r.monthly_total)} a month.</div>` : ""}
    ${(r.hidden || []).length ? `<details style="margin-top:8px"><summary class="note" style="cursor:pointer">${r.hidden.length} hidden</summary>
      <table style="margin-top:6px">${r.hidden.map(x => `<tr class="dim"><td>${esc(x.merchant)}</td><td class="note">${esc(x.cadence)}</td><td class=num>${money(x.typical)}</td><td class="note">${esc(x.last)}</td>
        <td><button class="attngo" data-undismiss="${esc(x.merchant)}">Restore</button></td></tr>`).join("")}</table></details>` : ""}
  </div>

  ${(r.habits||[]).length ? `<details class="group">
    <summary>${r.habits.length} regular but variable — groceries, fuel, bills
      (${r.habits.length} merchants)</summary>
    <div class="panel">
      <div class="note">Regular in time, irregular in amount, so there is nothing to
        cancel — but this is where the money actually goes. No yearly figure is shown,
        because projecting one from a handful of shopping trips would be fiction.</div>
      <table style="margin-top:8px">
        <tr><th scope=col>Merchant</th><th scope=col>Every</th>
          <th class=num scope=col>Typical</th><th class=num scope=col>Charges</th>
          <th class=num scope=col>Paid so far</th><th scope=col>Last</th></tr>
        ${r.habits.map(x=>`<tr><td>${esc(x.merchant)}</td><td>${esc(x.cadence)}</td>
          <td class=num>${money(x.typical)}</td><td class=num>${x.charges}</td>
          <td class=num>${money(x.total_paid)}</td><td>${esc(x.last)}</td></tr>`).join("")}
      </table></div></details>` : ""}
  ${goneQuiet}`;

  // Dismiss is a write, so it goes through the same endpoint as everything else
  // and the panel re-renders from the server rather than hiding the row locally.
  el.querySelectorAll("[data-dismiss]").forEach(b =>
    b.addEventListener("click", async ()=>{
      b.disabled = true;
      const q = new URLSearchParams({action:"dismiss", merchant:b.dataset.dismiss});
      try{ await fetch("/api/budget?" + q); }catch(e){ b.disabled = false; return; }
      BUDGET_FETCH = null; loadBudget();
    }));
  el.querySelectorAll("[data-undismiss]").forEach(b =>
    b.addEventListener("click", async ()=>{
      b.disabled = true;
      const q = new URLSearchParams({action:"undismiss", merchant:b.dataset.undismiss});
      try{ await fetch("/api/budget?" + q); }catch(e){ b.disabled = false; return; }
      BUDGET_FETCH = null; loadBudget();
    }));
  el.querySelectorAll("[data-recfilter]").forEach(b =>
    b.addEventListener("click", () => { RECUR_FILTER = b.dataset.recfilter; try{ localStorage.setItem("invest.recur.filter", RECUR_FILTER); }catch(e){} renderRecurring(r); }));
}

let RECUR_FILTER = "all";
try{ RECUR_FILTER = localStorage.getItem("invest.recur.filter") || "all"; }catch(e){}

// Month over month. The comparison is always against the newest COMPLETE month:
// a month that is half over reads as every category collapsing, which is the
// easiest way to make a feature like this lie.
function renderTrends(t){
  const el = $("#bgTrend");
  if(!el) return;
  if(!t || !t.month || !t.rows || !t.rows.length){
    el.innerHTML = `<div class="panel note">${esc((t && t.note) ||
      "Not enough finished months to compare yet.")}</div>`;
    return;
  }
  const arrow = r => r.direction === "up" ? "▲" : r.direction === "down" ? "▼" : "—";
  const tone = r => r.direction === "up" ? "var(--down)" : "var(--up)";
  const diff = t.total_now - t.total_typical;

  el.innerHTML = `
  <div class="panel">
    <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px">
      <b>${esc(t.month)} — ${money(t.total_now)} spent</b>
      <span class="note">against a typical ${money(t.total_typical)},
        median of the ${t.baseline_months} months from ${esc(t.baseline_from)}
        · <b style="color:${diff >= 0 ? "var(--down)" : "var(--up)"}">
          ${diff >= 0 ? "+" : "−"}${money(Math.abs(diff))}</b></span>
    </div>

    ${t.notable.length ? `<table style="margin-top:10px">
      <tr><th scope=col>Category</th><th class=num scope=col>This month</th>
        <th class=num scope=col>Typical</th><th class=num scope=col>Difference</th>
        <th scope=col>What drove it</th></tr>
      ${t.notable.map(r=>`<tr>
        <td><span style="color:${tone(r)}">${arrow(r)}</span> ${esc(r.category)}</td>
        <td class=num>${money(r.now)}</td>
        <td class=num>${money(r.typical)}</td>
        <td class=num style="color:${tone(r)}">${r.delta >= 0 ? "+" : "−"}${money(Math.abs(r.delta))}
          <span class="note">(${(r.share*100).toFixed(0)}%)</span></td>
        <td class="note">${(r.drivers||[]).slice(0,2).map(x =>
            `${esc(String(x.description).slice(0,28))} ${money(Math.abs(x.amount))}`).join("; ")
            || "spread across many charges"}</td></tr>`).join("")}
    </table>` : `<div class="note" style="margin-top:8px">Nothing moved enough to be
      worth flagging — every category is within its usual range.</div>`}

    <div class="note" style="margin-top:10px">A change has to be both a real
      proportion and real money before it appears here, because a 90% rise on a $2
      category is arithmetically dramatic and worth nothing.</div>
  </div>

  ${(t.unusual||[]).length ? `<div class="panel">
    <b>${t.unusual.length} charge${t.unusual.length>1?"s":""} far larger than usual for
      ${t.unusual.length>1?"their categories":"its category"}</b>
    <table style="margin-top:8px">
      <tr><th scope=col>Date</th><th scope=col>Charge</th><th scope=col>Category</th>
        <th class=num scope=col>Amount</th><th class=num scope=col>Usual there</th></tr>
      ${t.unusual.map(x=>`<tr><td>${esc(x.date)}</td>
        <td>${esc(String(x.description).slice(0,40))}</td>
        <td>${esc(x.category)}</td>
        <td class=num>${money(Math.abs(x.amount))}</td>
        <td class=num>${money(x.typical_for_category)}</td></tr>`).join("")}
    </table></div>` : ""}`;
}

// Your spreadsheet against the ledger. The differences are the point rather
// than errors: each side knows things the other does not, and which side is
// higher says which.
function renderReference(r){
  const el = $("#bgRef");
  if(!el) return;
  if(!r || !r.available){ el.innerHTML = ""; return; }
  const sign = v => moneyDelta(v);

  el.innerHTML = `
  <h2>Your spreadsheet, against this</h2>
  <div class="panel">
    <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;align-items:baseline">
      <b>${esc(r.months[0])} to ${esc(r.months[r.months.length-1])}</b>
      <span class="note">sheet ${money(r.sheet_total)} · this app ${money(r.app_total)} ·
        <b>${sign(r.difference)}</b></span>
    </div>
    <table style="margin-top:10px">
      <tr><th scope=col>Category</th><th class=num scope=col>Your sheet</th>
        <th class=num scope=col>This app</th><th class=num scope=col>Difference</th>
        <th scope=col>Most likely</th></tr>
      ${r.rows.map(x=>`<tr${x.matched?"":' class="dim"'}>
        <td>${esc(x.category)}${x.matched?"":' <span class="pill">no matching category here</span>'}</td>
        <td class=num>${money(x.sheet)}</td>
        <td class=num>${money(x.app)}</td>
        <td class=num>${sign(x.difference)}</td>
        <td class="note">${!x.matched ? "nothing here to compare it with"
          : x.difference < -50 ? "spending your sheet caught and this app cannot see — "
              + "usually cash, or a card not yet imported"
          : x.difference > 50 ? "spending that reached an account but never made it "
              + "into the sheet"
          : "the two agree"}</td></tr>`).join("")}
    </table>
    ${r.not_in_sheet.length ? `<div class="note" style="margin-top:10px">
      This app also tracks ${r.not_in_sheet.length} categories your sheet does not
      mention: ${r.not_in_sheet.slice(0,8).map(esc).join(", ")}.</div>` : ""}
    <div class="note" style="margin-top:8px">Neither column is the correct one. A
      hand-kept budget records cash and anything bought on a card whose export is not
      imported; the ledger records everything that moved through an account whether or
      not it was ever written down.</div>
  </div>`;
}

async function loadBudget(){
  const d = BUDGET = await fetchBudget();
  if(d.error){ $("#bgCards").innerHTML = `<div class="card">${esc(d.error)}</div>`; return; }

  if($("#bgAccount").options.length <= 1 && d.accounts){
    $("#bgAccount").innerHTML = `<option value="">All cash accounts</option>` +
      d.accounts.map(a=>`<option value="${esc(a.name)}">${esc(a.name)}</option>`).join("");
  }
  const months = d.by_month || [];
  $("#bgRange").textContent = months.length
    ? `${months[0].month} to ${months[months.length-1].month} · ${months.length} months` : "";

  const k = d.by_kind || {};
  const income = k.income || 0, spend = Math.abs(k.expense || 0);
  const invested = Math.abs(k.investment || 0);
  // Complete months only: a three-day first month and a six-day current
  // month were dividing the average down.
  const today = new Date().toISOString().slice(0, 7);
  const complete = months.filter((m, i) => m.month !== today && !(i === 0 && (m.days != null && m.days < 20)));
  renderDue(d.upcoming);
  const n = complete.length || months.length || 1;
  $("#bgCards").innerHTML = `
    <div class="card"><div class="k">Spending</div><div class="v">${money(d.monthly_spend)}</div>
      <div class="note">per month · ${money(spend)} total</div></div>
    <div class="card"><div class="k">Income</div><div class="v">${money(income/n)}</div>
      <div class="note">per complete month · ${money(income)} total</div></div>
    <div class="card"><div class="k">Invested</div><div class="v">${money(invested/n)}</div>
      <div class="note">per complete month · ${money(invested)} moved to brokerage</div></div>
    <div class="card"><div class="k">Uncategorised</div><div class="v">${d.unmatched_count}</div>
      <div class="note">${money(d.unmatched_out)} of it money going out</div></div>`;

  // The single most important caveat on this page, so it is not a footnote.
  // How much of the card spending is accounted for. The bank only records the
  // payment to the card, so every dollar paid to one is spending this page
  // cannot see inside until that card's own transactions are imported.
  $("#bgBlind").innerHTML = d.card_payments > 0 ? `
    <div class="panel" style="border-left:3px solid ${d.card_blind_spot > 0
        ? "var(--warn)" : "var(--up)"}">
      ${d.card_blind_spot > 0
        ? `<b>${money(d.card_blind_spot)} of card spending is still unaccounted for.</b>`
        : `<b>Every dollar paid to a card is accounted for.</b>`}
      <div class="note">
        ${money(d.card_payments)} left your bank accounts to pay credit cards.
        ${money(d.card_spend_seen)} of that is now itemised, from the card exports
        you have imported.
        ${d.card_blind_spot > 0
          ? `The remaining <b>${money(d.card_blind_spot)}</b> was spent on cards whose
             transactions are not in <code>data/cards/</code> yet — the bank records the
             payment, never what was bought with it. Those dollars are counted as a
             transfer rather than an expense, so the spending figures above exclude them.`
          : ""}
      </div>
    </div>` : "";

  renderTaxInsights(d.insights);
  renderGoals(d.goals);
  renderCrossings((d.insights || {}).crossings);
  renderReference(d.reference);
  renderTrends(d.trends);
  renderRecurring(d.recurring);
  drawSavedMonths(d);
  drawCategoryTrends(d);

  const cats = d.by_category || [];
  const exp = cats.filter(c=>c.kind === "expense");
  const totalExp = exp.reduce((a,c)=>a + Math.abs(c.total), 0) || 1;
  // Share is the column people actually scan, so it carries a bar as well as a
  // number: width against the largest category turns a list of percentages into
  // a ranking you can read without comparing digits. One hue — this encodes
  // magnitude, not identity — and the number stays beside it in ink, which is
  // also the visible label the palette's contrast check requires.
  const topExp = exp.length ? Math.abs(exp[0].total) : 1;
  $("#bgCats").innerHTML =
    `<tr><th scope=col>Category</th><th class=num scope=col>Total</th>
      <th class=num scope=col>Per month</th><th scope=col>Share</th>
      <th class=num scope=col>Txns</th></tr>` +
    exp.map(c=>`<tr><td>${esc(c.category)}</td>
      <td class=num>${money(Math.abs(c.total))}</td>
      <td class=num>${money(Math.abs(c.total)/n)}</td>
      <td><span class="sb"><i style="width:${
        Math.max(2, Math.round(Math.abs(c.total)/topExp*104))}px"></i>
        <span>${(Math.abs(c.total)/totalExp*100).toFixed(1)}%</span></span></td>
      <td class=num>${c.n}</td></tr>`).join("") +
    cats.filter(c=>c.kind !== "expense").map(c=>`<tr class="dim"><td>${esc(c.category)}
      <span class="pill">${esc(c.kind)}</span></td>
      <td class=num>${money(c.total)}</td><td class=num>${money(c.total/n)}</td>
      <td class=num>—</td><td class=num>${c.n}</td></tr>`).join("");

  // Spending, income and money moved to the brokerage on one baseline, stacked
  // per month. Three series is the all-pairs safe depth of the categorical
  // palette, so no fold-to-other is needed; a legend is present because two or
  // more series must never be identified by colour alone.
  $("#bgMonths").innerHTML = `
    <div class="note">Every month on one baseline. Hover a column for the figures.</div>
    <div class="legend">
      <span><i class="swatch" style="background:var(--s1)"></i>Spending</span>
      <span><i class="swatch" style="background:var(--s3)"></i>Income</span>
      <span><i class="swatch" style="background:var(--s2)"></i>To brokerage</span>
    </div>
    <div class="bgchart">${bgStack(months)}</div>
    <div class="bgaxis">${months.map(m=>`<span>${esc(m.month.slice(2))}</span>`).join("")}</div>`;

  // Grouped by merchant, largest first. 264 uncategorised transactions is 264
  // decisions listed one by one and about 30 grouped, because most of the tail
  // is the same handful of shops seen again and again — and one choice here
  // writes a rule that covers every charge from them, past and future.
  const opts = (d.categories||[]).map(c=>`<option value="${esc(c.name)}">${esc(c.name)}</option>`).join("");
  const groups = d.unmatched_groups || [];
  $("#bgUnmatched").innerHTML = groups.length ? `
    <div class="note">${d.unmatched_count} transactions match no rule —
      ${money(d.unmatched_out)} going out and ${money(d.unmatched_in)} coming in.
      Grouped into ${groups.length} merchants, largest first: choosing a category
      here writes a rule that covers every charge from that merchant, including
      the ones already imported.</div>
    <table id="bgUn"><tr><th scope=col>Merchant</th><th class=num scope=col>Charges</th>
      <th class=num scope=col>Total</th><th scope=col>Seen</th>
      <th scope=col>Categorise all as</th></tr>` +
    groups.map((g,i)=>`<tr>
      <td><code>${esc(g.pattern)}</code></td>
      <td class=num>${g.count}</td>
      <td class=num>${money(g.total)}</td>
      <td class="note">${esc(g.first)}${g.count > 1 ? ` … ${esc(g.last)}` : ""}</td>
      <td><select class="bgcat" data-i="${i}"><option value="">—</option>${opts}</select></td>
    </tr>`).join("") + `</table>` : `<div class="note">Everything is categorised.</div>`;

  document.querySelectorAll(".bgcat").forEach(sel =>
    sel.addEventListener("change", () => bgTeach(Number(sel.dataset.i), sel.value)));
}

// A rule is written from the merchant name the grouping already worked out, so
// the pattern offered is one that demonstrably matches every charge in the
// group rather than a guess at the next one.
async function bgTeach(i, category){
  if(!category || !BUDGET) return;
  const group = (BUDGET.unmatched_groups || [])[i];
  if(!group) return;
  const pattern = prompt(
    `Match which text? Every transaction whose description contains this will be `
    + `categorised as ${category}.\n\n`
    + `This currently matches ${group.count} transaction${group.count>1?"s":""}, `
    + `${money(Math.abs(group.total))} in total.`, group.pattern);
  if(!pattern){ loadBudget(); return; }
  const q = new URLSearchParams({action:"rule", pattern, category});
  const r = await (await fetch("/api/budget?" + q)).json();
  if(r.error){ alert(r.error); return; }
  BUDGET_FETCH = null; loadBudget();
}
