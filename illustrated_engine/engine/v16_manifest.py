"""V16 — license manifest + AI disclosure (DESIGN.md §11, WP10).

`build_manifest()` assembles `build/v16/<video_id>/manifest.json` purely
from the provenance each stage already emits in `pipeline_report.json` (the
`plates` dict from `engine.v15_plates.generate_plate`, `report["voice"]`
from `engine.voice.synthesize_video`, `report["audio_v16"]["manifest_rows"]`
from `engine.v16_audio`, the loaded brand dict) — no new LLM call, no new
external request.

`check_manifest_complete()` is the gate-side proof DESIGN asks for ("the
gate compares the render asset log with the manifest"): every plate path,
the voice file, and every music/sfx/sting row actually used by the render
must have exactly one manifest asset entry, and vice versa.

Distinctness history (engine.v16_gate's pure `check_distinctness`) is
persisted here — `record_distinctness()` is the one place that writes it,
called once per real `v15_pipeline` run, never from a re-gate/test.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # illustrated_engine
REPO = ROOT.parent                                  # video_engine

MANIFEST_VERSION = 1
HISTORY_PATH = ROOT / "build" / "v16_distinctness_history.json"
HISTORY_CAP = 30

# Per-provider licence facts for AI-generated plates. Only a provider with a
# WRITTEN commercial clearance is marked `commercial_ok: True` — every other
# provider defaults to False so the License hard gate (DESIGN §10.1) HOLDs
# instead of silently shipping an asset nobody actually cleared for
# monetised use. Sources: RESEARCH.md §5/§6; Phase-1 owner decision 3 (NIM
# "not approved for production"). WP8 (image chain overhaul, DESIGN §6.1)
# added the two entries below marked True: `cloudflare_workers_ai` (paid
# Cloudflare account, standard commercial API terms, model itself
# Apache-2.0 — RESEARCH.md §5.1) and `sdcpp_local` (fully self-hosted,
# Apache-2.0 model/TE/VAE, no third-party service terms apply at all —
# RESEARCH.md §5.3). `archive` is also marked True: `ArchiveProvider`
# (src/providers/image_gen.py) never returns anything BUT a source-
# confirmed item (NASA: not copyrighted per NASA media guidelines; Met:
# gated on the API's own `isPublicDomain: true` flag) — it raises rather
# than fall back to an unconfirmed image, so "archive" here means the same
# thing as every other provider-wide entry in this table, not a weaker
# blanket claim. OWNER FLAG: two archive sources only (NASA + Met); if a
# future WP adds Smithsonian/LoC/BHL, each needs its own per-item PD/CC0
# check before this entry can honestly cover it too.
IMAGE_PROVIDER_LICENSE: dict = {
    "nvidia_nim": {"model_license": "Apache-2.0 (FLUX.2-klein-4B)",
                  "service_terms_ref": "NVIDIA NIM trial/evaluation terms "
                                       "[owner decision: not approved for "
                                       "production; benchmark_only]",
                  "commercial_ok": False},
    "siliconflow": {"model_license": "unknown [U]",
                    "service_terms_ref": "SiliconFlow API terms [U] "
                                         "[dead: HTTP 401; benchmark_only]",
                    "commercial_ok": False},
    "hf_serverless": {"model_license": "unknown [U]",
                      "service_terms_ref": "HF Inference API terms [U] "
                                           "[dead: HTTP 410; benchmark_only]",
                      "commercial_ok": False},
    "pollinations": {"model_license": "unknown [U]",
                     "service_terms_ref": "Pollinations anonymous API "
                                          "[U, watermark-cropped WP8 - "
                                          "RESEARCH.md §6]",
                     "commercial_ok": False},
    "gemini_image": {"model_license": "unknown [U]",
                     "service_terms_ref": "Google Generative AI terms [U]",
                     "commercial_ok": False},
    "cloudflare_workers_ai": {"model_license": "Apache-2.0 (FLUX.2-klein-4B)",
                              "service_terms_ref": "Cloudflare Workers AI "
                                                   "standard API terms, paid "
                                                   "account (no trial/eval-"
                                                   "only clause found) "
                                                   "[S: owner to confirm]",
                              "commercial_ok": True},
    "sdcpp_local": {"model_license": "Apache-2.0 (FLUX.2-klein-4B + "
                                     "Qwen3-4B text encoder + VAE)",
                    "service_terms_ref": "self-hosted, no third-party "
                                         "service terms apply",
                    "commercial_ok": True},
    "archive": {"model_license": "n/a (archival photograph, not AI-generated)",
               "service_terms_ref": "NASA media guidelines / Met Museum "
                                    "Open Access (CC0) - ArchiveProvider "
                                    "only ever returns a source-confirmed "
                                    "PD/CC0 item or raises",
               "commercial_ok": True},
}

DISCLOSURE_NOTE = ("Illustrations are AI-generated in our house style; "
                   "narration uses a synthetic voice.")


# ------------------------------------------------------------- provenance --

def _sha256(path) -> str:
    p = Path(path)
    if not p.is_file():
        return ""
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pipeline_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def plate_asset_rows(plates: dict, plate_realistic: dict | None = None) -> list:
    """`plates`: prompt -> engine.v15_plates.generate_plate() result dict
    (only `ok` entries produce a row; procedural-fallback shots have no
    plate and are correctly absent from `assets`). `plate_realistic`:
    path -> bool|None (DESIGN §11 disclosure signal, from plate_qa); an
    unanswered plate (None) is treated as realistic=True — conservative, per
    DESIGN's own disclosure rule ("conservative": prefer disclosing)."""
    plate_realistic = plate_realistic or {}
    rows, seen = [], set()
    for prompt, r in plates.items():
        if not r.get("ok") or r["path"] in seen:
            continue
        seen.add(r["path"])
        lic = IMAGE_PROVIDER_LICENSE.get(r.get("provider"), {
            "model_license": "unknown [U]",
            "service_terms_ref": "unknown provider [U]",
            "commercial_ok": False})
        realistic = plate_realistic.get(r["path"])
        # WP8: "archive" plates are real archival photographs (NASA/Met),
        # not model output — ai_generated=False so DESIGN §11's
        # `ai_generated_imagery` disclosure signal stays honest once the
        # chain can actually pick this provider. Every other provider is
        # a generator, unchanged.
        ai_generated = r.get("provider") != "archive"
        rows.append({"kind": "plate", "sha256": _sha256(r["path"]),
                     "file": r["path"], "provider": r.get("provider"),
                     "model": r.get("model"), **lic, "prompt": prompt,
                     "seed": r.get("seed"), "ai_generated": ai_generated,
                     "realistic": True if realistic is None else realistic,
                     "lut_applied": r.get("lut_sha256")})
    return rows


