"""V4 edit-plan wrapper — planv3 + per-shot chrome/role/purpose fields +
subtitle hierarchy levels. Additive; v2/v3 stories unaffected."""

from __future__ import annotations

import json
import re
from pathlib import Path

_PASS_THROUGH = ("chrome", "role", "purpose", "claim", "evidence",
                 "motion_reason", "transition_reason", "chapter_title",
                 # V5 creative-director fields (§1/§5/§8/§12/§13)
                 "visual_mode", "evidence_type", "evidence_justification",
                 "motion_type", "subject_contract", "one_second")

_MARK = re.compile(r"\*([^*]+)\*")


def _cue_level(text: str, beat_function: str) -> int:
    """Subtitle hierarchy (§9): 1 normal, 2 important fact, 3 revelation."""
    marked = bool(_MARK.search(text)) or bool(re.search(r"\d", text))
    if beat_function in ("REVEAL", "PAYOFF") and marked:
        return 3
    if marked or beat_function == "TWIST":
        return 2
    return 1


def make_edit_plan_v4(paths, story_id: str):
    from engine import planv3
    eplan, rep = planv3.make_edit_plan_v3(paths, story_id)
    vp = json.loads((Path(paths.stories) / story_id / "visual_plan.json").read_text())
    shots_vp = {}
    for b in vp.get("beats", []):
        for s in b.get("shots", []):
            shots_vp[str(s["shot_id"])] = s
    story = json.loads((Path(paths.stories) / story_id / "story.json").read_text())
    beat_fn = {b.get("beat_id"): str(b.get("function", "")).upper()
               for b in story.get("beats", [])}
    beat_of = {}
    for b in vp.get("beats", []):
        for s in b.get("shots", []):
            beat_of[str(s["shot_id"])] = b.get("beat_id")

    for shot in eplan.get("shots", []):
        svp = shots_vp.get(str(shot["shot_id"]), {})
        for k in _PASS_THROUGH:
            if k in svp:
                shot[k] = svp[k]
        fn = beat_fn.get(beat_of.get(str(shot["shot_id"])), "")
        for cue in shot.get("captions", []) or []:
            cue["level"] = _cue_level(cue.get("text", ""), fn)

    eplan["engine"] = "v4"
    out = Path(paths.build) / "edit_plan.json"
    out.write_text(json.dumps(eplan, indent=2) + "\n")
    return eplan, rep
