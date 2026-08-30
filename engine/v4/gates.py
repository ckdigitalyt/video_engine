"""gates.py — V4 publish gates that measure THE ARTIFACT (directive §19).

The V3 publish gate scored fiction: a vision placeholder of 100/100 with
vision 0/24 online, planned renderer mixes instead of render_records, and
metadata never verified against the file it reported on. The V4 forensic
audit of dino_v1 (results/dino_v1/audit_v4.md) is the baseline these gates
must fail: 63.5 % frozen runtime, 0.078 scene-internal events/10 s, 31.5 %
flat-card time, one dhash-identical Motion Canvas template cluster, and
on-screen text repeating the narration verbatim.

Gates (all deterministic, computed from decoded pixels via
tools/v4_audit.py — never from the plan's self-description):

  ARTIFACT_METADATA     ffprobe of the exact artifact vs the declared spec
                        (also publishes the exact path it probed, §1)
  VISUAL_EVENT_DENSITY  >= 1.5 scene-internal events / 10 s
  STATIC_HOLD           no hold > 2.5 s unless shot-design-approved
  TEXT_CARD_OVERUSE     flat/card time < 10 % + no narration-repeat labels
  SHOT_DIVERSITY        renderer repeats + dhash duplicate clusters
  VISUAL_NOVELTY        frame novelty score across sampled frames
  CINEMATIC             cinematography fields, camera-move ratio, scale variety
  AI_VIDEO_COVERAGE     rendered vs attempted AI_VIDEO (informational)
  CREATIVE              human-like critic overall >= 8.0 (see critic.py)
"""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# §19 thresholds (calibrated on the dino_v1 forensic baseline, which every
# one of these gates must FAIL).
EVENT_DENSITY_MIN = 1.5        # events / 10 s (scene-internal)
STATIC_HOLD_MAX_SEC = 2.5      # §3 rule
FLAT_CARD_MAX_FRACTION = 0.10  # flat/text-card time < 10 % of runtime
NARRATION_REPEAT_RATIO = 0.60  # overlay-vs-narration similarity limit
MAX_CONSECUTIVE_SAME_RENDERER = 2
MIN_DISTINCT_RENDERERS = 3     # for shotlists of >= 8 shots
NOVELTY_MIN = 0.75             # fraction of samples in unique imagery
CAMERA_MOVE_RATIO_MIN = 0.35   # non-static camera_move share
SHOT_SCALE_VARIETY_MIN = 2     # distinct shot scales
# §20: creative critic score < 8.0 → FAIL (single definition in critic.py)
from engine.v4.critic import CREATIVE_PASS_MIN  # noqa: E402

_V4_AUDIT_PATH = PROJECT_ROOT / "tools" / "v4_audit.py"
_AUDIT_MOD: Any = None


def audit_tool() -> Any:
    """Load tools/v4_audit.py (metric implementations shared, not forked)."""
    global _AUDIT_MOD
    if _AUDIT_MOD is None:
        spec = importlib.util.spec_from_file_location("v4_audit", _V4_AUDIT_PATH)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _AUDIT_MOD = mod
    return _AUDIT_MOD


def _gate(name: str, ok: bool, detail: str,
          fixes: list[str] | None = None) -> dict:
    return {"gate": name, "pass": bool(ok), "detail": detail,
            "fixes": fixes or []}


# ── ARTIFACT_METADATA (§1) ──────────────────────────────────────────────

def artifact_metadata_gate(master: Path, expected: dict) -> dict:
    """ffprobe the actual file and compare with the declared spec.

    The gate result carries ``probe`` and the exact ``artifact_path`` that
    was probed — publish_gate.json must reference the artifact it verified,
    never a declared spec (the §1 910x512 confusion)."""
    va = audit_tool()
    master = Path(master)
    if not master.exists():
        return _gate("ARTIFACT_METADATA", False,
                     f"artifact missing: {master}")
    try:
        probe = va.probe(master)
    except Exception as exc:  # noqa: BLE001
        return _gate("ARTIFACT_METADATA", False, f"ffprobe failed: {exc}")
    issues: list[str] = []
    if expected.get("codec") and probe.get("codec") != expected["codec"]:
        issues.append(f"codec {probe.get('codec')} != {expected['codec']}")
    for key, actual in (("width", probe.get("width")),
                        ("height", probe.get("height"))):
        want = expected.get(key)
        if want and actual != want:
            issues.append(f"{key} {actual} != {want}")
    want_fps = expected.get("fps")
    if want_fps and probe.get("fps") and \
            abs(probe["fps"] - float(want_fps)) > 0.6:
        issues.append(f"fps {probe['fps']} != {want_fps}")
    want_dur = expected.get("duration_sec")
    if want_dur and probe.get("duration_sec") and \
            abs(probe["duration_sec"] - float(want_dur)) > 1.0:
        issues.append(f"duration {probe['duration_sec']}s != {want_dur}s")
    detail = (f"probed {master.name}: {probe.get('codec')} "
              f"{probe.get('width')}x{probe.get('height')}@"
              f"{probe.get('fps')}fps {probe.get('duration_sec')}s — "
              + ("matches declared spec" if not issues else "; ".join(issues)))
    gate = _gate("ARTIFACT_METADATA", not issues, detail, issues)
    gate["artifact_path"] = str(master.resolve())
    gate["probe"] = probe
    gate["declared"] = {k: v for k, v in expected.items()
                        if k in ("codec", "width", "height", "fps",
                                 "duration_sec")}
    gate["matches_declared"] = not issues
    return gate


