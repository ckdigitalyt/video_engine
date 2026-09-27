"""V15 — plate provider layer: one AI still per shot as the WORLD layer.

Directive §11: "AI image = one visual asset/layer/source for a scene". V14
rendered no plates at all (primitives on a navy gradient). V15 generates one
still per shot through the EXISTING image-generation fallback chain
(src/providers/image_gen): NIM FLUX.2-klein -> SiliconFlow -> HF serverless
-> Pollinations -> Gemini image — first success wins, every failure recorded.
The chain only ADDS a tier above V14's procedural grammars: when every
provider fails the shot compiler falls back to the V14 procedural subject
(asset_tier="procedural", visible to the gate), never a silent downgrade.

Per plate:
  - prompt = bible prefix + shot subject + composition hint + no-text suffix
    (engine.v15_style.image_prompt); deterministic seed from the prompt
  - normalized to 1080x1920 (cover fit, LANCZOS + light unsharp)
  - subject analysis: V13 depth_layers saliency mask, cleaned into a smooth
    silhouette -> subject bbox + centroid (camera target, label anchor,
    text quiet-zone) + an optional feathered subject cutout for a subtle
    parallax band
  - global content-addressed cache build/cache/v15_plates/<key>.png + .json
    (provider, model, seconds, prompt) shared by every story in a batch

plate_qa(): ONE vision call per story on a labelled contact sheet of all its
plates (director.vision_ask judge chain) -> failing plates (garbled text,
wrong subject, off-style, empty) regenerate once with a new seed. Bounded:
one QA call + <= one regeneration round.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
CACHE_DIR = ROOT / "build" / "cache" / "v15_plates"
W, H = 1080, 1920
REQ_W, REQ_H = 720, 1280  # providers snap to their nearest 9:16-ish size
PROVIDER_ORDER = ("nvidia_nim", "siliconflow", "hf_serverless",
                  "pollinations", "gemini_image")
PLATE_VERSION = "plate/1"

for _p in (REPO, ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _key(prompt: str, seed: int) -> str:
    return hashlib.sha256(f"{PLATE_VERSION}|{prompt}|{seed}|{W}x{H}"
                          .encode()).hexdigest()[:16]


def _normalize(src: Path, out: Path) -> None:
    im = Image.open(src).convert("RGB")
    sw, sh = im.size
    sc = max(W / sw, H / sh)
    nw, nh = round(sw * sc), round(sh * sc)
    im = im.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - W) // 2, (nh - H) // 2
    im = im.crop((left, top, left + W, top + H))
    if sc > 1.05:  # recover a little crispness lost to the upscale
        im = im.filter(ImageFilter.UnsharpMask(radius=1.6, percent=60,
                                               threshold=2))
    im.save(out, "PNG", optimize=True)


def _factory():
    from src.providers.image_gen import ImageGenFactory
    return ImageGenFactory()


def generate_plate(prompt: str, seed: int, *, providers=PROVIDER_ORDER,
                   log: list | None = None) -> dict:
    """-> {ok, path, provider, seconds, key, attempts, cached}."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _key(prompt, seed)
    out = CACHE_DIR / f"{key}.png"
    meta_p = CACHE_DIR / f"{key}.json"
    if out.exists() and meta_p.exists():
        meta = json.loads(meta_p.read_text())
        return dict(meta, ok=True, path=str(out), cached=True)
    attempts = []
    fac = _factory()
    for name in providers:
        try:
            prov = fac.get(name)
            if not prov.is_available():
                attempts.append({"provider": name, "error": "unavailable"})
                continue
            t0 = time.time()
            raw = CACHE_DIR / f"{key}.{name}.raw.png"
            prov.generate(prompt, str(raw), width=REQ_W, height=REQ_H,
                          seed=seed)
            _normalize(raw, out)
            raw.unlink(missing_ok=True)
            meta = {"key": key, "provider": name,
                    "model": getattr(prov, "model", None)
                    or getattr(prov, "_model", None) or name,
                    "seconds": round(time.time() - t0, 2), "seed": seed,
                    "prompt": prompt, "attempts": attempts,
                    "version": PLATE_VERSION}
            meta_p.write_text(json.dumps(meta, indent=1))
            return dict(meta, ok=True, path=str(out), cached=False)
        except Exception as e:  # descend the chain, record why
            attempts.append({"provider": name, "error": str(e)[:200]})
    if log is not None:
        log.append({"prompt": prompt[:120], "attempts": attempts})
    return {"ok": False, "key": key, "attempts": attempts, "path": None}


# ------------------------------------------------------- subject analysis --

