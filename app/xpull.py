"""Pull the followed accounts' new posts from X, without a browser.

`research/x_pull.js` does this by hand: paste it into a logged-in x.com tab
once a week. That works, and it is also why the mention history is three days
long — a manual step that has to be remembered is a manual step that does not
happen. This is the same calls, made from here, so launchd can run it nightly.

What it needs from the user, once: the two cookies that identify their logged-in
session, in `data/.x`. There is no free API — X's own starts at $100 a month —
so the session is the only way to read the timelines. `data/` is gitignored.

Be aware of two things:

* **That cookie is the account.** Anyone holding it is logged in as the user.
  It is read from disk, sent only to x.com, and never logged or printed.
* **Automated collection sits outside X's terms of service.** This is a terms
  question, not a technical one, and it is the same stance the codebase already
  takes with the Yahoo fallback in prices.py: the choice is the user's, it is
  made once, and it is written down rather than buried.

The pull is deliberately slow. X answers with HTTP 429 after roughly twenty
accounts in an hour, so accounts are spaced out and a 429 backs off rather than
hammering.
"""
from __future__ import annotations

import gzip
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import netsafe

ROOT = Path(__file__).resolve().parent.parent
COOKIE_FILE = ROOT / "data" / ".x"
QUERY_CACHE = ROOT / "data" / "x-queryids.json"
HANDLE_CACHE = ROOT / "research" / "x" / "handles.json"
PULL_DIR = ROOT / "research" / "x" / "pulls"

