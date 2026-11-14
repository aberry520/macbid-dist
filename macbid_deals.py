#!/usr/bin/env python3
"""MAC.BID deal finder.

Scans MAC.BID's public lot search (the same search index the mac.bid website
itself uses) for live lots closing soon, and reports the ones that fit the
settings in config.yaml next to this script:

  - retail_price >= min_retail
  - current_bid <= max_bid   (bid price only; fees/tax NOT added)
  - lot is AT the configured warehouse, or can be transferred there
  - closing within look_ahead_hours of the run time

Usage:
  python3 macbid_deals.py [--config config.yaml] [--min-retail N] [--max-bid N]
                          [--warehouse NAME] [--look-ahead-hours N] [--out FILE]
  Overrides on the command line beat the config file.

Output: a Markdown report printed to stdout. With --out, also saved to a file.
Exit code 0 even when no lots match (the report just says so); 1 on error.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

TYPESENSE_HOST = "xczkhpt94lod37gqp.a1.typesense.net"
# Search-only key published in mac.bid's own public website code; it can only
# search the public lot index, it cannot bid, log in, or change anything.
TYPESENSE_API_KEY = "jxX8RU6YVOkm9esgd9buaYjulIWv6N52"
COLLECTION = "prod_macdiscount_alias"
ET = datetime.timezone(datetime.timedelta(hours=-5))  # Eastern, standard time


def load_config(path):
    cfg = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            cfg[key.strip()] = value.strip()
    return cfg


def num(v):
    """Typesense numeric filters need ints for int32 fields like current_bid."""
    return str(int(v)) if float(v) == int(float(v)) else str(v)


def search_lots(warehouse, min_retail, max_bid, now_epoch, end_epoch, per_page=50):
    # Typesense filter: live lots, retail high enough, bid low enough,
    # closing in the window, and at the warehouse or transferable to it.
    filter_by = (
        "lot_status:LIVE && "
        f"retail_price:>={num(min_retail)} && current_bid:<={num(max_bid)} && "
        f"expected_closing_utc:>{now_epoch} && expected_closing_utc:<{end_epoch} && "
        f"(auction_location:{warehouse} || transfer_locations:{warehouse})"
    )
    body = {"searches": [{
        "collection": COLLECTION,
        "q": "*",
        "query_by": "product_name",
        "filter_by": filter_by,
        "sort_by": "expected_closing_utc:asc",
        "per_page": per_page,
        "exclude_fields": "embedding,description,keywords,images,inventory_images",
    }]}
    # NOTE: this endpoint is fetched with curl, not urllib — Python's urllib
    # intermittently fails reading the chunked responses from this host
    # (IncompleteRead), while curl handles them reliably.
    last_exc = None
    for _attempt in range(3):
        try:
            proc = subprocess.run(
                ["curl", "-s", "-m", "30", "-X", "POST",
                 f"https://{TYPESENSE_HOST}/multi_search",
                 "-H", f"X-TYPESENSE-API-KEY: {TYPESENSE_API_KEY}",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps(body)],
                capture_output=True, text=True, timeout=40)
            if proc.returncode != 0:
                raise RuntimeError(f"curl failed (rc={proc.returncode}): {proc.stderr.strip()}")
            result = json.loads(proc.stdout)["results"][0]
            if "error" in result:
                raise RuntimeError(f"MAC.BID search error: {result.get('error')}")
            return result
        except Exception as exc:  # noqa: BLE001 - transport is flaky; retry, then fail loudly
            last_exc = exc
            if isinstance(exc, RuntimeError) and "search error" in str(exc):
                raise
            time.sleep(2)
    raise RuntimeError(f"MAC.BID search failed after retries: {last_exc}")


def fmt_money(v):
    return f"${v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else f"${v}"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="MAC.BID deal finder")
    ap.add_argument("--config", default=os.path.join(here, "config.yaml"))
    ap.add_argument("--warehouse")
    ap.add_argument("--min-retail", type=float)
    ap.add_argument("--max-bid", type=float)
    ap.add_argument("--look-ahead-hours", type=float)
    ap.add_argument("--max-results", type=int)
    ap.add_argument("--out")
    args = ap.parse_args()

    cfg = load_config(args.config)
    warehouse = args.warehouse or cfg.get("warehouse", "Anderson")
    min_retail = args.min_retail if args.min_retail is not None else float(cfg.get("min_retail", 100))
    max_bid = args.max_bid if args.max_bid is not None else float(cfg.get("max_bid", 30))
    look_ahead = args.look_ahead_hours if args.look_ahead_hours is not None else float(cfg.get("look_ahead_hours", 7))
    max_results = args.max_results or int(cfg.get("max_results", 50))

    now = datetime.datetime.now(datetime.timezone.utc)
    now_epoch = int(now.timestamp())
    end_epoch = int((now + datetime.timedelta(hours=look_ahead)).timestamp())
    run_et = now.astimezone(ET)

    try:
        result = search_lots(warehouse, min_retail, max_bid, now_epoch, end_epoch,
                             per_page=max_results)
    except Exception as exc:  # noqa: BLE001 - report plainly, don't crash the cron
        print(f"MAC.BID scan failed: {exc}", file=sys.stderr)
        return 1

    hits = result.get("hits", [])
    found = result.get("found", len(hits))

    lines = []
    lines.append(f"# MAC.BID deals — {run_et:%A %B %d, %Y at %-I:%M %p ET}")
    lines.append("")
    lines.append(f"Warehouse: **{warehouse}** (lots at {warehouse}, or transferable there)  ")
    lines.append(f"Filters: retail ≥ {fmt_money(min_retail)} · current bid ≤ {fmt_money(max_bid)} (bid only, no fees) · closing in the next {look_ahead:g}h  ")
    lines.append(f"Found: **{found}** lot{'s' if found != 1 else ''} closing by {(now + datetime.timedelta(hours=look_ahead)).astimezone(ET):%-I:%M %p ET}")
    lines.append("")

    if not hits:
        lines.append("No lots match right now. Nothing to bid on under these settings.")
    else:
        for hit in hits[:max_results]:
            d = hit["document"]
            close = datetime.datetime.fromtimestamp(
                d["expected_closing_utc"], datetime.timezone.utc).astimezone(ET)
            mins_left = max(0, int((d["expected_closing_utc"] - now_epoch) / 60))
            hours, mins = divmod(mins_left, 60)
            left = f"{hours}h {mins}m" if hours else f"{mins}m"
            retail = d.get("retail_price") or 0
            bid = d.get("current_bid") or 0
            pct = int(round(100 * (1 - bid / retail))) if retail else 0
            at = "at warehouse" if d.get("auction_location") == warehouse else "transferable"
            url = f"https://www.mac.bid/?aid={d.get('auction_id')}&lid={d.get('lot_number')}"
            lines.append(f"## {d.get('product_name', '').strip()} — Lot {d.get('lot_number')}")
            lines.append(f"- **Retail {fmt_money(retail)} · current bid {fmt_money(bid)}** ({pct}% off retail) · {d.get('condition', '')} · {d.get('category', '')}")
            lines.append(f"- Location: {d.get('auction_location')} ({at}) · Closes **{close:%-I:%M %p ET}** ({left} left) · {d.get('total_bids', 0)} bids")
            lines.append(f"- [Open lot on mac.bid]({url})")
            lines.append("")
        if found > len(hits[:max_results]):
            lines.append(f"_Showing the {len(hits[:max_results])} soonest-closing of {found} matches._")

    report = "\n".join(lines)
    print(report)
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            f.write(report + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
