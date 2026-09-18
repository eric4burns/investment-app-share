"""The first-run screen's back end: file kinds, safe names, multipart parsing,
the key and profile writes, and an upload that imports."""
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import setup_flow as sf

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

check("every kind names a folder, extensions and an importer", all({"folder", "ext", "importer", "label"} <= set(v) for v in sf.KINDS.values()))
check("every kind with a screen has export steps", all(k in sf.HOW_TO_EXPORT for k in ("fidelity", "robinhood", "bank", "cards", "payroll")))
check("a filename is reduced to a safe base name", sf.safe_name("../../etc/passwd") == "passwd" and sf.safe_name("Accounts_History (1).csv") == "Accounts_History _1_.csv", sf.safe_name("Accounts_History (1).csv"))

# multipart, the way a browser sends a FormData with one field and one file
body = (b"--XX\r\nContent-Disposition: form-data; name=\"kind\"\r\n\r\nfidelity\r\n"
        b"--XX\r\nContent-Disposition: form-data; name=\"file\"; filename=\"Accounts_History.csv\"\r\nContent-Type: text/csv\r\n\r\n"
        b"Run Date,Action,Symbol\r\n01/02/2026,YOU BOUGHT,IREN\r\n\r\n--XX--\r\n")
fields, files = sf.parse_multipart("multipart/form-data; boundary=XX", body)
check("the field and the file come out of a multipart body", fields.get("kind") == "fidelity" and len(files) == 1 and files[0][1] == "Accounts_History.csv", (fields, [f[:2] for f in files]))
check("the file's bytes are intact", files[0][2].startswith(b"Run Date,Action,Symbol"), files[0][2][:30])

# save_upload refuses the wrong extension and an empty file
try:
    sf.save_upload("fidelity", "notes.txt", b"x" * 100); check("a .txt is refused as a Fidelity CSV", False)
except ValueError as e:
    check("a .txt is refused as a Fidelity CSV", "should end in .csv" in str(e), str(e))
try:
    sf.save_upload("bank", "x.ofx", b""); check("an empty file is refused", False)
except ValueError as e:
    check("an empty file is refused", "empty" in str(e), str(e))
try:
    sf.save_upload("nope", "x.csv", b"x" * 100); check("an unknown kind is refused", False)
except ValueError as e:
    check("an unknown kind is refused", "unknown" in str(e), str(e))

# the key file and the profile, written to a temporary root
tmp = Path(tempfile.mkdtemp())
orig_key, orig_cfg = sf.prices.ALPACA_KEY_FILE, sf.config.CONFIG_PATH
try:
    sf.prices.ALPACA_KEY_FILE = tmp / "data" / ".alpaca"
    sf.config.CONFIG_PATH = tmp / "config.json"
    sf.write_alpaca("  PKTEST  ", "secret\n")
    check("the key is written as two clean lines", (tmp / "data" / ".alpaca").read_text() == "PKTEST\nsecret\n", (tmp / "data" / ".alpaca").read_text())
    r = sf.write_profile("married_jointly", "29")
    check("the profile lands in config.json and other keys survive", r == {"filing_status": "married_jointly", "age": 29}, r)
    (tmp / "config.json").write_text('{"savings_goal": 3500}')
    r = sf.write_profile("single", None)
    import json
    cfg = json.loads((tmp / "config.json").read_text())
    check("writing the profile keeps what was already in config.json", cfg.get("savings_goal") == 3500 and cfg.get("filing_status") == "single", cfg)
    try:
        sf.write_alpaca("", ""); check("an empty key is refused", False)
    except ValueError:
        check("an empty key is refused", True)
finally:
    sf.prices.ALPACA_KEY_FILE, sf.config.CONFIG_PATH = orig_key, orig_cfg

# The launchers a friend double-clicks. Phone access goes through Tailscale's
# private address only: the app has no password, so a launcher that bound
# 0.0.0.0 would put the ledger on whatever Wi-Fi the laptop joined.
ROOT = Path(__file__).resolve().parent.parent
for name in ("Investment App.command", "Investment App.bat"):
    text = (ROOT / name).read_text()
    check(f"{name}: never listens on every interface", "0.0.0.0" not in text)
    check(f"{name}: listens on the Tailscale address beside localhost when there is one",
          "tailscale" in text.lower() and re.search(r'INVESTMENT_APP_HOST="?127\.0\.0\.1,', text))
    check(f"{name}: prints the phone address, and how to get one when there is none",
          ":8737/" in text and "same account" in text.lower())
    # A friend is not asked to install Python: the launcher fetches a private
    # copy with uv when none is there (D128), and still opens python.org only
    # as the fallback when that fails.
    check(f"{name}: fetches Python itself when none is installed",
          "astral.sh/uv" in text and "run --no-project --python 3.12" in text and "python.org/downloads" in text)
mac = (ROOT / "Investment App.command").read_text()
check("the Mac launcher clears the quarantine flag once it is running",
      "xattr -dr com.apple.quarantine" in mac)
check("the Windows launcher sets no runtime variable inside a ( ) block",
      not re.search(r"\(\s*\n[^)]*set \"?UV=", (ROOT / "Investment App.bat").read_text()))
gs = (ROOT / "GETTING-STARTED.md").read_text()
check("getting started: has the phone steps", "## On your phone" in gs and "same account" in gs)
check("getting started: says nothing has to be installed, and how to get past the Gatekeeper block",
      "Nothing to install" in gs and "Open Anyway" in gs and "drag" in gs and "Run anyway" in gs)

failed = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  -> {detail}"))
print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
