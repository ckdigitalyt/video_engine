"""Illustrated-documentary engine (1080x1920@30, ffmpeg-only, deterministic).

Artifact flow:
  story.json + visual_plan.json
      -> plan.validate / plan.make_edit_plan -> build/edit_plan.json
      -> compose.render_shot (per shot: zoompan camera + Pillow overlay PNGs
         + .ass captions via text_ass) -> build/shots/<shot_id>.mp4
      -> compose.render_video (transition concat + optional loudnorm audio)
      -> output/final.mp4
      -> qa.qa_video -> build/qa/qa.json + qa/contact_sheet.jpg

Locked frame layout (1080x1920@30):
  black canvas | title band y=120..440 | artwork panel y=460..1240 (1080x780)
  caption zone y=1240..1580 | footer y>1580 empty black.
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.2.0"


class Paths:
    """Filesystem layout. All roots overridable so smoke/qa can run in a sandbox."""

    def __init__(self, root=None, assets_dir=None, build_dir=None,
                 overlays_dir=None, output_dir=None):
        self.root = Path(root) if root else Path(__file__).resolve().parent.parent
        self.assets = Path(assets_dir) if assets_dir else self.root / "assets"
        self.build = Path(build_dir) if build_dir else self.root / "build"
        self.overlays = Path(overlays_dir) if overlays_dir else self.root / "build" / "overlays"
        self.output = Path(output_dir) if output_dir else self.root / "output"
        self.shots = self.build / "shots"
        self.ass = self.build / "ass"
        self.qa = self.build / "qa"
        self.fonts = self.root / "assets" / "fonts"
        self.templates = self.root / "templates"
        self.stories = self.root / "stories"

    def ensure_dirs(self):
        for p in (self.assets, self.build, self.overlays, self.output,
                  self.shots, self.ass, self.qa):
            p.mkdir(parents=True, exist_ok=True)
        return self
