"""Pull video transcripts from the analysts whose methods we want to encode.

Long-form video is far better raw material than posts: a tweet shows the
conclusion, a video shows the reasoning — which indicators are on the chart, on
what timeframe, what invalidates the setup, how size is chosen. Those are
exactly the fields a method definition needs and exactly what a post omits.

Transcripts are free, unlimited and searchable. This is a research-time tool,
not part of the app, so it may use a dependency the app itself does not.

    python3 research/fetch_transcripts.py            # all configured channels
    python3 research/fetch_transcripts.py CantoneseCat 12
"""
from __future__ import annotations

import html
import json
import re
import sys
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

import yt_dlp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ytpull  # noqa: E402

OUT = Path(__file__).resolve().parent / "transcripts"

# One list, in app/ytpull.py, keyed by the same handle the X pull uses so a
# person posting on both platforms counts once in the crowd reading.
CHANNELS = ytpull.CHANNELS

# Whisper, for videos with no captions at all. Cantonese Cat's chart videos are
# the case that forced this: no description, no chapters, no caption track, so
# the whole hour was unreadable. Built by research/video/setup.sh; absent is
# fine, it just means those videos are skipped as before.
WHISPER = Path(__file__).resolve().parent / "video" / "vendor" / "whisper.cpp"
WHISPER_BIN = WHISPER / "build" / "bin" / "whisper-cli"
WHISPER_MODEL = WHISPER / "models" / "ggml-small.en.bin"
# Transcribing runs at roughly half real time, so an unattended job needs a
# ceiling on both the length of one video and how many it will attempt.
WHISPER_MAX_MIN = 90
WHISPER_MAX_PER_RUN = 2


def list_videos(url: str, limit: int) -> list[dict]:
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
            "playlistend": limit, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=False)
    return [e for e in (info.get("entries") or []) if e.get("id")]


# YouTube rate-limits caption fetches hard, and running two channels at once
# earned a 429 on every request. Pace them and back off rather than hammering.
PACE_SECONDS = 4.0
MAX_ATTEMPTS = 4


def _fetch_with_backoff(url: str) -> bytes:
    delay = 8.0
    for attempt in range(MAX_ATTEMPTS):
        try:
            return urllib.request.urlopen(url, timeout=60).read()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == MAX_ATTEMPTS - 1:
                raise
            wait = delay * (2 ** attempt) + random.uniform(0, 3)
            print(f"      429 — waiting {wait:.0f}s")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def transcript(video_id: str) -> tuple[dict, str] | None:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "writeautomaticsub": True, "writesubtitles": True, "subtitleslangs": ["en"]}
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

    tracks = (info.get("subtitles") or {}).get("en") or \
             (info.get("automatic_captions") or {}).get("en") or []
    pick = next((t for t in tracks if t.get("ext") == "json3"), tracks[0] if tracks else None)
    if not pick:
        return None
    raw = _fetch_with_backoff(pick["url"]).decode("utf-8", "replace")
    if pick.get("ext") == "json3":
        data = json.loads(raw)
        text = " ".join(seg.get("utf8", "")
                        for ev in data.get("events", []) for seg in (ev.get("segs") or []))
    else:
        text = re.sub(r"<[^>]+>", "", raw)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()

    meta = {"id": video_id, "title": info.get("title"),
            "channel": info.get("channel") or info.get("uploader"),
            "upload_date": info.get("upload_date"),
            "duration_min": round((info.get("duration") or 0) / 60, 1),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "chars": len(text)}
    return meta, text


def whisper_transcript(video_id: str, info: dict) -> tuple[dict, str] | None:
    """Transcribe the audio locally, for a video YouTube has no captions for.

    Everything here is already on the machine: yt-dlp fetches the audio track,
    afconvert (part of macOS) makes the 16 kHz mono WAV whisper.cpp wants.
    """
    import subprocess
    import tempfile
    if not (WHISPER_BIN.exists() and WHISPER_MODEL.exists()):
        return None
    minutes = (info.get("duration") or 0) / 60
    if minutes > WHISPER_MAX_MIN:
        print(f"      too long for whisper ({minutes:.0f} min)")
        return None
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        audio = tmp / "a.m4a"
        opts = {"quiet": True, "no_warnings": True, "format": "bestaudio[ext=m4a]/bestaudio",
                "outtmpl": str(audio), "hls_prefer_native": True}
        with yt_dlp.YoutubeDL(opts) as y:
            y.download([f"https://www.youtube.com/watch?v={video_id}"])
        got = audio if audio.exists() else next(iter(tmp.glob("a.*")), None)
        if not got:
            return None
        wav = tmp / "a.wav"
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
                        str(got), str(wav)], check=True, capture_output=True)
        out = tmp / "t"
        subprocess.run([str(WHISPER_BIN), "-m", str(WHISPER_MODEL), "-f", str(wav),
                        "-otxt", "-of", str(out), "-np"], check=True, capture_output=True)
        text = (out.with_suffix(".txt")).read_text()
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    meta = {"id": video_id, "title": info.get("title"),
            "channel": info.get("channel") or info.get("uploader"),
            "upload_date": info.get("upload_date"),
            "duration_min": round(minutes, 1),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "source": "whisper", "chars": len(text)}
    return meta, text


def fetch(channel: str, url: str, limit: int) -> None:
    folder = OUT / channel
    folder.mkdir(parents=True, exist_ok=True)
    try:
        videos = list_videos(url, limit)
    except Exception as exc:                              # noqa: BLE001
        print(f"  {channel}: cannot list — {type(exc).__name__}: {str(exc)[:90]}")
        return
    print(f"  {channel}: {len(videos)} recent videos")
    for v in videos:
        path = folder / f"{v['id']}.txt"
        if path.exists():
            print(f"    have  {v['id']}  {(v.get('title') or '')[:60]}")
            continue
        try:
            got = transcript(v["id"])
        except Exception as exc:                          # noqa: BLE001
            print(f"    FAIL  {v['id']}  {type(exc).__name__}: {str(exc)[:60]}")
            continue
        if not got:
            if fetch.whispered < WHISPER_MAX_PER_RUN:
                print(f"    no captions — transcribing {v['id']} locally")
                try:
                    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                           "skip_download": True}) as y:
                        info = y.extract_info(
                            f"https://www.youtube.com/watch?v={v['id']}", download=False)
                    got = whisper_transcript(v["id"], info)
                except Exception as exc:                      # noqa: BLE001
                    print(f"    FAIL  {v['id']}  whisper: {type(exc).__name__}: {str(exc)[:60]}")
                    got = None
                fetch.whispered += 1
            if not got:
                print(f"    none  {v['id']}  (no captions)")
                continue
        meta, text = got
        path.write_text(text)
        time.sleep(PACE_SECONDS)
        (folder / f"{v['id']}.json").write_text(json.dumps(meta, indent=2))
        print(f"    got   {v['id']}  {meta['chars']:>6,} chars  {meta['duration_min']:>5}min  "
              f"{(meta['title'] or '')[:52]}")


fetch.whispered = 0


def main() -> int:
    args = sys.argv[1:]
    limit = int(args[1]) if len(args) > 1 else 8
    targets = {args[0]: CHANNELS[args[0]]} if args and args[0] in CHANNELS else CHANNELS
    for name, url in targets.items():
        fetch(name, url, limit)
    total = sum(1 for _ in OUT.rglob("*.txt"))
    chars = sum(len(p.read_text()) for p in OUT.rglob("*.txt"))
    print(f"\n  {total} transcripts, {chars:,} characters in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
