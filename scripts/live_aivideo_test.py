"""live_aivideo_test.py — Phase 2B-finisher LIVE test of the AI-video path.

Directive §8 goal: ≥3 successful generations across ≥2 distinct
providers/models, incl. ≥1 I2V + ≥1 T2V. Every attempt (provider, space/
endpoint, outcome, error class, elapsed) is recorded into
results/v4_aivideo_live_test.json. Prompts come from the §11 cinematic
prompt builder (engine/v4/prompts.py); the I2V keyframe comes from NVIDIA
FLUX (nvidia_nim). Quota wallets are INDEPENDENT (§8): hf_router draws
monthly included credits (observed depleted, HTTP 402, 2026-08-30);
ZeroGPU draws the daily GPU-min allowance (~5 min/day) — spend it on
short 480p generations only and stop immediately on QUOTA_EXHAUSTED.

Resumable: prior attempts in the results file are preserved; providers
already attempted this phase are skipped. HF_TOKEN is read from .env and
never printed/logged.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/ubuntu/video_engine")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# .env → env (do not overwrite existing; never echo values)
for _line in (ROOT / ".env").read_text().splitlines():
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

from engine.broker.cache import BrokerCache                       # noqa: E402
from engine.broker.failures import classify_failure               # noqa: E402
from engine.broker.providers.hf_router import (                   # noqa: E402
    HFRouterI2VProvider, HFRouterT2VProvider)
from engine.broker.providers.imageapi import NvidiaNimImageProvider  # noqa: E402
from engine.broker.zerogpu_scheduler import ZeroGPUScheduler      # noqa: E402
from engine.v4.prompts import (                                   # noqa: E402
    ShotSpec, build_cinematic_prompt, build_negative_prompt)

RESULTS_PATH = ROOT / "results" / "v4_aivideo_live_test.json"
RESULTS = {
    "generated_at_utc": None,
    "directive_goal": "≥3 successful AI-video generations across ≥2 distinct "
                      "providers/models, incl. ≥1 I2V + ≥1 T2V",
    "attempts": [],
    "spaces_probed": {},
    "quota_accounting": {},
    "summary": {},
}
if RESULTS_PATH.exists():
    try:
        _prior = json.loads(RESULTS_PATH.read_text())
        RESULTS["attempts"] = _prior.get("attempts", [])
        RESULTS["spaces_probed"] = _prior.get("spaces_probed", {})
        RESULTS["quota_accounting"] = _prior.get("quota_accounting", {})
        print(f"resuming: {len(RESULTS['attempts'])} prior attempt(s) loaded",
              flush=True)
    except Exception:
        pass


def _save():
    RESULTS["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(RESULTS, indent=2) + "\n")


def _record(provider: str, model: str, kind: str, outcome: str, *,
            space_id: str = "", endpoint: str = "", error: str = "",
            elapsed: float = 0.0, output: str = "", extra: dict | None = None):
    rec = {
        "attempted_provider": provider,
        "space_id": space_id,
        "endpoint": endpoint,
        "model": model,
        "output_kind": kind,
        "outcome": outcome,
        "success": outcome == "success",
        "failure_reason": error[:500] if error else "",
        "error_class": classify_failure(error) if error else "",
        "fallback_reason": "",
        "elapsed_sec": round(elapsed, 1),
        "output": output,
    }
    if extra:
        rec["detail"] = extra
    RESULTS["attempts"].append(rec)
    print(f"[{outcome.upper()}] {provider} {model} ({kind}) "
          f"{rec['elapsed_sec']}s {rec['error_class']}", flush=True)
    _save()
    return rec


def _hf_credits_depleted() -> bool:
    return any(a["error_class"] == "QUOTA_EXHAUSTED"
               and a["attempted_provider"].startswith("hf_router")
               for a in RESULTS["attempts"])


def _zerogpu_quota_exhausted() -> bool:
    return any(a["error_class"] == "QUOTA_EXHAUSTED"
               and a["attempted_provider"].startswith("zerogpu")
               for a in RESULTS["attempts"])


def _already_attempted(provider: str) -> bool:
    return any(a["attempted_provider"] == provider
               for a in RESULTS["attempts"])


def main() -> int:
    cache = BrokerCache()
    successes = 0

    spec_t2v = ShotSpec(
        subject="a lone lighthouse on a basalt cliff",
        action="its beam sweeps across rolling storm clouds as waves explode "
               "against the rocks below",
        environment="a remote North Atlantic headland at dusk",
        camera_move="push_in", shot_scale="wide",
        lighting_change="the beam pulses, briefly lighting wet stone",
        motion="spray drifts through the beam, clouds race overhead",
        duration_sec=5.0, seed=11)
    prompt_t2v = build_cinematic_prompt(spec_t2v, variant="generic")
    neg = build_negative_prompt(spec_t2v)

    # ── Attempt 1: HF router T2V (Wan2.2-T2V-A14B via fal-ai, monthly credits)
    if not _already_attempted("hf_router_t2v"):
        t0 = time.time()
        try:
            p = HFRouterT2VProvider(cache=cache)
            res = p.generate_video(prompt_t2v, duration=5.0, aspect="16:9",
                                   seed=11)
            _record("hf_router_t2v", "Wan2.2-T2V-A14B", "t2v", "success",
                    endpoint="fal-ai/wan/v2.2-a14b/text-to-video",
                    elapsed=time.time() - t0, output=res.path,
                    extra={"bytes": Path(res.path).stat().st_size,
                           "prompt": prompt_t2v})
            successes += 1
        except Exception as exc:  # noqa: BLE001
            _record("hf_router_t2v", "Wan2.2-T2V-A14B", "t2v", "failed",
                    endpoint="fal-ai/wan/v2.2-a14b/text-to-video",
                    error=f"{type(exc).__name__}: {exc}",
                    elapsed=time.time() - t0)
        if _hf_credits_depleted():
            print("NOTE: monthly credits depleted (402) — ZeroGPU path is an "
                  "independent wallet, continuing there.", flush=True)
    else:
        print("skip hf_router_t2v (already attempted this phase)", flush=True)

    # ── ZeroGPU probe (no quota cost): /gradio_api/info per candidate Space
    scheduler = None
    try:
        scheduler = ZeroGPUScheduler()
        probe = scheduler.probe(force=True)
        RESULTS["spaces_probed"] = {
            sid: {"reachable": info is not None,
                  "source": getattr(info, "source", ""),
                  "endpoints": sorted(e.name for e in info.endpoints)[:8]
                  if info else []}
            for sid, info in probe.items()}
        RESULTS["quota_accounting"]["zerogpu_ledger"] = scheduler.ledger.status()
        print("probe:", json.dumps(RESULTS["spaces_probed"], indent=1)[:800],
              flush=True)
        _save()
    except Exception as exc:  # noqa: BLE001
        print("probe failed:", type(exc).__name__, exc, flush=True)

    # ── Attempt 2: NVIDIA FLUX keyframe (image quota — none of the above)
    spec_kf = ShotSpec(
        subject="a lone lighthouse on a basalt cliff",
        action="its beam cuts through storm clouds over exploding waves",
        environment="a remote North Atlantic headland at dusk",
        camera_move="static", shot_scale="wide", duration_sec=5.0, seed=11)
    keyframe = ""
    if not _already_attempted("nvidia_nim"):
        t0 = time.time()
        try:
            nim = NvidiaNimImageProvider(cache=cache)
            kf = nim.generate_image(
                build_cinematic_prompt(spec_kf, variant="generic"),
                aspect="16:9", seed=11)
            keyframe = str(kf.path)
            _record("nvidia_nim", "flux.2-klein-4b", "keyframe_image",
                    "success", elapsed=time.time() - t0, output=keyframe,
                    extra={"bytes": Path(keyframe).stat().st_size})
        except Exception as exc:  # noqa: BLE001
            _record("nvidia_nim", "flux.2-klein-4b", "keyframe_image", "failed",
                    error=f"{type(exc).__name__}: {exc}",
                    elapsed=time.time() - t0)
    else:
        _prior_kf = [a for a in RESULTS["attempts"]
                     if a["attempted_provider"] == "nvidia_nim"
                     and a["success"]]
        keyframe = _prior_kf[-1]["output"] if _prior_kf else ""
        print(f"skip nvidia_nim (prior attempt, keyframe={keyframe})",
              flush=True)

    # ── Attempt 3: HF router I2V (Wan2.2-I2V-A14B) from the FLUX keyframe
    if not _already_attempted("hf_router_i2v"):
        if not keyframe:
            _record("hf_router_i2v", "Wan2.2-I2V-A14B", "i2v", "skipped",
                    error="keyframe generation failed")
        elif _hf_credits_depleted():
            _record("hf_router_i2v", "Wan2.2-I2V-A14B", "i2v", "skipped",
                    error="monthly included credits depleted (HTTP 402 "
                          "observed on T2V attempt) — independent wallet, "
                          "ZeroGPU path continues")
            print("skip hf_router_i2v — credits depleted", flush=True)
        else:
            t0 = time.time()
            try:
                p = HFRouterI2VProvider(cache=cache)
                res = p.image_to_video(keyframe, prompt_t2v, duration=5.0,
                                       aspect="16:9", seed=11)
                _record("hf_router_i2v", "Wan2.2-I2V-A14B", "i2v", "success",
                        endpoint="fal-ai/wan/v2.2-a14b/image-to-video",
                        elapsed=time.time() - t0, output=res.path,
                        extra={"keyframe": keyframe,
                               "bytes": Path(res.path).stat().st_size})
                successes += 1
            except Exception as exc:  # noqa: BLE001
                _record("hf_router_i2v", "Wan2.2-I2V-A14B", "i2v", "failed",
                        endpoint="fal-ai/wan/v2.2-a14b/image-to-video",
                        error=f"{type(exc).__name__}: {exc}",
                        elapsed=time.time() - t0)

    # ── Attempt 4: ZeroGPU T2V via the quota-aware scheduler (LTX pool) —
    # distinct provider AND model family. Minimal spend: 4s at low res.
    zerogpu_t2v_space = ""
    if (scheduler is not None and not _already_attempted("zerogpu_t2v")
            and not _zerogpu_quota_exhausted()
            and not scheduler.ledger.blocked):
        t0 = time.time()
        try:
            res = scheduler.generate_t2v(prompt_t2v, duration=4.0,
                                         negative=neg, seed=11)
            zerogpu_t2v_space = str(res.metadata.get("space_id", ""))
            _record("zerogpu_t2v", "scheduler-pool(LTX)", "t2v", "success",
                    space_id=zerogpu_t2v_space,
                    elapsed=time.time() - t0, output=str(res.path),
                    extra={"attempts": res.metadata.get("attempts", []),
                           "bytes": Path(res.path).stat().st_size})
            successes += 1
        except Exception as exc:  # noqa: BLE001
            _record("zerogpu_t2v", "scheduler-pool(LTX)", "t2v", "failed",
                    error=f"{type(exc).__name__}: {exc}",
                    elapsed=time.time() - t0,
                    extra={"attempts": [a.to_record()
                                        for a in scheduler.attempts]})
    elif scheduler is None:
        _record("zerogpu_t2v", "scheduler-pool(LTX)", "t2v", "skipped",
                error="scheduler unavailable")
    else:
        print("skip zerogpu_t2v (attempted/exhausted/blocked)", flush=True)

    # ── Attempt 5: ZeroGPU I2V (distinct Space: Saravutw Wan Lightning) —
    # only if the T2V attempt didn't trip the account-wide ledger.
    if (scheduler is not None and keyframe
            and not _already_attempted("zerogpu_i2v")
            and not _zerogpu_quota_exhausted()
            and not scheduler.ledger.blocked):
        t0 = time.time()
        try:
            res = scheduler.generate_i2v(keyframe, prompt_t2v, duration=4.0,
                                         negative=neg, seed=11)
            _record("zerogpu_i2v", "scheduler-pool(Wan-Lightning/LTX)", "i2v",
                    "success", space_id=str(res.metadata.get("space_id", "")),
                    elapsed=time.time() - t0, output=str(res.path),
                    extra={"attempts": res.metadata.get("attempts", []),
                           "keyframe": keyframe,
                           "bytes": Path(res.path).stat().st_size})
            successes += 1
        except Exception as exc:  # noqa: BLE001
            _record("zerogpu_i2v", "scheduler-pool(Wan-Lightning/LTX)", "i2v",
                    "failed", error=f"{type(exc).__name__}: {exc}",
                    elapsed=time.time() - t0,
                    extra={"attempts": [a.to_record()
                                        for a in scheduler.attempts]})
    elif not keyframe or scheduler is None:
        print("skip zerogpu_i2v (no keyframe or scheduler)", flush=True)
    else:
        print("skip zerogpu_i2v (attempted/exhausted/blocked)", flush=True)

    try:
        if scheduler is not None:
            RESULTS["quota_accounting"]["zerogpu_ledger"] = \
                scheduler.ledger.status()
    except Exception:
        pass

    ok = [a for a in RESULTS["attempts"] if a["success"]]
    video_ok = [a for a in ok if a["output_kind"] in ("t2v", "i2v")]
    providers = {a["attempted_provider"] for a in video_ok}
    kinds = {a["output_kind"] for a in video_ok}
    RESULTS["summary"] = {
        "video_successes": len(video_ok),
        "distinct_providers": sorted(providers),
        "output_kinds": sorted(kinds),
        "goal_met": len(video_ok) >= 3 and len(providers) >= 2
                    and {"t2v", "i2v"} <= kinds,
        "hf_router_credits_depleted": _hf_credits_depleted(),
        "zerogpu_quota_exhausted": _zerogpu_quota_exhausted(),
    }
    _save()
    print("SUMMARY:", json.dumps(RESULTS["summary"], indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
