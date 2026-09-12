"""V11 CAN_PUBLISH rework (Jade_todo_v11 P0) — the publish decision is the
conjunction of EIGHT named components; numeric scores can never override a
false component:

  TECHNICAL          qa5 technical group (>=95 gate, no p0 checks), motion
                     smoothness, audio-continuity, v6.2 completion checks
  FACTUAL            semantic QA (deterministic + exact-wording) — SEMANTIC_PASS
  CAPTION            caption state machine + caption_qa (NEW this run)
  DEBUG_FREE         DEBUG_LEAK_SCAN over drawn text + frames (NEW this run)
  VISUAL_EVIDENCE    evidence/cinematic coverage 80, subject acceptance,
                     CANVAS_OCCUPANCY, EXPLANATORY_MOTION_RATIO (A>C fails)
  VIEWER_SIMULATION  editorial8 viewer-simulation family (0.5s/2s/5s/15s/30s,
                     escalation curve, curiosity ladder, info gain)
  ANTI_TEMPLATE      structural fingerprint (antitemplate verdict) — the
                     editorial7 human-editor test stays a reported diagnostic
                     (it also surfaces through qa5's EDITORIAL group and the
                     top-concerns list; its payoff_70 numeric is advisory-class
                     where editorial8's semantic payoff gate passes)
  AUDIO              bed continuity + audio completion (loudness is
                     normalized at the mix: -14 LUFS / -1.5 dBTP, per qa5)

Any P0 defect (stale/overlapping caption, dev-token leak, confirmed subject
fail, tremble, audio restart, ...) forces CAN_PUBLISH=false regardless of
the numeric editorial/visual scores.
"""
from __future__ import annotations

import json
from pathlib import Path

COMPONENTS = ("TECHNICAL", "FACTUAL", "CAPTION", "DEBUG_FREE",
              "VISUAL_EVIDENCE", "VIEWER_SIMULATION", "ANTI_TEMPLATE",
              "AUDIO")


