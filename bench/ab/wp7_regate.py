"""WP7 right-rail proof: reproduce all 9 text_bounds failures documented in
bench/ab/wp2.md (the Phase 2 blackhole regate) through the CURRENT
engine.v15_shots code and confirm every one now clears engine.v15_gate's
right-rail check. No render, no LLM call, no plate — the 7 "label" cases
replay engine.v15_shots._label with a subject bbox chosen to reproduce the
documented box's y-range exactly (its height is a pure function of that
bbox); the 2 "number"/"headline" cases replay _text_layer the same way
WP6's own regression test does.

  python3 bench/ab/wp7_regate.py [out.json]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "illustrated_engine"
sys.path.insert(0, str(ROOT))
from engine import v15_gate as g  # noqa: E402
from engine import v15_shots as S  # noqa: E402

INK = {"fill": "#FFF7E8", "halo": "#15202B", "accent": "#E3A83B"}

# (case id, text, documented old box [x0,y0,x1,y1]) — bench/ab/wp2.md
LABEL_CASES = [
    ("B1_S1.label", "THE CLOCK", [747, 820, 1010, 904]),
    ("B2_S2.label", "INTACT GEARS", [668, 794, 1010, 878]),
    ("B3_S1.label", "GRAVITY'S GRIP", [630, 728, 1010, 812]),
    ("B3_S2.label", "CLOCKS AT DEPTH", [578, 822, 1010, 906]),
    ("B6_S1.label", "THE HORIZON", [691, 796, 1010, 880]),
    ("B6_S2.label", "FROZEN STILL", [676, 794, 1010, 878]),
    ("B7_S1.label", "THE BLACK HOLE", [605, 794, 1010, 878]),
]


def main(out_path: Path | None = None) -> int:
    results = {"documented_verdict": "FAIL (bench/ab/wp2.md)", "cases": []}
    all_ok = True

    for case_id, text, old_box in LABEL_CASES:
        y0, y1 = old_box[1], old_box[3]
        ay = y0 + 164  # engine.v15_shots._label's exact box-height formula
        bb = [300, ay - 100, 500, ay + 100]  # cx=400<=540 -> side="right"
        boxes = []
        lab = S._label("label", text, {"bbox": bb}, 1.0, 3.0, INK, boxes, "top")
        ok = lab is not None and not g._box_problems(boxes[0]["box"])
        all_ok = all_ok and ok
        results["cases"].append({"id": case_id, "text": text,
                                 "old_box": old_box,
                                 "new_box": boxes[0]["box"] if boxes else None,
                                 "pass": ok})

    number_boxes = []
    S._text_layer("number", "38 MICROSECONDS", y=S.LOW_ZONE_BOTTOM, size=230,
                  ink=INK, boxes=number_boxes, max_lines=2, anchor_bottom=True,
                  pop=True, accent=True, min_size=70)
    ok = not g._box_problems(number_boxes[0]["box"])
    all_ok = all_ok and ok
    results["cases"].append({"id": "B5_S2.number", "text": "38 MICROSECONDS",
                             "old_box": [82, 1031, 998, 1429],
                             "new_box": number_boxes[0]["box"], "pass": ok})

    headline_boxes = []
    S._text_layer("headline", "STILL TICKING. JUST SLOWER.",
                  y=S.LOW_ZONE_BOTTOM, size=150, ink=INK,
                  boxes=headline_boxes, max_lines=3, anchor_bottom=True)
    ok = not g._box_problems(headline_boxes[0]["box"])
    all_ok = all_ok and ok
    results["cases"].append({"id": "B7_S2.headline",
                             "text": "STILL TICKING. JUST SLOWER.",
                             "old_box": [85, 1112, 995, 1420],
                             "new_box": headline_boxes[0]["box"], "pass": ok})

    results["verdict"] = "PASS" if all_ok else "FAIL"
    results["n_cases"] = len(results["cases"])
    results["n_pass"] = sum(1 for c in results["cases"] if c["pass"])
    text = json.dumps(results, indent=1)
    print(text)
    if out_path:
        out_path.write_text(text)
    return 0 if all_ok else 1


if __name__ == "__main__":
    p = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    sys.exit(main(p))
