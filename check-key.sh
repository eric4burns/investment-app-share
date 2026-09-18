#!/bin/sh
# Does the Alpaca key in data/.alpaca actually work?
#
# A one-command answer, because the alternative was a multi-line python -c with
# embedded newlines — which breaks the moment it is pasted into a terminal, and
# a leading ~ that only expands in a shell.
cd "$(dirname "$0")"
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from app.ledger import connect
from app import prices

creds = prices.alpaca_credentials()
if not creds:
    print("  No credentials found in data/.alpaca")
    raise SystemExit(1)

key, secret = creds
print(f"  reading data/.alpaca: key id starts {key[:2]!r} ({len(key)} chars), "
      f"secret {len(secret)} chars")

result = prices.ensure_symbol(connect(), "AAPL", "2026-08-01", "2026-08-28",
                              as_equity=True)
if result.get("ok"):
    print(f"  KEY WORKS — fetched {result.get('cached', 0)} bars of AAPL")
else:
    err = str(result.get("error") or "")
    print(f"  KEY DID NOT WORK — {err}")
    # 401 and 403 mean different things and point at different fixes.
    if "401" in err:
        print("  401 = Alpaca does not accept this key id + secret pair.")
        print("  Resetting your PASSWORD does not change the API key — they are")
        print("  separate. Regenerate the key in the dashboard and paste both")
        print("  lines in fresh.")
    elif "403" in err:
        print("  403 = the key is valid but not entitled to this data feed.")
    print("  Cached prices still work; only NEW price fetches fail.")
    raise SystemExit(1)
PY