def run(qa5: dict, qa7: dict, res8: dict, sem: dict, caption_qa: dict,
        leak: dict, occupancy: dict, motion_ratio: dict,
        audio_hier: dict | None = None) -> dict:
    tech = ((qa5 or {}).get("groups") or {}).get("TECHNICAL") or {}
    tech_gate = ((qa5 or {}).get("gates") or {}).get("TECHNICAL", 95.0)
    motion = (qa5 or {}).get("motion") or {}
    audio = (qa5 or {}).get("audio_continuity") or {}
    v62 = (qa5 or {}).get("v62_checks") or {}
    subj = (qa5 or {}).get("subject_recheck") or {}
    # V11 P1b-fix — subject rows that were never verified (vision judge
    # unreachable from the first call => every row UNVERIFIED) must not
    # pass VISUAL_EVIDENCE: the recheck only re-judges FAIL rows, so an
    # all-UNVERIFIED column leaves still_fail empty and slipped through.
    # Rule: subject evidence exists only if at least one row is PASS.
    _sc_rows = (((qa5 or {}).get("director") or {}).get(
        "subject_correctness") or {}).get("rows") or []
    _no_subject_evidence = bool(_sc_rows) and not any(
        str(r.get("verdict", "")).upper() == "PASS" for r in _sc_rows)
    q7g = (qa7 or {}).get("gates") or {}
    g8 = (res8 or {}).get("gates") or {}

    components = {
        "TECHNICAL": bool(
            tech.get("score", 0) >= tech_gate
            and not tech.get("p0_defects")
            and motion.get("ok", False)
            and audio.get("ok", False)
            and all(c.get("ok") for c in v62.values())
        ),
        "FACTUAL": bool((sem or {}).get("SEMANTIC_PASS")),
        "CAPTION": bool((caption_qa or {}).get("CAPTION_PASS")),
        "DEBUG_FREE": bool((leak or {}).get("DEBUG_FREE")),
        "VISUAL_EVIDENCE": bool(
            q7g.get("evidence_cinematic_80", False)
            and not subj.get("still_fail")
            and not _no_subject_evidence
            and (occupancy or {}).get("occupancy_pass", False)
            and (motion_ratio or {}).get("motion_pass", False)
        ),
        "VIEWER_SIMULATION": bool(
            g8.get("viewer_simulation", False)
            and g8.get("escalation_curve", False)
            and g8.get("curiosity_ladder", False)
            and g8.get("info_gain_60", False)
            # V11 P1 §7/§8 — core editorial metrics join the gate:
            # value density + scroll-stop (a MAJOR scroll-stop failure
            # prevents publication, P0 semantics).
            and g8.get("value_density", False)
            and g8.get("scroll_stop", False)
        ),
        "ANTI_TEMPLATE": bool(q7g.get("anti_template", False)),
        # V11 P1 §9 — the AUDIO component adds the hierarchy QA (bed-free
        # silence default honored, no masking, sane dynamic range) on top of
        # continuity + completion.
        "AUDIO": bool(audio.get("ok", False)
                      and (v62.get("audio_completion") or {}).get("ok", False)
                      and ((audio_hier or {}).get("AUDIO_HIERARCHY_PASS", True))),
    }
    reported_diagnostics = {
        "human_editor_gates": q7g.get("human_editor_gates"),
        "editorial7_failed_gates": [k for k, v in q7g.items() if not v],
    }

    p0_defects = []
    if not components["TECHNICAL"]:
        p0_defects += [f"technical:{c}" for c in tech.get("p0_defects", [])]
        if not motion.get("ok", False):
            p0_defects.append("technical:motion_tremble")
        if not audio.get("ok", False):
            p0_defects.append("technical:audio_continuity")
    if not components["CAPTION"]:
        p0_defects += [f"caption:{f.get('rule')}({f.get('shot')})"
                       for f in (caption_qa or {}).get("findings", [])
                       if f.get("severity") == "P0"][:8]
    if not components["DEBUG_FREE"]:
        p0_defects += [f"leak:{h.get('token')}@{h.get('source')}"
                       for h in (leak or {}).get("source_hits", [])][:8]
        if (leak or {}).get("frame_hits"):
            p0_defects.append("leak:frame_text_outside_zones")
    if not components["VISUAL_EVIDENCE"]:
        if subj.get("still_fail"):
            p0_defects.append(f"subject:{subj['still_fail']}")
        if _no_subject_evidence:
            _n_unv = sum(1 for r in _sc_rows
                         if str(r.get("verdict", "")).upper() == "UNVERIFIED")
            p0_defects.append(
                f"subject:no verified subject rows "
                f"({_n_unv}/{len(_sc_rows)} UNVERIFIED — vision judge "
                f"unavailable at QA time; gate not hand-waved)")
        if not (occupancy or {}).get("occupancy_pass", False):
            p0_defects.append("occupancy:" + ",".join(
                (occupancy or {}).get("below_target_undeclared", [])[:6]))
        if not (motion_ratio or {}).get("motion_pass", False):
            p0_defects.append("motion_ratio:A>=C")
    for name in ("FACTUAL", "VIEWER_SIMULATION", "ANTI_TEMPLATE", "AUDIO"):
        if not components[name]:
            p0_defects.append(name.lower())
    if audio_hier is not None and not audio_hier.get("AUDIO_HIERARCHY_PASS", True):
        p0_defects.append("audio_hierarchy:" + ",".join(
            sorted({f.get("rule", "?") for f in audio_hier.get("findings", [])
                    if f.get("severity") == "P0"}))[:60])
    # V11 P1 §8 — scroll-stop MAJOR failures are P0 defects, named
    sstop = (res8 or {}).get("scroll_stop") or {}
    for k in sstop.get("major_failures", []) or []:
        p0_defects.append(f"scroll_stop:{k}")
    # V11 P1 §7 — thin value density is named too
    if not (res8 or {}).get("gates", {}).get("value_density", True):
        p0_defects.append("value_density:" + json.dumps(
            (res8.get("value_density") or {}).get("weak_intervals", []))[:80])

    can_publish = all(components[c] for c in COMPONENTS)
    return {
        "schema": "v11.publish_gate/1.0",
        "components": components,
        "reported_diagnostics": reported_diagnostics,
        "CAN_PUBLISH": bool(can_publish),
        "p0_defects": p0_defects,
        "note": ("CAN_PUBLISH = AND of 8 named components; numeric scores do "
                 "not override a false component (Jade_todo_v11 P0)"),
    }


def write_report(res: dict, out_dir: Path, story_id: str = "") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / (f"publish_gate_{story_id}.json" if story_id
                   else "publish_gate.json")
    p.write_text(json.dumps(res, indent=1) + "\n")
    return p
