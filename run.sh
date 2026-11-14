#!/bin/sh
# MAC.BID Deal Finder — Mac / Linux launcher. Double-click or run ./run.sh
cd "$(dirname "$0")"
python3 macbid_deals.py --out "reports/$(date +%Y%m%d-%H%M).md"
echo
echo "Report saved in the reports/ folder. Press Enter to close."
read -r _ 2>/dev/null || true