def analyze_subject(plate_path) -> dict:
    """Saliency subject silhouette -> bbox/centroid/cutout (cached)."""
    plate_path = Path(plate_path)
    side = plate_path.with_suffix(".subject.json")
    if side.exists():
        return json.loads(side.read_text())
    from engine.depth_layers import derive_masks
    res = derive_masks(plate_path)
    info = {"method": res.get("method"), "bbox": None, "centroid": None,
            "coverage": 0.0, "cutout": None, "calm": {}}
    lum = np.asarray(Image.open(plate_path).convert("L").resize((270, 480)),
                     dtype=np.float32)
    # calm-ness (low detail) of the top / bottom thirds for text placement
    gy, gx = np.gradient(lum)
    energy = np.hypot(gx, gy)
    info["calm"] = {"top": round(float(energy[40:170].mean()), 2),
                    "bottom": round(float(energy[300:430].mean()), 2)}
    info["mean_lum"] = {"top": round(float(lum[40:170].mean()), 1),
                        "bottom": round(float(lum[300:430].mean()), 1),
                        "all": round(float(lum.mean()), 1)}
    mp = (res.get("masks") or {}).get("SUBJECT")
    if mp:
        m = Image.open(mp).convert("L").resize((W // 4, H // 4))
        # close speckle, smooth into a silhouette, feather the edge
        m = m.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9))
        m = m.filter(ImageFilter.GaussianBlur(6)).point(
            lambda v: 255 if v > 110 else 0)
        m = m.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(4))
        a = np.asarray(m, dtype=np.float32) / 255.0
        cov = float((a > 0.5).mean())
        if 0.03 <= cov <= 0.7:
            ys, xs = np.nonzero(a > 0.5)
            info["bbox"] = [int(xs.min() * 4), int(ys.min() * 4),
                            int(xs.max() * 4), int(ys.max() * 4)]
            info["centroid"] = [int(xs.mean() * 4), int(ys.mean() * 4)]
            info["coverage"] = round(cov, 3)
            cut = plate_path.with_suffix(".cutout.png")
            m.resize((W, H), Image.BILINEAR).save(cut)
            info["cutout"] = str(cut)
        for p in (res.get("masks") or {}).values():  # raw masks not needed
            Path(p).unlink(missing_ok=True)
    side.write_text(json.dumps(info, indent=1))
    return info


# ---------------------------------------------------------------- plate QA --

QA_QUESTION = """You are checking AI illustration plates for an explainer video.
Style required: {style}
The sheet shows {n} numbered plates. Main subject each plate must show:
{items}
For EACH plate first say in <= 8 words what it actually shows, then decide.
A plate FAILS only for:
 "text": visible letters, words, numbers, signatures or garbled writing;
 "wrong_subject": the MAIN object named above is absent (e.g. asked for a
   skate blade, shows a building). Artistic interpretation, missing minor
   details, stylization or a different viewpoint are NOT failures;
 "broken": empty, corrupted, or incoherent image.
Return ONLY JSON: {{"plates": [{{"n": 1, "shows": "...", "fail": null}}]}}
with "fail" one of null, "text", "wrong_subject", "broken"."""


def _main_subject(subject: str) -> str:
    """First clause of the shot subject — the thing that must be visible."""
    first = re.split(r"(?<=[.;])\s", subject.strip(), maxsplit=1)[0]
    return " ".join(first.split()[:18])


def contact_sheet(paths: list, out: Path, cols: int = 5) -> Path:
    tw, th = 288, 512
    rows = -(-len(paths) // cols)
    sheet = Image.new("RGB", (cols * tw, rows * (th + 28)), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype(str(ROOT / "assets/fonts/Inter-Variable.ttf"), 20)
    except Exception:
        f = None
    for i, p in enumerate(paths):
        x, y = (i % cols) * tw, (i // cols) * (th + 28)
        sheet.paste(Image.open(p).convert("RGB").resize((tw, th)), (x, y + 28))
        d.text((x + 6, y + 3), f"#{i + 1}", fill=(255, 220, 90), font=f)
    sheet.save(out, "JPEG", quality=85)
    return out


def plate_qa(items: list, style: str, sheet_path: Path) -> dict:
    """items: [{path, subject}] -> {checked, fail: {index: reason}, raw}."""
    if not items:
        return {"checked": False, "fail": {}, "reason": "no plates"}
    from engine.director import vision_ask
    contact_sheet([it["path"] for it in items], sheet_path)
    listing = "\n".join(f"#{i + 1}: {_main_subject(it['subject'])}"
                        for i, it in enumerate(items))
    ans = vision_ask(sheet_path, QA_QUESTION.format(
        style=style[:200], n=len(items), items=listing),
        max_tokens=60 * len(items) + 200)
    if not isinstance(ans, dict) or "plates" not in ans:
        return {"checked": False, "fail": {}, "raw": ans,
                "reason": "judge unavailable or unparseable"}
    fails = {}
    for f in ans.get("plates") or []:
        try:
            n = int(f.get("n")) - 1
        except Exception:
            continue
        if 0 <= n < len(items) and f.get("fail") in ("text", "wrong_subject",
                                                     "broken"):
            fails[n] = f["fail"]
    return {"checked": True, "fail": fails, "raw": ans}