# ── VISUAL_EVENT_DENSITY (§2/§19) ─────────────────────────────────────

def visual_event_density_gate(master_audit: dict,
                              shot_audits: dict[str, dict] | None = None,
                              shot_cuts: int = 0) -> dict:
    va = audit_tool()
    duration = master_audit.get("visual_event_density", {}).get("duration_sec") or 0.0
    if shot_audits:
        total = sum(int(a.get("visual_event_density", {}).get("events", 0))
                    for a in shot_audits.values())
        source = f"{len(shot_audits)} shot audits (scene-internal)"
    else:
        total = max(0, int(master_audit.get("visual_event_density", {})
                           .get("events", 0)) - shot_cuts)
        source = f"master audit minus {shot_cuts} shot cut(s)"
    density = round(total * 10.0 / duration, 3) if duration else 0.0
    ok = density >= EVENT_DENSITY_MIN
    detail = (f"{total} scene-internal events over {duration:.1f}s = "
              f"{density}/10s ({source}); threshold >= {EVENT_DENSITY_MIN}")
    fixes = [] if ok else [
        "decompose static shots into micro_events (§4) and implement them "
        "in the renderers; a slow zoom on an unchanged image scores ~0"]
    return _gate("VISUAL_EVENT_DENSITY", ok, detail, fixes) | \
        {"events": total, "density_per_10s": density}


# ── STATIC_HOLD (§3/§19) ────────────────────────────────────────────────

def static_hold_gate(master_audit: dict,
                     shot_audits: dict[str, dict] | None = None,
                     approvals: dict[str, str] | None = None) -> dict:
    """No hold > 2.5 s unless shot-design-approved with justification.

    approvals: {shot_id: justification} (or {"__master__": ...} for a
    global approval when per-shot audits are unavailable)."""
    approvals = approvals or {}
    offenders: list[str] = []
    approved: list[str] = []
    total_hold = 0.0
    longest = 0.0
    if shot_audits:
        for sid, a in shot_audits.items():
            holds = a.get("static_holds", {}).get("holds_over_2_5s", [])
            for h in holds:
                dur = float(h.get("duration_sec", 0))
                longest = max(longest, dur)
                if sid in approvals:
                    approved.append(f"{sid} ({dur:.1f}s): {approvals[sid]}")
                else:
                    offenders.append(f"{sid}: hold {dur:.1f}s")
            total_hold += float(a.get("static_holds", {}).get("total_hold_sec", 0))
    else:
        holds = master_audit.get("static_holds", {}).get("holds_over_2_5s", [])
        total_hold = float(master_audit.get("static_holds", {}).get(
            "total_hold_sec", 0))
        for h in holds:
            dur = float(h.get("duration_sec", 0))
            longest = max(longest, dur)
            if "__master__" in approvals:
                approved.append(f"master hold {dur:.1f}s: {approvals['__master__']}")
            else:
                offenders.append(f"master hold {dur:.1f}s at t={h.get('start_sec')}")
    ok = not offenders
    detail = (f"longest hold {longest:.2f}s (max {STATIC_HOLD_MAX_SEC}s), "
              f"total frozen {total_hold:.1f}s, "
              f"{len(offenders)} unapproved / {len(approved)} approved")
    fixes = [] if ok else [
        "add micro_events to the offending shots; Ken Burns alone is NOT "
        "dynamic (§3); longer holds need shot-design approval + justification"]
    return _gate("STATIC_HOLD", ok, detail, fixes) | \
        {"longest_hold_sec": round(longest, 3),
         "total_hold_sec": round(total_hold, 3),
         "unapproved": offenders, "approved": approved}