def font_asset_rows(brand: dict) -> list:
    from engine.brand import font_path
    rows, seen = [], set()
    for role, spec in (brand.get("fonts") or {}).items():
        fp = font_path(brand, role)
        if str(fp) in seen:
            continue
        seen.add(str(fp))
        rows.append({"kind": "font", "file": spec["file"],
                     "license": spec.get("license", "unknown"),
                     "commercial_ok": True})
    return rows


def llm_calls_since(t_start: float, t_end: float | None = None,
                    ledger_path: Path | None = None) -> dict:
    """count + by_stage over `build/llm_ledger.jsonl` rows timestamped
    inside [t_start, t_end] — the ledger is global/cumulative across runs,
    so this is the only way to scope it to one render (`v15_pipeline`
    already records `t_start`)."""
    path = ledger_path or (ROOT / "build" / "llm_ledger.jsonl")
    by_stage: dict = {}
    count = 0
    if not path.exists():
        return {"count": 0, "by_stage": {}}
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        ts = row.get("ts")
        if ts is None or ts < t_start or (t_end is not None and ts > t_end):
            continue
        count += 1
        by_stage[row.get("stage", "?")] = by_stage.get(row.get("stage", "?"), 0) + 1
    return {"count": count, "by_stage": by_stage}


# --------------------------------------------------------------- manifest --

