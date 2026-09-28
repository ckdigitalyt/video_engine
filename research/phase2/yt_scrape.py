"""Phase 2: public per-video stats for @most.amazing.wonders from watch pages
(fallback: OAuth token is invalid_grant and yt-dlp full extraction is bot-walled)."""
import json, re, sys, time, urllib.request
from pathlib import Path
D = Path("/home/ubuntu/phase2_out/yt")
rows = []
for tab in ("shorts", "videos"):
    for e in json.loads((D / f"flat_{tab}.json").read_text())["entries"]:
        vid = e["id"]
        req = urllib.request.Request((f"https://www.youtube.com/shorts/{vid}" if tab == "shorts" else f"https://www.youtube.com/watch?v={vid}"),
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US"})
        try:
            h = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        except Exception as ex:
            rows.append({"id": vid, "err": str(ex)[:80]}); continue
        g = lambda p: (m.group(1) if (m := re.search(p, h)) else None)
        cm = g(r'"commentCount":\{"simpleText":"([^"]+)"') or g(r'"contextualInfo":\{"runs":\[\{"text":"([^"]+)"')
        kw = g(r'"keywords":(\[[^\]]*\])')
        desc = g(r'"shortDescription":"((?:[^"\\]|\\.)*)"')
        rows.append({"id": vid, "tab": tab, "title": e.get("title"),
                     "views": int(g(r'"viewCount":"(\d+)"') or 0),
                     "likes": int(g(r'"likeCount":"(\d+)"') or 0),
                     "comments": cm, "len_s": int(g(r'"lengthSeconds":"(\d+)"') or 0),
                     "date": g(r'"publishDate":"([^"]+)"'),
                     "tags": json.loads(kw) if kw else [],
                     "desc": json.loads(f'"{desc}"')[:400] if desc else ""})
        time.sleep(1.0)
(D / "scraped.json").write_text(json.dumps(rows, indent=1))
print(len(rows), sum(1 for r in rows if r.get("views")))
