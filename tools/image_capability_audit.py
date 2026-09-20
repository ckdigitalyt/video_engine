"""image_capability_audit.py — V13 M1a live provider capability probe.

Probes edit/multi-ref support for every wired image provider at LOW
resolution and writes docs/v13/PROVIDER_CAPABILITIES.md (date-stamped
matrix: edit / multi-ref / depth-edge / max-res / latency).

Budget discipline (M1a directive): at most MAX_LIVE_PROBES image-API
calls per run.  Honesty over coverage — a provider whose probe fails is
recorded as unsupported, never guessed.  Key NAMES are written, never
values; keys load from .env (gitignored).

Usage:
    python3 tools/image_capability_audit.py            # key presence only
    python3 tools/image_capability_audit.py --live     # with live probes
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO, ".env"), override=True)

from src.providers.image_gen import (  # noqa: E402
    GeminiImageProvider,
    NvidiaNimProvider,
    SiliconFlowProvider,
    _looks_like_image,
)

MAX_LIVE_PROBES = 3
DOC_PATH = REPO / "docs" / "v13" / "PROVIDER_CAPABILITIES.md"
PROBE_PROMPT = ("Add one small solid red circle in the top-left corner. "
                "Keep everything else identical.")
MULTIREF_PROMPT = ("Combine both reference images into one scene: the blue "
                   "panel on the left, the green panel on the right.")


def _make_source(path: str, w: int = 512, h: int = 288) -> None:
    """Deterministic probe source image — a blue gradient with a white box.
    (Built locally with PIL: costs zero API calls.)"""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), (38, 58, 92))
    d = ImageDraw.Draw(im)
    for x in range(w):
        d.line([(x, 0), (x, h)],
               fill=(38 + x * 60 // w, 58, 92 + x * 90 // w))
    d.rectangle([w // 3, h // 3, 2 * w // 3, 2 * h // 3],
                outline=(255, 255, 255), width=4)
    im.save(path, "PNG")


def _probe(fn) -> dict:
    """Run one probe; return a result dict; never raises."""
    t0 = time.time()
    try:
        out = fn()
        ok = out and Path(str(out)).exists() and _looks_like_image(str(out))
        return {"status": "ok" if ok else "bad-output",
                "latency_s": round(time.time() - t0, 1),
                "detail": str(out) if ok else "payload failed sanity check"}
    except NotImplementedError as exc:
        return {"status": "unsupported", "latency_s": 0.0,
                "detail": str(exc)[:120]}
    except Exception as exc:  # noqa: BLE001 — probe records, never crashes
        return {"status": "failed",
                "latency_s": round(time.time() - t0, 1),
                "detail": f"{type(exc).__name__}: {str(exc)[:140]}"}


def run_audit(live: bool) -> dict:
    """Probe each wired provider within the live-call budget."""
    src = os.path.join(REPO, "cache", "generated", "audit_src.png")
    Path(src).parent.mkdir(parents=True, exist_ok=True)
    _make_source(src)
    src2 = os.path.join(REPO, "cache", "generated", "audit_src2.png")
    _make_source(src2, 512, 512)

    budget = {"calls": 0}

    def within_budget(fn) -> dict:
        if budget["calls"] >= MAX_LIVE_PROBES:
            return {"status": "skipped-budget", "latency_s": 0.0,
                    "detail": f"probe budget {MAX_LIVE_PROBES} exhausted"}
        budget["calls"] += 1
        return _probe(fn)

    results: dict[str, dict] = {}

    # gemini_image — one edit roundtrip (same endpoint powers multi-ref).
    g = GeminiImageProvider()
    results["gemini_image"] = {
        "key": "GEMINI_API_KEY", "has_key": g.is_available(),
        "edit": within_budget(lambda: g.edit_image(
            PROBE_PROMPT, src, aspect="16:9", seed=42)) if live
            else {"status": "not-probed", "latency_s": 0.0, "detail": "dry run"},
        "multiref": "wired (2–14 refs, same endpoint) — not probed (budget)",
        "max_res": "1024-class output (model default)",
    }

    # nvidia_nim — one kontext img2img attempt.
    n = NvidiaNimProvider()
    results["nvidia_nim"] = {
        "key": "NVIDIA_API_KEY", "has_key": n.is_available(),
        "edit": within_budget(lambda: n.edit_image(
            PROBE_PROMPT, src, aspect="16:9", seed=42)) if live
            else {"status": "not-probed", "latency_s": 0.0, "detail": "dry run"},
        "multiref": "unsupported (kontext takes exactly one image)",
        "max_res": "≤1344 px (NIM allowed dims)",
    }

    # siliconflow — one edit attempt (Qwen-Image-Edit first).
    s = SiliconFlowProvider()
    results["siliconflow"] = {
        "key": "SILICONFLOW_API_KEY", "has_key": s.is_available(),
        "edit": within_budget(lambda: s.edit_image(
            PROBE_PROMPT, src, aspect="16:9", seed=42)) if live
            else {"status": "not-probed", "latency_s": 0.0, "detail": "dry run"},
        "multiref": "wired (Qwen-Image-Edit-2509 image list) — not probed (budget)",
        "max_res": "1024-class (generations endpoint)",
    }

    # pollinations / hf_serverless — keyless/fallback-only, no probe needed.
    results["pollinations"] = {
        "key": "none (keyless)", "has_key": True,
        "edit": "unsupported → single-pass text→img fallback",
        "multiref": "unsupported → single-pass fallback",
        "max_res": "1280x720 verified (repo note 2026-08)",
    }
    results["hf_serverless"] = {
        "key": "HF_TOKEN", "has_key": bool(os.environ.get("HF_TOKEN")),
        "edit": "unsupported (inference endpoint is text→img only)",
        "multiref": "unsupported",
        "max_res": "model-dependent (FLUX.1-schnell ≤1024)",
    }

    for name, r in results.items():
        if isinstance(r.get("edit"), dict) and r["edit"]["status"] == "ok":
            r["multiref_note"] = r["multiref"]
    return results


def render_doc(results: dict, live: bool) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Provider Capabilities — V13 M1a",
        "",
        f"*Live-probed: {now} · mode: "
        f"{'live (≤3 image calls)' if live else 'dry (key presence only)'} · "
        "prober: `tools/image_capability_audit.py` · key NAMES only, values "
        "stay in `.env` (gitignored).*",
        "",
        "| provider | key | edit_image | generate_multi_ref | depth/edge | max res | edit latency |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, r in results.items():
        edit = r["edit"]
        if isinstance(edit, dict):
            edit_s = f"{'✅ probed' if edit['status'] == 'ok' else '❌ ' + edit['status']}"
        else:
            edit_s = str(edit)
        lines.append(
            f"| `{name}` | `{r['key']}` ({'present' if r['has_key'] else 'MISSING'}) "
            f"| {edit_s} | {r['multiref']} | unsupported (planned M3) "
            f"| {r['max_res']} "
            f"| {edit.get('latency_s', '—') if isinstance(edit, dict) else '—'}s |")
    lines += [
        "",
        "## Probe detail",
        "",
    ]
    for name, r in results.items():
        edit = r["edit"]
        if isinstance(edit, dict):
            lines.append(f"- **{name}**: edit={edit['status']} "
                         f"({edit['latency_s']}s) — {edit['detail']}")
        else:
            lines.append(f"- **{name}**: {edit_s}")
    lines += [
        "",
        "## Fallback rule (Contract 2)",
        "",
        "Any provider without edit/multi-ref support raises "
        "`NotImplementedError`; `edit_image_with_fallback` / "
        "`generate_multi_ref_with_fallback` degrade to single-pass text→img "
        "and report `(path, edited=False)` so plate sidecars (M1b) can flag "
        "degraded stages. Endpoint failures degrade the same way — a failed "
        "op must never crash the factory or a render.",
        "",
        "Honesty rule: providers whose live probe failed are recorded "
        "unsupported above; multi-ref rows marked \"wired — not probed\" "
        "have code paths but no live evidence in this run.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true",
                    help=f"run live probes (max {MAX_LIVE_PROBES} image calls)")
    args = ap.parse_args()

    results = run_audit(live=args.live)
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(render_doc(results, live=args.live))

    print(f"wrote {DOC_PATH.relative_to(REPO)}")
    for name, r in results.items():
        edit = r["edit"]
        status = edit["status"] if isinstance(edit, dict) else str(edit)
        lat = f"{edit['latency_s']}s" if isinstance(edit, dict) else "—"
        print(f"  {name:14s} edit={status:16s} {lat:>6s} "
              f"key={'yes' if r['has_key'] else 'NO'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
