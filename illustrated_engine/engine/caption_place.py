"""V11 P1 §5 — adaptive caption placement (Jade_todo_v11).

P0 anchored every caption in ONE coordinate: the below-card band
(card bottom + 24). The directive: stop permanently reserving one
coordinate. Per shot, detect what the frame is doing — diagram labels,
key evidence, arrows, lower-third information, visual focal points —
and place the caption in the cleanest available safe zone. Captions
must never obscure key evidence.

Detection sources (all deterministic, plan-time):
  shot["events"] / v8 state rects  — evidence, arrows and label anchors
  (REVEAL/ISOLATE/HIGHLIGHT/number_pop rects are card-normalized and are
  exactly where the renderer draws attention),
  shot["title"]/["tag"]/["title_overlay"]/["end_card"] — header chrome
  (brand block + episode title draw at frame y 64..184),
  evidence rect area/centroid      — visual focal points.

Candidate safe zones (frame px, 1080x1920, KIN_CAP_H carrier): the
default below-card band (faces the card's bottom edge), a lower retreat
slot in the bottom art band, and the top art band (faces the card's top
edge). Each zone is scored against the shot's evidence mass and chrome;
ties keep the default so placement varies only when the geometry
demands it. An authored shot["caption_zone"] (valid zone id) wins
outright. Zones live OUTSIDE the card, so a caption can never cover
in-card evidence by construction — caption_qa re-verifies both the band
containment and the evidence clearance from the render report.
"""
from __future__ import annotations

from engine import flags as _flags
from engine.planv5 import CARD_W, CARD_H, CARD_Y0, FOOTER_Y

FRAME_W, FRAME_H = 1080, 1920
KIN_CAP_H = 192          # carrier strip height (engine/captions.py)
BAND_GAP = 24            # clearance between card edge and caption zone
CROWD_PX = 44            # vertical proximity counted as crowding
TOP_MARGIN = 12          # top zone inset from the frame edge
BOT_MARGIN = 24          # bottom zone inset from the frame edge

# penalty weights (lower total = cleaner zone)
W_CROWD = 1.0            # zone within CROWD_PX of the focal evidence rect
W_CHROME = 6.0           # zone carries title / tag / chrome / end-card
W_DEFAULT = 0.35         # mild bias keeping the default zone on ties
W_EVIDENCE = 1.0         # evidence mass share in the zone's facing third
W_LOW_EXTRA = 0.20       # below_card_low is the retreat slot
EDGE_THIRD = 1.0 / 3.0   # card thirds adjacent to the top/bottom zones

DEFAULT_ZONE = "below_card"


def card_to_frame(rect_card) -> tuple:
    """Card-normalized [x, y, w, h] -> frame px (x0, y0, x1, y1)."""
    x, y, w, h = [float(v) for v in rect_card]
    return (x * CARD_W, CARD_Y0 + y * CARD_H,
            (x + w) * CARD_W, CARD_Y0 + (y + h) * CARD_H)


def zones() -> dict:
    """Candidate caption zones {zone_id: (top, bot)} for the active flags.

    V10_VERTICAL/V11_FULLBLEED: the card owns y 192..1440, so the bottom
    art band (1440..1920) offers the default slot plus a lower slot, and
    the top band (0..192) the third. Legacy geometry keeps its historical
    1350..1520 band as the default.
    """
    if _flags.vertical10():
        card_bot = CARD_Y0 + CARD_H
        return {
            "below_card": (card_bot + BAND_GAP, card_bot + BAND_GAP + KIN_CAP_H),
            "below_card_low": (FRAME_H - BOT_MARGIN - KIN_CAP_H,
                               FRAME_H - BOT_MARGIN),
            "top_band": (TOP_MARGIN, TOP_MARGIN + KIN_CAP_H),
        }
    return {
        "below_card": (1350, 1520),
        "top_band": (TOP_MARGIN, TOP_MARGIN + KIN_CAP_H),
    }


