"""
planner.py — ManimPlanner for generating scientific animations.

When stock footage cannot adequately visualize a scientific concept (black holes,
redshift, Drake equation, spacetime curvature, etc.), the ManimPlanner generates
custom animation scripts and renders them.

Topics suitable for Manim:
- Fermi paradox / Drake equation
- Black hole geometry / gravitational lensing
- Redshift / light bending
- Big Bang timeline
- Solar system / exoplanet orbits
- Galaxy formation
- Gravitational waves
- Data visualizations (graphs, charts, equations)
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from src.providers.factory import ProviderFactory
from src.providers.llm_provider import LLMProvider


# ═══════════════════════════════════════════════════════════════════════════
# Types
# ═══════════════════════════════════════════════════════════════════════════

class ManimTopic(str, Enum):
    FERMI_PARADOX = "fermi_paradox"
    DRAKE_EQUATION = "drake_equation"
    BLACK_HOLE_GEOMETRY = "black_hole_geometry"
    LIGHT_BENDING = "light_bending"
    REDSHIFT = "redshift"
    BIG_BANG_TIMELINE = "big_bang_timeline"
    SOLAR_SYSTEM = "solar_system"
    EXOPLANETS = "exoplanets"
    GALAXY_FORMATION = "galaxy_formation"
    GRAVITATIONAL_WAVES = "gravitational_waves"
    NEURAL_NETWORKS = "neural_networks"
    DNA = "dna"
    EVOLUTION = "evolution"
    CLIMATE = "climate"
    TIMELINE = "timeline"
    DATA_VISUALIZATION = "data_visualization"
    EQUATION = "equation"
    ORBIT_SIMULATION = "orbit_simulation"
    CUSTOM = "custom"


@dataclass
class ManimPlan:
    """Plan for generating a Manim animation."""

    topic: ManimTopic
    script_path: str = ""
    output_path: str = ""
    duration: float = 10.0
    prompt: str = ""
    resolution: str = "1920x1080"
    quality: str = "medium"  # low, medium, high

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic.value,
            "script_path": self.script_path,
            "output_path": self.output_path,
            "duration": self.duration,
            "prompt": self.prompt[:100],
            "resolution": self.resolution,
            "quality": self.quality,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Default scripts (simple cases we can generate without LLM)
# ═══════════════════════════════════════════════════════════════════════════

_DEFAULT_SCRIPTS = {
    ManimTopic.DRAKE_EQUATION: """
from manim import *

class DrakeEquation(Scene):
    def construct(self):
        title = Text("Drake Equation", font_size=48)
        self.play(Write(title))
        self.wait(0.5)
        self.play(title.animate.to_edge(UP))

        equation = MathTex(
            "N = R^* \\times f_p \\times n_e \\times f_l \\times f_i \\times f_c \\times L",
            font_size=36
        )
        self.play(Write(equation))
        self.wait(2)

        labels = VGroup(
            Tex("R* = Star formation rate", font_size=28),
            Tex("fp = Planets with life", font_size=28),
            Tex("ne = Habitable planets", font_size=28),
            Tex("fl = Life develops", font_size=28),
            Tex("fi = Intelligent life", font_size=28),
            Tex("fc = Communicates", font_size=28),
            Tex("L = Civilization lifetime", font_size=28),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.2)
        labels.next_to(equation, DOWN, buff=0.5)

        self.play(Write(labels))
        self.wait(2)
""",
    ManimTopic.BLACK_HOLE_GEOMETRY: """
from manim import *

class BlackHoleGeometry(Scene):
    def construct(self):
        title = Text("Black Hole Spacetime", font_size=48)
        self.play(Write(title))
        self.wait(1)
        self.play(title.animate.to_edge(UP))

        # Draw a simple 2D spacetime grid
        grid = NumberPlane(
            x_range=[-7, 7, 1],
            y_range=[-5, 5, 1],
            background_line_style={
                "stroke_color": BLUE_D,
                "stroke_width": 1,
                "stroke_opacity": 0.3,
            },
        )
        self.play(Create(grid), run_time=2)

        # Create a black hole
        hole = Circle(radius=0.5, color=BLACK, fill_opacity=1, stroke_color=YELLOW)
        hole.move_to(ORIGIN)
        self.play(FadeIn(hole))

        # Event horizon label
        label = Text("Event Horizon", font_size=24, color=YELLOW)
        label.next_to(hole, DOWN, buff=0.3)
        self.play(Write(label))
        self.wait(2)
""",
    ManimTopic.REDSHIFT: """
from manim import *

class Redshift(Scene):
    def construct(self):
        title = Text("Cosmological Redshift", font_size=48)
        self.play(Write(title))
        self.wait(1)
        self.play(title.animate.to_edge(UP))

        # Light waves stretching
        def create_wave(color, offset=0):
            wave = ParametricFunction(
                lambda t: np.array([t, 0.5 * np.sin(2 * np.pi * (t - offset)), 0]),
                t_range=[-5, 5],
                color=color,
                stroke_width=3,
            )
            return wave

        wave_blue = create_wave(BLUE, 0)
        wave_red = create_wave(RED, 2)

        wave_blue.next_to(ORIGIN, UP, buff=1)
        wave_red.next_to(ORIGIN, DOWN, buff=1)

        blue_label = Text("Emitted (Blue)", font_size=24, color=BLUE)
        blue_label.next_to(wave_blue, LEFT)
        red_label = Text("Observed (Red)", font_size=24, color=RED)
        red_label.next_to(wave_red, LEFT)

        self.play(
            Create(wave_blue), Write(blue_label),
            Create(wave_red), Write(red_label),
        )
        self.wait(2)