# X's public web-client bearer. Not a secret: it is in every page of the site,
# and it is the token the browser itself sends.
BEARER = ("AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
          "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

# Seconds between accounts. The browser script used 3.5s and still hit the
# limit around twenty accounts; a nightly job has all night, so it can afford
# to be slow enough not to.
GAP = 150
# What a 429 costs before the next attempt, and how many times to take it.
BACKOFF = 900
RETRIES = 2
# How far back to look when there is no previous pull to continue from.
FIRST_PULL_DAYS = 7


class XPullError(RuntimeError):
    """Something the user has to fix — a missing or expired session."""


def credentials() -> tuple[str, str] | None:
    """auth_token and ct0 from data/.x, in that order. Comments are skipped."""
    if not COOKIE_FILE.exists():
        return None
    vals = [l.strip() for l in COOKIE_FILE.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")]
    # Tolerate "name=value" as well as a bare value: the natural thing to do is
    # copy the cookie row out of the browser, which brings the name with it.
    vals = [v.split("=", 1)[1] if v.lower().startswith(("auth_token=", "ct0=")) else v
            for v in vals]
    return (vals[0], vals[1]) if len(vals) >= 2 else None


def _fetch(url: str, auth: str, ct0: str, timeout: int = 45) -> str:
    req = urllib.request.Request(url, headers={
        "authorization": "Bearer " + urllib.parse.unquote(BEARER),
        "x-csrf-token": ct0,
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "content-type": "application/json",
        "user-agent": UA,
        "accept-encoding": "gzip",
        "cookie": f"auth_token={auth}; ct0={ct0}",
    })
    resp = netsafe.urlopen(req, timeout=timeout)
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def _page(url: str, auth: str, ct0: str) -> str:
    req = urllib.request.Request(url, headers={
        "user-agent": UA, "accept-encoding": "gzip",
        "cookie": f"auth_token={auth}; ct0={ct0}",
    })
    resp = netsafe.urlopen(req, timeout=45)
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


WANTED_OPS = ("UserTweets", "UserByScreenName")


def query_ids(auth: str, ct0: str, refresh: bool = False) -> dict[str, str]:
    """GraphQL query ids, which change with every deploy of X's front end.

    They live in the site's own JavaScript. WHICH page is asked for matters
    more than whether the session is valid: https://x.com/ serves a
    logged-out entry bundle whose 117 chunks contain none of these operations,
    while https://x.com/home serves a bundle that does — and it does so even
    with expired cookies, which was confirmed by a 401 arriving from the first
    GraphQL call rather than from discovery. So a dead session breaks the pull
    but not this.

    Cached, because discovery costs a hundred-odd requests to a CDN. A cached
    id that has gone stale shows up as an empty result rather than an error, so
    the caller re-runs this with refresh=True when a pull comes back empty.
    """
    if QUERY_CACHE.exists() and not refresh:
        cached = json.loads(QUERY_CACHE.read_text())
        if all(op in cached for op in WANTED_OPS):
            return cached

    html = _page("https://x.com/home", auth, ct0)
    found: dict[str, str] = {}
    seen: set[str] = set()
    for src in re.findall(r'src="(https://abs\.twimg\.com/[^"]+\.js)"', html):
        base = src.rsplit("/", 1)[0] + "/"
        todo = [src]
        while todo and len(found) < len(WANTED_OPS):
            url = todo.pop()
            if url in seen:
                continue
            seen.add(url)
            try:
                body = _page(url, auth, ct0)
            except Exception:                                  # noqa: BLE001
                continue
            for op in WANTED_OPS:
                m = re.search(r'queryId:"([^"]+)",operationName:"%s"' % op, body)
                if m:
                    found.setdefault(op, m.group(1))
            if len(seen) < 200:
                todo += [base + c.lstrip("./") for c in re.findall(
                    r'"\.?/?(assets/[A-Za-z0-9_.\-]+?-[A-Za-z0-9_]{8}\.js)"', body)]
    if not all(op in found for op in WANTED_OPS):
        raise XPullError(
            "Could not read X's GraphQL query ids from the logged-in page. "
            "That almost always means the session in data/.x has expired — "
            "sign in to x.com again and copy a fresh auth_token and ct0.")
    QUERY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    QUERY_CACHE.write_text(json.dumps(found, indent=2))
    return found


def _graphql(qid: str, op: str, variables: dict, auth: str, ct0: str,
             features: dict | None = None) -> dict:
    qs = "variables=" + urllib.parse.quote(json.dumps(variables))
    qs += "&features=" + urllib.parse.quote(json.dumps(features or {}))
    url = f"https://x.com/i/api/graphql/{qid}/{op}?{qs}"
    for attempt in range(RETRIES + 1):
        try:
            return json.loads(_fetch(url, auth, ct0))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < RETRIES:
                time.sleep(BACKOFF)
                continue
            if e.code in (401, 403):
                raise XPullError(
                    f"X refused the session ({e.code}). The cookies in data/.x "
                    "have expired; sign in to x.com and copy fresh ones.") from e
            raise
    raise XPullError("rate limited by X after retrying")


def handle_ids(handles: list[str], auth: str, ct0: str,
               qids: dict[str, str]) -> dict[str, str]:
    """Screen name -> numeric id, cached on disk.

    An account's id never changes, so this costs one request per handle ever
    rather than one per night. The browser script walked the user's whole
    following list to get these, which needed their own user id as well.
    """
    cache = json.loads(HANDLE_CACHE.read_text()) if HANDLE_CACHE.exists() else {}
    missing = [h for h in handles if h not in cache]
    for h in missing:
        data = _graphql(qids["UserByScreenName"], "UserByScreenName",
                        {"screen_name": h}, auth, ct0,
                        {"hidden_profile_subscriptions_enabled": True,
                         "responsive_web_graphql_exclude_directive_enabled": True,
                         "verified_phone_label_enabled": False,
                         "creator_subscriptions_tweet_preview_api_enabled": True,
                         "responsive_web_graphql_timeline_navigation_enabled": True})
        uid = (((data.get("data") or {}).get("user") or {}).get("result") or {}).get("rest_id")
        if uid:
            cache[h] = uid
        time.sleep(3)
    if missing:
        HANDLE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        HANDLE_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True))
    return cache


def _walk_tweets(node, acc: list) -> None:
    if not isinstance(node, dict):
        if isinstance(node, list):
            for v in node:
                _walk_tweets(v, acc)
        return
    if node.get("__typename") == "Tweet" and node.get("legacy") and node.get("rest_id"):
        acc.append(node)
    for v in node.values():
        _walk_tweets(v, acc)