def evidence_rects(shot: dict) -> list:
    """Occupied card-space rects for one shot -> [(rect, kind, weight)].

    Sources: event/state spec rects (evidence, arrows, labels, pops —
    each already card-clamped by the planner) and the shot's declared
    key_number rect. These are the diagram labels / key evidence / arrow
    anchors / focal points the caption must never obscure.
    """
    out = []
    for ev in shot.get("events", []) or []:
        spec = ev.get("spec") or {}
        rc = spec.get("rect")
        if rc:
            out.append(([float(v) for v in rc], str(ev.get("kind")), 1.0))
        for r in spec.get("rects") or []:
            out.append(([float(v) for v in r], str(ev.get("kind")), 1.0))
    for st in ((shot.get("v8") or {}).get("states") or []):
        spec = st.get("spec") or {}
        rc = spec.get("rect")
        if rc:
            out.append(([float(v) for v in rc], f"state:{st.get('name')}", 1.0))
    kn = shot.get("key_number_rect")
    if kn:
        out.append(([float(v) for v in kn], "number_pop", 1.0))
    return out


def _chrome_rects(shot: dict) -> list:
    """Header / lower-third chrome occupancy -> [(rect_frame, kind, weight)].

    The brand block (episode tag, end-card mark) draws at frame y 64..184
    (layout.BRAND_RECT) — the top art band; the title overlay lives in the
    same header region (composev5._title_overlay_png). A shot carrying any
    of those must not take the top band.
    """
    out = []
    if (str(shot.get("title") or "").strip()
            or str(shot.get("tag") or "").strip()
            or shot.get("title_overlay")
            or shot.get("end_card")):
        out.append(([0.0, 64.0, 1080.0, 184.0], "header_chrome", 1.0))
    return out


def _v_gap(a: tuple, b: tuple) -> float:
    """Vertical gap between two (y0, y1) spans; 0 when they overlap."""
    return max(0.0, max(a[0], b[0]) - min(a[1], b[1]))


def _third_shares(evidence: list) -> tuple:
    """-> (top_share, bottom_share, focal_span): share of evidence area
    whose center sits in the card's top / bottom third (the thirds each
    art band continues), plus the dominant (focal) rect's frame span."""
    top_m = bot_m = tot = 0.0
    focal, focal_area = None, -1.0
    for rc, _kind, _w in evidence:
        x0, y0, x1, y1 = card_to_frame(rc)
        area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        if area <= 0:
            continue
        tot += area
        if area > focal_area:
            focal, focal_area = (y0, y1), area
        cy = (y0 + y1) / 2.0 - CARD_Y0
        if cy < EDGE_THIRD * CARD_H:
            top_m += area
        elif cy > (1.0 - EDGE_THIRD) * CARD_H:
            bot_m += area
    if tot <= 0:
        return 0.0, 0.0, focal
    return top_m / tot, bot_m / tot, focal


def score_zone(zone_id: str, zrect: tuple, evidence: list, chrome: list) -> tuple:
    """-> (penalty, reasons). Lower is cleaner.

    Each zone is penalized by the share of the shot's evidence mass in
    the card third it faces (the top band continues the card's top rows,
    the below-card band faces the card's bottom edge): the busier that
    edge, the stronger the pull away — the caption belongs on the clean
    side, away from the labels/arrows/focal points it must never
    obscure. below_card_low is the retreat slot: flat penalty, so it wins
    exactly when the adjacent below-card zone is penalized beyond its
    default bias.
    """
    zy = (zrect[0], zrect[1])
    penalty, reasons = 0.0, []
    top_share, bot_share, focal = _third_shares(evidence)
    if zone_id == "below_card":
        penalty += W_DEFAULT + W_EVIDENCE * bot_share
        if bot_share > 0.5:
            reasons.append(f"busy_bottom_edge:{bot_share:.2f}")
    elif zone_id == "below_card_low":
        penalty += W_DEFAULT + W_LOW_EXTRA
        reasons.append("non_default")
    else:  # top_band
        penalty += W_DEFAULT + W_EVIDENCE * top_share
        if top_share > 0.5:
            reasons.append(f"busy_top_edge:{top_share:.2f}")
    if focal is not None:
        gap = _v_gap(zy, focal)
        if gap < CROWD_PX:
            penalty += W_CROWD * (1.0 + (CROWD_PX - gap) / CROWD_PX)
            reasons.append(f"crowd:focal@{int(gap)}px")
    for rc, kind, _w in chrome:
        gap = _v_gap(zy, (rc[1], rc[3]))
        if gap <= 0:
            penalty += W_CHROME
            reasons.append(f"chrome:{kind}")
    return penalty, reasons


