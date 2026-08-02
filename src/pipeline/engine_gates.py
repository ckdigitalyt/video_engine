"""
engine_gates.py — Wave-1 engine integration layer.

Wires the new frameworks into any pipeline as reusable gates:

  PRE-VISUAL  : build EntitySpecs per scene (semantic, LLM-first)
  ASSET-GATE  : verify each candidate asset before it enters the timeline
                (multi-signal + vision fallback; semantic mismatch = fatal)
  CAMERA      : intent-driven camera moves with diversity tracking
  INSTRUMENT  : record per-shot diagnostics (why did this frame appear?)
  POST-RENDER : deterministic QA (block only on objective failures)
  AUDIO       : three-track mix + two-pass loudness

Any pipeline (clip-based or stills-first) can call these gates; no
topic-specific logic lives here.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.verification.entity_spec import EntitySpec
from src.verification.spec_builder import build_spec
from src.verification.asset_verifier import AssetVerifier
from src.cinematic.camera_language import CameraDirector, DiversityTracker
from src.diagnostics.shot_instrumenter import ShotInstrumenter, ShotRecord
from src.qa.deterministic_qa import DeterministicQA, QAReport


class EngineGates:
    """Composable Wave-1 gates for documentary pipelines."""

    def __init__(
        self,
        llm_provider=None,
        vision_enabled: bool = True,
        verbose: bool = True,
    ):
        self._llm = llm_provider
        self._verifier = AssetVerifier(vision_enabled=vision_enabled)
        self._camera = CameraDirector()
        self._diversity = DiversityTracker()
        self._instrumenter = ShotInstrumenter()
        self._qa = DeterministicQA()
        self._verbose = verbose

    # ── PRE-VISUAL: entity specs ───────────────────────────────────────

    def build_scene_specs(self, scenes_data: list[dict], facts: Optional[list] = None,
                          confidence: float = 1.0) -> dict[int, EntitySpec]:
        """EntitySpec per scene, derived from narration + facts."""
        specs = {}
        for i, s in enumerate(scenes_data):
            spec = build_spec(
                beat_id=f"scene{i}",
                scene_id=i,
                narration=s.get("narration", ""),
                facts=facts,
                provider=self._llm,
                confidence=confidence,
            )
            specs[i] = spec
            if self._verbose:
                print(f"  [spec] scene{i}: intent={spec.scene_intent} "
                      f"req={spec.required_entities[:3]} "
                      f"prohib={spec.prohibited_entities[:3]}")
        return specs

    # ── ASSET-GATE: verify candidate assets ────────────────────────────

    def verify_asset(self, spec: EntitySpec, *, asset_path: str = "",
                     title: str = "", description: str = "", filename: str = "",
                     provider: str = "", tags: Optional[list] = None,
                     query_used: str = "", pre_verified: bool = False) -> dict:
        """Verify one asset against its scene spec. Returns result dict.

        ``pre_verified=True`` for human-approved assets (e.g. pinned real
        NASA photos): they bypass the semantic gate (recorded as verified
        by human) — the gate's job is catching UNVERIFIED assets.
        """
        if pre_verified:
            return {
                "passed": True, "score": 1.0, "pre_verified": True,
                "signal_scores": {}, "reasons": ["human-approved (pinned)"],
                "matched_required": list(spec.required_entities),
                "violated_prohibited": [], "missing_required": [],
                "vision_check": None,
            }
        res = self._verifier.verify(
            spec, asset_path=asset_path, title=title, description=description,
            filename=filename, provider=provider, tags=tags, query_used=query_used,
        )
        if self._verbose and not res.passed:
            print(f"  [gate] !! REJECT {os.path.basename(asset_path) or filename}: "
                  f"{res.reasons}")
        return res.to_dict()

    # ── CAMERA: intent-driven motion with diversity ────────────────────

    def camera_decision(self, intent: str = "default") -> dict:
        d = self._camera.decide(intent)
        return d.to_dict()

    def camera_diversity(self) -> dict:
        return self._camera.diversity()

    # ── INSTRUMENT: per-shot records ───────────────────────────────────

    def record_shot(self, *, scene_id, beat_index, shot_index, asset_path,
                    asset_source, asset_title, query_used, shot_duration_s,
                    narration_duration_s, camera_motion, motion_params,
                    transition, timeline_start_s, timeline_end_s,
                    verification: Optional[dict] = None,
                    entity_spec: Optional[dict] = None) -> None:
        rec = ShotRecord(
            scene_id=scene_id, beat_index=beat_index, shot_index=shot_index,
            asset_path=asset_path, asset_source=asset_source,
            asset_title=asset_title, query_used=query_used,
            verification=verification, entity_spec=entity_spec,
            shot_duration_s=shot_duration_s,
            narration_duration_s=narration_duration_s,
            camera_motion=camera_motion, motion_params=motion_params,
            transition=transition, timeline_start_s=timeline_start_s,
            timeline_end_s=timeline_end_s,
        )
        self._instrumenter.add_shot(rec)
        self._diversity.record(asset_path, transition, camera_motion, shot_duration_s)

    def write_diagnostics(self, out_dir: str, render_s: float = 0.0,
                          extra: Optional[dict] = None) -> str:
        path = self._instrumenter.write(out_dir, render_s, extra)
        csv_path = self._instrumenter.write_csv(out_dir)
        if self._verbose:
            print(f"  [diag] {path}")
            print(f"  [diag] {csv_path}")
            print(f"  [diversity] {self._diversity.metrics()}")
        return path

    def explain_frame(self, ts: float) -> str:
        return self._instrumenter.explain(ts)

    # ── POST-RENDER: deterministic QA ──────────────────────────────────

    def run_qa(self, video_path: str, timeline_path: Optional[str] = None) -> QAReport:
        report = self._qa.run(video_path, timeline_path)
        if self._verbose:
            for c in report.checks:
                mark = "PASS" if c.passed else "FAIL"
                print(f"  [qa] {mark} {c.name}: {c.detail[:90]}")
        return report

    def qa_gate(self, video_path: str, timeline_path: Optional[str] = None,
                out_dir: Optional[str] = None) -> tuple[bool, dict]:
        """Run QA; returns (allow_render, report_dict). Blocks ONLY objective failures."""
        report = self.run_qa(video_path, timeline_path)
        data = report.to_dict()
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, "qa_report.json"), "w") as f:
                json.dump(data, f, indent=2)
        return (not data["blocking_failures"], data)