# ── TEXT_CARD_OVERUSE (§13/§24/§19) ─────────────────────────────────────

def _overlay_text(shot: dict) -> str:
    tc = shot.get("text_card") or {}
    if isinstance(tc, dict) and tc.get("present") and tc.get("text"):
        return str(tc["text"])
    return str(shot.get("text_overlay") or "")


def text_card_overuse_gate(master_audit: dict, shots: list[dict]) -> dict:
    """flat/card time < 10 % of runtime + no verbatim narration-repeat."""
    from difflib import SequenceMatcher

    flat_fraction = float(master_audit.get("black_flat", {}).get(
        "flat_fraction", 0.0))
    issues: list[str] = []
    if flat_fraction >= FLAT_CARD_MAX_FRACTION:
        issues.append(
            f"flat/card time {flat_fraction:.1%} >= "
            f"{FLAT_CARD_MAX_FRACTION:.0%} of runtime")
    repeats: list[str] = []
    for shot in shots:
        overlay = _overlay_text(shot).lower().strip()
        if not overlay:
            continue
        narr = str(shot.get("metadata", {}).get("narration") or "").lower()
        sid = shot.get("shot_id", "?")
        if narr and (overlay in narr or narr in overlay):
            repeats.append(sid)
            issues.append(f"{sid}: text {overlay[:60]!r} repeats narration verbatim")
        elif narr:
            ratio = SequenceMatcher(None, overlay, narr[: len(overlay) * 2]).ratio()
            if ratio >= NARRATION_REPEAT_RATIO:
                repeats.append(sid)
                issues.append(
                    f"{sid}: text {overlay[:60]!r} paraphrases narration "
                    f"({ratio:.0%})")
    ok = not issues
    detail = (f"flat/card {flat_fraction:.1%} (< "
              f"{FLAT_CARD_MAX_FRACTION:.0%} required), "
              f"{len(repeats)} narration-repeat label(s)")
    fixes = [] if ok else [
        "show the claim instead of labelling it (§24); text cards < 1.5 s "
        "and never a narration repeat (§13)"]
    return _gate("TEXT_CARD_OVERUSE", ok, detail, fixes) | \
        {"flat_fraction": flat_fraction, "repeats": repeats}


# ── SHOT_DIVERSITY (§19) ────────────────────────────────────────────────

def shot_diversity_gate(hash_samples: list[dict], shots: list[dict]) -> dict:
    """Renderer repeats + dhash duplicate clusters.

    hash_samples: [{label, t, hash}] — per-shot audit samples preferred."""
    va = audit_tool()
    issues: list[str] = []
    clusters: list[dict] = va.find_duplicates(hash_samples) if hash_samples else []
    for c in clusters:
        issues.append("dhash duplicate imagery across shots: "
                      + ", ".join(c["labels"][:6])
                      + ("…" if len(c["labels"]) > 6 else ""))
    # renderer repeats (same policy as the v3 VARIETY gate, stricter run cap)
    histogram: dict[str, int] = {}
    max_run = 0
    run = 0
    prev: str | None = None
    for s in shots:
        rid = s.get("renderer", "?")
        histogram[rid] = histogram.get(rid, 0) + 1
        run = run + 1 if rid == prev else 1
        max_run = max(max_run, run)
        prev = rid
    if max_run > MAX_CONSECUTIVE_SAME_RENDERER:
        issues.append(f"renderer run of {max_run} > "
                      f"{MAX_CONSECUTIVE_SAME_RENDERER}")
    if len(shots) >= 8 and len(histogram) < MIN_DISTINCT_RENDERERS:
        issues.append(f"renderer histogram too narrow: {histogram}")
    ok = not issues
    detail = (f"mix={histogram}, maxrun={max_run}, "
              f"{len(clusters)} duplicate dhash cluster(s)")
    fixes = [] if ok else [
        "vary templates per shot (MOTION_CANVAS de-templating variant), "
        "break renderer runs, and re-route duplicated imagery"]
    return _gate("SHOT_DIVERSITY", ok, detail, fixes) | \
        {"renderer_histogram": histogram, "max_consecutive": max_run,
         "duplicate_clusters": [
             {"labels": c["labels"]} for c in clusters]}


# ── VISUAL_NOVELTY (§19) ────────────────────────────────────────────────

