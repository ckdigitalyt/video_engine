"""V4 QA — three-axis + editorial intelligence + factual integrity.

Extends the V3 groups with:
    information_velocity       (gate >= 80)
    narration_visual_alignment (gate >= 80)
    information_density        (gate >= 75, diagram assets)
    factual_verification       (P0 — must PASS)
    hook_strength / payoff_strength (editorial)
    human-editor test          (§14, 8 questions per shot)

Publication gate v4: numeric gates AND factual PASS AND no P0. Numeric QA
never auto-declares publishable — the report always carries TOP 3
HUMAN-EDITOR CONCERNS next to CAN_PUBLISH (§15/§16).
"""

from __future__ import annotations

import json
from pathlib import Path

from engine import alignment, density, editorial, facts, velocity

GATES_V4 = {
    "TECHNICAL": 95.0, "VISUAL": 80.0, "EDITORIAL": 80.0,
    "INFORMATION_VELOCITY": 80.0, "NARRATION_VISUAL_ALIGNMENT": 80.0,
    "INFORMATION_DENSITY": 75.0,
}


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text()) if Path(path).exists() else {}


def _hook_strength(story: dict, plan: dict) -> tuple:
    shots = plan.get("shots", [])
    ret = editorial.validate_retention_structure(story)
    first = shots[0] if shots else {}
    ok = ret["ok"] and first.get("opening") and float(first.get("duration_s", 99)) <= 7.5
    detail = f"retention_ok={ret['ok']} opening={bool(first.get('opening'))} first_dur={first.get('duration_s')}"
    return (100.0 if ok else 55.0), detail


def _payoff_strength(story: dict, plan: dict) -> tuple:
    shots = plan.get("shots", [])
    last = shots[-1] if shots else {}
    beats = story.get("beats", [])
    last_beat = beats[-1] if beats else {}
    text = (last_beat.get("narration") or "").lower()
    fns = editorial.beat_functions(story)
    is_payoff = fns.get(last_beat.get("beat_id")) == "PAYOFF"
    has_endcard = bool(last.get("end_card"))
    has_number = any(c.isdigit() for c in text)
    mem_words = ("not ", "never", "still", "out there", "remember", "hiding", "secret")
    has_memorable = any(w in text for w in mem_words) or has_number
    ok = is_payoff and has_endcard and has_memorable
    detail = f"payoff={is_payoff} endcard={has_endcard} memorable={has_memorable}"
    return (100.0 if ok else 55.0), detail


def _density_checks(story_dir: Path, build_dir: Path) -> tuple:
    """Score the FINAL stage of every v4 staged diagram (intermediate stages
    are intentionally sparse; their pacing is judged by velocity, not density)."""
    man_p = Path(build_dir) / "diag_stages" / "manifest_v4.json"
    scores, rows = [], []
    if man_p.exists():
        man = json.loads(man_p.read_text())
        assets_dir = Path(build_dir).parent / "assets"
        for name, stages in man.items():
            if not stages:
                continue
            if stages[-1].get("kind", "diagram") != "diagram":
                continue          # annotation overlays: plate stays visible,
                                  # near-empty by design -> not density-scored
            p2 = assets_dir / f"{stages[-1]['asset']}.png"
            if not p2.exists():
                continue
            from PIL import Image as _PILImage
            m = density.diagram_density(_PILImage.open(p2))
            scores.append(m["score"])
            rows.append({"asset": p2.name, **m})
    mean = round(sum(scores) / max(1, len(scores)), 1)
    return mean, rows


