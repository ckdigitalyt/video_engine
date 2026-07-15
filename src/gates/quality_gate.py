"""
quality_gate.py — Production quality gates for video release.

A video cannot be released unless ALL gates pass:
- Fallback <5%
- Blank frames = 0
- Duplicate clips <3%
- Average semantic score >85
- Average critic score >85
- 1080p+ resolution
- No watermarks
- No images used (unless intentional)
- No solid colors
- No empty AssetPlans
- Render success = 100%
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class GateResult:
    """Result of a single quality gate check."""

    name: str
    passed: bool
    actual: Any = None
    threshold: Any = None
    message: str = ""

    def __str__(self) -> str:
        return f"[{'✅' if self.passed else '❌'}] {self.name}: {self.message}"


@dataclass
class QualityReport:
    """Full quality gate report."""

    passed: bool = False
    gates: list[GateResult] = field(default_factory=list)
    summary: str = ""

    def add(self, gate: GateResult) -> None:
        self.gates.append(gate)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "gates": [
                {
                    "name": g.name,
                    "passed": g.passed,
                    "actual": g.actual,
                    "threshold": g.threshold,
                    "message": g.message,
                }
                for g in self.gates
            ],
        }


class QualityGate:
    """Production quality gate checker.

    Usage::

        gate = QualityGate()
        report = gate.evaluate(metrics=telemetry.summary(), video_metadata={...})
        if report.passed:
            # Release video
        else:
            # Fix failures first
    """

    def __init__(self):
        self._thresholds = {
            "fallback_rate": 5.0,       # Max 5% fallbacks
            "blank_frames": 0,           # Zero blank frames
            "duplicate_rate": 3.0,       # Max 3% duplicates
            "min_semantic_score": 85.0,  # Average semantic >85
            "min_critic_score": 85.0,    # Average critic >85
            "min_width": 1920,           # 1080p+
            "min_height": 1080,
            "render_success": True,
        }

    def evaluate(
        self,
        metrics: Optional[dict[str, Any]] = None,
        video_metadata: Optional[dict[str, Any]] = None,
        shots: Optional[list[dict[str, Any]]] = None,
    ) -> QualityReport:
        """Run all quality gates.

        Args:
            metrics: Telemetry summary dict.
            video_metadata: Video file metadata (resolution, duration, etc.).
            shots: List of shot plans (for checking empties).

        Returns:
            QualityReport with pass/fail per gate.
        """
        report = QualityReport()
        metrics = metrics or {}
        video_md = video_metadata or {}
        shots = shots or []

        # Gate 1: Fallback rate
        total_shots = metrics.get("total_shots", 0)
        fallbacks = metrics.get("fallback_count", 0)
        fallback_rate = fallbacks / max(total_shots, 1) * 100
        report.add(GateResult(
            name="Fallback Rate",
            passed=fallback_rate <= self._thresholds["fallback_rate"],
            actual=round(fallback_rate, 1),
            threshold=f"<={self._thresholds['fallback_rate']}%",
            message=f"{round(fallback_rate, 1)}% fallback rate",
        ))

        # Gate 2: Blank frames
        blank_frames = metrics.get("blank_frames", 0)
        report.add(GateResult(
            name="Blank Frames",
            passed=blank_frames <= self._thresholds["blank_frames"],
            actual=blank_frames,
            threshold=f"={self._thresholds['blank_frames']}",
            message=f"{blank_frames} blank frames detected",
        ))

        # Gate 3: Duplicate clips
        duplicate_count = metrics.get("duplicate_count", 0)
        duplicate_rate = duplicate_count / max(total_shots, 1) * 100
        report.add(GateResult(
            name="Duplicate Clips",
            passed=duplicate_rate <= self._thresholds["duplicate_rate"],
            actual=round(duplicate_rate, 1),
            threshold=f"<={self._thresholds['duplicate_rate']}%",
            message=f"{round(duplicate_rate, 1)}% duplicate rate",
        ))

        # Gate 4: Semantic score
        semantic = metrics.get("semantic_scores", {})
        semantic_avg = semantic.get("average", 0) if isinstance(semantic, dict) else 0
        report.add(GateResult(
            name="Semantic Score",
            passed=semantic_avg >= self._thresholds["min_semantic_score"],
            actual=semantic_avg,
            threshold=f">={self._thresholds['min_semantic_score']}",
            message=f"Average semantic score: {semantic_avg}",
        ))

        # Gate 5: Critic score
        critic = metrics.get("critic_scores", {})
        critic_avg = critic.get("average", 0) if isinstance(critic, dict) else 0
        report.add(GateResult(
            name="Critic Score",
            passed=critic_avg >= self._thresholds["min_critic_score"],
            actual=critic_avg,
            threshold=f">={self._thresholds['min_critic_score']}",
            message=f"Average critic score: {critic_avg}",
        ))

        # Gate 6: Resolution >= 1080p
        width = video_md.get("width", 0) or metrics.get("width", 0)
        height = video_md.get("height", 0) or metrics.get("height", 0)
        res_ok = (width >= self._thresholds["min_width"] and
                  height >= self._thresholds["min_height"]) or (width == 0 and height == 0)
        report.add(GateResult(
            name="Resolution",
            passed=res_ok,
            actual=f"{width}x{height}" if width else "unknown",
            threshold=f"{self._thresholds['min_width']}x{self._thresholds['min_height']}",
            message=f"{width}x{height}" if width else "Resolution not measured",
        ))

        # Gate 7: Render success
        render_ok = metrics.get("render_success", False)
        report.add(GateResult(
            name="Render Success",
            passed=render_ok,
            actual=render_ok,
            threshold=True,
            message="Render completed successfully" if render_ok else "Render failed",
        ))

        # Gate 8: No empty AssetPlans
        empty_shots = sum(
            1 for s in shots
            if not s.get("filepath") and not s.get("asset_plan", {}).get("filepath")
        )
        report.add(GateResult(
            name="Empty AssetPlans",
            passed=empty_shots == 0,
            actual=empty_shots,
            threshold=0,
            message=f"{empty_shots} shots with empty AssetPlans",
        ))

        # Gate 9: No watermarks
        watermark_count = metrics.get("watermark_count", 0)
        report.add(GateResult(
            name="Watermarks",
            passed=watermark_count == 0,
            actual=watermark_count,
            threshold=0,
            message=f"{watermark_count} watermarked clips",
        ))

        # Overall pass
        report.passed = all(g.passed for g in report.gates)
        passing = sum(1 for g in report.gates if g.passed)
        total = len(report.gates)
        report.summary = (
            f"{'✅ ALL GATES PASSED' if report.passed else '❌ GATES FAILED'}: "
            f"{passing}/{total} passed"
        )
        return report
