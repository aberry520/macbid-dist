#!/usr/bin/env python3
"""Upload a file to a Google Drive folder using a service account.

Used by the GitHub Actions workflow to put each day's MAC.BID report CSV
into Austin's Google Drive. It is NOT used by macbid_deals.py itself.

Setup (one time, see README.md "Google Drive" section):
  1. In Google Cloud, create a service account with the Drive API enabled
     and download its JSON key.
  2. In Google Drive, create a folder and share it with the service
     account's email address as an Editor.
  3. In GitHub repo Settings -> Secrets -> Actions, add:
       GOOGLE_SERVICE_ACCOUNT_JSON = the whole contents of the key JSON file
       DRIVE_FOLDER_ID = the folder's ID (the part after /folders/ in its URL)

Usage:
  GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}' \
  DRIVE_FOLDER_ID='1AbC...' \
  python3 drive_upload.py reports/20261114-1700.csv

  or: python3 drive_upload.py --file reports/20261114-1700.csv \
           --service-account-json /path/to/key.json --folder-id 1AbC...

The upload is a new file each run (timestamped names don't clash). Requires:
  pip install google-api-python-client google-auth
"""
import argparse
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser(description="Upload a file to Google Drive")
    ap.add_argument("file", nargs="?", help="File to upload")
    ap.add_argument("--file", dest="file_opt")
    ap.add_argument("--service-account-json",
                    default=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""))
    ap.add_argument("--folder-id",
                    default=os.environ.get("DRIVE_FOLDER_ID", ""))
    args = ap.parse_args()

    path = args.file_opt or args.file
    if not path or not os.path.exists(path):
        print(f"File not found: {path}", file=sys.stderr)
        return 1
    if not args.service_account_json:
        print("Missing GOOGLE_SERVICE_ACCOUNT_JSON (service account key). "
              "Skipping Drive upload.", file=sys.stderr)
        return 2
    if not args.folder_id:
        print("Missing DRIVE_FOLDER_ID. Skipping Drive upload.", file=sys.stderr)
        return 2

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        print("google-api-python-client is not installed. Run:\n"
              "  pip install google-api-python-client google-auth",
              file=sys.stderr)
        return 1

    key = args.service_account_json
    if key.strip().startswith("{"):
        info = json.loads(key)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive.file"])
    else:
        creds = service_account.Credentials.from_service_account_file(
            key, scopes=["https://www.googleapis.com/auth/drive.file"])

    drive = build("drive", "v3", credentials=creds)
    name = os.path.basename(path)
    media = MediaFileUpload(path, resumable=True)
    created = drive.files().create(
        body={"name": name, "parents": [args.folder_id]},
        media_body=media, fields="id,name,webViewLink").execute()
    print(f"Uploaded to Google Drive: {created.get('name')} "
          f"({created.get('webViewLink')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
