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
        "can_publish_numeric": bool(numeric_ok),
        # §15/§16: numeric scores never auto-declare publishable — humans see
        # the concerns next to the flag and decide.
        "CAN_PUBLISH": bool(numeric_ok),
        "publish_note": "CAN_PUBLISH reflects numeric gates + P0 only; review top_3_human_editor_concerns before publishing.",
    }
    (build_dir / "qa" / "qa4.json").write_text(json.dumps(out, indent=2))
    return out


def paths_assets(build_dir: Path) -> Path:
    """Assets dir inferred from the build dir layout (repo/assets)."""
    return Path(build_dir).parent / "assets"
