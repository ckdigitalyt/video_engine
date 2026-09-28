"""Re-gate an existing V15 work dir with the WP2 deterministic checks (no
render, no LLM call): plate QA report, plate OCR, text bounds + right rail,
caption safe zone.

  python3 bench/ab/wp2_regate.py ~/phase2_out/e2e_blackhole
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "illustrated_engine"
sys.path.insert(0, str(ROOT))
from engine import v15_gate as g  # noqa: E402


def main(work: Path) -> int:
    rep = json.loads((work / "pipeline_report.json").read_text())
    specs = {p.name[:-len(".spec.json")]: json.loads(p.read_text())
             for p in sorted((work / "scenes").glob("*.spec.json"))}
    overlays = json.loads(
        (work / "assembly_report.json").read_text())["caption_overlays"]
    checks = {"plates": g.check_plates(specs, rep.get("plate_qa")),
              "text_bounds": g.check_text_bounds(specs),
              "caption_safe": g.check_caption_safe(overlays, g._caption_top()),
              "asset_tier": g.check_assets(rep["shots"])}
    out = {"was": rep.get("publish_gate"), "now": g.verdict_of(checks),
           "failures": {k: v["fails"] for k, v in checks.items()
                        if not v["ok"]}}
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).expanduser()))
