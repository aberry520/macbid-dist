#!/usr/bin/env python3
"""MAC.BID automatic starrer — for the GitHub Actions workflow.

Runs unattended: refreshes the MAC.BID login, then stars the lots from the
same deal-finder scan. It never bids or buys — it only adds watchlist stars.

How it logs in (no email/password, no SMS code per run):
  The MAC.BID website keeps a refresh token in the browser and uses it to
  stay logged in: PUT https://api.macdiscount.com/auth/refresh-token with
  {"device_id": ..., "token": <raw refresh token>, "remember_me": false}.
  That returns a fresh short-lived access token AND a new refresh token
  (rotation — the old one stops working, and the window rolls 3 days
  forward from each refresh). This script does the same, then writes the
  NEW refresh token to a file so the workflow can save it back into the
  GitHub secret for the next run. If the run misses 3 days in a row, the
  refresh token dies and a human has to sign in again and update the secret.

Secrets (set in the repo: Settings -> Secrets and variables -> Actions):
  MACBID_REFRESH_TOKEN - the current refresh_token from the browser's
      mac_auths entry (DevTools -> Application -> Local Storage -> mac_auths).
      Re-copy it after any manual sign-in/refresh, since each refresh rotates it.
  MACBID_DEVICE_ID     - the device_id from the same place (localStorage).
  MACBID_USER_ID       - optional, defaults to 344685 (from the captured URL).

Environment (set by the workflow, not secrets):
  MACBID_TOKEN_OUT     - path of the file to write the new refresh token to.
      Written as soon as the refresh succeeds, before any starring, so the
      workflow can save it even if starring fails. The file is never
      committed to the repo and is deleted by the workflow after use.

The script NEVER prints any token value. Logs show lot numbers and counts only.

Usage:
  python3 star_action.py [--config config.yaml] [--dry-run]
                         [--test-one LOT_NUMBER] [--max-results N]
  --dry-run    : show what would be starred, without calling the API.
  --test-one   : star just one lot (by lot number, e.g. 1741S), for testing.
  --max-results: cap how many lots to star (default: config max_results).

Exit code 0 when every attempted lot is confirmed starred; 1 otherwise.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

USER_ID = os.environ.get("MACBID_USER_ID", "344685")
API_BASE = "https://api.macdiscount.com"
WATCHLIST_URL = f"{API_BASE}/user/{USER_ID}/watchlist"
REFRESH_URL = f"{API_BASE}/auth/refresh-token"

# The refresh call only worked from Postman, and plain curl hung until
# timeout — so this sends Postman's header set, exactly as the working
# Postman request did.
REFRESH_HEADERS = [
    "-H", "Accept: */*",
    "-H", "Accept-Encoding: gzip, deflate, br",
    "-H", "Connection: keep-alive",
    "-H", "Content-Type: application/json",
    "-H", "Origin: https://www.mac.bid",
    "-A", "PostmanRuntime/7.44.0",
]

# The watchlist calls need the browser's header set (plain curl hangs).
STAR_HEADERS = [
    "-H", "Accept: */*",
    "-H", "Accept-Language: en-US,en;q=0.9",
    "-H", "Origin: https://www.mac.bid",
    "-H", "Referer: https://www.mac.bid/",
    "-H", "Sec-Fetch-Dest: empty",
    "-H", "Sec-Fetch-Mode: cors",
    "-H", "Sec-Fetch-Site: cross-site",
    "-A", ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"),
]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from macbid_deals import load_config, search_lots  # noqa: E402


def curl_json(method, url, headers, body=None, timeout=30):
    """POST/PUT/GET with curl. Returns (status_code, parsed_json_or_None)."""
    cmd = ["curl", "-s", "-m", str(timeout), "-w", "\n%{http_code}",
           "-X", method, url] + headers
    if body is not None:
        cmd += ["-d", json.dumps(body, separators=(",", ":"))]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout + 10)
    out = proc.stdout.rsplit("\n", 1)
    text, code = (out[0], out[1]) if len(out) == 2 else (proc.stdout, "")
    try:
        data = json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        data = None
    try:
        return int(code), data
    except ValueError:
        return 0, data


def refresh_login(refresh_token, device_id):
    """Exchange the refresh token for a fresh access token.

    Returns (access_token, new_refresh_token). Raises on failure.
    The new refresh token replaces the old one — the caller must save it.
    """
    code, data = curl_json("PUT", REFRESH_URL, REFRESH_HEADERS, {
        "device_id": device_id,
        "token": refresh_token,  # raw token, NO "Bearer " prefix
        "remember_me": False,
    })
    if code != 200 or not isinstance(data, dict) \
            or not data.get("access_token"):
        detail = ""
        if isinstance(data, dict) and data.get("message"):
            detail = f" — {data['message']}"
        raise RuntimeError(
            f"Login refresh failed (HTTP {code}){detail}. The refresh token "
            "may have expired (it dies after 3 days without a refresh) — "
            "sign in on mac.bid again and update the MACBID_REFRESH_TOKEN "
            "secret with the fresh value from mac_auths.")
    return data["access_token"], data.get("refresh_token")


def star_one(token, lot_id, lot_number):
    """Star one lot. Returns (ok, note, auth_failed). Retries once on a
    soft failure. auth_failed is True when the site rejected the login
    itself (401), so the caller can try a different token."""
    for attempt in (1, 2):
        code, data = curl_json(
            "POST", WATCHLIST_URL,
            # The site sends the token BARE here — no "Bearer " prefix.
            # Sending "Bearer <token>" gets a 401 (proven by two live runs).
            ["-H", f"Authorization: {token}",
             "-H", "Content-Type: application/json"] + STAR_HEADERS,
            {"auction_lot_id": lot_id})
        if code == 401:
            return False, "login token rejected (401)", True
        if code == 200 and isinstance(data, dict) \
                and data.get("watchlist_date_created"):
            return True, "starred", False
        if code == 200 and isinstance(data, dict) and data.get("id") == lot_id:
            return True, "starred (no date in reply, id matches)", False
        note = f"attempt {attempt}: HTTP {code}"
        if isinstance(data, dict) and data.get("message"):
            note += f" — {data['message']}"
        if attempt == 1:
            time.sleep(1)
    return False, note, False


def get_watchlist_ids(token):
    """Best-effort read-back of the watchlist. Returns a set of lot ids, or
    None when the list call is not supported."""
    code, data = curl_json(
        "GET", WATCHLIST_URL,
        ["-H", f"Authorization: {token}"] + STAR_HEADERS)  # bare, no Bearer
    if code != 200 or data is None:
        return None
    items = data if isinstance(data, list) else data.get("watchlist") \
        or data.get("results") or data.get("data") or []
    ids = set()
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict):
            for key in ("auction_lot_id", "lot_id", "id"):
                if isinstance(it.get(key), int):
                    ids.add(it[key])
                    break
    return ids


def lot_internal_id(doc):
    """Internal numeric id for a Typesense lot document."""
    for key in ("lot_id", "auction_lot_id"):
        if isinstance(doc.get(key), int):
            return doc[key]
    return None


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Refresh MAC.BID login and "
                                 "star deal lots.")
    ap.add_argument("--config", default=os.path.join(here, "config.yaml"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-one")
    ap.add_argument("--max-results", type=int)
    args = ap.parse_args()

    cfg = load_config(args.config)
    warehouse = cfg.get("warehouse", "Anderson")
    min_retail = float(cfg.get("min_retail", 100))
    max_bid = float(cfg.get("max_bid", 30))
    look_ahead = float(cfg.get("look_ahead_hours", 7))
    max_results = args.max_results or int(cfg.get("max_results", 50))

    now = datetime.datetime.now(datetime.timezone.utc)
    now_epoch = int(now.timestamp())
    end_epoch = int((now + datetime.timedelta(hours=look_ahead)).timestamp())
    try:
        result = search_lots(warehouse, min_retail, max_bid, now_epoch,
                             end_epoch, per_page=max_results)
    except Exception as exc:  # noqa: BLE001 - report plainly
        print(f"MAC.BID scan failed: {exc}", file=sys.stderr)
        return 1

    lots = []
    for hit in result.get("hits", [])[:max_results]:
        d = hit["document"]
        lid = lot_internal_id(d)
        if lid is None:
            print(f"WARNING: no internal id for lot {d.get('lot_number')} "
                  f"({d.get('product_name')}) — skipping", file=sys.stderr)
            continue
        lots.append({
            "lot_id": lid,
            "lot_number": d.get("lot_number"),
            "product": (d.get("product_name") or "").strip(),
            "current_bid": d.get("current_bid"),
        })
    if args.test_one:
        lots = [l for l in lots
                if str(l["lot_number"]).upper() == args.test_one.upper()]
        if not lots:
            print(f"Lot {args.test_one} is not in the current scan "
                  f"(it may no longer match the filters).", file=sys.stderr)
            return 1

    print(f"{len(lots)} lot(s) to star "
          f"(warehouse {warehouse}, retail >= ${min_retail:g}, "
          f"bid <= ${max_bid:g})")
    for lot in lots:
        print(f"  Lot {lot['lot_number']}: {lot['product']} "
              f"(id {lot['lot_id']}, bid ${lot['current_bid']})")

    if args.dry_run:
        print("Dry run — nothing was starred.")
        return 0

    refresh_token = os.environ.get("MACBID_REFRESH_TOKEN", "").strip()
    device_id = os.environ.get("MACBID_DEVICE_ID", "").strip()
    if not refresh_token or not device_id:
        print("MACBID_REFRESH_TOKEN and MACBID_DEVICE_ID must be set — "
              "see README.md for where they come from.", file=sys.stderr)
        return 1

    try:
        access_token, new_refresh = refresh_login(refresh_token, device_id)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Login refreshed.")

    # Save the rotated token FIRST, before starring, so the workflow can
    # store it even if starring fails. The value is written to a file,
    # never printed.
    out_path = os.environ.get("MACBID_TOKEN_OUT", "").strip()
    if out_path and new_refresh:
        with open(out_path, "w") as f:
            f.write(new_refresh)
        print("New refresh token saved for the workflow to store.")
    elif not new_refresh:
        print("WARNING: refresh response had no new refresh token — the "
              "old one may still be valid, but the secret was not updated.",
              file=sys.stderr)

    token = access_token

    already = get_watchlist_ids(token)
    if already is not None:
        print(f"Watchlist already holds {len(already)} lot(s).")

    # Which token the site accepts as the login for starring is not fully
    # settled: the refresh response's access_token is the documented one,
    # but the first live run got 401 on every lot with it. The site's own
    # session also holds the (rotated) refresh token, so if the access
    # token is rejected, fall back to the refresh token as the login and
    # keep using whichever one works. The log records which one it was.
    bearer = token
    bearer_name = "access token"
    starred, failed = [], []
    for lot in lots:
        if already is not None and lot["lot_id"] in already:
            print(f"  Lot {lot['lot_number']}: already watched — skipped")
            starred.append(lot)
            continue
        ok, note, auth_failed = star_one(bearer, lot["lot_id"],
                                         lot["lot_number"])
        if auth_failed and bearer_name == "access token" and new_refresh:
            print(f"  Lot {lot['lot_number']}: access token rejected — "
                  f"retrying with the refresh token as the login")
            bearer = new_refresh
            bearer_name = "refresh token"
            ok, note, auth_failed = star_one(bearer, lot["lot_id"],
                                             lot["lot_number"])
        print(f"  Lot {lot['lot_number']}: {note}")
        (starred if ok else failed).append(lot)
        time.sleep(0.3)
    if starred and bearer_name != "access token":
        print(f"\nNote: starring worked with the {bearer_name}, not the "
              f"access token — the script will keep using it.")

    if failed:
        print(f"\n{len(failed)} lot(s) NOT starred:")
        for lot in failed:
            print(f"  Lot {lot['lot_number']}: {lot['product']}")
    if already is None:
        print("\nNote: could not read the watchlist back for a second check — "
              "the per-lot replies above are the confirmation.")
    else:
        after = get_watchlist_ids(bearer)
        if after is not None:
            missing = [l for l in starred if l["lot_id"] not in after]
            if missing:
                print("\nSecond check: these starred lots are NOT on the "
                      "watchlist after all:")
                for lot in missing:
                    print(f"  Lot {lot['lot_number']}: {lot['product']}")
                return 1
            print("\nSecond check: all starred lots confirmed on the "
                  "watchlist.")
    print(f"\nDone: {len(starred)} starred, {len(failed)} failed.")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
