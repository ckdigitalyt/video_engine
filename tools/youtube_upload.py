#!/usr/bin/env python3
"""YouTube uploader for Jade Studio videos.

STANDING POLICY (S directive, 2026-08-05): uploads are ALWAYS unlisted.
Public uploads are hard-rejected by design. Do not remove this guard.

Usage:
  python tools/youtube_upload.py results/<slug>/<slug>_mixed.mp4 \
      [--title TITLE] [--description DESC] [--privacy unlisted|private]

Credentials (OAuth 2.0, YouTube Data API v3):
  - client_secret.json  -> ~/.openclaw/credentials/youtube/client_secret.json
  - token.json          -> ~/.openclaw/credentials/youtube/token.json
                           (auto-created on first authorization)

If token.json is missing or expired, the script prints an authorization
URL; open it, approve, and paste the code back on stdin.
"""

import argparse
import json
import os
import sys
from pathlib import Path

CRED_DIR = Path.home() / ".openclaw" / "credentials" / "youtube"
CLIENT_SECRET = CRED_DIR / "client_secret.json"
TOKEN_FILE = CRED_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

ALLOWED_PRIVACY = {"unlisted", "private"}  # PUBLIC IS NOT ALLOWED.


def load_or_create_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not CLIENT_SECRET.exists():
            sys.exit(
                f"ERROR: missing {CLIENT_SECRET}\n"
                "You must create a Google Cloud OAuth client (Desktop app) with the\n"
                "YouTube Data API v3 enabled and save its client_secret.json here."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
        # Set redirect_uri on the flow (registered as http://localhost for
        # installed clients). Passing it as a kwarg to authorization_url()
        # collides with requests_oauthlib ("multiple values"). Without it
        # Google errors 400 invalid_request (missing redirect_uri).
        REDIRECT_URI = "http://localhost"
        flow.redirect_uri = REDIRECT_URI
        url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        print("AUTH_URL_START")
        print(url)
        print("AUTH_URL_END")
        print("After approving, paste the full redirect URL (or just the code) here:")
        raw = input().strip()
        if "code=" in raw:
            raw = raw.split("code=", 1)[1].split("&", 1)[0]
        flow.fetch_token(code=raw)
        creds = flow.credentials
        CRED_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())
        print(f"Token saved to {TOKEN_FILE}")
    return creds


def main():
    ap = argparse.ArgumentParser(description="Upload a video to YouTube (unlisted only).")
    ap.add_argument("video", help="path to the .mp4 to upload")
    ap.add_argument("--title", default=None)
    ap.add_argument("--description", default="")
    ap.add_argument("--privacy", default="unlisted", choices=sorted(ALLOWED_PRIVACY))
    args = ap.parse_args()

    if args.privacy not in ALLOWED_PRIVACY:
        sys.exit("ERROR: public uploads are forbidden by policy (unlisted/private only).")

    video = Path(args.video)
    if not video.exists():
        sys.exit(f"ERROR: video not found: {video}")

    # Default title/description from run_report.json when not given.
    title, description = args.title, args.description
    if not title:
        run_report = video.parent / "run_report.json"
        if run_report.exists():
            try:
                report = json.loads(run_report.read_text())
                title = report.get("topic", video.stem)
                description = description or f"{report.get('topic', '')} — Jade Studio documentary."
                sd = video.parent / "synthetic_disclosure.json"
                if sd.exists():
                    disc = json.loads(sd.read_text())
                    if disc.get("disclosure_label"):
                        description = f"{description}\n\n{disc['disclosure_label']}"
            except Exception:
                title = video.stem
        else:
            title = video.stem

    creds = load_or_create_credentials()

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {"title": title, "description": description},
        "status": {
            "privacyStatus": args.privacy,
            "selfDeclaredMadeForKids": False,
            # C2PA / synthetic-media disclosure (2026 platform policy):
            # this pipeline produces AI-generated imagery + synthetic
            # narration, so the upload is flagged as altered content.
            "alteredContentInfo": {"alteredContentDisclosed": True},
        },
    }
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True)

    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")

    vid = response.get("id")
    print(f"OK: https://youtu.be/{vid} (privacy={args.privacy})")


if __name__ == "__main__":
    main()
