"""
publish_status.py — Publish-readiness state machine (expert review rec #10).

The pipeline previously had only a boolean ``publish_ready`` inside
publish_gate.json.  A blocked video "completed" identically to a good one,
which made REVISION_REQUIRED work invisible (tunguska/fermi both completed
with blocked gates).

This module defines the single status enum every run must resolve to:

    PUBLISH_READY      — all gates pass; safe to declare done/upload (unlisted)
    REVISION_REQUIRED  — at least one gate blocked; the run's artifacts are
                         evidence for a revision loop, NOT a finished video
    BLOCKED            — pipeline could not produce a watchable artifact
                         (render failure, coverage failure, fatal errors)

Every runner (mission_run / mission_stills) writes a ``STATUS`` file and a
``status`` field in run_report.json so a cron-driven daily pipeline can make
one deterministic decision: upload only when PUBLISH_READY.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from typing import Optional


class PublishStatus(str, Enum):
    PUBLISH_READY = "PUBLISH_READY"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    BLOCKED = "BLOCKED"


# ── Gate name → recommendation group (expert review taxonomy) ────────────
# Used to enrich the status payload so a revision pass knows WHICH class of
# failure occurred (factual vs visual vs audio vs retention vs source-res).
FACTUAL_GATES = {"claim_verification", "claim_contradictions",
                 "unsupported_quantitative_claims", "entity_disambiguation",
                 "manim_facts", "script_fact_review", "authentic_audio"}
VISUAL_GATES = {"shot_hold", "repeated_assets", "frozen_frames",
                "static_shots", "visual_artifacts", "resolution_headroom",
                "opening_black_frames", "hook_strength", "style_drift",
                "style_locked", "off_topic_assets", "semantic_alignment"}
AUDIO_GATES = {"loudness_master", "dead_air", "dead_air_audio",
               "narration_clipping", "ducking_depth", "voice_switching",
               "voice_loudness_consistency"}
RETENTION_GATES = {"shot_hold", "hook_strength", "max_shot_duration",
                   "pacing", "dead_air", "opening_black_frames"}


def _blocked_names(gate: dict) -> list[str]:
    """Names of the checks that actually blocked a gate report.

    v14 fix: prefer the gate's explicit ``blocking_failures`` list when
    present.  Advisory checks (e.g. ``unsupported_quantitative_claims``
    which is report-only by design) must NOT count as blockers — the
    whale run was wrongly held at REVISION_REQUIRED for an advisory flag.
    """
    bf = gate.get("blocking_failures")
    if isinstance(bf, list):
        return [str(x) for x in bf if x]
    out = []
    for c in gate.get("checks", []):
        if not c.get("passed", True):
            out.append(c.get("name", "unknown"))
    return out


def resolve_status(*,
                   publish_gate: Optional[dict] = None,
                   pre_render_gate: Optional[dict] = None,
                   claim_gate: Optional[dict] = None,
                   fatal_errors: Optional[list] = None,
                   artifacts: Optional[list] = None) -> dict:
    """Resolve the run-level publish status from every gate report.

    Order of precedence (strictest first):
      1. BLOCKED       — fatal errors / missing final artifact
      2. REVISION      — any blocking check in ANY gate
      3. PUBLISH_READY — everything passed

    Returns a payload dict suitable for run_report.json + STATUS file:
        {status, publish_ready, blocked_by: {gate: [checks]},
         categories: [factual|visual|audio|retention], summary}
    """
    fatal = [e for e in (fatal_errors or []) if e]
    missing = not artifacts or not any(
        os.path.exists(a) for a in artifacts)
    if fatal or missing:
        blocked_by: dict[str, list[str]] = {"fatal": fatal}
        if missing:
            blocked_by["fatal"].append("final video artifact missing")
        return {
            "status": PublishStatus.BLOCKED.value,
            "publish_ready": False,
            "blocked_by": blocked_by,
            "categories": [],
            "summary": "Pipeline failed to produce a watchable artifact.",
        }

    blocked: dict[str, list[str]] = {}
    for label, gate in (("publish", publish_gate),
                        ("pre_render", pre_render_gate),
                        ("claims", claim_gate)):
        if gate is None:
            continue
        names = _blocked_names(gate)
        if names:
            blocked[label] = names

    if not blocked:
        return {
            "status": PublishStatus.PUBLISH_READY.value,
            "publish_ready": True,
            "blocked_by": {},
            "categories": [],
            "summary": "All gates passed — video is publish-ready.",
        }

    # Classify blocked checks into the expert-review taxonomy.
    all_names = {n for names in blocked.values() for n in names}
    cats = []
    if all_names & FACTUAL_GATES:
        cats.append("factual")
    if all_names & VISUAL_GATES:
        cats.append("visual")
    if all_names & AUDIO_GATES:
        cats.append("audio")
    if all_names & RETENTION_GATES:
        cats.append("retention")
    if not cats:
        cats.append("other")

    return {
        "status": PublishStatus.REVISION_REQUIRED.value,
        "publish_ready": False,
        "blocked_by": blocked,
        "categories": sorted(set(cats)),
        "summary": "Gates blocked — revision required before publication: "
                   + "; ".join(f"{k}: {', '.join(v)}" for k, v in blocked.items()),
    }


def write_status(run_dir: str, status: dict) -> str:
    """Write STATUS.json (and human-readable STATUS) into the run dir."""
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, "STATUS.json")
    with open(path, "w") as f:
        json.dump(status, f, indent=2)
    human = os.path.join(run_dir, "STATUS")
    with open(human, "w") as f:
        f.write(f"{status['status']}\n")
        if status.get("blocked_by"):
            f.write("blocked by:\n")
            for gate, names in status["blocked_by"].items():
                f.write(f"  {gate}: {', '.join(names)}\n")
    return path