def posts_for(uid: str, since: datetime, auth: str, ct0: str,
              qids: dict[str, str], count: int = 40) -> list[dict]:
    """The account's OWN posts since `since` — no retweets, no other people."""
    data = _graphql(qids["UserTweets"], "UserTweets",
                    {"userId": uid, "count": count, "includePromotedContent": False,
                     "withQuickPromoteEligibilityTweetFields": False,
                     "withVoice": False, "withV2Timeline": True},
                    auth, ct0)
    found: list = []
    _walk_tweets(data, found)
    out, seen = [], set()
    for t in found:
        legacy = t.get("legacy") or {}
        if str(legacy.get("user_id_str") or "") != str(uid):
            continue
        if legacy.get("retweeted_status_result") or (legacy.get("full_text") or "").startswith("RT @"):
            continue
        try:
            when = datetime.strptime(legacy["created_at"], "%a %b %d %H:%M:%S %z %Y")
        except (KeyError, ValueError):
            continue
        if when < since or t["rest_id"] in seen:
            continue
        seen.add(t["rest_id"])
        text = (((t.get("note_tweet") or {}).get("note_tweet_results") or {})
                .get("result") or {}).get("text") or legacy.get("full_text") or ""
        # The photos on the post — the charts. Kept as URLs here; xcharts.py
        # saves the files the same night, so a chart deleted later is still
        # on disk (the user asked to pull charts in by account, 2026-09-13).
        media = ((legacy.get("extended_entities") or {}).get("media")
                 or legacy.get("entities", {}).get("media") or [])
        images = [m.get("media_url_https") for m in media
                  if m.get("type") == "photo" and m.get("media_url_https")]
        out.append({"id": t["rest_id"], "date": when.isoformat(),
                    "text": re.sub(r"\s+", " ", text)[:600],
                    "reply": bool(legacy.get("in_reply_to_status_id_str")),
                    "images": images})
    return out


def last_pull_end() -> datetime | None:
    """Where the previous COMPLETED pull stopped, so nights neither overlap nor
    leave holes.

    A partial pull is skipped deliberately. Its timestamp covers only the
    accounts that finished, so treating it as the new starting point would
    silently skip everything the accounts it never reached had posted.
    """
    best = None
    for p in sorted(PULL_DIR.glob("*.json")) if PULL_DIR.exists() else []:
        try:
            d = json.loads(p.read_text())
        except (ValueError, OSError):
            continue
        if d.get("partial"):
            continue
        stamp = d.get("pulled") or d.get("since")
        if not stamp:
            continue
        try:
            when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        best = when if best is None or when > best else best
    return best


def pull(handles: list[str], since: datetime | None = None,
         gap: int = GAP, log=print, checkpoint=None, done: dict | None = None) -> dict:
    """Fetch each handle's new posts, checkpointing as it goes.

    A full pass takes over an hour, and the first real run was killed by memory
    pressure at about the fifty-minute mark with nothing written -- the result
    was only saved at the end. An unattended nightly job cannot work that way,
    so `checkpoint` is called with the partial result after every account and
    `done` lets a later run skip what is already in hand.
    """
    creds = credentials()
    if not creds:
        raise XPullError(
            f"No X session. Put auth_token on line 1 and ct0 on line 2 of "
            f"{COOKIE_FILE.relative_to(ROOT)} — see research/x/SETUP.md.")
    auth, ct0 = creds
    if since is None:
        prev = last_pull_end()
        since = prev or datetime.now(timezone.utc) - timedelta(days=FIRST_PULL_DAYS)
    qids = query_ids(auth, ct0)
    ids = handle_ids(handles, auth, ct0, qids)

    out = {"since": since.isoformat(), "started": datetime.now(timezone.utc).isoformat(),
           "note": "automated nightly pull (app/xpull.py)", "partial": True,
           "tweets": dict(done or {}), "errors": [], "ids": ids}
    todo = [h for h in handles if h not in out["tweets"]]
    if done:
        log(f"  resuming — {len(out['tweets'])} accounts already done, {len(todo)} to go")
    for i, h in enumerate(todo):
        uid = ids.get(h)
        if not uid:
            out["errors"].append(f"{h}: no user id")
            continue
        try:
            out["tweets"][h] = posts_for(uid, since, auth, ct0, qids)
            log(f"  {h}: {len(out['tweets'][h])} posts")
        except XPullError:
            raise
        except Exception as e:                                 # noqa: BLE001
            out["errors"].append(f"{h}: {e}")
            log(f"  {h}: {e}")
        if checkpoint:
            checkpoint(out)
        if i + 1 < len(todo):
            time.sleep(gap)
    # Only a finished pass may be used as the next run's starting point.
    out["partial"] = False
    out["pulled"] = datetime.now(timezone.utc).isoformat()
    return out
