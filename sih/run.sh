#!/bin/bash
# ============================================================
#  SIH AeroTwin - quick launcher (Linux/macOS).
#  Paths resolve from this script's own location.
# ============================================================
cd "$(dirname "$0")"

python3 start_app.py start
sleep 5
echo "System is live."
