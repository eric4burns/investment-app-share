"""The nightly X pull: parsing, filtering, and continuing from the last pull.

None of this touches the network. What is worth testing is everything around
the request — which posts count, where the window starts, and whether a
credential file a human typed is read the way they meant it.
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import xpull

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


# ---- credentials ---------------------------------------------------------
def creds_from(text):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".x"
        p.write_text(text)
        real, xpull.COOKIE_FILE = xpull.COOKIE_FILE, p
        try:
            return xpull.credentials()
        finally:
            xpull.COOKIE_FILE = real


check("two bare lines read as auth_token then ct0",
      creds_from("aaa\nbbb\n") == ("aaa", "bbb"))
check("comments and blank lines are skipped",
      creds_from("# auth_token first\n\naaa\n# then ct0\nbbb\n") == ("aaa", "bbb"))
# Copying the row straight out of the browser brings the name with it, and
# sending "auth_token=abc" as the value fails with a 401 that says nothing.
check("a pasted name=value pair is accepted",
      creds_from("auth_token=aaa\nct0=bbb\n") == ("aaa", "bbb"))
check("one line is not enough to be a session", creds_from("aaa\n") is None)
check("a missing file is no session, not a crash", creds_from("") is None)

# ---- which posts count ---------------------------------------------------
SINCE = datetime(2026, 9, 1, tzinfo=timezone.utc)
NEW = "Wed Sep 10 12:00:00 +0000 2026"
OLD = "Mon Aug 25 12:00:00 +0000 2026"


def tweet(tid, uid, when, text, **legacy):
    return {"__typename": "Tweet", "rest_id": tid,
            "legacy": {"user_id_str": uid, "created_at": when, "full_text": text, **legacy}}


def run(nodes, uid="7"):
    captured = {}

    def fake(qid, op, variables, auth, ct0, features=None):
        captured["vars"] = variables
        return {"data": {"list": nodes}}

    real, xpull._graphql = xpull._graphql, fake
    try:
        return xpull.posts_for(uid, SINCE, "a", "b", {"UserTweets": "q"}), captured
    finally:
        xpull._graphql = real


got, cap = run([
    tweet("1", "7", NEW, "$IREN looks ready"),
    tweet("2", "7", OLD, "old news $IREN"),
    tweet("3", "9", NEW, "someone else's post"),
    tweet("4", "7", NEW, "RT @someone: not mine"),
    tweet("5", "7", NEW, "quoted", retweeted_status_result={"x": 1}),
    tweet("1", "7", NEW, "$IREN looks ready"),
])
ids = [t["id"] for t in got]
check("a post from the account inside the window is kept", "1" in ids)
check("a post older than the window is dropped", "2" not in ids)
check("another account's post in the same response is dropped", "3" not in ids)
check("a retweet by text prefix is dropped", "4" not in ids)
check("a retweet by payload is dropped", "5" not in ids)
check("the same post appearing twice is stored once", ids.count("1") == 1, ids)
check("dates are normalised to ISO, which x-mentions.py can read",
      got and got[0]["date"].startswith("2026-09-10"), got[0]["date"] if got else None)
check("the request asks for the account's own timeline", cap["vars"]["userId"] == "7")

# A long post carries its full text in note_tweet, and the cashtags that matter
# are often past the 280-character cut.
long_post = tweet("9", "7", NEW, "truncated…")
long_post["note_tweet"] = {"note_tweet_results": {"result": {"text": "full $DGXX thesis"}}}
got, _ = run([long_post])
check("a long post uses its full text, not the truncated one",
      got[0]["text"] == "full $DGXX thesis", got[0]["text"] if got else None)

# The photos on a post are the charts; their URLs travel with the post so
# xcharts.py can save them the same night. A video is not a chart.
with_media = tweet("10", "7", NEW, "$IREN weekly", extended_entities={"media": [
    {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/a.jpg"},
    {"type": "video", "media_url_https": "https://pbs.twimg.com/media/v.jpg"},
    {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/b.jpg"}]})
got, _ = run([with_media, tweet("11", "7", NEW, "no picture")])
check("photo URLs travel with the post, videos do not",
      got[0]["images"] == ["https://pbs.twimg.com/media/a.jpg", "https://pbs.twimg.com/media/b.jpg"], got[0].get("images"))
check("a post with no media has an empty list", got[1]["images"] == [], got[1].get("images"))

# ---- where the window starts --------------------------------------------
with tempfile.TemporaryDirectory() as d:
    real, xpull.PULL_DIR = xpull.PULL_DIR, Path(d)
    try:
        check("with no pulls on disk there is nothing to continue from",
              xpull.last_pull_end() is None)
        (Path(d) / "2026-09-05.json").write_text(json.dumps(
            {"pulled": "2026-09-05T03:00:00+00:00", "tweets": {}}))
        (Path(d) / "2026-09-09.json").write_text(json.dumps(
            {"pulled": "2026-09-09T03:00:00+00:00", "tweets": {}}))
        # Continuing from the LATEST pull is what keeps nights from overlapping;
        # continuing from the earliest would re-read a week every night.
        check("the window continues from the most recent pull",
              xpull.last_pull_end() == datetime(2026, 9, 9, 3, tzinfo=timezone.utc),
              xpull.last_pull_end())
        (Path(d) / "broken.json").write_text("{not json")
        check("an unreadable pull does not stop the rest being read",
              xpull.last_pull_end() == datetime(2026, 9, 9, 3, tzinfo=timezone.utc))
        # A run killed part-way covers only the accounts it reached, so using
        # its timestamp as the next start would skip everything the accounts it
        # never got to had posted. The first real run died at ~50 minutes.
        (Path(d) / "2026-09-10.json").write_text(json.dumps(
            {"pulled": "2026-09-10T03:00:00+00:00", "partial": True, "tweets": {}}))
        check("a partial pull is not treated as a starting point",
              xpull.last_pull_end() == datetime(2026, 9, 9, 3, tzinfo=timezone.utc),
              xpull.last_pull_end())
        (Path(d) / "naive.json").write_text(json.dumps(
            {"pulled": "2026-09-11T03:00:00", "tweets": {}}))
        # A hand-edited file can lose the timezone, and comparing naive to aware
        # raises rather than returning a wrong answer, which would kill the job.
        check("a pull stamped without a timezone is still usable",
              xpull.last_pull_end() == datetime(2026, 9, 11, 3, tzinfo=timezone.utc))
    finally:
        xpull.PULL_DIR = real

# ---- the account list ----------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "research"))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "x_nightly", Path(__file__).resolve().parent.parent / "research" / "x-nightly.py")
x_nightly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(x_nightly)

accts = x_nightly.accounts()
check("the account list is read and is not empty", len(accts) > 10, len(accts))
check("comments in the account list are not treated as handles",
      not any(a.startswith("#") for a in accts))
check("a leading @ is stripped", not any(a.startswith("@") for a in accts))
check("handles are unique", len(accts) == len(set(accts)),
      [a for a in accts if accts.count(a) > 1])

# ---- the setup script refuses a bad paste --------------------------------
# The first version accepted an 8-character fragment as the auth_token with the
# real token in the ct0 slot. That reaches X as a plausible request and comes
# back "Could not authenticate you", which points the user at their session
# instead of at their paste.
import subprocess
SCRIPT = Path(__file__).resolve().parent.parent / "research" / "x" / "setup-session.sh"
AUTH = "a" * 40
CT0 = "b" * 160


def setup_with(first, second):
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "session"
        r = subprocess.run([str(SCRIPT)], input=f"{first}\n{second}\n", text=True,
                           capture_output=True, env={"PATH": "/usr/bin:/bin:/usr/sbin",
                                                     "X_SESSION_FILE": str(target)})
        return r.returncode, (r.stdout + r.stderr), target.exists()


code, out, wrote = setup_with("abcd1234", AUTH)
check("a truncated auth_token is refused", code != 0 and not wrote, code)
check("...and the message says which one was cut short", "cut short" in out, out[-160:])
# Shape tells the two apart with no ambiguity, so a swap is corrected rather
# than bounced back at someone who has already done the fiddly part.
code, out, wrote = setup_with(CT0, AUTH)
check("the two pasted in the wrong order are swapped, not refused", wrote, out[-200:])
check("...and the swap is mentioned rather than done silently",
      "other way round" in out)
code, out, wrote = setup_with(AUTH, "")
check("an empty second paste is refused", code != 0 and not wrote, code)
check("...and points at the Console's paste block",
      "allow pasting" in out)
code, out, wrote = setup_with("", "")
check("empty input writes nothing", code != 0 and not wrote, code)
code, out, wrote = setup_with(f"auth_token={AUTH}", f"ct0={CT0}")
check("a pasted name=value pair is stripped and accepted", wrote, out[-200:])

# ---- checkpointing -------------------------------------------------------
saved = []
calls = {"n": 0}


def fake_posts(uid, since, auth, ct0, qids, count=40):
    calls["n"] += 1
    if uid == "boom":
        raise RuntimeError("network gone")
    return [{"id": f"t{uid}", "date": "2026-09-10T00:00:00+00:00", "text": "x", "reply": False}]


real_posts, real_creds, real_qids, real_ids = (
    xpull.posts_for, xpull.credentials, xpull.query_ids, xpull.handle_ids)
xpull.posts_for = fake_posts
xpull.credentials = lambda: ("a", "b")
xpull.query_ids = lambda a, b, refresh=False: {"UserTweets": "q", "UserByScreenName": "q"}
xpull.handle_ids = lambda hs, a, b, q: {h: h for h in hs}
try:
    got = xpull.pull(["one", "two", "three"], since=SINCE, gap=0,
                     log=lambda m: None, checkpoint=lambda d: saved.append(len(d["tweets"])))
    check("the partial result is saved after every account", saved == [1, 2, 3], saved)
    check("a finished pass is not marked partial", got["partial"] is False)
    check("...and carries the timestamp the next run continues from", "pulled" in got)

    # Resuming must not re-request accounts already in hand: a full pass is an
    # hour against a limit of roughly twenty accounts per hour.
    calls["n"] = 0
    got = xpull.pull(["one", "two", "three"], since=SINCE, gap=0, log=lambda m: None,
                     done={"one": [], "two": []})
    check("a resumed pull only fetches what is missing", calls["n"] == 1, calls["n"])
    check("...and keeps the accounts already done", set(got["tweets"]) == {"one", "two", "three"})

    calls["n"] = 0
    got = xpull.pull(["one", "boom", "three"], since=SINCE, gap=0, log=lambda m: None)
    check("one account failing does not stop the rest",
          set(got["tweets"]) == {"one", "three"} and got["errors"], got["errors"])
finally:
    xpull.posts_for, xpull.credentials, xpull.query_ids, xpull.handle_ids = (
        real_posts, real_creds, real_qids, real_ids)

# ---- the rate limit ------------------------------------------------------
# The browser script used 3.5s between accounts and still hit 429 at about
# twenty. A nightly job has all night, so the default must be far slower.
check("accounts are spaced far enough apart to clear X's limit",
      xpull.GAP >= 60, xpull.GAP)
check("a full pass still fits in one night",
      xpull.GAP * len(accts) < 6 * 3600, xpull.GAP * len(accts))

failed = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<72} {detail if not ok else ''}")
print(f"\n  {len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