def build_manifest(*, video_id: str, brand: dict, voice: dict | None,
                   plates: dict, plate_realistic: dict | None,
                   audio_rows: list, llm_calls: dict, verdict: str,
                   metadata: dict | None = None) -> dict:
    from engine.brand import cube_path, cube_sha256
    plate_rows = plate_asset_rows(plates, plate_realistic)
    assets = plate_rows + list(audio_rows or []) + font_asset_rows(brand)
    voice = voice or {}
    any_realistic = any(r["realistic"] for r in plate_rows)
    # WP8: archive rows are real photographs (ai_generated=False), so this
    # must check the per-row flag, not just "any plate row at all" — a
    # video built entirely from archive plates has no AI imagery to disclose.
    disclosure = {"ai_generated_imagery": any(r["ai_generated"] for r in plate_rows),
                 "realistic_synthetic": any_realistic,
                 "synthetic_voice": True,
                 "youtube_altered_content": any_realistic,
                 "description_note": DISCLOSURE_NOTE}
    attribution = [r["attribution_text"] for r in assets
                  if r.get("attribution_required") and r.get("attribution_text")]
    return {
        "version": MANIFEST_VERSION, "video_id": video_id,
        "pipeline_sha": pipeline_sha(),
        "brand": {"id": brand.get("brand_id"), "version": brand.get("version"),
                  "lut_sha256": cube_sha256(cube_path(brand))
                  if brand.get("_dir") else None},
        "publishable": verdict == "PASS",
        "voice": {"provider": voice.get("provider"), "model": voice.get("model"),
                  "voice": voice.get("voice_id"),
                  "license": voice.get("license_ref"),
                  "commercial_ok": bool(voice.get("commercial_ok"))},
        "assets": assets,
        "llm_calls": llm_calls,
        "disclosure": disclosure,
        "attribution_block": "\n".join(attribution),
        # B5 (VIS): title/description/tags, engine.v16_metadata.build_metadata
        "metadata": metadata or {},
    }


def check_manifest_complete(manifest: dict, *, plate_paths: list,
                            voice_wav, audio_rows: list) -> dict:
    """DESIGN §11 completeness: the render asset log (every plate path
    actually compiled into a shot + the voice track + every music/sfx/sting
    row the render used) must match the manifest's `assets` 1:1 (voice is
    checked against `manifest["voice"]`, not `assets`, per the schema)."""
    fails = []
    manifest_plate_files = {r["file"] for r in manifest["assets"]
                            if r["kind"] == "plate"}
    used_plate_files = set(plate_paths)
    for missing in used_plate_files - manifest_plate_files:
        fails.append(f"plate used in the render has no manifest entry: {missing}")
    for extra in manifest_plate_files - used_plate_files:
        fails.append(f"manifest lists a plate not used in the render: {extra}")
    manifest_audio_files = {r["file"] for r in manifest["assets"]
                            if r["kind"] in ("music", "sfx", "sting")}
    used_audio_files = {r["file"] for r in (audio_rows or [])}
    for missing in used_audio_files - manifest_audio_files:
        fails.append(f"audio asset used in the render has no manifest entry: "
                     f"{missing}")
    for extra in manifest_audio_files - used_audio_files:
        fails.append(f"manifest lists an audio asset not used in the render: "
                     f"{extra}")
    if voice_wav is not None and Path(voice_wav).exists() and not manifest.get("voice", {}).get("provider"):
        fails.append("voice track present but manifest.voice has no provider")
    return {"ok": not fails, "fails": fails[:10]}


# ----------------------------------------------------------- distinctness --

def load_distinctness_history(path: Path | None = None) -> list:
    path = path or HISTORY_PATH
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def record_distinctness(entry: dict, path: Path | None = None,
                        cap: int = HISTORY_CAP) -> None:
    """Replace any existing entry for the same video_id (a re-render of the
    same topic must not count as two distinct videos), append, keep the
    most recent `cap`."""
    path = path or HISTORY_PATH
    history = [h for h in load_distinctness_history(path)
              if h.get("video_id") != entry.get("video_id")]
    history.append(entry)
    history = history[-cap:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=1))
