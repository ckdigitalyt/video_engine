"""Phase 2: public read of @most.amazing.wonders via YouTube Data API v3.
Builds the client like tools/youtube_upload.py; never prints credential data.
Token refresh happens in memory only (token.json is not rewritten)."""
import json, os, sys
from pathlib import Path
CRED = Path.home() / ".openclaw/credentials/youtube/token.json"
OUT = Path("/home/ubuntu/phase2_out/yt")
OUT.mkdir(parents=True, exist_ok=True)
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

def client():
    mode = sys.argv[1] if len(sys.argv) > 1 else "oauth"
    if mode == "oauth":
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        c = Credentials.from_authorized_user_file(str(CRED), ["https://www.googleapis.com/auth/youtube.upload"])
        if c.expired and c.refresh_token:
            c.refresh(Request())
        return build("youtube", "v3", credentials=c, cache_discovery=False)
    key = None
    for line in Path("/home/ubuntu/video_engine/.env").read_text().splitlines():
        if line.startswith(mode + "="):
            key = line.split("=", 1)[1].strip().strip('"\'')
    return build("youtube", "v3", developerKey=key, cache_discovery=False)

yt = client()
try:
    ch = yt.channels().list(part="snippet,statistics,contentDetails,brandingSettings",
                            forHandle="most.amazing.wonders").execute()
except HttpError as e:
    import re; print("channels.list ERR", e.status_code, re.sub(r"key=[^&\s]+", "key=REDACTED", str(e))[:300]); sys.exit(2)
items = ch.get("items", [])
if not items:
    print("no channel"); sys.exit(3)
c = items[0]
(OUT / "channel.json").write_text(json.dumps(c, indent=1))
print(json.dumps({"id": c["id"], "title": c["snippet"]["title"], "published": c["snippet"]["publishedAt"],
                  "desc": c["snippet"].get("description", "")[:300], "stats": c["statistics"]}, indent=1))
up = c["contentDetails"]["relatedPlaylists"]["uploads"]
ids, tok = [], None
while True:
    r = yt.playlistItems().list(part="contentDetails", playlistId=up, maxResults=50, pageToken=tok).execute()
    ids += [i["contentDetails"]["videoId"] for i in r["items"]]
    tok = r.get("nextPageToken")
    if not tok:
        break
vids = []
for i in range(0, len(ids), 50):
    r = yt.videos().list(part="snippet,statistics,contentDetails,status,topicDetails",
                         id=",".join(ids[i:i+50])).execute()
    vids += r["items"]
(OUT / "videos.json").write_text(json.dumps(vids, indent=1))
print("videos:", len(vids))
