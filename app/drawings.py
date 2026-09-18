"""Hand-drawn chart annotations, stored server-side.

The detector draws structure automatically, but nothing auto-drawn ever lands
exactly where you want it, and a line you cannot move or place yourself is a
suggestion rather than a tool. These are yours: placed by hand, adjusted by
hand, and kept.

Server-side rather than in browser storage for one reason — the phone. A
drawing saved in localStorage exists on the machine that made it and nowhere
else, and reaching this app from a phone is a stated requirement of the
project.

Coordinates are stored as (time, price) pairs, never pixels. A pixel is
meaningless the moment the window resizes or the range changes; a price on a
date survives both, and survives a timeframe change well enough to be
re-anchored rather than lost.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS drawings (
    id          INTEGER PRIMARY KEY,
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    pane        TEXT NOT NULL DEFAULT 'price',
    kind        TEXT NOT NULL,
    points      TEXT NOT NULL,
    colour      TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_drawings_chart ON drawings (symbol, timeframe);
"""

# A drawing the renderer does not understand is worse than none, so the kinds
# are closed and validated on the way in rather than trusted on the way out.
KINDS = {
    "trend":   2,      # two anchors; drawn only between them
    "ray":     2,      # two anchors; drawn between them and on to the right edge
    "level":   1,      # one anchor; only the price is used
    "channel": 3,      # two anchors plus a third fixing the parallel offset
    "fib":     2,      # two anchors defining the leg to retrace
}

# A trend and a ray differ only in where the renderer stops, so the same two
# anchors are valid for both and switching between them must not lose the line.
EXTENDABLE = ("trend", "ray")


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def _clean_points(kind: str, points) -> list[list]:
    want = KINDS[kind]
    if not isinstance(points, list) or len(points) != want:
        raise ValueError(f"{kind} needs exactly {want} point(s), got "
                         f"{len(points) if isinstance(points, list) else type(points).__name__}")
    out = []
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise ValueError("each point must be [time, price]")
        time, price = p
        # An anchor is a bar identifier, and there are now three shapes of one:
        # a business-day string on daily charts, a UNIX timestamp NUMBER on
        # intraday charts, and a "+N" logical offset for an anchor placed to the
        # RIGHT of the last bar, which is how a trendline or a fib is projected
        # into the future. All three are stored as text; only emptiness is
        # rejected.
        if isinstance(time, (int, float)) and not isinstance(time, bool):
            time = repr(int(time)) if float(time).is_integer() else repr(time)
        if not isinstance(time, str) or not time:
            raise ValueError("point time must be a bar date, timestamp or +offset")
        try:
            price = float(price)
        except (TypeError, ValueError):
            raise ValueError("point price must be a number") from None
        # A NaN or infinity would render as an invisible line that still
        # expands the price scale, which looks like a broken chart rather than
        # a bad drawing.
        if price != price or price in (float("inf"), float("-inf")):
            raise ValueError("point price must be finite")
        out.append([time, price])
    # A channel's third anchor fixes the parallel offset, so two anchors sharing
    # a timestamp make the base line vertical and the offset undefined. Rejected
    # here rather than stored and discovered when the chart will not paint.
    if kind in ("trend", "ray", "channel", "fib") and out[0][0] == out[1][0]:
        raise ValueError(f"a {kind} needs two DIFFERENT times, both are {out[0][0]}")
    return out


def add(conn, symbol: str, timeframe: str, kind: str, points,
        pane: str = "price", colour: str | None = None) -> dict:
    ensure_schema(conn)
    kind = (kind or "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"unknown drawing kind {kind!r}")
    cleaned = _clean_points(kind, points)
    row = conn.execute(
        """INSERT INTO drawings (symbol, timeframe, pane, kind, points, colour,
                                 created_at)
           VALUES (?,?,?,?,?,?,?)""",
        ((symbol or "").strip().upper(), (timeframe or "D").strip().upper()[:1],
         (pane or "price").strip()[:40], kind, json.dumps(cleaned), colour,
         datetime.now(timezone.utc).isoformat(timespec="seconds")))
    conn.commit()
    return {"id": row.lastrowid, "kind": kind, "points": cleaned, "pane": pane}


def move(conn, drawing_id: int, points) -> dict:
    """Replace a drawing's anchors, keeping its identity.

    Dragging an endpoint has to preserve the id, or every adjustment would
    create a new drawing and the old one would have to be found and deleted.
    """
    ensure_schema(conn)
    row = conn.execute("SELECT kind FROM drawings WHERE id = ?", (drawing_id,)).fetchone()
    if not row:
        return {"error": f"no drawing {drawing_id}"}
    cleaned = _clean_points(row["kind"], points)
    conn.execute("UPDATE drawings SET points = ? WHERE id = ?",
                 (json.dumps(cleaned), drawing_id))
    conn.commit()
    return {"id": drawing_id, "points": cleaned}


def remove(conn, drawing_id: int) -> dict:
    ensure_schema(conn)
    conn.execute("DELETE FROM drawings WHERE id = ?", (drawing_id,))
    conn.commit()
    return {"removed": drawing_id}


def clear(conn, symbol: str, timeframe: str) -> dict:
    """Every drawing on ONE chart. Deliberately not 'every drawing anywhere'."""
    ensure_schema(conn)
    cur = conn.execute("DELETE FROM drawings WHERE symbol = ? AND timeframe = ?",
                       ((symbol or "").strip().upper(),
                        (timeframe or "D").strip().upper()[:1]))
    conn.commit()
    return {"removed": cur.rowcount}


def for_chart(conn, symbol: str, timeframe: str) -> list[dict]:
    ensure_schema(conn)
    rows = conn.execute(
        """SELECT id, pane, kind, points, colour, created_at FROM drawings
            WHERE symbol = ? AND timeframe = ? ORDER BY id""",
        ((symbol or "").strip().upper(), (timeframe or "D").strip().upper()[:1]))
    return [{"id": r["id"], "pane": r["pane"], "kind": r["kind"],
             "points": json.loads(r["points"]), "colour": r["colour"],
             "created_at": r["created_at"]} for r in rows]