def visual_novelty_gate(hash_samples: list[dict],
                        max_hamming: int = 6) -> dict:
    """Frame novelty score: the share of sampled frames that are NOT part
    of repeated imagery. With per-shot samples, samples inside a cross-shot
    dhash cluster count as repeated; with a single video, samples closer
    than max_hamming to another sample count as repeated."""
    if len(hash_samples) < 2:
        return _gate("VISUAL_NOVELTY", False,
                     "not enough sampled frames for a novelty score")
    va = audit_tool()
    labels = {s.get("label") for s in hash_samples}
    repeated = 0
    if len(labels) >= 2:
        clusters = va.find_duplicates(hash_samples, max_hamming)
        clustered = {m["label"] for c in clusters for m in c["members"]}
        # count every *sample* inside a cross-shot cluster
        for s in hash_samples:
            if s.get("label") in clustered:
                repeated += 1
        in_cluster = repeated
    else:
        in_cluster = 0
        for i, s in enumerate(hash_samples):
            if any(i != j and va.hamming(s["hash"], o["hash"]) <= max_hamming
                   for j, o in enumerate(hash_samples)):
                in_cluster += 1
        repeated = in_cluster
    novelty = round(1.0 - repeated / len(hash_samples), 3)
    ok = novelty >= NOVELTY_MIN
    detail = (f"novelty {novelty} ({repeated}/{len(hash_samples)} sampled "
              f"frames in repeated imagery); threshold >= {NOVELTY_MIN}")
    fixes = [] if ok else [
        "the video re-uses the same imagery — one visual template or asset "
        "repeated; redesign the repeated shots"]
    return _gate("VISUAL_NOVELTY", ok, detail, fixes) | \
        {"novelty": novelty}


# ── CINEMATIC (§6/§19) ──────────────────────────────────────────────────

def cinematic_gate(shots: list[dict]) -> dict:
    """Cinematography fields present + non-static camera ratio + scale variety.

    A plan without v4 cinematography fields (pre-v4 shotlist) fails
    outright — the §6 fields must influence every renderer."""
    issues: list[str] = []
    n = len(shots)
    if n == 0:
        return _gate("CINEMATIC", False, "no shots")
    with_fields = sum(1 for s in shots
                      if s.get("camera_move") and s.get("shot_scale"))
    if with_fields < n:
        issues.append(
            f"{n - with_fields}/{n} shots missing cinematography fields "
            "(camera_move/shot_scale) — plan is not v4")
    non_static = sum(1 for s in shots
                     if str(s.get("camera_move") or "static") != "static")
    ratio = round(non_static / n, 3)
    if ratio < CAMERA_MOVE_RATIO_MIN:
        issues.append(f"non-static camera_move ratio {ratio} < "
                      f"{CAMERA_MOVE_RATIO_MIN}")
    scales = {s.get("shot_scale") for s in shots if s.get("shot_scale")}
    if len(scales) < SHOT_SCALE_VARIETY_MIN:
        issues.append(f"shot_scale variety {sorted(scales)} < "
                      f"{SHOT_SCALE_VARIETY_MIN} distinct scales")
    ok = not issues
    detail = (f"cinematography fields {with_fields}/{n}, camera-move "
              f"ratio {ratio}, scales {sorted(x for x in scales if x)}")
    fixes = [] if ok else [
        "plan through the §5 hierarchy (stage A cinematography) so every "
        "shot carries camera/subject/environment/lighting intent"]
    return _gate("CINEMATIC", ok, detail, fixes) | \
        {"camera_move_ratio": ratio, "shot_scales": sorted(
            str(x) for x in scales)}


# ── AI_VIDEO_COVERAGE (§7/§19, informational) ───────────────────────────

def ai_video_coverage_gate(render_records: list[dict] | None) -> dict:
    """Rendered-vs-attempted AI_VIDEO coverage.

    Informational until the AI-video providers work (§8): the gate records
    the §7 fallback chain evidence (attempted_provider / failure_reason /
    fallback_reason) and never blocks publication by itself — the STATIC_
    HOLD and VISUAL_EVENT_DENSITY gates catch the degradation instead."""
    records = render_records or []
    planned = [r for r in records
               if r.get("planned_renderer") == "AI_VIDEO"
               or r.get("shot_class") == "HERO"]
    attempted = sum(len(r.get("attempts", []) or []) for r in planned)
    rendered = sum(1 for r in planned if r.get("renderer") == "AI_VIDEO")
    degraded = [r.get("shot_id", "?") for r in planned
                if r.get("renderer") != "AI_VIDEO" and planned]
    coverage = round(rendered / len(planned), 3) if planned else None
    detail = (f"AI_VIDEO {rendered}/{len(planned)} planned shots rendered"
              if planned else
              "no AI_VIDEO-planned shots (informational gate)")
    if attempted:
        detail += f", {attempted} provider attempt(s) recorded"
    if degraded:
        detail += f"; degraded: {degraded[:6]}"
    return _gate("AI_VIDEO_COVERAGE", True, detail, []) | \
        {"planned": len(planned), "rendered": rendered,
         "attempted": attempted, "coverage": coverage,
         "degraded_shot_ids": degraded, "informational": True}


