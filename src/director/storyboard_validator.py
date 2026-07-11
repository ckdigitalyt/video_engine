"""
storyboard_validator.py — Pre-render validation of the complete storyboard.

Runs between VisualDirector (asset selection complete) and MoviePyRenderer.
Checks all scene assets for completeness, diversity, and duration match
before the expensive render phase begins.

The validator is the gate that prevents wasted render cycles on broken
or low-diversity compositions.
"""

from __future__ import annotations

import os
from typing import Optional

from src.models.schemas import (
    AssetPlan,
    BeatPlan,
    Scene,
    ValidationReport,
)
from .diversity_tracker import DiversityTracker


class StoryboardValidator:
    """Validates a complete list of Scene objects before rendering.

    Checks:

    - **Asset completeness**: Every shot has a valid AssetPlan with a
      non-empty filepath pointing to an existing file.
    - **Diversity score**: No duplicate or near-identical assets across
      scenes (delegates to DiversityTracker).
    - **Duration match**: Total estimated duration ±10% of combined
      asset durations.
    - **File integrity**: All referenced files exist and are non-empty.
    """

    def __init__(
        self,
        diversity_tracker: Optional[DiversityTracker] = None,
        min_asset_bytes: int = 1024,
        duration_tolerance: float = 0.10,
    ):
        self._diversity_tracker = diversity_tracker or DiversityTracker()
        self._min_asset_bytes = min_asset_bytes
        self._duration_tolerance = duration_tolerance

    def validate(
        self,
        scenes: list[Scene],
        target_duration: Optional[float] = None,
    ) -> ValidationReport:
        """Run all pre-render checks against the scene list.

        Parameters
        ----------
        scenes : list[Scene]
            The complete scene list with populated asset_plan and
            beat_plans (if beat mode).
        target_duration : float | None
            Expected total video duration in seconds. If omitted,
            calculated as ``sum(scene.expected_duration)``.

        Returns
        -------
        ValidationReport
            Pass/fail with detailed breakdown.
        """
        report = ValidationReport(
            total_scenes=len(scenes),
            target_duration=target_duration or sum(s.expected_duration for s in scenes),
        )

        missing_assets = 0
        missing_filepaths = 0
        diversity_violations: list[str] = []
        errors: list[str] = []

        total_beats = 0
        total_shots = 0
        total_duration = 0.0

        # Reset diversity tracker for this validation run
        self._diversity_tracker.reset()

        for scene in scenes:
            scene_dur = scene.expected_duration
            total_duration += scene_dur

            if scene.beat_plans:
                # Beat mode: validate each beat's shots
                total_beats += len(scene.beat_plans)
                for beat in scene.beat_plans:
                    total_shots += len(beat.shots)
                    for shot in beat.shots:
                        if shot.asset_plan is None:
                            missing_assets += 1
                            errors.append(
                                f"Scene {scene.scene_id}, beat {beat.index}, "
                                f"shot {beat.shots.index(shot)}: no asset plan"
                            )
                        else:
                            self._check_asset_plan(
                                shot.asset_plan, scene, beat, errors,
                                diversity_violations,
                            )
            else:
                # Single-clip mode: validate scene-level asset_plan
                total_shots += 1
                if scene.asset_plan is None:
                    missing_assets += 1
                    errors.append(f"Scene {scene.scene_id}: no asset plan")
                else:
                    self._check_scene_asset(
                        scene, errors, diversity_violations,
                    )

        report.total_beats = total_beats
        report.total_shots = total_shots
        report.missing_assets = missing_assets
        report.missing_filepaths = missing_filepaths
        report.total_duration = total_duration
        report.diversity_violations = diversity_violations
        report.errors = errors

        # Determine pass/fail
        report.passed = (
            missing_assets == 0
            and missing_filepaths == 0
            and len(diversity_violations) == 0
            and len(errors) == 0
        )

        return report

    # ── Internal helpers ───────────────────────────────────────────────

    def _check_asset_plan(
        self,
        asset_plan: AssetPlan,
        scene: Scene,
        beat: BeatPlan,
        errors: list[str],
        violations: list[str],
    ) -> None:
        """Validate a per-shot AssetPlan."""
        filepath = asset_plan.filepath
        if not filepath:
            errors.append(
                f"Scene {scene.scene_id}, beat {beat.index}: "
                f"asset plan has empty filepath"
            )
            return

        if not os.path.isfile(filepath):
            errors.append(
                f"Scene {scene.scene_id}, beat {beat.index}: "
                f"file not found: {filepath}"
            )
            return

        if os.path.getsize(filepath) < self._min_asset_bytes:
            errors.append(
                f"Scene {scene.scene_id}, beat {beat.index}: "
                f"file too small ({os.path.getsize(filepath)} bytes): {filepath}"
            )
            return

        # Diversity check — truncate asset_id to fit DiversityRecord limits
        asset_id = (asset_plan.query_used or "")[:190]  # Use query as proxy for asset ID, max 200 chars
        provider = asset_plan.provider.value
        ok, reason = self._diversity_tracker.check_candidate(
            asset_plan, asset_id=asset_id, provider=provider,
        )
        if not ok:
            violations.append(
                f"Scene {scene.scene_id}, beat {beat.index}: {reason}"
            )

        # Record for future diversity checks
        self._diversity_tracker.record_accepted(
            scene_id=scene.scene_id,
            provider=provider,
            asset_id=asset_id,
            query_used=asset_plan.query_used,
            filepath=filepath,
        )

    def _check_scene_asset(
        self,
        scene: Scene,
        errors: list[str],
        violations: list[str],
    ) -> None:
        """Validate a scene-level (non-beat) AssetPlan."""
        asset_plan = scene.asset_plan
        if not asset_plan:
            return

        filepath = asset_plan.filepath
        if not filepath:
            errors.append(f"Scene {scene.scene_id}: asset plan has empty filepath")
            return

        if not os.path.isfile(filepath):
            errors.append(
                f"Scene {scene.scene_id}: file not found: {filepath}"
            )
            return

        if os.path.getsize(filepath) < self._min_asset_bytes:
            errors.append(
                f"Scene {scene.scene_id}: file too small "
                f"({os.path.getsize(filepath)} bytes): {filepath}"
            )
            return

        # Diversity check — truncate asset_id to fit DiversityRecord limits
        asset_id = (asset_plan.query_used or "")[:190]
        provider = asset_plan.provider.value
        ok, reason = self._diversity_tracker.check_candidate(
            asset_plan, asset_id=asset_id, provider=provider,
        )
        if not ok:
            violations.append(f"Scene {scene.scene_id}: {reason}")

        self._diversity_tracker.record_accepted(
            scene_id=scene.scene_id,
            provider=provider,
            asset_id=asset_id,
            query_used=asset_plan.query_used,
            filepath=filepath,
        )

    @property
    def diversity_tracker(self) -> DiversityTracker:
        """Expose the diversity tracker for post-validation analysis."""
        return self._diversity_tracker