def run_qa4(video_path: Path, story_dir: Path, build_dir: Path = None) -> dict:
    story_dir = Path(story_dir)
    video_path = Path(video_path)
    build_dir = Path(build_dir or "build")
    qa2 = _load(build_dir / "qa" / "qa2.json")
    continuity = _load(build_dir / "continuity.json")
    style = _load(build_dir / "style_continuity.json")
    phone = _load(build_dir / "phone_qa.json")
    raster = _load(build_dir / "raster_text_qa.json")
    plan = _load(build_dir / "edit_plan.json")
    story = _load(story_dir / "story.json")
    vp = _load(story_dir / "visual_plan.json")

    # ---- reuse v3 group builders ----
    from engine import qa3
    t = qa3._tech_checks(qa2)
    v = qa3._visual_checks(qa2, continuity, style, phone, raster)
    e = qa3._editorial_checks(story, plan)
    e.add("retention_structure", 100.0 if editorial.validate_retention_structure(story)["ok"] else 50.0,
          "beat functions HOOK..PAYOFF")
    hs, hs_d = _hook_strength(story, plan)
    e.add("hook_strength", hs, hs_d)
    ps, ps_d = _payoff_strength(story, plan)
    e.add("payoff_strength", ps, ps_d)

    # ---- factual integrity (P0) ----
    fact = facts.verify_story(story_dir)
    e.add("factual_verification", 100.0 if fact["ok"] else 0.0,
          f"{fact['facts_count']} verified claims; uncovered={len(fact['uncovered'])}",
          p0=not fact["ok"])

    # ---- v4 metrics ----
    purpose_map = editorial.shot_purpose_map(story, vp)
    total = sum(float(s.get("duration_s", 0)) for s in plan.get("shots", []))
    iv = velocity.information_velocity(purpose_map, plan.get("shots", []), total)
    al = alignment.narration_visual_alignment(purpose_map, plan.get("shots", []), story)
    dmean, drows = _density_checks(story_dir, build_dir)

    he = editorial.human_editor_test(purpose_map, al, drows, iv)

    # ---- role-aware thresholds (§7): per-role palette bars, not one bar ----
    shot_by_asset = {}
    for s2 in plan.get("shots", []):
        a2 = str(s2.get("asset", ""))
        if a2 and a2 not in shot_by_asset:
            shot_by_asset[a2] = str(s2.get("role", "")).upper()
    role_rows = []
    for ca in continuity.get("assets", []):
        if ca.get("programmatic"):
            continue
        base = str(ca.get("file", "")).replace(".png", "")
        role = shot_by_asset.get(base, "")
        thr = float(editorial.ROLE_THRESHOLDS.get(role, {}).get("palette", 0.55))
        sc = float(ca.get("score_after") or 0.0)
        role_rows.append({"asset": base, "role": role, "palette": round(sc, 3),
                          "threshold": thr, "ok": bool(sc >= thr)})
    role_ok = all(r["ok"] for r in role_rows) if role_rows else True
    v.add("role_threshold_audit",
          100.0 if role_ok else round(100.0 * sum(1 for r in role_rows if r["ok"]) / len(role_rows), 1),
          "; ".join(f"{r['asset']}({r['role']}) {r['palette']:.2f}<{r['threshold']}"
                    for r in role_rows if not r["ok"]) or "all roles pass")

    # ---- V5 creative-director layer (§19: the only new gate inputs) ----
    from engine import director
    assets_dir = paths_assets(build_dir)
    dplan = director.plan_review(story, vp, plan)

    # §8/§9 subject correctness: vision acceptance on contracted assets
    subj_rows = []
    for b in vp.get("beats", []):
        for s in b.get("shots", []):
            ct = s.get("subject_contract")
            if not ct:
                continue
            ap = assets_dir / f"{s.get('asset', '')}.png"
            if not ap.exists():
                subj_rows.append({"shot_id": s["shot_id"], "asset": s.get("asset"),
                                  "verdict": "MISSING_ASSET", "ok": False,
                                  "via": "static", "depicted": ""})
                continue
            r = director.subject_check(ap, ct)
            r.update({"shot_id": s["shot_id"], "asset": s.get("asset"),
                      "role": str(ct.get("role", ""))})
            subj_rows.append(r)
    subj_fail = [r for r in subj_rows if r.get("verdict") == "FAIL"]
    missing_assets = [r for r in subj_rows if r.get("verdict") == "MISSING_ASSET"]
    subj_score = round(100.0 * sum(1 for r in subj_rows if r.get("verdict") == "PASS")
                       / max(1, len(subj_rows)), 1)

    # §2 one-second comprehension (static over diagram/comparison cards)
    vp_by_id = {str(s["shot_id"]): s for b in vp.get("beats", [])
                for s in b.get("shots", [])}
    oc_rows = []
    for s in plan.get("shots", []):
        vs = vp_by_id.get(str(s["shot_id"]), {})
        mode = str(vs.get("visual_mode", "")).upper()
        if not (mode in director.ONE_SECOND_MODES or vs.get("one_second")):
            continue
        cards = [e["spec"]["png"] for e in s.get("events", [])
                 if e.get("kind") == "stage_overlay"
                 and e.get("spec", {}).get("png")]
        oc_rows.append({"shot_id": s["shot_id"], "mode": mode,
                        **director.one_second_static(vs, cards)})
    oc_mean = round(sum(r["score"] for r in oc_rows) / max(1, len(oc_rows)), 1) \
        if oc_rows else 100.0

    # §20 nine-question review; vision spot-checks on <=3 rendered frames
    frames = _director_frames(video_path, plan, vp_by_id, build_dir)
    review = director.creative_director_review(story, vp, plan,
                                               plate_dir=assets_dir,
                                               sample_frames=frames)
    gate_notes = []
    if subj_fail:  # §8: subject_correctness > style_score, hero failures block
        gate_notes.append("subject FAIL: " + ", ".join(
            f"{r['asset']} ({r.get('depicted', '?')[:60]})" for r in subj_fail))
    if missing_assets:
        gate_notes.append("contracted asset missing: "
                          + ", ".join(r["asset"] for r in missing_assets))
    # §2 gate is aggregate (same pattern as IV/NVA/ID means); per-shot
    # marginals stay in the report rows for disclosure, not a hard veto -
    # the pixel-mass heuristic under-measures typography and multi-color
    # diagram cards (thin strokes split bins), which eye checks clear.
    one_second_marginal = [f"{r['shot_id']} {r['score']:.0f}"
                           for r in oc_rows if r["score"] < 70.0]
    if oc_mean < 70.0:
        gate_notes.append(
            "one-second FAIL: mean {:.0f} < 70".format(oc_mean)
            + (f" (marginal: {', '.join(one_second_marginal)})"
               if one_second_marginal else ""))
    review = dict(review)
    review["gate_notes"] = gate_notes
    review["one_second_marginal"] = one_second_marginal
    if gate_notes:
        review["verdict"] = "FAIL"

    groups = {
        "TECHNICAL": t.as_dict(),
        "VISUAL": v.as_dict(),
        "EDITORIAL": e.as_dict(),
    }
    metrics = {
        "INFORMATION_VELOCITY": {"score": iv["score"], "gate": GATES_V4["INFORMATION_VELOCITY"],
                                 "ok": iv["ok"], "stretches": iv["stretches"]},
        "NARRATION_VISUAL_ALIGNMENT": {"score": al["score"], "gate": GATES_V4["NARRATION_VISUAL_ALIGNMENT"],
                                       "ok": al["ok"]},
        "INFORMATION_DENSITY": {"score": dmean, "gate": GATES_V4["INFORMATION_DENSITY"],
                                "ok": dmean >= GATES_V4["INFORMATION_DENSITY"], "assets": drows},
    }

    p0 = []
    for gname, g in groups.items():
        for c in g["checks"]:
            if c["p0"] and c["score"] < 100:
                p0.append({"group": gname, "check": c["name"], "detail": c["detail"]})

    numeric_ok = (
        groups["TECHNICAL"]["score"] >= GATES_V4["TECHNICAL"]
        and groups["VISUAL"]["score"] >= GATES_V4["VISUAL"]
        and groups["EDITORIAL"]["score"] >= GATES_V4["EDITORIAL"]
        and all(m["ok"] for m in metrics.values())
        and not p0
    )

    # ---- TOP 3 HUMAN-EDITOR CONCERNS (§15: never auto-declared) ----
    concerns = []
    for f in he["flagged"][:3]:
        concerns.append(f"shot {f['shot_id']}: failed {f['no_count']}/8 human-editor questions")
    if not iv["ok"]:
        worst = max(iv["stretches"], key=lambda s: s["t1"] - s["t0"], default=None)
        if worst:
            concerns.append(f"low information velocity {worst['t0']:.0f}-{worst['t1']:.0f}s — stretch without new information")
    low_align = [r["shot_id"] for r in al["shots"] if r["generic_risk"]][:3]
    if low_align:
        concerns.append(f"narration/visual gap in shots {low_align} — concrete claims on generic imagery")
    low_d = [r["asset"] for r in drows if not r["ok"]][:3]
    if low_d:
        concerns.append(f"diagram density issues: {low_d}")
    if review["verdict"] != "PASS":
        for gn in (review.get("gate_notes") or [])[:2]:
            concerns.append(gn)
        for vn in (review.get("vision_notes") or [])[:1]:
            concerns.append(vn)
    if not concerns:
        scored = []
        for gname, g in groups.items():
            for c in g["checks"]:
                if c["score"] < 100:
                    scored.append((c["score"], gname, c["name"], c["detail"]))
        for sc, gname, name, detail in sorted(scored)[:3]:
            concerns.append(f"[{gname}] {name} = {sc:.0f} — {detail[:110]}")
    concerns = concerns[:3]

    out = {
        "video": str(video_path), "story": str(story_dir),
        "groups": groups, "metrics": metrics, "gates": GATES_V4,
        "p0_defects": p0,
        "human_editor": {"rows": he["rows"], "flagged": he["flagged"]},
        "top_3_human_editor_concerns": concerns,
        "director": {
            # §19: subject_correctness + one_second_comprehension + §20 review
            "plan_violations": {"critical": dplan["critical"],
                                "warnings": dplan["warnings"][:12]},
            "subject_correctness": {"score": subj_score, "gate": "100% PASS",
                                    "rows": subj_rows},
            "one_second_comprehension": {"score": oc_mean, "gate": 70.0,
                                         "rows": oc_rows},
            "creative_director_review": review,
        },
        "can_publish_numeric": bool(numeric_ok),
        # §21: numeric gates AND §20 creative-director review = PASS
        "CAN_PUBLISH": bool(numeric_ok and review["verdict"] == "PASS"),
        "publish_note": "V5 §21: CAN_PUBLISH = numeric gates + P0 none + creative_director_review PASS (subject_correctness and one-second gate through the review).",
    }
    (build_dir / "qa" / "qa4.json").write_text(json.dumps(out, indent=2))
    return out


