"""V15 — plate provider layer: one AI still per shot as the WORLD layer.

Directive §11: "AI image = one visual asset/layer/source for a scene". V14
rendered no plates at all (primitives on a navy gradient). V15 generates one
still per shot through the EXISTING image-generation fallback chain
(src/providers/image_gen) — first success wins, every failure recorded.
The chain only ADDS a tier above V14's procedural grammars: when every
provider fails the shot compiler falls back to the V14 procedural subject
(asset_tier="procedural", visible to the gate), never a silent downgrade.

WP8 (DESIGN §6.1) reordered the production chain to try a `commercial_ok`
source before the ones that are not: archive (PD/CC0) -> Cloudflare Workers
AI flux-2-klein-4b -> Gemini image -> local flux-2-klein-4b via
stable-diffusion.cpp -> Pollinations (watermark-cropped last resort). NIM
left the production chain (owner decision, PROGRESS.md 2026-09-27: "not
approved for production") and is now `benchmark_only` on its provider class
— WP10's real tunguska render used it 16/18 times before this change,
which is why every plate on that render was `commercial_ok: false`
(bench/ab/wp10.md). The order lives in `configs/images.yaml`
(`image_gen.chain.production`), read once at import with the same order as
a hardcoded fallback so this module still works if the config is missing.

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

plate_qa(): a free OCR pre-filter (tesseract, watermark/signature strips)
then ONE vision call per story on a labelled contact sheet of all its
plates (director.vision_ask -> llm adapter, stage plate_qa) -> failing plates (garbled text,
wrong subject, off-style, empty, watermark) regenerate once with a new seed. Bounded:
one QA call + <= one regeneration round. WP2: fail-closed — the result says
whether QA actually ran (`checked`, `ocr_checked`) and the gate treats "did
not run" as HOLD.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from engine.brand import apply_lut

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
CACHE_DIR = ROOT / "build" / "cache" / "v15_plates"
W, H = 1080, 1920
REQ_W, REQ_H = 720, 1280  # providers snap to their nearest 9:16-ish size

for _p in (REPO, ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# WP8/DESIGN §6.1 production order (see module docstring). Read from
# configs/images.yaml so "switching providers is a config change only"
# (the WP1 principle) also holds for the image chain; the tuple below is
# the fallback if the config key is missing, not a second source of truth.
_DEFAULT_PROVIDER_ORDER = ("archive", "cloudflare_workers_ai", "gemini_image",
                          "sdcpp_local", "pollinations")


def _load_provider_order() -> tuple:
    from src.utils.config import get_config
    order = get_config("image_gen.chain.production", None)
    return tuple(order) if order else _DEFAULT_PROVIDER_ORDER


PROVIDER_ORDER = _load_provider_order()
# plate/2 (WP6): every cached plate is now brand-graded at ingest (below),
# so plate/1 cache entries (ungraded) must miss and regenerate, not be
# silently served as if they carried the brand look.
PLATE_VERSION = "plate/2"


def _key(prompt: str, seed: int) -> str:
    return hashlib.sha256(f"{PLATE_VERSION}|{prompt}|{seed}|{W}x{H}"
                          .encode()).hexdigest()[:16]


def _crop_watermark(path: Path, frac: float | None = None) -> None:
    """Crop the bottom strip off *path* in place (WP8/DESIGN §6.1: "Pollinations
    ... watermark detector + crop"). Pollinations stamps its watermark
    bottom-left (module docstring OCR_STRIPS below, seen shipping live in
    the Phase 2 blackhole run); OCR-detect-and-regenerate alone let 2 of
    those ship anyway on WP10's real tunguska render (bench/ab/wp10.md) —
    this removes the stamp's pixels before OCR/QA ever sees them, rather
    than only detecting it after the fact."""
    if frac is None:
        from src.utils.config import get_config
        frac = get_config("image_gen.pollinations.watermark_crop_frac", 0.08)
    im = Image.open(path).convert("RGB")
    w, h = im.size
    cropped = im.crop((0, 0, w, max(1, round(h * (1 - frac)))))
    cropped.save(path)


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
            if name == "pollinations":
                _crop_watermark(raw)
            _normalize(raw, out)
            raw.unlink(missing_ok=True)
            # WP6 plate ingest: grade through the brand LUT in place, once,
            # before caching — every cached plate carries the brand look and
            # its cube hash, so the gate can prove it (the "LUT-hash test").
            graded = CACHE_DIR / f"{key}.graded.png"
            lut_sha256 = apply_lut(out, graded)
            graded.replace(out)
            meta = {"key": key, "provider": name,
                    "model": getattr(prov, "model", None)
                    or getattr(prov, "_model", None) or name,
                    "seconds": round(time.time() - t0, 2), "seed": seed,
                    "prompt": prompt, "attempts": attempts,
                    "version": PLATE_VERSION, "lut_sha256": lut_sha256}
            meta_p.write_text(json.dumps(meta, indent=1))
            return dict(meta, ok=True, path=str(out), cached=False)
        except Exception as e:  # descend the chain, record why
            attempts.append({"provider": name, "error": str(e)[:200]})
    if log is not None:
        log.append({"prompt": prompt[:120], "attempts": attempts})
    return {"ok": False, "key": key, "attempts": attempts, "path": None}


# ------------------------------------------------------- WP8 chain helpers --

def providers_for_beat_function(function: str | None,
                                base: tuple = PROVIDER_ORDER) -> tuple:
    """DESIGN §6.1: "Pollinations ... never for hero shots". `function` is
    the beat's `function` field (HOOK/PAYOFF/... — the same field
    `v15_gate.check_assets` already reads as the hero signal, not a new
    concept). Drops `pollinations` from the chain when
    the shot belongs to a HOOK or PAYOFF beat; every other function is
    unaffected."""
    from src.utils.config import get_config
    never_for = set(get_config("image_gen.pollinations.never_for_beat_functions",
                               ["HOOK", "PAYOFF"]))
    if function in never_for:
        return tuple(p for p in base if p != "pollinations")
    return base


def cloudflare_available() -> bool:
    from src.providers.image_gen import CloudflareWorkersAIProvider
    return CloudflareWorkersAIProvider().is_available()


def low_plate_mode() -> bool:
    """DESIGN §6.2: Cloudflare absent -> low-plate mode. Pure predicate; see
    `image_chain_report` for the budget it implies. Callers that skip
    generation entirely when this is True still have a working chain
    (archive/gemini/sdcpp_local/pollinations) — this only says whether the
    fast, high-quota primary is up."""
    return not cloudflare_available()


def image_chain_report() -> dict:
    """DESIGN §6.2: "The batch preflight reports the expected plate
    throughput." One cheap, no-network(*) summary of chain state for a
    pipeline/batch report. (*cloudflare_available() is a credential check,
    not a live call.)"""
    from src.utils.config import get_config
    low = low_plate_mode()
    return {
        "provider_order": list(PROVIDER_ORDER),
        "cloudflare_available": not low,
        "low_plate_mode": low,
        "max_generated_plates": (get_config(
            "image_gen.low_plate_mode.max_generated_plates", 6) if low else None),
    }


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


# ------------------------------------------------------------ OCR filter --

# Providers stamp their name in a plate corner (Pollinations: "pollinations.ai",
# bottom-left; seen shipping in the Phase 2 blackhole). Full-plate OCR of
# textured illustration is mostly noise, so only the top/bottom edge strips are
# read and only a known stamp token or a domain-like string counts as a hit.
OCR_STRIPS = ((0.90, 1.0), (0.0, 0.07))     # (top, bottom) fractions of height
WATERMARK_TOKENS = ("pollinations", "shutterstock", "gettyimages", "istock",
                    "alamy", "adobestock", "depositphotos", "dreamstime",
                    "midjourney", "watermark")
_DOMAIN = re.compile(r"[a-z0-9-]{4,}\.(?:ai|com|net|io|org|co)\b")
OCR_VERSION = "ocr/1"


def _ocr_strip(im: Image.Image) -> str:
    im = im.convert("L")
    im = im.resize((im.width * 3, im.height * 3), Image.LANCZOS)
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        im.save(f.name)
        p = subprocess.run(["tesseract", f.name, "-", "--psm", "6"],
                           capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[:120])
    return p.stdout


def ocr_watermark(plate_path) -> dict:
    """-> {checked, hits}. checked=False when tesseract is missing/failed
    (unverified, never a silent pass). Cached beside the plate."""
    plate_path = Path(plate_path)
    side = plate_path.with_suffix(".ocr.json")
    if side.exists():
        cached = json.loads(side.read_text())
        if cached.get("version") == OCR_VERSION:
            return cached
    try:
        im = Image.open(plate_path)
        w, h = im.size
        text = " ".join(_ocr_strip(im.crop((0, int(h * a), w, int(h * b))))
                        for a, b in OCR_STRIPS).lower()
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        return {"checked": False, "hits": [], "reason": f"ocr failed: {e}"[:160]}
    squashed = re.sub(r"[^a-z0-9]", "", text)
    hits = sorted({t for t in WATERMARK_TOKENS if t in squashed}
                  | set(_DOMAIN.findall(re.sub(r"[:;,]", ".", text))))
    res = {"checked": True, "hits": hits, "version": OCR_VERSION}
    side.write_text(json.dumps(res))
    return res


# ---------------------------------------------------------------- plate QA --

QA_QUESTION = """You are checking AI illustration plates for an explainer video.
Style required: {style}
The sheet shows {n} numbered plates. Main subject each plate must show:
{items}
For EACH plate first say in <= 8 words what it actually shows, then decide.
A plate FAILS only for:
 "text": visible letters, words, numbers, signatures, logos, watermarks or
   garbled writing;
 "wrong_subject": the MAIN object named above is absent (e.g. asked for a
   skate blade, shows a building). Artistic interpretation, missing minor
   details, stylization or a different viewpoint are NOT failures;
 "broken": empty, corrupted, or incoherent image.
