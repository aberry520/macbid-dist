# MAC.BID Deal Finder

Finds MAC.BID auction lots closing soon that are worth bidding on for resale:
high retail value, low current bid, at your warehouse or transferable there.

No account, no login, no Muse needed to run it — it only reads MAC.BID's
public lot listings. It never bids or changes anything. Running it yourself
uses **zero** Muse usage.

## What you need

- **Python 3** (3.8 or newer) — download from https://www.python.org/downloads/
  (on Windows, tick "Add python.exe to PATH" during install)
- **curl** — already on Mac and Linux; on Windows 10/11 it is built in.
  Check with: `curl --version` and `python --version`

## Run it (anytime)

**Mac / Linux:** double-click `run.sh`, or in a terminal in this folder:
```
./run.sh
```

**Windows:** double-click `run.bat`, or in a terminal in this folder:
```
run.bat
```

Or directly:
```
python macbid_deals.py
```

Each run prints the report and saves a copy in `reports/` with the date
and time in the file name, e.g. `reports/20261114-1700.md` — plus a CSV
version with the same name (`reports/20261114-1700.csv`) made automatically.
The CSV has one row per lot: product, lot number, location, at warehouse or
transferable, retail price, current bid, % off retail, condition, category,
closing time, bids, and the mac.bid link. It opens in Excel or Google Sheets.

## Change the settings

Open `config.yaml` in any text editor (Notepad, TextEdit) and change:

| Setting | What it does |
|---|---|
| `warehouse` | Your pickup warehouse, exactly as MAC.BID spells it — e.g. `Anderson`, `Greenville`, `Spartanburg`, `Cowpens`, `Rock Hill`, `Gastonia`. A lot is included when it is AT this warehouse, or when this warehouse is in the lot's transfer list. |
| `min_retail` | Only lots with a retail value at or above this ($) |
| `max_bid` | Only lots whose current bid is at or below this ($). Bid price only — the 15% buyer's premium, $3 lot fee and tax are NOT added. |
| `look_ahead_hours` | How far ahead to look for closing lots. At a 5pm run, 7 hours covers the whole evening close. |
| `max_results` | Most lots shown in the report (soonest-closing first) |

Save the file and run it again — no other changes needed.

You can also override settings for one run without editing the file:
```
python macbid_deals.py --warehouse Greenville --min-retail 200 --max-bid 25
```

## Run it automatically every day at 5pm

**Windows — Task Scheduler:** Create a basic task, daily at 5:00 PM,
action "Start a program", program `run.bat`, start in this folder.

**Mac — launchd / Linux — cron:** add this line with `crontab -e`
(5pm, daily; change the path to where you put this folder):
```
0 17 * * * cd /path/to/macbid-deal-finder && ./run.sh >> reports/cron.log 2>&1
```

## Host it online (free, no computer needed)

The easiest free way is **GitHub Actions** — it runs the scan on GitHub's
computers on a schedule, even when your computer is off:

1. Create a free account at https://github.com and a new **private**
   repository (e.g. `macbid-deals`).
2. Upload all the files in this folder to it, including the
   `.github/workflows/macbid.yml` file.
3. That's it — it runs every day at 5pm Eastern (winter time).

**Reading the report — no downloading:** each run commits the new report
(Markdown + CSV) back into the repo, so just open your repo on GitHub,
go into the `reports/` folder, and click the newest file. GitHub shows the
Markdown report right on the page, and the CSV can be opened in the browser
or downloaded. The run also still saves a copy under
**Actions → the run → Artifacts** as a backup.

Note: the schedule in the workflow file is in UTC. 5pm Eastern is 22:00 UTC
in winter (EST) and 21:00 UTC in summer (EDT). The file is set to 22:00 UTC;
change the `cron:` line to `0 21 * * *` when daylight saving starts.

## Automatic starring (GitHub Action, optional)

`star_action.py` + `.github/workflows/star.yml` star the evening's deals
for you — no computer needed, no token to paste each time. Each day at
5:10pm Eastern (just after the report run) it refreshes the MAC.BID login,
stars the lots matching `config.yaml`, and saves the new login token back
for the next run.

**One-time setup — three secrets** (repo → **Settings → Secrets and
variables → Actions → New repository secret**):

