"""V13B M4 — unit tests: visual-first caption placement (choose_caption_zone),
hook support anchor, and full-canvas world-shot helpers.

Run: python3 tests/test_v13b_m4.py   (exit 0 = all passed)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import caption_place as cp
from engine import composev5  # noqa: F401  (import smoke: world helpers wired)
from engine import layout
from engine import flags


def _sidecar(subject, annotations=None, plate=(2160, 3840)):
    """Synthetic v13-plate-sidecar@1 with a full-extent BACKGROUND layer."""
    w, h = plate
    layers = [{"name": "BACKGROUND", "bbox_px": [0, 0, w, h]},
              {"name": "SUBJECT", "bbox_px": list(subject)}]
    return {"schema": "v13-plate-sidecar@1",
            "subject_bbox_px": list(subject),
            "annotation_rects_px": [list(a) for a in (annotations or [])],
            "layers": layers}


def _shot(**kw):
    shot = {"shot_id": "T1", "beat_id": "B1", "duration_s": 3.0,
            "camera": {"primitive": "ZOOM_IN", "from_scale": 1.0,
                       "to_scale": 1.2}}
    shot.update(kw)
    return shot


def test_a_subject_top_third_picks_lower_band():
    """Subject in the top third -> caption picks a lower band."""
    shot = _shot(plate_sidecar=_sidecar([180, 120, 1980, 1180]))
    z = cp.choose_caption_zone(shot, shot["plate_sidecar"])
    assert z["zone"] in ("below_card", "below_card_low"), z
    assert z["top"] > 1200, z
    cov = z["sidecar_coverage"]
    assert cov["top_band"] > 0.5, cov           # art measured in the top band
    assert cov[z["zone"]] == 0.0, cov            # chosen band is clean
    print("  a) subject top third ->", z["zone"], "coverage", cov)


def test_a2_annotations_push_off_covered_band():
    """Art in BOTH the top band and the below-card band -> retreat slot."""
    sc = _sidecar([180, 120, 1980, 1100],
                  annotations=[[400, 3050, 1800, 3300]])
    z = cp.choose_caption_zone(_shot(plate_sidecar=sc), sc)
    assert z["zone"] == "below_card_low", z
    print("  a2) top+bottom art ->", z["zone"], "coverage",
          z["sidecar_coverage"])


def test_b_subject_fills_falls_back_to_below_card():
    """Subject fills the frame (every band covered) -> below_card default."""
    sc = _sidecar([0, 0, 2160, 3840])
    z = cp.choose_caption_zone(_shot(plate_sidecar=sc), sc)
    assert z["zone"] == "below_card", z
    print("  b) filling subject ->", z["zone"], "coverage",
          z["sidecar_coverage"])


def test_c_authored_caption_zone_wins():
    """Authored shot['caption_zone'] wins over the measured choice."""
    sc = _sidecar([180, 120, 1980, 1180])   # measurement says: lower band
    shot = _shot(caption_zone="top_band", plate_sidecar=sc)
    z = cp.choose_caption_zone(shot, sc)
    assert z["zone"] == "top_band" and z["reasons"] == ["authored"], z
    # ... and via the choose_zone wrapper (what the renderer calls)
    assert cp.choose_zone(shot)["zone"] == "top_band"
    print("  c) authored top_band wins over measured", z["considered"])


def test_d_no_sidecar_is_legacy_identical():
    """No sidecar / flag off -> byte-identical legacy behavior."""
    shot = _shot(events=[{"kind": "number_pop", "t": 1.0,
                          "spec": {"rect": [0.3, 0.8, 0.4, 0.1],
                                   "text": "0"}}])
    legacy = cp._choose_zone_legacy(shot)
    assert cp.choose_zone(dict(shot)) == legacy
    assert cp.choose_caption_zone(dict(shot), None) == legacy
    os.environ["V13B_M4_CAPTIONS"] = "0"
    try:
        assert cp.choose_caption_zone(shot, _sidecar([0, 0, 2160, 3840])) == legacy
    finally:
        os.environ.pop("V13B_M4_CAPTIONS")
    print("  d) no-sidecar/flag-off == legacy", legacy["zone"])


def test_e_zone_structure_unchanged():
    """Same keys as the legacy structure (sidecar_coverage additive only)."""
    legacy_keys = set(cp._choose_zone_legacy(_shot()))
    z = cp.choose_caption_zone(_shot(plate_sidecar=_sidecar([180, 120, 1980, 1180])),
                               _sidecar([180, 120, 1980, 1180]))
    assert legacy_keys <= set(z), (legacy_keys, set(z))
    for k in ("zone", "top", "bot", "penalty", "reasons",
              "evidence_count", "considered"):
        assert k in z, k
    zs = cp.zones()
    assert (z["top"], z["bot"]) in [tuple(v) for v in zs.values()]
    print("  e) zone structure preserved:", z["zone"], (z["top"], z["bot"]))


def test_f_report_and_render_share_the_choice():
    """Overlay-report path resolves the SAME zone the render path chose."""
    sc = _sidecar([180, 120, 1980, 1180])
    shot = _shot(plate_sidecar=sc,
                 captions=[{"text": "the ice is slippery", "t0": 0.2, "t1": 2.4}])
    render_zone = cp.choose_caption_zone(shot, shot.get("plate_sidecar"))
    report_zone = cp.choose_caption_zone(dict(shot, extra=1),
                                         shot.get("plate_sidecar"))
    assert render_zone["zone"] == report_zone["zone"]
    assert (render_zone["top"], render_zone["bot"]) == \
           (report_zone["top"], report_zone["bot"])
    print("  f) render/report zones agree:", render_zone["zone"])


def test_g_world_detection_and_camera_fragment():
    """World-kit detection + full-frame camera fragment (dry compose)."""
    world_canvas = {"panel_usage": "none", "composition": "macro_world"}
    shot = _shot(canvas=dict(world_canvas),
                 visual_grammar={"composition": "macro_world"})
    assert composev5._shot_is_world(shot), "world kit must be full-frame"
    panel = _shot(canvas={"panel_usage": "hero_island",
                          "composition": "universal_presentation_panel"},
                  visual_grammar={"composition": "universal_presentation_panel"})
    assert not composev5._shot_is_world(panel), "panel must keep card layout"
    frag, n, meta = composev5._world_camera_filter(shot, 1836, 3264, 3.0, fps=30)
    assert n == 90, n
    assert "scale=1080:1920" in frag and "overlay" not in frag
    assert meta["world_content"] == [1836, 3264]
    assert meta["world_camera"]["from"]["w"] > 0.30
    os.environ["V13B_M4_FULLCANVAS"] = "0"
    try:
        assert not composev5._shot_is_world(shot), "rollback flag must restore"
    finally:
        os.environ.pop("V13B_M4_FULLCANVAS")
    print("  g) world detection + camera fragment ok", meta["primitive"])


def test_h_hook_support_anchor():
    """Opening+plate -> compact support slot OUTSIDE the chosen band."""
    sc = _sidecar([180, 120, 1980, 1180])   # art top -> captions go below_card
    shot = _shot(opening=True, plate_sidecar=sc)
    anchor = layout.hook_support_anchor(shot)
    assert anchor is not None, "opening plate shot must demote the title"
    assert anchor == cp.zones()["below_card_low"], anchor
    chosen = cp.choose_zone(shot)
    assert not (anchor[0] < chosen["bot"] and chosen["top"] < anchor[1]), \
        "support line must not share rows with the narration band"
    # no plate sidecar -> legacy large title path
    assert layout.hook_support_anchor(_shot(opening=True)) is None
    assert layout.hook_support_anchor(_shot(plate_sidecar=sc)) is None
    print("  h) hook support anchor", anchor, "caption band",
          (chosen["top"], chosen["bot"]))


if __name__ == "__main__":
    assert flags.m4_captions13b() and flags.m4_fullcanvas13b()
    test_a_subject_top_third_picks_lower_band()
    test_a2_annotations_push_off_covered_band()
    test_b_subject_fills_falls_back_to_below_card()
    test_c_authored_caption_zone_wins()
    test_d_no_sidecar_is_legacy_identical()
    test_e_zone_structure_unchanged()
    test_f_report_and_render_share_the_choice()
    test_g_world_detection_and_camera_fragment()
    test_h_hook_support_anchor()
    print("ALL V13B M4 UNIT TESTS PASSED")
