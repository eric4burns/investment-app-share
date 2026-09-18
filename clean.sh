#!/bin/sh
# Remove regenerable output only. Never touches data/, ledger*.db or config.json.
cd "$(dirname "$0")"
rm -rf node_modules; find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
find logs -name '*.log' -mtime +30 -delete 2>/dev/null
echo "investment-app: cleaned (npm install brings node_modules back; tests/phone_shots.mjs needs it)"
