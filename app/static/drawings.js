/**
 * Hand-drawn chart annotations: a canvas laid over the chart.
 *
 * The first attempt drew these as line series on the chart itself. That is why
 * it failed, in three separate ways that all trace back to the same choice:
 *
 *   - A series takes part in autoscale, so one drawing with degenerate geometry
 *     stretched the price scale until the candles were a flat smear. That was
 *     the "the whole chart disappeared while I was scrolling" report.
 *   - A series is not hit-testable. There is no way to ask which line the
 *     pointer is over, so a placed channel could not be selected, and with no
 *     selection there was no delete. That was "I can't click on it so there's
 *     no way to delete it".
 *   - A series owns its own data, so moving a line meant rebuilding it.
 *
 * A canvas above the chart has none of those properties. It cannot touch the
 * price scale, hit-testing is ordinary geometry, and moving a shape is moving
 * two numbers. The chart underneath is never modified at all.
 *
 * Anchors are (time, price), never pixels — a pixel means nothing after a
 * resize or a zoom. Time is snapped to a bar on placement, which is both what
 * traders expect and what keeps the anchor mappable after a timeframe change.
 */
(function (global) {
  "use strict";

  var HANDLE = 4.5;            // half-size of an anchor square, in pixels
  var GRAB = 9;                // how close the pointer must be to grab a line
  var FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
  var FIB_EXT = [1.618, 2];

  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

  // Distance from a point to a segment. The whole of hit-testing rests on this,
  // so it handles the degenerate zero-length case rather than dividing by zero
  // and returning NaN, which compares false against every threshold and makes a
  // shape silently unselectable.
  function distToSegment(px, py, x1, y1, x2, y2) {
    var dx = x2 - x1, dy = y2 - y1;
    var len2 = dx * dx + dy * dy;
    if (len2 === 0) return Math.hypot(px - x1, py - y1);
    var t = clamp(((px - x1) * dx + (py - y1) * dy) / len2, 0, 1);
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
  }

  function ChartDrawings(opts) {
    this.chart = opts.chart;
    this.series = opts.series;
    this.host = opts.host;
    this.bars = opts.bars || [];
    this.symbol = opts.symbol;
    this.timeframe = opts.timeframe;
    this.theme = opts.theme || {};
    this.onChange = opts.onChange || function () {};
    this.onError = opts.onError || function () {};

    this.items = [];
    this.tool = "cursor";
    this.selected = null;
    this.draft = null;          // shape being placed
    this.drag = null;           // {mode, id, handle, from}
    // Amber: the one colour the page reserves for what the user drew.
    this.colour = opts.colour || "#F59E0B";
    this.disposed = false;

    this._index = new Map();
    this.setBars(this.bars);
    this._buildCanvas();
    this._bind();
    this._loop();
  }

  ChartDrawings.prototype.setBars = function (bars) {
    this.bars = bars || [];
    this._index = new Map();
    for (var i = 0; i < this.bars.length; i++) this._index.set(this.bars[i].time, i);
  };

  // ------------------------------------------------------------- canvas ----
  ChartDrawings.prototype._buildCanvas = function () {
    var c = this.canvas = document.createElement("canvas");
    c.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:3";
    if (getComputedStyle(this.host).position === "static") this.host.style.position = "relative";
    this.host.appendChild(c);
    this.ctx = c.getContext("2d");
    this._resize();
  };

  ChartDrawings.prototype._resize = function () {
    var dpr = global.devicePixelRatio || 1;
    var w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return false;
    if (this.canvas.width === Math.round(w * dpr) && this.canvas.height === Math.round(h * dpr)) return false;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.canvas.style.width = w + "px";
    this.canvas.style.height = h + "px";
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return true;
  };

  // -------------------------------------------------------- coordinates ----
  ChartDrawings.prototype.indexOf = function (time) {
    var ahead = this.futureOffset(time);
    if (ahead != null) return this.bars.length - 1 + ahead;
    if (this._index.has(time)) return this._index.get(time);
    if (!this.bars.length) return null;
    // A drawing placed on the daily chart has anchors no weekly bar shares.
    // Falling back to the nearest bar re-anchors it instead of dropping it,
    // which is the difference between a line that follows you across
    // timeframes and one that silently disappears.
    var lo = 0, hi = this.bars.length - 1;
    if (time <= this.bars[0].time) return 0;
    if (time >= this.bars[hi].time) return hi;
    while (lo < hi - 1) {
      var mid = (lo + hi) >> 1;
      if (this.bars[mid].time <= time) lo = mid; else hi = mid;
    }
    return this.bars[lo].time === time ? lo
      : (time - this.bars[lo].time < this.bars[hi].time - time ? lo : hi);
  };

  ChartDrawings.prototype.xOf = function (time) {
    var i = this.indexOf(time);
    if (i == null) return null;
    return this.chart.timeScale().logicalToCoordinate(i);
  };
  ChartDrawings.prototype.yOf = function (price) {
    var y = this.series.priceToCoordinate(price);
    return (y == null || !isFinite(y)) ? null : y;
  };
  ChartDrawings.prototype.priceAt = function (y) {
    var p = this.series.coordinateToPrice(y);
    return (p == null || !isFinite(p)) ? null : p;
  };
  // Snapping to a bar is deliberate. An anchor between bars has no time to
  // store, and a line whose end wobbles with sub-pixel pointer movement is the
  // "clunky" feeling this is meant to fix.
  // An anchor to the RIGHT of the last bar is stored as a logical OFFSET,
  // "+12", rather than a time. There is no bar there to name, and extrapolating
  // a date would have to know about weekends, holidays and the timeframe. An
  // offset is none of those things and survives switching daily to weekly,
  // which a fabricated timestamp would not.
  //
  // This is what lets a trendline or a fib be projected forward, which is the
  // direction anyone actually reads them in.
  ChartDrawings.prototype.snapTime = function (x) {
    if (!this.bars.length) return null;
    var l = this.chart.timeScale().coordinateToLogical(x);
    if (l == null) return null;
    var i = Math.round(l), last = this.bars.length - 1;
    if (i > last) return "+" + Math.min(i - last, ChartDrawings.MAX_FUTURE);
    return this.bars[clamp(i, 0, last)].time;
  };

  ChartDrawings.MAX_FUTURE = 400;   // far enough to be useful, not unbounded

  ChartDrawings.prototype.futureOffset = function (time) {
    return (typeof time === "string" && time.charAt(0) === "+")
      ? parseInt(time.slice(1), 10) : null;
  };

  ChartDrawings.prototype.pointsOf = function (d) {
    var out = [];
    for (var i = 0; i < d.points.length; i++) {
      var x = this.xOf(d.points[i][0]), y = this.yOf(d.points[i][1]);
      if (x == null || y == null) return null;
      out.push([x, y]);
    }
    return out;
  };

  // ------------------------------------------------------------ geometry ----
  // Where a shape's outline runs, as a list of segments in pixels. Hit-testing
  // and painting both read this, so a shape can never be drawn somewhere it
  // cannot be clicked — which is exactly how the last version stranded a
  // channel on screen with no way to select it.
  ChartDrawings.prototype.segmentsOf = function (d) {
    var p = this.pointsOf(d);
    if (!p || !p.length) return null;
    // Two anchors is the minimum for everything except a level, whether the
    // shape is finished or still being dragged out.
    if (d.kind !== "level" && p.length < 2) return null;
    var w = this.plot().w;
    if (d.kind === "level") return [[0, p[0][1], w, p[0][1]]];
    if (d.kind === "trend") return [[p[0][0], p[0][1], p[1][0], p[1][1]]];
    if (d.kind === "ray") {
      var dx = p[1][0] - p[0][0], dy = p[1][1] - p[0][1];
      if (dx === 0) return [[p[0][0], p[0][1], p[1][0], p[1][1]]];
      var t = (w - p[0][0]) / dx;
      return [t > 1 ? [p[0][0], p[0][1], p[0][0] + dx * t, p[0][1] + dy * t]
        : [p[0][0], p[0][1], p[1][0], p[1][1]]];
    }
    if (d.kind === "channel") {
      // A channel is drawn while it is still being placed, and until the third
      // click it has only two anchors. Reaching for the missing one threw on
      // every animation frame of the placement — a hundred exceptions to draw
      // one shape, none of which the smoke test saw, because it only ever drew
      // a trendline.
      if (p.length < 3) return [[p[0][0], p[0][1], p[1][0], p[1][1]]];
      var off = this._channelOffset(p);
      return [[p[0][0], p[0][1], p[1][0], p[1][1]],
      [p[0][0], p[0][1] + off, p[1][0], p[1][1] + off]];
    }
    if (d.kind === "fib") {
      var segs = [], lo = p[0][1], hi = p[1][1];
      var all = FIB.concat(FIB_EXT);
      var x1 = Math.min(p[0][0], p[1][0]), x2 = Math.max(p[0][0], p[1][0]);
      for (var i = 0; i < all.length; i++) {
        var y = lo + (hi - lo) * all[i];
        segs.push([x1, y, w, y]);
      }
      return segs;
    }
    return null;
  };

  // The parallel edge is offset in PIXELS, not price. On a log scale a fixed
  // price offset is not a parallel line, and the channel visibly splays.
  ChartDrawings.prototype._channelOffset = function (p) {
    var dx = p[1][0] - p[0][0];
    if (dx === 0) return 0;
    var onLine = p[0][1] + (p[1][1] - p[0][1]) * ((p[2][0] - p[0][0]) / dx);
    return p[2][1] - onLine;
  };

  // ----------------------------------------------------------- painting ----
  // The plot area only: the canvas covers the whole chart element, but the
  // price axis down the right and the time axis along the bottom are not places
  // a drawing belongs. Unclipped, a level ran straight through the price labels
  // and a steep trendline crossed the dates.
  ChartDrawings.prototype.plot = function () {
    var w = this.host.clientWidth, h = this.host.clientHeight;
    var right = 0, bottom = 0;
    try { right = this.chart.priceScale("right").width() || 0; } catch (e) {}
    try { bottom = this.chart.timeScale().height() || 0; } catch (e) {}
    return { w: Math.max(0, w - right), h: Math.max(0, h - bottom) };
  };

  ChartDrawings.prototype.render = function () {
    if (this.disposed) return;
    var ctx = this.ctx, w = this.host.clientWidth, h = this.host.clientHeight;
    if (!ctx || !w) return;
    ctx.clearRect(0, 0, w, h);
    var plot = this.plot();
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, plot.w, plot.h);
    ctx.clip();
    for (var i = 0; i < this.items.length; i++) this._paint(this.items[i], this.items[i].id === this.selected);
    if (this.draft) this._paint(this.draft, true, true);
    ctx.restore();
  };

  ChartDrawings.prototype._paint = function (d, isSel, isDraft) {
    var ctx = this.ctx;
    var segs = this.segmentsOf(d);
    if (!segs) return;
    var colour = d.colour || this.colour;

    // Shading needs both edges. Until the third click a channel has one, so the
    // fill is skipped rather than reaching for an edge that is not there yet —
    // the draft still draws as a plain line, which is what it is.
    if (d.kind === "channel" && segs.length >= 2) {
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(segs[0][0], segs[0][1]); ctx.lineTo(segs[0][2], segs[0][3]);
      ctx.lineTo(segs[1][2], segs[1][3]); ctx.lineTo(segs[1][0], segs[1][1]);
      ctx.closePath();
      ctx.fillStyle = colour; ctx.globalAlpha = 0.10; ctx.fill();
      ctx.restore();
    }

    ctx.save();
    ctx.strokeStyle = colour;
    // What the user drew is theirs: a level is one of the chart's 2px solids,
    // over the 1px furniture the app draws on its own.
    ctx.lineWidth = isSel ? 2.5 : (d.kind === "level" ? 2 : 1.75);
    if (isDraft) ctx.setLineDash([5, 4]);
    for (var i = 0; i < segs.length; i++) {
      var s = segs[i];
      // A fib's extension levels are dashed so a projected target never reads
      // as a level price has actually respected.
      var isExt = d.kind === "fib" && i >= FIB.length;
      ctx.save();
      if (isExt) { ctx.setLineDash([4, 4]); ctx.globalAlpha = 0.75; }
      ctx.beginPath(); ctx.moveTo(s[0], s[1]); ctx.lineTo(s[2], s[3]); ctx.stroke();
      ctx.restore();
    }
    ctx.restore();

    if (d.kind === "fib") this._fibLabels(d, segs, colour);
    if (d.kind === "level" && !isDraft) this._levelLabel(d, segs[0], colour);
    if (isSel) this._handles(d);
  };

  // A level's price, as a filled tag at the left end of the line — the same
  // shape the price axis gives the average-cost line, so a hand-drawn level
  // reads as a labelled level and not as a stray rule.
  ChartDrawings.prototype._levelLabel = function (d, seg, colour) {
    var ctx = this.ctx;
    var price = d.points && d.points[0] ? d.points[0][1] : null;
    if (price == null) return;
    var text = "your level " + Number(price).toFixed(price >= 100 ? 1 : 2);
    ctx.save();
    ctx.font = "600 11px -apple-system,BlinkMacSystemFont,'Inter','Segoe UI',Roboto,sans-serif";
    var w = ctx.measureText(text).width + 10, h = 16;
    var x = 6, y = seg[1] - h / 2;
    ctx.fillStyle = colour;
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.fill();
    ctx.fillStyle = "#131722";
    ctx.textBaseline = "middle";
    ctx.fillText(text, x + 5, seg[1]);
    ctx.restore();
  };

  ChartDrawings.prototype._fibLabels = function (d, segs, colour) {
    var ctx = this.ctx, all = FIB.concat(FIB_EXT);
    var p = this.pointsOf(d); if (!p) return;
    var lo = d.points[0][1], hi = d.points[1][1];
    ctx.save();
    ctx.font = "10px ui-monospace,Menlo,monospace";
    ctx.fillStyle = colour;
    ctx.textBaseline = "middle";
    for (var i = 0; i < segs.length && i < all.length; i++) {
      var price = lo + (hi - lo) * all[i];
      ctx.fillText(all[i].toFixed(3).replace(/0+$/, "").replace(/\.$/, "") +
        "  " + price.toFixed(2), segs[i][0] + 4, segs[i][1] - 6);
    }
    ctx.restore();
  };

  ChartDrawings.prototype._handles = function (d) {
    var p = this.pointsOf(d);
    if (!p) return;
    var ctx = this.ctx;
    ctx.save();
    // The card ground, from chartTheme() when it is given; the literals are
    // its --bg-1 per theme.
    ctx.fillStyle = this.theme.bg || (this.theme.dark ? "#1B1F2B" : "#FFFFFF");
    ctx.strokeStyle = d.colour || this.colour;
    ctx.lineWidth = 1.75;
    for (var i = 0; i < p.length; i++) {
      ctx.beginPath();
      ctx.rect(p[i][0] - HANDLE, p[i][1] - HANDLE, HANDLE * 2, HANDLE * 2);
      ctx.fill(); ctx.stroke();
    }
    ctx.restore();
  };

  // ------------------------------------------------------- hit testing ----
  ChartDrawings.prototype.handleAt = function (x, y) {
    // Newest first, so the shape drawn on top is the one grabbed.
    for (var i = this.items.length - 1; i >= 0; i--) {
      var d = this.items[i];
      if (d.id !== this.selected) continue;
      var p = this.pointsOf(d);
      if (!p) continue;
      for (var j = 0; j < p.length; j++) {
        if (Math.abs(x - p[j][0]) <= GRAB && Math.abs(y - p[j][1]) <= GRAB) {
          return { id: d.id, handle: j };
        }
      }
    }
    return null;
  };

  ChartDrawings.prototype.itemAt = function (x, y) {
    for (var i = this.items.length - 1; i >= 0; i--) {
      var d = this.items[i];
      var segs = this.segmentsOf(d);
      if (!segs) continue;
      for (var j = 0; j < segs.length; j++) {
        var s = segs[j];
        if (distToSegment(x, y, s[0], s[1], s[2], s[3]) <= GRAB) return d;
      }
    }
    return null;
  };

  // ------------------------------------------------------------- events ----
  ChartDrawings.prototype._at = function (e) {
    var r = this.host.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  ChartDrawings.prototype._bind = function () {
    var self = this;
    // Capture phase, on the host. The chart library binds to its own canvas
    // inside this element, so listening here runs first and lets us decide
    // per-event whether this is a drawing gesture or an ordinary pan. Swallow
    // everything and the chart stops panning; swallow nothing and a drag on a
    // line scrolls the chart out from under it.
    this._down = function (e) {
      if (e.button !== 0) return;
      var pt = self._at(e);

      if (self.tool !== "cursor") {
        // Click to start, click again to finish. Holding the button down still
        // works for anyone who prefers it — see _up — but it is no longer the
        // only way, which is what every charting package people are used to
        // does and what this did not.
        if (self.draft) self._finishDraft(); else self._startDraft(pt);
        self._downAt = pt;
        self._eat(e); return;
      }

      var h = self.handleAt(pt.x, pt.y);
      if (h) {
        self.drag = { mode: "handle", id: h.id, handle: h.handle };
        self._eat(e); return;
      }
      var hit = self.itemAt(pt.x, pt.y);
      if (hit) {
        self.select(hit.id);
        self.drag = { mode: "body", id: hit.id, last: pt,
                      lastLogical: self.chart.timeScale().coordinateToLogical(pt.x) };
        self._eat(e); return;
      }
      // Nothing under the pointer: drop the selection and let the chart pan.
      if (self.selected != null) { self.select(null); }
    };

    this._move = function (e) {
      var pt = self._at(e);
      if (self.draft) { self._extendDraft(pt); self._eat(e); return; }
      if (self.drag) { self._applyDrag(pt); self._eat(e); return; }
      // Hover styling only while the pointer is actually over the chart. The
      // move listener is on the window so a drag that leaves the chart still
      // tracks, but that also means it fires for every mouse move on the page,
      // and running hit tests against all of them is pure waste.
      if (!self.host.contains(e.target)) return;
      if (self.tool !== "cursor") { self.host.style.cursor = "crosshair"; return; }
      var over = self.handleAt(pt.x, pt.y) || self.itemAt(pt.x, pt.y);
      self.host.style.cursor = over ? "pointer" : "";
    };

    this._up = function (e) {
      if (self.draft) {
        // Only a genuine DRAG completes on release. A click barely moves, and
        // finishing on its release is what forced the button to be held down:
        // the draft would end the instant it began.
        //
        // Two guards, because 6px was not enough. A real mouse click jitters,
        // and a click that reads as a 7px drag finished the draft with both
        // anchors on the SAME BAR — which _finishDraft discards in silence and
        // then resets the tool, so nothing appeared and the only thing that
        // seemed to work was holding the button down. The distance is now 12px,
        // and a release also refuses to finish anything that is not yet a valid
        // drawing: two anchors on one bar is never what anyone meant.
        var from = self._downAt, pt = self._at(e);
        var far = from && Math.abs(pt.x - from.x) + Math.abs(pt.y - from.y) > 12;
        var d = self.draft, need = ChartDrawings.KINDS[d.kind];
        var distinct = need < 2 || (d.points.length > 1 &&
                                    d.points[0][0] !== d.points[1][0]);
        if (far && distinct) self._finishDraft();
        self._eat(e); return;
      }
      if (self.drag) {
        var id = self.drag.id, moved = self.drag.moved;
        self.drag = null;
        if (moved) self._persistMove(id);
        self._eat(e);
      }
    };

    this._key = function (e) {
      if (e.key === "Escape") {
        if (self.draft) { self.draft = null; self.render(); }
        self.setTool("cursor");
        return;
      }
      if ((e.key === "Delete" || e.key === "Backspace") && self.selected != null) {
        var t = e.target && e.target.tagName;
        if (t === "INPUT" || t === "TEXTAREA" || t === "SELECT") return;
        e.preventDefault();
        self.remove(self.selected);
      }
    };

    this.host.addEventListener("pointerdown", this._down, true);
    global.addEventListener("pointermove", this._move, true);
    global.addEventListener("pointerup", this._up, true);
    global.addEventListener("keydown", this._key);
  };

  ChartDrawings.prototype._eat = function (e) {
    e.preventDefault();
    e.stopPropagation();
    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
  };

  // -------------------------------------------------------- placing ----
  ChartDrawings.prototype._startDraft = function (pt) {
    var time = this.snapTime(pt.x), price = this.priceAt(pt.y);
    if (time == null || price == null) return;
    var need = ChartDrawings.KINDS[this.tool];
    if (this.draft && this.draft.kind === this.tool) return;
    this.draft = { id: -1, kind: this.tool, colour: this.colour,
                   points: [[time, price], [time, price]].slice(0, Math.max(2, need)) };
    if (this.tool === "level") this.draft.points = [[time, price]];
    this.draft.placed = 1;
    this.render();
  };

  ChartDrawings.prototype._extendDraft = function (pt) {
    var d = this.draft; if (!d) return;
    var time = this.snapTime(pt.x), price = this.priceAt(pt.y);
    if (time == null || price == null) return;
    var i = Math.min(d.placed, d.points.length - 1);
    d.points[i] = [time, price];
    if (d.kind === "channel" && d.placed >= 2) {
      // The third anchor only contributes its price offset, so it tracks the
      // pointer vertically and stays under the second anchor horizontally.
      d.points[2] = [d.points[1][0], price];
    }
    this.render();
  };

  ChartDrawings.prototype._finishDraft = function () {
    var d = this.draft; if (!d) return;
    var need = ChartDrawings.KINDS[d.kind];
    d.placed++;
    if (d.kind === "channel" && d.placed === 2) {
      // Two clicks set the base line; the third sets the width. Keep drafting.
      d.points[2] = [d.points[1][0], d.points[1][1]];
      this.render();
      return;
    }
    if (d.placed < need) { this.render(); return; }
    var points = d.points.slice(0, need);
    // Two anchors on the same bar is a vertical line: undrawable, and the
    // server refuses it. Catching it here means a stray double-click is a
    // no-op rather than an error toast.
    if (need > 1 && points[0][0] === points[1][0]) {
      this.draft = null; this.setTool("cursor"); this.render(); return;
    }
    this.draft = null;
    this.setTool("cursor");
    this._persistAdd(d.kind, points, d.colour);
  };

  ChartDrawings.KINDS = { trend: 2, ray: 2, level: 1, channel: 3, fib: 2 };

  // -------------------------------------------------------- dragging ----
  ChartDrawings.prototype._applyDrag = function (pt) {
    var d = this.byId(this.drag.id); if (!d) return;
    if (this.drag.mode === "handle") {
      var time = this.snapTime(pt.x), price = this.priceAt(pt.y);
      if (time == null || price == null) return;
      var pts = d.points.map(function (p) { return p.slice(); });
      pts[this.drag.handle] = d.kind === "channel" && this.drag.handle === 2
        ? [pts[2][0], price] : [time, price];
      if (d.points.length > 1 && pts[0][0] === pts[1][0]) return;   // stays drawable
      d.points = pts;
      this.drag.moved = true;
      this.render();
      return;
    }
    // Body drag. Both axes move through the chart's own conversions rather than
    // by adding a delta to the stored values, so this is correct on a log scale
    // and after a scale change, where a fixed price delta is not a fixed
    // distance on screen.
    var logical = this.chart.timeScale().coordinateToLogical(pt.x);
    if (logical == null) return;
    var dLogical = Math.round(logical - this.drag.lastLogical);
    var dy = pt.y - this.drag.last.y;
    if (!dLogical && !dy) return;
    var self = this, ok = true;
    var next = d.points.map(function (p) {
      var i = self.indexOf(p[0]);
      var y = self.yOf(p[1]);
      if (i == null || y == null) { ok = false; return p; }
      var ni = clamp(i + dLogical, 0, self.bars.length - 1);
      var np = self.priceAt(y + dy);
      if (np == null) { ok = false; return p; }
      return [self.bars[ni].time, np];
    });
    if (!ok) return;
    if (next.length > 1 && next[0][0] === next[1][0]) return;
    d.points = next;
    this.drag.last = pt;
    this.drag.lastLogical = this.drag.lastLogical + dLogical;
    this.drag.moved = true;
    this.render();
  };

  // ------------------------------------------------------------- state ----
  ChartDrawings.prototype.byId = function (id) {
    return this.items.filter(function (d) { return d.id === id; })[0] || null;
  };

  ChartDrawings.prototype.setItems = function (list) {
    this.items = (list || []).map(function (d) {
      return { id: d.id, kind: d.kind, points: d.points, colour: d.colour, pane: d.pane };
    });
    if (this.selected != null && !this.byId(this.selected)) this.selected = null;
    this.render();
    this.onChange(this.items, this.selected);
  };

  ChartDrawings.prototype.setTool = function (tool) {
    this.tool = tool || "cursor";
    if (this.tool === "cursor") this.host.style.cursor = "";
    this.draft = null;
    this.onChange(this.items, this.selected);
    this.render();
  };

  ChartDrawings.prototype.select = function (id) {
    this.selected = id;
    this.render();
    this.onChange(this.items, this.selected);
  };

  ChartDrawings.prototype.setColour = function (c) { this.colour = c; };

  ChartDrawings.prototype.setTheme = function (t) { this.theme = t || {}; this.render(); };

  // --------------------------------------------------------- server io ----
  ChartDrawings.prototype._q = function (extra) {
    var q = new URLSearchParams({ symbol: this.symbol, timeframe: this.timeframe });
    for (var k in extra) if (extra[k] != null) q.set(k, extra[k]);
    return q;
  };

  // A GET, like every other mutation in this app. That is a wart — a write
  // behind a GET is why the server needs a Sec-Fetch-Site guard at all — but it
  // is the convention here, and the guard covers it. Half-migrating one
  // endpoint to POST would leave the rest unprotected by the same reasoning
  // while gaining nothing.
  ChartDrawings.prototype._post = function (extra) {
    var self = this;
    return fetch("/api/drawings?" + this._q(extra))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.error) { self.onError(j.error); return null; }
        return j;
      })
      .catch(function (e) { self.onError(String(e && e.message || e)); return null; });
  };

  ChartDrawings.prototype.reload = function () {
    var self = this;
    return fetch("/api/drawings?" + this._q({}))
      .then(function (r) { return r.json(); })
      .then(function (j) { self.setItems(j && j.drawings); return j; })
      .catch(function (e) { self.onError(String(e && e.message || e)); });
  };

  ChartDrawings.prototype._persistAdd = function (kind, points, colour) {
    var self = this;
    // Shown immediately with a temporary id, so placing a line never feels like
    // it is waiting on the network, then reconciled with what the server
    // actually stored.
    var temp = { id: -Date.now(), kind: kind, points: points, colour: colour };
    this.items.push(temp);
    this.select(temp.id);
    this._post({ action: "add", kind: kind, points: JSON.stringify(points), colour: colour })
      .then(function (j) {
        if (!j || !j.id) {
          self.items = self.items.filter(function (d) { return d !== temp; });
          self.select(null);
          return;
        }
        temp.id = j.id;
        self.select(j.id);
      });
  };

  ChartDrawings.prototype._persistMove = function (id) {
    var d = this.byId(id);
    if (!d || d.id < 0) return;
    this._post({ action: "move", id: d.id, points: JSON.stringify(d.points) });
  };

  ChartDrawings.prototype.remove = function (id) {
    var self = this;
    var d = this.byId(id); if (!d) return;
    this.items = this.items.filter(function (x) { return x.id !== id; });
    if (this.selected === id) this.selected = null;
    this.render();
    this.onChange(this.items, this.selected);
    if (d.id > 0) this._post({ action: "remove", id: d.id });
  };

  ChartDrawings.prototype.clear = function () {
    var self = this;
    this.items = []; this.selected = null;
    this.render(); this.onChange(this.items, this.selected);
    return this._post({ action: "clear" });
  };

  // ------------------------------------------------------------- loop ----
  // Redraw when the view has actually moved, checked rather than subscribed to.
  // The chart emits a visible-range event for pan and zoom but nothing at all
  // for a price-scale drag or an autoscale, so an event-driven overlay slides
  // out of alignment with the candles in exactly the cases nobody tests.
  ChartDrawings.prototype._loop = function () {
    var self = this;
    var last = "";
    function frame() {
      if (self.disposed) return;
      try {
        var r = self.chart.timeScale().getVisibleLogicalRange();
        var probe = self.bars.length
          ? self.series.priceToCoordinate(self.bars[self.bars.length - 1].close) : 0;
        var sig = [r && r.from, r && r.to, probe,
                   self.host.clientWidth, self.host.clientHeight].join("|");
        var resized = self._resize();
        if (sig !== last || resized) { last = sig; self.render(); }
      } catch (e) { /* the chart is mid-teardown; the next frame will settle */ }
      self._raf = requestAnimationFrame(frame);
    }
    this._raf = requestAnimationFrame(frame);
  };

  ChartDrawings.prototype.dispose = function () {
    this.disposed = true;
    if (this._raf) cancelAnimationFrame(this._raf);
    this.host.removeEventListener("pointerdown", this._down, true);
    global.removeEventListener("pointermove", this._move, true);
    global.removeEventListener("pointerup", this._up, true);
    global.removeEventListener("keydown", this._key);
    if (this.canvas && this.canvas.parentNode) this.canvas.parentNode.removeChild(this.canvas);
    this.host.style.cursor = "";
  };

  global.ChartDrawings = ChartDrawings;
})(window);