Also answer, for EACH plate: could a viewer mistake it for a real photo or
real footage of a real event or person (not an illustration)? Stylised
illustration in the required style should almost always be false.
{anatomy_block}Return ONLY JSON:
{{"plates": [{{"n": 1, "shows": "...", "fail": null, "realistic": false{anatomy_field}}}]}}
with "fail" one of null, "text", "wrong_subject", "broken".{anatomy_note}"""

ANATOMY_BLOCK = """Some plates name a specific real animal with required
anatomy (listed below as "anatomy:"). For ONLY those plates also answer
"anatomy_ok": does the plate get that animal's listed anatomy right (e.g. a
Stegosaurus must show back plates and tail spikes, NOT a frill; a
Tyrannosaurus must show two-fingered forelimbs, NOT three)? A plate with
wrong anatomy for its named animal FAILS "bad_anatomy" even if the species
is otherwise recognizable.
{anatomy_items}
"""
ANATOMY_FIELD = ', "anatomy_ok": true'
ANATOMY_NOTE = (' "bad_anatomy" is also a valid "fail" value, for the '
                "anatomy-checked plates only.")


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
    """items: [{path, subject}] -> {checked, ocr_checked, fail: {index:
    reason}, ocr_hits, realistic, raw}. `fail` merges the OCR pre-filter
    (always run, no LLM cost) with the vision verdict; `checked` is True
    only when the vision call really returned a verdict. `realistic`
    (DESIGN §11 disclosure signal, WP10) is index -> bool|None, None for any
    plate the vision call didn't answer for (e.g. QA unavailable) — callers
    treat None conservatively (assume realistic) rather than silently
    defaulting to False."""
    if not items:
        return {"checked": False, "ocr_checked": False, "fail": {},
                "reason": "no plates"}
    ocr = [ocr_watermark(it["path"]) for it in items]
    ocr_checked = all(o["checked"] for o in ocr)
    ocr_hits = {i: o["hits"] for i, o in enumerate(ocr) if o["hits"]}
    fails = {i: "text" for i in ocr_hits}
    realistic = {i: None for i in range(len(items))}
    from engine.director import vision_ask
    from engine.species import species_for
    contact_sheet([it["path"] for it in items], sheet_path)
    listing = "\n".join(f"#{i + 1}: {_main_subject(it['subject'])}"
                        for i, it in enumerate(items))
    # B2 (VIS): anatomy-checked plate indices, for the judge's checklist and
    # for interpreting its "anatomy_ok" answers afterwards.
    species_hits = {i: species_for(it["subject"]) for i, it in enumerate(items)}
    species_hits = {i: v for i, v in species_hits.items() if v}
    anatomy_block = anatomy_field = anatomy_note = ""
    if species_hits:
        anatomy_items = "\n".join(
            f"#{i + 1} anatomy: " + " / ".join(a for _, a in hits)
            for i, hits in species_hits.items())
        anatomy_block = ANATOMY_BLOCK.format(anatomy_items=anatomy_items)
        anatomy_field, anatomy_note = ANATOMY_FIELD, ANATOMY_NOTE
    ans = vision_ask(sheet_path, QA_QUESTION.format(
        style=style[:200], n=len(items), items=listing,
        anatomy_block=anatomy_block, anatomy_field=anatomy_field,
        anatomy_note=anatomy_note),
        max_tokens=60 * len(items) + 200, stage="plate_qa")
    if not isinstance(ans, dict) or "plates" not in ans:
        return {"checked": False, "ocr_checked": ocr_checked, "fail": fails,
                "ocr_hits": ocr_hits, "realistic": realistic, "raw": ans,
                "reason": "judge unavailable or unparseable"}
    for f in ans.get("plates") or []:
        try:
            n = int(f.get("n")) - 1
        except Exception:
            continue
        if 0 <= n < len(items) and f.get("fail") in (
                "text", "wrong_subject", "broken", "bad_anatomy"):
            fails[n] = f["fail"]
        if 0 <= n < len(items) and isinstance(f.get("realistic"), bool):
            realistic[n] = f["realistic"]
        if (0 <= n < len(items) and n in species_hits
                and f.get("anatomy_ok") is False and n not in fails):
            fails[n] = "bad_anatomy"
    return {"checked": True, "ocr_checked": ocr_checked, "fail": fails,
            "ocr_hits": ocr_hits, "realistic": realistic, "raw": ans}
