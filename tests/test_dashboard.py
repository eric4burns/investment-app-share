"""Structural checks on the dashboard page.

These exist because a set of sequential text replacements silently attached the
wrong panel labels to the wrong content — the Risk tab rendered the trade
record — and nothing caught it but looking at the screen. Structure is cheap to
assert and expensive to eyeball.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PAGE = (ROOT / "app" / "dashboard.html").read_text()

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

# The markup alone. The script also carries the same attribute names — a
# querySelector for [data-sub-panel="overview"], the SECTIONS table — and a
# scan of the whole file counted those as panels.
# The head carries a four-line script of its own since Phase 2 commit 2 (the
# theme choice, applied before first paint), so the split is at the first
# script AFTER <body>, not the first in the file.
_BODY_AT = PAGE.index("<body")
MARKUP = PAGE[:_BODY_AT] + PAGE[_BODY_AT:].split("<script", 1)[0]
_TAIL = PAGE[len(MARKUP):]

# The script is nine files under app/static since 2026-09-13 (the page was
# one 9,000-line file), loaded by plain <script src> tags in the order the
# page gives, sharing the global scope exactly as the one inline script did.
# Every check below reads them concatenated in that order, so it sees the
# same text it always did; the tags themselves are checked further down.
_SRCS = re.findall(r'<script src="/static/([\w-]+\.js)"></script>', _TAIL)
VENDORED = ["lightweight-charts.js", "drawings.js"]
APP_JS = [s for s in _SRCS if s not in VENDORED]
_INLINE = re.findall(r"<script>(.*?)</script>", _TAIL, re.S)
SCRIPT = "\n".join((ROOT / "app" / "static" / s).read_text() for s in APP_JS) + "\n" + "\n".join(_INLINE)
HTML = MARKUP + SCRIPT

panels = re.findall(r'<section class="tab" data-panel="(\w+)"', MARKUP)
tabs = re.findall(r'<button data-section="(\w+)"', MARKUP.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0])

check("every section button has a matching panel", sorted(tabs) == sorted(panels),
      (sorted(tabs), sorted(panels)))
check("no duplicate panels", len(panels) == len(set(panels)), panels)
check("sections are balanced",
      HTML.count("<section") == HTML.count("</section>") == len(panels),
      (HTML.count("<section"), HTML.count("</section>")))
# Phase 2 (research/audits/phase2-spec-2026-09-13.md): seven sections, in
# this order, and the phone's bottom bar plus its More sheet reach all seven.
SPEC_SECTIONS = ["today", "money", "stocks", "follow", "bot", "chart", "budget"]
check("the seven Phase 2 sections, in the agreed order", tabs == SPEC_SECTIONS, tabs)
phone = re.findall(r'data-section="(\w+)"',
                   MARKUP.split('id="phonebar"', 1)[1] if 'id="phonebar"' in MARKUP else "")
check("the phone bar and its More sheet reach every section",
      sorted(phone) == sorted(SPEC_SECTIONS), sorted(phone))

# Every element the JavaScript addresses must exist exactly once. A duplicated
# id means one of them is silently never written to.
addressed = set(re.findall(r'\$\("#([\w-]+)"\)', HTML))
# Created by the script at runtime rather than written in the markup, so a
# static scan cannot see them: the indicator picker, and the overview chart's
# hover readout.
DYNAMIC_IDS = {"addind", "ovtip", "nwtip", "nwchart",
    # Rendered inside the symbol page's read: the book and the reason a decision is logged with.
    "vdbucket", "vdwhy",
    # The "open another name" box, built into #symhead by renderSymHead.
    "symgo", "symgoform",
    # The sample-year message line on Get started, rendered at runtime (D129).
    "gssamplemsg",
    # Retired with Phase 2: the Outlook's permanently hidden change log. Its
    # render function stays (the payload still carries `changed`) and returns
    # when the panel is absent.
    "changed"}
for el in sorted(addressed - DYNAMIC_IDS):
    n = len(re.findall(rf'id="{el}"', HTML))
    if n != 1:
        check(f"#{el} exists exactly once", False, f"found {n}")
check("every element addressed by script exists exactly once",
      all(len(re.findall(rf'id="{e}"', HTML)) == 1 for e in addressed - DYNAMIC_IDS))

# Content belongs to the panel a reader would expect it in — now the
# sub-panel, per the old → new table in the Phase 2 spec.
EXPECTED = {
    "money/overview":   ["cards", "chart", "bench", "accts"],
    "money/holdings":   ["holdings", "attrib", "posmoves"],
    "money/trades":     ["tradecards", "trades", "fillpanel", "jrnl2"],
    # Today → What to do is ONE ranked list (#todo); its four sources keep
    # their hosts under it, hidden, so their render functions still run. The
    # full alert log is its own sub-tab. The old Diagnose tab's concentration
    # reading (a portfolio-level figure) folds under the risk table.
    "today/todo":       ["todo", "buyplans", "attention", "dxfindings"],
    "today/market":     ["mktmood"],
    "today/alerts":     ["alerts"],
    "money/risk":       ["riskcards", "ddchart", "corrgrid", "acctrisk", "conccards", "dxlevels"],
    "money/sectors":    ["themeexp", "sectorexp"],
    # The verdict card that opened under this table is the symbol page now.
    "stocks/calls":     ["vdtable", "pricefresh"],
    "stocks/watchlist": ["wlgroups", "wladd"],
    "stocks/setups":    ["setupslist"],
    "stocks/rebuy":     ["rebuylist"],
    # One method scanner; the Research tab's second copy is gone.
    "stocks/newstocks": ["discover", "methodsfold", "methodscan"],
    "follow/graded":    ["outsidetable"],
    "follow/charts":    ["sccharts", "schide", "scbyname"],   # one grid since D127; the Patreon grid folded in
    "follow/methods":   ["reskind", "ressel", "resdetail"],
    "follow/record":    ["outsideform", "oaRecord"],
    "bot/paper":        ["paper"],
    "bot/record":       ["scorecard", "calib", "jrnl", "replay"],
    "bot/backtest":     ["btrun", "btchart", "bttable"],
    "chart/chart":      ["symbol", "pricechart", "chartinfo"],
    # The symbol page: the read, the levels, who I follow on it, my trades.
    "chart/read":       ["symread", "tapanel", "chartasof"],
    "chart/plan":       ["symplan"],
    "chart/follow":     ["symfollow"],
    "chart/trades":     ["symtrades"],
    "budget/summary":   ["bgCards"],
}
bodies = dict(re.findall(r'<section class="tab" data-panel="(\w+)"[^>]*>(.*?)</section>', MARKUP, re.S))
subbodies = {}
for panel, body in bodies.items():
    for sub, sb in re.findall(r'<div class="subpanel" data-sub-panel="([\w-]+)"[^>]*>(.*?)(?=<div class="subpanel" |</section>|$)', body, re.S):
        subbodies[f"{panel}/{sub}"] = sb
for view, ids in EXPECTED.items():
    missing = [i for i in ids if f'id="{i}"' not in subbodies.get(view, "")]
    check(f"{view} holds its own content", not missing, missing or "")
# The filter bar reads for My Money alone now, and sits inside it.
check("the period / scope / benchmark bar lives inside My Money",
      'id="filters"' in bodies.get("money", "") and 'id="filters"' not in bodies.get("stocks", ""))
# Two tombstones and a permanently hidden panel were deleted with the move.
check("no tombstone note is left pointing at a tab that no longer exists",
      "has moved to the" not in MARKUP and 'id="changed"' not in MARKUP)

# Anything the script tries to render into must live inside some panel, or it
# is written to an element the user can never see.
in_panels = "".join(bodies.values())
# Controls that legitimately live outside the panels (the shared filter bar),
# plus ids created at runtime inside a panel and therefore invisible to a
# static scan of the markup.
OUTSIDE_OK = {"tabs", "alert", "asof", "symlist",
              "setupswl",   # created at runtime inside the Setups panel
              "phonebar", "phonemore", "moresheet", "moreback",  # the phone's bottom bar and its sheet
              "chartown",   # the OTC-line link under a proxied chart, created at runtime
              "gsopen",     # the header link that opens Get started
              "theme",      # the header's System / Light / Dark toggle
              # the Get started screen, rendered at runtime inside #getstarted (Overview)
              "gsclose", "gskey", "gssecret", "gssavekey", "gsprices", "gskeymsg", "gsstatus", "gsage", "gssaveprofile", "gsprofilemsg",
              "gssample", "gsunsample", "gssamplemsg",   # the sample-year buttons (D129)
              "planmax", "plangap", "planmsg"}   # the buy-plan form on a verdict card
# Built at runtime INSIDE #exitrules, which is itself inside the risk panel —
# a static scan of the markup cannot see them there.
DYNAMIC = {"addind", "ovtip", "nwtip", "nwchart",
           "exitpos", "exitsym", "exitdetail",
           # The range and scale pickers on the category small multiples, built
           # inside #bgCatTrend — which is a panel, just not one this static
           # scan can see into.
           "smrange", "smscale",
           # The "recorded" confirmation line, built inside #symread on the symbol page,
           # and the "open another name" box built into #symhead above it.
           "vdsaved", "symgo", "symgoform",
           # The book and the reason a decision is logged with, on the same page.
           "vdbucket", "vdwhy",
           # The trade-around panel and its core input, under My trades on a flagged name.
           "tradearound", "coreshares", "coresave",
           # The refresh button, built inside #pricefresh on the outlook panel
           # and only when the prices are actually behind.
           "pricepull"}
strays = [e for e in addressed
          if f'id="{e}"' in HTML and f'id="{e}"' not in in_panels
          and e not in OUTSIDE_OK | DYNAMIC]
check("no rendered element sits outside every panel", not strays, strays)

# Counting every "hidden>" in the file was close enough while the tab panels
# were the only hidden things on the page. They are not any more — the budget
# tab has its own sub-panels, five of six of them hidden — so the count has to
# name which elements it means rather than assume it owns the whole document.
tab_tags = re.findall(r'<section class="tab" data-panel="(\w+)"[^>]*>', MARKUP)
visible_tabs = [t for t in re.findall(r'<section class="tab" data-panel="\w+"[^>]*>', MARKUP) if " hidden" not in t]
check("only one section is visible on load", len(visible_tabs) == 1, visible_tabs)
check("and it is My Money, the landing screen", 'data-panel="money"' in "".join(visible_tabs), visible_tabs)

# The same invariant one level down, in every section: opening it must land
# on exactly one sub-panel, never all of them stacked or none at all.
for panel, body in bodies.items():
    sub_tags = re.findall(r'<div class="subpanel" data-sub-panel="[\w-]+"[^>]*>', body)
    visible_subs = [t for t in sub_tags if " hidden" not in t]
    check(f"only the first {panel} sub-panel is visible on load",
          len(sub_tags) > 1 and len(visible_subs) == 1 and visible_subs[0] == sub_tags[0], visible_subs)

    # Every sub-tab button needs a panel and vice versa — the same mismatch the
    # main tabs are checked for, which is the bug this whole file exists for.
    row = re.search(r'<div class="subtabs"[^>]*data-section="(\w+)"', body)
    sub_buttons = re.findall(r'<button data-sub="([\w-]+)"', body)
    sub_panels = re.findall(r'data-sub-panel="([\w-]+)"', body)
    check(f"every {panel} sub-tab has a matching sub-panel",
          row and row.group(1) == panel and sub_buttons and sorted(sub_buttons) == sorted(sub_panels),
          (sorted(sub_buttons), sorted(sub_panels)))
    # The script's SECTIONS table is what the router and the loaders read; it
    # must list the same sub-tabs in the same order as the row on screen.
    m = re.search(rf'^\s*{panel}:\s*\[([^\]]*)\]', SCRIPT, re.M)
    in_script = re.findall(r'"([\w-]+)"', m.group(1)) if m else []
    check(f"the script's SECTIONS entry for {panel} matches its sub-tab row",
          in_script == sub_buttons, (in_script, sub_buttons))

# Every old tab name — a bookmark, a deep link, a showTab("outlook") left in
# the script — must resolve to a view that exists.
OLD = ["overview", "diagnose", "holdings", "outlook", "setups", "newstocks", "trades", "risk",
       "chart", "watchlist", "sectors", "budget", "research", "tradebot", "backtest"]
old_map = dict(re.findall(r'\b(\w+): "([\w/]+)"', SCRIPT.split("const OLD_TABS", 1)[1].split("};", 1)[0]))
views = set(subbodies) | set(bodies)
bad = [t for t in OLD if old_map.get(t) not in views]
check("every old tab name redirects to a view that exists", not bad, bad)

# --- Phase 2, commit 3: Today and the symbol page ----------------------------
# The symbol page's header sits ABOVE its sub-tab row, so the five tabs read
# as tabs of the name; the mini chart and the scope switch are gone with the
# card; every name click goes through one door.
chart_body = bodies.get("chart", "")
check("the symbol page header precedes the Chart sub-tab row",
      0 <= chart_body.find('id="symhead"') < chart_body.find('class="subtabs"'))
check("the verdict card and its mini chart are retired",
      'id="verdictdetail"' not in MARKUP and "drawMini" not in SCRIPT and 'id="vdmini"' not in SCRIPT)
check("the Outlook scope switch is retired with the card",
      "OUT_SCOPE" not in SCRIPT and "showOutScope" not in SCRIPT)
check("one door for every name click: openSymbol", "function openSymbol(" in SCRIPT
      and SCRIPT.count("openSymbol(") >= 10, SCRIPT.count("openSymbol("))
check("the [data-sym] delegate opens the page, not a bare chart",
      re.search(r'closest\("\[data-sym\]"\)[\s\S]{0,400}openSymbol\(el\.dataset\.sym, "chart"\)', SCRIPT) is not None)
check("the old card's entry point still exists and lands on the page",
      re.search(r'function showVerdict\(sym\)\{ openSymbol\(sym, "read"\); \}', SCRIPT) is not None)
check("the Today list is one ranked list with a cap and a fold",
      "function renderTodo(" in SCRIPT and "TODO_CAP" in SCRIPT and "show all ${shown.length}" in SCRIPT)
check("the Today list ranks by dollars at stake, then by kind",
      re.search(r"b\.dollars - a\.dollars\s*\|\|\s*KIND_RANK\[a\.kind\] - KIND_RANK\[b\.kind\]", SCRIPT) is not None)
check("the Today list dedupes alerts the way the log does", "function dedupeAlerts(" in SCRIPT
      and SCRIPT.count("dedupeAlerts(") >= 3)
check("the Today list's empty state is the agreed sentence", "Nothing needs you today." in SCRIPT)
check("every alert kind says what to do in words", "function alertTodo(" in SCRIPT
      and all(f'case "{k}"' in SCRIPT for k in ("level", "verdict", "earnings", "wash", "ladder", "plan")))
check("the setups rows lead with the three prices",
      "function threeLevels(" in SCRIPT and "Buy at</th><th class=num scope=col>Sell into</th><th class=num scope=col>Wrong below</th>" in SCRIPT)
check("the calls table carries the same three columns",
      'title="The level to buy or add at' in SCRIPT and SCRIPT.count("${threeLevels(") >= 2)
check("Calls made renders into both hosts from one payload",
      '$("#jrnl")' in SCRIPT and '$("#jrnl2")' in SCRIPT and 'id="jrnl2"' in subbodies.get("money/trades", ""))
check("one method scanner, linked from the research page",
      'id="resscan"' not in MARKUP and "openMethodScan(" in SCRIPT and "#stocks/newstocks?method=" in SCRIPT)
check("the levels ladder marks what is the user's own",
      'class="minetag"' in SCRIPT and "Your drawn level" in SCRIPT and "Your target" in SCRIPT and "Your buy plan" in SCRIPT)

# --- Phase 2, commit 4: the chart -------------------------------------------
# One toolbar row above the chart; everything else behind two folds that
# remember their state; the indicator chips stay out. The chart opens on a
# year of bars, keeps its saved-settings keys, floors the linear axis at zero,
# carries one attribution, and paints what is the user's louder than what the
# app drew on its own.
chart_sub = subbodies.get("chart/chart", "")
_bar = re.search(r'<div class="bar" id="chartbar">(.*?)</div>', chart_sub, re.S)
_bar = _bar.group(1) if _bar else ""
check("the chart toolbar is one row: symbol, timeframe, range, Load, refresh, fullscreen",
      all(f'id="{i}"' in _bar for i in ["symbol", "tf", "rangetoggle", "loadsym", "refresh", "fullscreen"])
      and not any(f'id="{i}"' in _bar for i in ["setup", "hist", "scale", "compare", "paneSize", "chartdate"]))
_tools = chart_sub.split('data-fold="tools"', 1)[1].split("</details>", 1)[0] if 'data-fold="tools"' in chart_sub else ""
_levels = chart_sub.split('data-fold="levels"', 1)[1].split("</details>", 1)[0] if 'data-fold="levels"' in chart_sub else ""
check("Tools holds setup, as-of, history, panes, scale, compare, drawing and appearance",
      all(f'id="{i}"' in _tools for i in ["setup", "chartdate", "hist", "paneSize", "scale", "compare", "drawbar", "stylebox"]))
check("Levels & structure holds the structure toggles, show-all S/R and the S/R chips",
      all(f'id="{i}"' in _levels for i in ["stLines", "stZones", "stZonesAll", "structlegend"]))
check("the two folds remember whether they were open",
      "function foldOpen(" in SCRIPT and "function rememberFold(" in SCRIPT and 'details[data-fold]' in SCRIPT)
check("the indicator chip row stays outside the folds",
      'id="indbar"' in chart_sub and 'id="indbar"' not in _tools and 'id="indbar"' not in _levels)
check("the chart opens on a year of bars for the timeframe, 1Y / All toggled",
      "YEAR_BARS" in SCRIPT and re.search(r"YEAR_BARS = \{D: 250, W: 52, M: 12", SCRIPT) is not None
      and "showLastBars(yearBars())" in SCRIPT and "function setRangeChoice(" in SCRIPT)
check("the range choice is saved beside the older keys, which keep their names",
      'SETTINGS_KEY = "investment-app.settings.v1"' in SCRIPT and 'VIEW_KEY = "invest.chartview.v1"' in SCRIPT
      and "range: CHART_RANGE" in SCRIPT and 'saved.range === "all"' in SCRIPT)
# The price pane's chart is the createChart that follows the lower panes
# being cleared; the drawdown chart on Risk is built from the same call.
_main = SCRIPT.split('$("#lowerwrap").innerHTML = "";', 1)[1][:2500] if '$("#lowerwrap").innerHTML = "";' in SCRIPT else ""
_lower = SCRIPT.split("const lc = LightweightCharts.createChart(wrap, {", 1)[1][:900] if "createChart(wrap, {" in SCRIPT else ""
check("one attribution: the price pane keeps it, every lower pane drops it",
      "attributionLogo" not in _main and "attributionLogo:false" in _lower)
check("the linear price axis is floored at zero",
      "const linearFloor = " in SCRIPT and SCRIPT.count("autoscaleInfoProvider: linearFloor") >= 3)
check("the crosshair and grid take the theme's muted and grid tokens",
      "vertLine:{color:th.muted" in _main and "grid:{vertLines:{color:th.grid}, horzLines:{color:th.grid}}" in _main)
check("the volume pane is never under 90px",
      all(int(v) >= 90 for v in re.findall(r"vol: (\d+)", SCRIPT)) and re.findall(r"vol: (\d+)", SCRIPT))
check("the average cost is a 2px solid with a filled axis label",
      re.search(r'color:th\.mineCost, lineWidth:2,\s*lineStyle:0, axisLabelVisible:true, title:"avg cost"', SCRIPT) is not None)
check("the user's buy plans, target and stop are amber 2px lines with labels",
      all(f'color:th.mineLevel, lineWidth:2, lineStyle:0, axisLabelVisible:true, title:"{t}"' in SCRIPT
          for t in ["your buy plan", "your target", "your stop"]))
check("the verdict's three prices and the flip are drawn on the chart, and redrawn when the page lands",
      "function drawVerdictLines(" in SCRIPT and all(t in SCRIPT for t in ['"buy at"', '"sell into"', '"wrong below"', '"flips"'])
      and "drawVerdictLines(sym)" in SCRIPT and "drawVerdictLines(symbol)" in SCRIPT)
check("the fills are haloed size-2 arrows on their own layer",
      "function drawFillMarks(" in SCRIPT and 'className = "fillmarks"' in SCRIPT and "size:2, labels:true" in SCRIPT
      and "ctx.lineWidth = 2; ctx.strokeStyle = halo" in SCRIPT)
check("generic furniture is a hairline: MAs at 75%, trendlines 1px, S/R the nearest pair dashed",
      "rgba(colour, .75), lineWidth:1" in SCRIPT and "seg(l.from, l.to, STRUCT_COLOURS[l.side], 0, 1)" in SCRIPT
      and 'title: z === sup ? "S" : "R"' in SCRIPT and "if(opts.zonesAll)" in SCRIPT)
check("the read and the as-of line use the chart's level colours",
      "function threePriceLine(" in SCRIPT and SCRIPT.count("threePriceLine(") >= 3 and 'class="srlvl"' in SCRIPT)
check("the phone gets a chart of at least 420px and a one-line readout",
      "#pricechart{height:max(420px" in MARKUP and ".readout{flex-wrap:nowrap;overflow:hidden" in MARKUP)

# --- the script files ------------------------------------------------------
# Nine files, one per section plus core, in dependency order after the two
# vendored ones; core first, because it carries the fetch wrapper that stamps
# the write token on every /api/ request — a request sent from a file loaded
# before it would go out bare and be refused. The page's own script is one
# line: the init() call, so that nothing of the app lives inline any more.
SPLIT = ["core.js", "money.js", "today.js", "stocks.js", "follow.js", "bot.js",
         "symbol.js", "chart.js", "budget.js"]
check("the page loads the vendored scripts, then the nine app files, in order",
      _SRCS == VENDORED + SPLIT, _SRCS)
check("every app script file exists", all((ROOT / "app" / "static" / s).is_file() for s in SPLIT))
_core = (ROOT / "app" / "static" / "core.js").read_text()
check("the token fetch wrapper is the first thing in core.js, before any fetch",
      "window.fetch = " in _core and _core.index("window.fetch = ") < 2000
      and not re.search(r"(?<![.\w])fetch\(", _core[:_core.index("window.fetch = ")]))
check("the only inline script after the markup is the init() call",
      [x.strip() for x in _INLINE] == ["init();"], _INLINE)
check("init() is a declaration in money.js", "async function init(){" in (ROOT / "app" / "static" / "money.js").read_text())
check("no app file declares a top-level let or const another one also declares",
      len(_decls := re.findall(r"^(?:const|let)\s+([\w$]+)", SCRIPT, re.M)) == len(set(_decls)),
      sorted({d for d in _decls if _decls.count(d) > 1}))

# --- script sanity -------------------------------------------------------
# `top`, `name`, `status` and friends already exist on `window`. Declaring one
# with const/let at script scope is a SyntaxError that kills the ENTIRE script,
# so the page renders its shell, every fetch never fires, and the endpoints all
# still return 200 — which looks exactly like a broken server. That cost real
# time, so it is asserted rather than remembered.
WINDOW_GLOBALS = {"top", "name", "status", "length", "location", "history",
                  "parent", "self", "origin", "closed", "event", "external",
                  "frames", "screen", "menubar", "toolbar"}
script = "\n".join(re.findall(r"<script>(.*?)</script>", MARKUP, re.S)) + "\n" + SCRIPT
shadowed = sorted({m for m in re.findall(r"\b(?:const|let|var)\s+(\w+)\s*=", script)
                   if m in WINDOW_GLOBALS})
check("no declaration shadows a window global", not shadowed, shadowed)

# Every function the markup or the script calls must actually be defined.
defined = set(re.findall(r"(?:async\s+)?function\s+(\w+)", script))
# Arrow functions in every shape they are written here — `const f = x => …`,
# `const f = (a, b) => …`, `const f = async () => …`. Matching only the
# parenthesised form reported half this file's helpers as undefined, which is
# how this check came to be written so that it could never fail.
defined |= set(re.findall(
    r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\(|[A-Za-z_$][\w$]*\s*=>)",
    script))
called = set(re.findall(r"\b([a-zA-Z_]\w*)\s*\(", script))
# CSS functions appear inside style strings the script builds, so they are
# "called" by this regex without ever being JavaScript.
CSS_FUNCS = {"minmax","repeat","rgba","rgb","calc","translate","var","url",
             "linear-gradient","scale","rotate","hsl"}
BUILTINS = CSS_FUNCS | {"if","for","while","switch","catch","return","typeof","function",
            "fetch","parseFloat","parseInt","Number","String","Array","Object",
            "JSON","Math","Date","setTimeout","matchMedia","console","alert","confirm","prompt",
            "require","import","await","new","document","window","localStorage",
            "URLSearchParams","Promise","Set","Map","isNaN","encodeURIComponent",
            "decodeURIComponent","addEventListener","querySelector"}
missing = sorted(c for c in called - defined - BUILTINS
                 if c.islower() and len(c) > 3 and f"{c}(" in script
                 and f".{c}(" not in script and f"function {c}" not in script
                 # A CSS function inside a template literal is not a JS call.
                 # `linear-gradient(90deg,...)` matched as a call to
                 # `gradient()` — the regex sees the tail of a hyphenated name,
                 # and every CSS function would trip this the same way.
                 and f"-{c}(" not in script)
# `missing` was built by a comprehension whose own predicate was `f"{c}(" in
# script`, and the assertion then checked exactly that — true by construction,
# for any input. This is the check that exists to catch the blank-page bug, so
# it has to actually assert that the list is EMPTY.
# LIMIT, stated so nobody mistakes this for full coverage: the search is
# regex-based and cannot tell code from prose inside a template literal, so it
# is restricted to all-lowercase names. That catches this file's own helper
# style (money, pick, shade) but NOT a camelCase call, where "Alpha (" in a
# sentence is indistinguishable from a call to Alpha(). The real guard against
# the blank-page bug is the window-global shadowing check above, which is what
# that bug actually was.
check("no obviously undefined lowercase helper is called",
      not missing, missing[:8])

# --- the script must actually PARSE ----------------------------------------
# This project has shipped a blank page twice from a SyntaxError: once from
# `const top` shadowing a window global, once from a scope="col" insertion that
# terminated a JS string. Both times the whole suite was green, because nothing
# ever asked whether the script parses. If a JS engine is on the machine, ask.
import shutil as _shutil
import subprocess as _subprocess
import tempfile as _tempfile

_node = _shutil.which("node")
if _node:
    # Each file on its own — the browser parses them one at a time, and a
    # SyntaxError in one is that file's whole contents gone — and then all of
    # them as one script, which is what catches a top-level `let` or `const`
    # declared in two files: the second script throws and everything in it
    # is missing, with the first eight files apparently fine.
    for _name in APP_JS:
        _proc = _subprocess.run([_node, "--check", str(ROOT / "app" / "static" / _name)],
                                capture_output=True, text=True)
        check(f"static/{_name} parses as JavaScript", _proc.returncode == 0,
              (_proc.stderr or "").strip().splitlines()[:2])
    with _tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as _tmp:
        _tmp.write(script)
        _js = _tmp.name
    _proc = _subprocess.run([_node, "--check", _js], capture_output=True, text=True)
    check("the dashboard script parses as JavaScript", _proc.returncode == 0,
          (_proc.stderr or "").strip().splitlines()[:2])
    Path(_js).unlink(missing_ok=True)
else:
    # Not a silent skip: the tally would shrink and nothing would say why.
    check("a JS engine is available to syntax-check the dashboard", False,
          "install node to enable the parse check")

failures = [c for c in CHECKS if not c[1]]
# --- multi-series indicators ---------------------------------------------
# Indicators return either an ARRAY of points or an OBJECT of named series.
# The price pane special-cased Bollinger by name and passed everything else
# straight to setData(), so Keltner and Ichimoku handed it a plain object.
# Lightweight Charts drew nothing, and because the throw escaped the render
# callback, the average-cost line, the trade marks and the whole structure
# overlay never ran either — which is why turning Ichimoku on made HH/HL and
# the channels stop working. They were fine; they never got to draw.
import sqlite3 as _sq                                    # noqa: E402
from app import indicators as _I                          # noqa: E402

_bars = [{"time": f"2026-01-{d:02d}", "open": 10.0 + d, "high": 11.0 + d,
          "low": 9.0 + d, "close": 10.5 + d, "volume": 1000 + d}
         for d in range(1, 29)] * 20
for _i, _b in enumerate(_bars):
    _b["time"] = f"20{20 + _i // 365:02d}-{(_i % 12) + 1:02d}-{(_i % 28) + 1:02d}"

_dict_price = []
for _name, _meta in _I.REGISTRY.items():
    if _meta["pane"] != "price":
        continue
    try:
        _out = _meta["fn"](_bars)
    except TypeError:
        continue                       # needs explicit params; exercised elsewhere
    if isinstance(_out, dict):
        _dict_price.append(_name)

check("more than one price-pane indicator returns named series",
      len(_dict_price) > 1, _dict_price)
# The guard that makes them all work, rather than a name-by-name special case
# that the next banded indicator would silently fall through.
check("the price pane branches on shape, not on indicator name",
      "Array.isArray(sp.data)" in HTML)
check("Ichimoku's cloud is drawn rather than treated as loose lines",
      'spec.startsWith("ichimoku")' in HTML and "addAreaSeries" in HTML)
# One broken indicator must not take the rest of the chart down with it.
check("indicator drawing is isolated so one failure cannot abort the render",
      "failed to draw" in HTML)

for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<52} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