# ── CREATIVE (§20) — thin wrapper over the critic gate ──────────────────

def creative_gate(critic: dict) -> dict:
    """Creative critic verdict as a gate: overall < 8.0 → FAIL (§20).

    A technically valid video with a low creative score MUST fail."""
    overall = float(critic.get("overall_score") or 0.0)
    would = bool(critic.get("would_publish"))
    ok = would and overall >= CREATIVE_PASS_MIN
    detail = (f"creative critic {overall:.1f}/10 "
              f"({'LLM' if critic.get('available') else 'heuristic'}), "
              f"would_publish={would}; threshold >= {CREATIVE_PASS_MIN}")
    fixes = [] if ok else list(critic.get("top_5_problems", []))[:5]
    return _gate("CREATIVE", ok, detail, fixes) | \
        {"scores": critic.get("scores", {}),
         "overall_score": overall, "would_publish": would}


# ── Aggregate runner ────────────────────────────────────────────────────

def run_v4_gates(master: str | Path, *,
                 shots: list[dict] | None = None,
                 render_records: list[dict] | None = None,
                 shot_audits: dict[str, dict] | None = None,
                 approvals: dict[str, str] | None = None,
                 expected_spec: dict | None = None,
                 critic: dict | None = None,
                 master_audit: dict | None = None,
                 analysis_mode: bool = False) -> dict:
    """Run every §19 gate against the actual artifact.

    analysis_mode: audit-only run (e.g. against dino_v1 artifacts) — no
    critic LLM is invoked; the CREATIVE gate uses the deterministic
    heuristic critic so the verdict is still grounded in measured pixels.
    """
    va = audit_tool()
    master = Path(master)
    shots = shots or []
    if master_audit is None:
        master_audit = va.audit_video(master, label=master.stem)

    expected = expected_spec or {}
    if not expected:
        # derive the declared spec from the plan metadata when absent
        expected = {"codec": "h264", "width": 1920, "height": 1080, "fps": 30}

    gates: dict[str, dict] = {}

    # ARTIFACT_METADATA: ffprobe the exact file, publish the path probed.
    gates["ARTIFACT_METADATA"] = artifact_metadata_gate(master, expected)

    # Scene-internal event counting: prefer per-shot audits; otherwise
    # subtract the shot cuts (n-1 hard cuts) from master-level spikes.
    shot_cuts = max(0, len(shots) - 1) if shots else 0
    gates["VISUAL_EVENT_DENSITY"] = visual_event_density_gate(
        master_audit, shot_audits, shot_cuts)
    gates["STATIC_HOLD"] = static_hold_gate(master_audit, shot_audits,
                                            approvals)

    hash_samples: list[dict] = []
    if shot_audits:
        for a in shot_audits.values():
            hash_samples.extend(a.get("hash_samples", []))
    else:
        hash_samples = master_audit.get("hash_samples", [])
    gates["TEXT_CARD_OVERUSE"] = text_card_overuse_gate(master_audit, shots)
    gates["SHOT_DIVERSITY"] = shot_diversity_gate(hash_samples, shots)
    gates["VISUAL_NOVELTY"] = visual_novelty_gate(hash_samples)
    gates["CINEMATIC"] = cinematic_gate(shots)
    gates["AI_VIDEO_COVERAGE"] = ai_video_coverage_gate(render_records)

    if critic is None:
        from engine.v4.critic import heuristic_critic
        critic = heuristic_critic(shots, audit=master_audit,
                                  shot_audits=shot_audits)
    gates["CREATIVE"] = creative_gate(critic)

    failed = [name for name, g in gates.items() if not g["pass"]]
    doc = {
        "version": 4,
        "overall": "PASS" if not failed else "FAIL",
        "artifact": {
            "path": str(master.resolve()),
            "probed_by": "ARTIFACT_METADATA gate",
            "probe": gates["ARTIFACT_METADATA"].get("probe", {}),
            "matches_declared": gates["ARTIFACT_METADATA"].get(
                "matches_declared", False),
        },
        "master": str(master),
        "duration_sec": master_audit.get("visual_event_density", {})
        .get("duration_sec"),
        "analysis_mode": bool(analysis_mode),
        "gates": gates,
        "failed_gates": failed,
        "critic": critic,
    }
    return doc