def choose_zone(shot: dict) -> dict:
    """Pick the cleanest safe zone for this shot's captions.

    An authored shot["caption_zone"] (valid zone id) wins outright —
    editorial placement stays possible; the detector covers every shot
    that does not declare one. Deterministic otherwise: ties resolve in
    zones() declaration order with the default zone biased to win, so
    placement varies only when evidence geometry or chrome demands it.
    """
    evidence = evidence_rects(shot)
    chrome = _chrome_rects(shot)
    ranked = []
    for zid, (top, bot) in zones().items():
        pen, reasons = score_zone(zid, (top, bot), evidence, chrome)
        ranked.append((pen, zid, top, bot, reasons))
    ranked.sort(key=lambda r: (r[0], list(zones()).index(r[1])))
    pen, zid, top, bot, reasons = ranked[0]
    considered = {r[1]: round(r[0], 2) for r in ranked}
    authored = str(shot.get("caption_zone") or "").strip()
    if authored and authored in zones():
        ztop, zbot = zones()[authored]
        return {"zone": authored, "top": int(ztop), "bot": int(zbot),
                "penalty": 0.0, "reasons": ["authored"],
                "evidence_count": len(evidence), "considered": considered}
    return {"zone": zid, "top": int(top), "bot": int(bot),
            "penalty": round(pen, 2), "reasons": reasons[:6],
            "evidence_count": len(evidence), "considered": considered}


def plan_shot_zones(plan: dict) -> dict:
    """Per-shot placement decisions for a whole edit plan."""
    out = {}
    for s in plan.get("shots", []) or []:
        out[str(s.get("shot_id"))] = choose_zone(s)
    varied = len({v["zone"] for v in out.values()}) > 1
    return {"shots": out, "zones_available": sorted(zones()),
            "placement_varies": varied}


# ---------------------------------------------------------------------------
# V12 P1 — caption hierarchy (Jade_todo_v12 §P1 Caption Hierarchy)
# Three separated text classes; C minimized; narration max 2 lines; never
# two text layers competing for attention; adaptive safe-zones stay
# mandatory; per-kit caption zones respected.

ARCHITECTURE_ZONES = {          # kit caption_architecture -> allowed zones
    "edge_band": ("below_card", "below_card_low"),
    "top_band": ("top_band",),
    "in_scene": ("below_card", "below_card_low"),
}

_B_EVENT_KINDS = ("number_pop", "text_emphasis", "stage_overlay")


def _narration_lines(cue: dict) -> int:
    """Declared line count of a narration cue (mirrors captions._cue_lines:
    explicit `lines` wins, then embedded newlines, else a single line)."""
    lines = cue.get("lines")
    if lines and all(str(l).strip() for l in lines):
        return len(lines)
    text = str(cue.get("text", ""))
    if "\n" in text:
        return len([l for l in text.split("\n") if l.strip()])
    return 1