1. `MACBID_REFRESH_TOKEN` — in Chrome, signed in to mac.bid, press F12 →
   **Application** → **Local Storage** → `https://www.mac.bid` → click
   `mac_auths`. Copy the `refresh_token` value (the long string starting
   `eyJ...`). Paste it as the secret. Re-copy it after any manual
   sign-in, since every refresh replaces it with a new one.
2. `MACBID_DEVICE_ID` — same place, the `device_id` entry.
3. `GH_PAT` — a **classic** personal access token from
   https://github.com/settings/tokens (scope: `repo`). The workflow needs
   it to save the rotated token back into the secret — the built-in
   workflow token can't update secrets. Without it, starring still runs
   once, but the next run fails because the old token is dead.

**How it stays logged in:** the MAC.BID site keeps a refresh token in the
browser and uses it to stay signed in without another SMS code. The
workflow does the same: `PUT /auth/refresh-token` with the stored token
gets a fresh 30-minute access token plus a new refresh token. The window
rolls 3 days forward on every refresh, so a daily run keeps it alive
indefinitely — but if no run succeeds for 3 days straight, the token dies
and you'll need to sign in again and update the secret by hand.

**Safety notes:** the refresh token is a full-account credential (it can
bid and buy, not just star), so keep the repo private and never paste the
token anywhere except the secret itself. The workflow never prints any
token value, and the rotated token passes through a file that is deleted
right after use. The script itself never bids or buys — it only adds
watchlist stars, and only counts a star when the site confirms it.

To test it right away: **Actions → Star MAC.BID deals → Run workflow**.
If the refresh token is stale you'll see a clear error telling you to
re-copy it from `mac_auths`.

## Google Drive — get the CSV there automatically

If you'd rather have each day's CSV land in a Google Drive folder, the
workflow can upload it for you. One-time setup (about 10 minutes):

1. **Google Cloud** (https://console.cloud.google.com) — create a free
   project, go to **APIs & Services → Library**, enable **Google Drive API**.
2. **APIs & Services → Credentials → Create Credentials → Service account.**
   Give it any name, then on the service account go to **Keys → Add Key →
   Create new key → JSON** and download the file. Note the service
   account's email address (it looks like `something@something.iam.gserviceaccount.com`).
3. **Google Drive** (https://drive.google.com) — create a folder, e.g.
   `MAC.BID reports`. Right-click it → **Share** → add the service
   account email from step 2 as an **Editor**. (A service account can't
   see your Drive unless you share a folder with it — this step is the
   one people usually miss.)
4. **GitHub** — in your repo go to **Settings → Secrets and variables →
   Actions → New repository secret** and add two secrets:
   - `GOOGLE_SERVICE_ACCOUNT_JSON` — paste the entire contents of the
     JSON key file from step 2.
   - `DRIVE_FOLDER_ID` — open the Drive folder in your browser; the ID is
     the long string after `/folders/` in the address bar.
5. Done. The next scheduled run uploads that day's CSV into the folder.
   If the secrets aren't set, that step is simply skipped and everything
   else still works.

To upload a CSV by hand from your own computer instead:
```
pip install google-api-python-client google-auth
python drive_upload.py reports/20261114-1700.csv
```
(with the same two values set as environment variables
`GOOGLE_SERVICE_ACCOUNT_JSON` and `DRIVE_FOLDER_ID`).

Other free options that work the same way: **PythonAnywhere** (free tier,
one scheduled task) or **Replit** (scheduled deployments) — upload this
folder, set the run command to `python macbid_deals.py`, schedule 5pm daily.

## What a report looks like

See `reports/sample-report.md` — each lot shows the item, lot number,
retail value, current bid and % off retail, condition, whether it's at your
warehouse or transferable there, closing time, and a link to open the lot
on mac.bid.

## How it works (for the curious)

MAC.BID's website searches a public Typesense index
(`prod_macdiscount_alias`) — the tool asks that same index for live lots
(`lot_status:LIVE`) with `retail_price`, `current_bid`,
`expected_closing_utc`, `auction_location` and `transfer_locations`,
then filters and sorts them. The search key in the script is a search-only
key published in mac.bid's own public website code; it can only search
public listings. Lots close from 6pm Eastern, mostly 7–11pm on weeknights,
with a 2-minute reset if someone bids late — so a 5pm run is the evening's
watchlist.