def paths_assets(build_dir: Path) -> Path:
    """Assets dir inferred from the build dir layout (repo/assets)."""
    return Path(build_dir).parent / "assets"


def _director_frames(video_path: Path, plan: dict, vp_by_id: dict,
                     build_dir: Path) -> dict:
    """Extract <=3 frames for §9 vision spot-checks: hero, one diagram,
    payoff. Bounded — vision is an acceptance check, not a metric farm."""
    import subprocess
    out_dir = Path(build_dir) / "qa" / "director_frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    shots = plan.get("shots", [])
    if not shots:
        return {}
    picks, acc = {}, 0.0
    hero_done = diagram_done = payoff_done = False
    for i, s in enumerate(shots):
        sid = str(s["shot_id"])
        dur = float(s.get("duration_s", 0))
        mode = str(vp_by_id.get(sid, {}).get("visual_mode", "")).upper()
        t = None
        if not hero_done and i == 0:
            t, hero_done = acc + min(1.5, dur / 2), True
        elif not diagram_done and mode in ("DIAGRAM", "COMPARISON", "SPLIT",
                                           "TIMELINE", "SCALE",
                                           "TRANSFORMATION"):
            t, diagram_done = acc + dur * 0.75, True
        elif not payoff_done and i == len(shots) - 1:
            t, payoff_done = acc + dur * 0.5, True
        if t is not None:
            fp = out_dir / f"{sid}.png"
            if not fp.exists():
                subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error",
                                "-y", "-ss", f"{t:.2f}", "-i", str(video_path),
                                "-frames:v", "1", str(fp)], check=False)
            if fp.exists():
                picks[sid] = str(fp)
        acc += dur
    return picks
