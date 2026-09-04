"""V3 edit-plan builder — wraps planv2 (architecture unchanged), then:

  * injects progressive stage-overlay events (§7) from the visual plan
  * flags captions_v3 (dynamic contrast backing, integrated captions)
  * carries the v3 full-bleed visual rect
"""

from __future__ import annotations

import json
from pathlib import Path


def make_edit_plan_v3(paths, story_id: str):
    from engine import planv2
    eplan, rep = planv2.make_edit_plan_v2(paths, story_id)
    vp = json.loads((Path(paths.stories) / story_id / "visual_plan.json").read_text())
    shots_vp = {}
    for b in vp.get("beats", []):
        for s in b.get("shots", []):
            shots_vp[str(s["shot_id"])] = s

    for shot in eplan.get("shots", []):
        svp = shots_vp.get(str(shot["shot_id"]), {})
        prog = svp.get("progressive")
        if prog:
            dur = float(shot["duration_s"])
            for st in prog.get("stages", []):
                full = Path(paths.build) / "diag_stages" / f"{st['asset']}_full.png"
                if not full.exists():
                    rep["errors"].append(f"{shot['shot_id']}: missing stage {st['asset']}")
                    continue
                shot["events"].append({
                    "t": round(float(st["at"]) * dur, 3),
                    "kind": "stage_overlay",
                    "spec": {"png": str(full), "asset": st["asset"]},
                })
            shot["events"].sort(key=lambda e: e["t"])
        if svp.get("stage_chips"):
            shot.setdefault("events", [])
            cdur = float(shot["duration_s"])
            for ch in svp["stage_chips"]:
                png = Path(paths.build) / "diag_stages" / f"{ch['asset']}_full.png"
                if not png.exists():
                    rep["errors"].append(f"{shot['shot_id']}: missing chip {ch['asset']}")
                    continue
                shot["events"].append({
                    "t": round(float(ch["at"]) * cdur, 3),
                    "kind": "stage_overlay",
                    "spec": {"png": str(png), "asset": ch["asset"]},
                })
            shot["events"].sort(key=lambda e: e["t"])
        if svp.get("end_card"):
            shot["end_card"] = svp["end_card"]

    eplan["engine"] = "v3"
    eplan["captions_v3"] = True
    eplan["visual_rect"] = [0, 176, 1080, 1744]
    out = Path(paths.build) / "edit_plan.json"
    out.write_text(json.dumps(eplan, indent=2) + "\n")
    return eplan, rep