""",
}


class ManimPlanner:
    """Plan and optionally generate Manim animations for scientific topics.

    Usage::

        planner = ManimPlanner()
        plan = planner.plan(topic=ManimTopic.DRAKE_EQUATION)
        if plan.script_path:
            output = planner.render(plan)
    """

    def __init__(self, output_dir: str = "cache/manim", provider: Optional[LLMProvider] = None):
        self._output_dir = output_dir
        os.makedirs(self._output_dir, exist_ok=True)
        factory = ProviderFactory()
        self._provider = provider or factory.get_llm_provider_for_role("planner")

    # ── Public API ─────────────────────────────────────────────────────

    def plan(self, topic: ManimTopic, custom_prompt: str = "") -> ManimPlan:
        """Create a ManimPlan for a given topic.

        If the topic has a default script, uses it.
        Otherwise attempts LLM generation.
        """
        # Determine if this topic has a default script
        if topic in _DEFAULT_SCRIPTS:
            plan = ManimPlan(topic=topic, prompt=topic.value)
            script_path = self._write_script(plan)
            plan.script_path = script_path
            return plan

        # For custom/unknown topics, use LLM
        if custom_prompt:
            script = self._generate_script(custom_prompt)
            if script:
                plan = ManimPlan(topic=topic, prompt=custom_prompt)
                plan.script_path = self._write_script(plan, content=script)
                return plan

        return ManimPlan(topic=topic)

    def render(self, plan: ManimPlan) -> Optional[str]:
        """Render a ManimPlan to video.

        Returns output filepath on success, None on failure.
        Requires manim to be installed.
        """
        if not plan.script_path or not os.path.exists(plan.script_path):
            print(f"[ManimPlanner] No script to render for {plan.topic.value}")
            return None

        output_name = os.path.splitext(os.path.basename(plan.script_path))[0]
        output_path = os.path.join(self._output_dir, f"{output_name}.mp4")

        # Check if already rendered (cached)
        if os.path.exists(output_path):
            print(f"[ManimPlanner] Using cached render: {output_path}")
            plan.output_path = output_path
            return output_path

        cmd = [
            "manim",
            "-qh" if plan.quality == "high" else "-qm",
            "-r", plan.resolution,
            "-o", output_path,
            plan.script_path,
            output_name,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0 and os.path.exists(output_path):
                plan.output_path = output_path
                print(f"[ManimPlanner] Rendered: {output_path}")
                return output_path
            else:
                print(f"[ManimPlanner] Render failed: {result.stderr[:200]}")
                return None
        except FileNotFoundError:
            print("[ManimPlanner] manim not installed. Skipping.")
            return None
        except subprocess.TimeoutExpired:
            print("[ManimPlanner] manim render timed out")
            return None

    def is_render_available(self) -> bool:
        """Check if manim is installed on this system."""
        try:
            subprocess.run(["manim", "--version"], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def score_for_topic(self, topic: str) -> float:
        """Score how well a topic maps to Manim (0-1)."""
        topic_lower = topic.lower()
        manim_keywords = {
            "equation", "graph", "chart", "diagram", "simulation",
            "timeline", "orbit", "geometry", "wavelength", "spectrum",
            "quantum", "relativity", "gravity", "curvature", "black hole",
            "redshift", "big bang", "evolution", "neural network",
        }
        matches = sum(1 for kw in manim_keywords if kw in topic_lower)
        score = min(matches / 3.0, 1.0)
        return score

    # ── Internal ───────────────────────────────────────────────────────

    def _write_script(self, plan: ManimPlan, content: str = "") -> str:
        """Write the Manim Python script to disk."""
        script_content = content or _DEFAULT_SCRIPTS.get(plan.topic, "")
        if not script_content:
            return ""

        safe_name = plan.topic.value.replace(" ", "_").lower()
        script_path = os.path.join(self._output_dir, f"{safe_name}.py")
        with open(script_path, "w") as f:
            f.write(script_content)
        return script_path

    def _generate_script(self, prompt: str) -> str:
        """Use LLM to generate a Manim script from a description."""
        system = """You generate Manim (Mathematical Animation Engine) Python scripts.
The script must be a valid, runnable Python file that defines a Scene subclass.
Use only basic shapes, text, and simple animations. Keep it under 50 lines.
Import: from manim import *
"""

        user = f"Create a Manim animation for: {prompt}"
        try:
            response = self._provider.llm_complete(
                system=system,
                prompt=user,
                temperature=0.4,
                max_tokens=1000,
            )
            # Extract code block
            if "```python" in response:
                response = response.split("```python")[1]
                if "```" in response:
                    response = response.split("```")[0]
            elif "```" in response:
                response = response.split("```")[1]
                if "```" in response:
                    response = response.split("```")[0]
            return response.strip()
        except Exception as e:
            print(f"[ManimPlanner] Script generation failed: {e}")
            return ""
