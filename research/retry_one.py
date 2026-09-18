"""Patiently retry a single video's transcript until YouTube's IP block lifts.

Bounded and slow on purpose: the block was earned by fetching too fast, so this
waits minutes between attempts rather than seconds and gives up rather than
grinding indefinitely.

    python3 research/retry_one.py <video_id> [channel] [minutes]
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_transcripts import OUT, transcript

vid = sys.argv[1] if len(sys.argv) > 1 else "LAVUBk28DSA"
channel = sys.argv[2] if len(sys.argv) > 2 else "TheRonnieVShow"
budget_min = int(sys.argv[3]) if len(sys.argv) > 3 else 40

folder = OUT / channel
folder.mkdir(parents=True, exist_ok=True)
deadline = time.time() + budget_min * 60
wait, attempt = 60, 0

while time.time() < deadline:
    attempt += 1
    try:
        got = transcript(vid)
    except Exception as exc:                                # noqa: BLE001
        print(f"attempt {attempt}: {type(exc).__name__}", flush=True)
        got = None
    if got:
        meta, text = got
        (folder / f"{vid}.txt").write_text(text)
        (folder / f"{vid}.json").write_text(json.dumps(meta, indent=2))
        print(f"GOT {vid}: {meta['chars']:,} chars — {meta['title']}", flush=True)
        sys.exit(0)
    print(f"  blocked; waiting {wait}s", flush=True)
    time.sleep(wait)
    wait = min(wait * 1.5, 420)

print("gave up — still blocked", flush=True)
sys.exit(1)