def classify_shot_text(shot: dict) -> dict:
    """Inventory the shot's text into A/B/C.

    A = narration captions (the kinetic strip; shot["captions"])
    B = semantic labels (number pops, text emphasis, stage overlays,
        state labels — data attached to the visual evidence)
    C = decorative text (title/tag/title-overlay/end-card chrome)
    """
    a = [{"text": str(c.get("text") or ""), "t0": float(c.get("t0") or 0),
          "t1": float(c.get("t1") or 0), "lines": _narration_lines(c)}
         for c in shot.get("captions") or []]
    b = []
    for e in shot.get("events") or []:
        if str(e.get("kind")) in _B_EVENT_KINDS:
            txt = str((e.get("spec") or {}).get("text") or "").strip()
            if txt:
                b.append({"kind": str(e.get("kind")), "text": txt,
                          "t": float(e.get("t") or 0)})
    for st in (shot.get("v8") or {}).get("states") or []:
        lab = str((st.get("spec") or {}).get("label") or "").strip()
        if lab:
            b.append({"kind": f"state:{st.get('name')}", "text": lab,
                      "t": float(st.get("t") or 0)})
    c_texts = [str(x).strip() for x in (shot.get("title"), shot.get("tag"))
               if str(x or "").strip()]
    if shot.get("end_card"):
        c_texts.append("end_card")
    # title_overlay is a DISABLED render path (pre-V7 composev5 behavior):
    # inventoried as declared chrome, but it draws nothing, so it cannot
    # compete for attention on screen.
    if shot.get("title_overlay"):
        c_texts.append("title_overlay (disabled path)")
    rendered_c = [t for t in c_texts if not t.startswith("title_overlay")]
    return {"A": a, "B": b, "C": c_texts, "C_rendered": rendered_c}


def caption_hierarchy(plan: dict) -> dict:
    """3-class caption separation report over the whole plan.

    Findings (honest, never silently repaired):
      narration_line_cap      an A cue declared with more than 2 lines
      competing_text_layers   B label inside an active A cue window, or C
                              chrome while narration is on screen — two
                              text layers fighting for the same eye
      kit_zone_violated       a canvas (planv9) shot whose authored
                              caption_zone leaves the kit's declared
                              caption architecture
    """
    shots = plan.get("shots") or []
    rows, findings = [], []
    c_shots = 0
    for s in shots:
        inv = classify_shot_text(s)
        sid = str(s.get("shot_id"))
        max_lines = max([c["lines"] for c in inv["A"]], default=0)
        if max_lines > 2:
            findings.append({"rule": "narration_line_cap", "shot_id": sid,
                             "severity": "FAIL", "lines": max_lines,
                             "note": "narration captions render max 2 lines "
                                     "(captions.MAX_LINES)"})
        competing = []
        for lbl in inv["B"]:
            if any(c["t0"] - 0.05 <= lbl["t"] <= c["t1"] + 0.05
                   for c in inv["A"]):
                competing.append(f"B:{lbl['kind']}@{lbl['t']}")
        if inv["C_rendered"] and inv["A"]:
            competing.append("C:" + "+".join(inv["C_rendered"]))
        if competing:
            findings.append({"rule": "competing_text_layers",
                             "shot_id": sid, "severity": "FAIL",
                             "detail": competing,
                             "note": "two text layers compete for attention; "
                                     "move the label out of the narration "
                                     "window or drop the chrome"})
        zone_ok = None
        canvas = s.get("canvas") or {}
        arch = str(canvas.get("caption_architecture") or "")
        if arch:
            allowed = ARCHITECTURE_ZONES.get(arch, ("below_card",
                                                    "below_card_low",
                                                    "top_band"))
            zone_ok = str(s.get("caption_zone") or "") in allowed
            if not zone_ok:
                findings.append({"rule": "kit_zone_violated", "shot_id": sid,
                                 "severity": "FAIL",
                                 "architecture": arch,
                                 "zone": s.get("caption_zone"),
                                 "allowed": list(allowed)})
        if inv["C"]:
            c_shots += 1
        rows.append({"shot_id": sid, "A": len(inv["A"]), "B": len(inv["B"]),
                     "C": inv["C"], "max_narration_lines": max_lines,
                     "competing": competing,
                     "caption_zone": s.get("caption_zone"),
                     "kit_zone_ok": zone_ok})
    n = len(shots) or 1
    c_share = c_shots / n
    return {"shots": rows,
            "counts": {"A_cues": sum(r["A"] for r in rows),
                       "B_labels": sum(r["B"] for r in rows),
                       "C_shots": c_shots, "C_share": round(c_share, 3)},
            "C_minimized": c_share <= 0.5,
            "findings": findings,
            "caption_hierarchy_pass": not findings,
            "verdict": "pass" if not findings else
                       ("c_heavy" if c_share > 0.5 else "findings")}
