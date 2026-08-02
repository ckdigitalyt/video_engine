"""
voyager_timeline.py — Manim scene: 1977 → 2026 journey timeline.

Milestones along a horizontal line, each fading in with its year:
  Sep 1977  launch
  1979      Jupiter flyby
  1980      Saturn flyby
  2012      interstellar space
  2026      still calling home

Rendered at 1920x1080 30fps. Used by the stills-first mission pipeline.
"""

from manim import *


class VoyagerTimeline(Scene):
    def construct(self):
        GREY = "#E5E7EB"
        DIM = "#9CA3AF"
        AMBER = "#F59E0B"
        CYAN = "#67E8F9"

        title = Text("FIVE DECADES, ONE MISSION", font_size=32, color=GREY)
        title.to_edge(UP, buff=0.5)
        self.play(FadeIn(title, shift=DOWN * 0.2), run_time=0.8)

        line = Line(LEFT * 5.4, RIGHT * 5.4, stroke_width=2.5, color="#374151")
        line.to_edge(DOWN, buff=2.0)
        self.play(Create(line), run_time=0.8)

        milestones = [
            ("1977", "LAUNCH", -5.4, GREY),
            ("1979", "JUPITER", -2.7, CYAN),
            ("1980", "SATURN", 0.0, CYAN),
            ("2012", "INTERSTELLAR", 2.7, AMBER),
            ("2026", "STILL CALLING", 5.4, AMBER),
        ]

        for year, label, x, color in milestones:
            pos = line.point_from_proportion((x + 5.4) / 10.8)
            dot = Dot(pos, radius=0.12, color=color)
            year_t = Text(year, font_size=26, color=color)
            year_t.next_to(pos, UP, buff=0.45)
            lab_t = Text(label, font_size=16, color=DIM)
            lab_t.next_to(pos, DOWN, buff=0.3)
            ring = Circle(radius=0.25, stroke_color=color, stroke_width=2)
            ring.move_to(pos)
            ring.scale(0.1)
            self.play(
                FadeIn(dot), FadeIn(year_t, shift=UP * 0.1),
                FadeIn(lab_t), FadeIn(ring),
                run_time=0.55,
            )
            self.play(
                ring.animate.scale(2.6).set_opacity(0.15),
                run_time=0.6,
            )
            self.remove(ring)

        closing = Text("THE LONGEST VOYAGE IN HISTORY", font_size=28, color=GREY)
        closing.to_edge(DOWN, buff=1.0)
        self.play(FadeIn(closing, shift=UP * 0.15), run_time=0.9)
        self.wait(1.2)
