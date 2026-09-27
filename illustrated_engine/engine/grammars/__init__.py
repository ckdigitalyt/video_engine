"""V14 Stage 6 — visual grammar library (directive §9, §37 Stage 6).

Usage:
    python3 -m engine.grammars list
    python3 -m engine.grammars build <GRAMMAR> <content.json> [out.spec.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from engine.grammars.base import Grammar, GrammarError
from engine.grammars.data_graphic import DataGraphic
from engine.grammars.map_transformation import MapTransformation
from engine.grammars.process_flow import ProcessFlow
from engine.grammars.rich_illustrated import RichIllustratedScene
from engine.grammars.scale_dive import ScaleDive

GRAMMARS = {g.name: g() for g in (RichIllustratedScene, ScaleDive, DataGraphic,
                                  ProcessFlow, MapTransformation)}


def available_grammars() -> dict:
    return {n: g.summary for n, g in GRAMMARS.items()}


def build_scene(grammar_name: str, content: dict) -> dict:
    """Content -> validated Scene IR. Raises GrammarError on bad content or
    invalid generated IR (every build ends in validate_scene_spec)."""
    g = GRAMMARS.get(grammar_name)
    if g is None:
        raise GrammarError(f"unknown grammar {grammar_name!r}; "
                           f"available: {sorted(GRAMMARS)}")
    return g.build(content)


def main(argv) -> int:
    if len(argv) >= 1 and argv[0] == "list":
        for n, s in available_grammars().items():
            print(f"{n}\n    {s}")
        return 0
    if len(argv) >= 3 and argv[0] == "build":
        content = json.loads(Path(argv[2]).read_text())
        spec = build_scene(argv[1], content)
        if len(argv) >= 4:
            out = Path(argv[3])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(spec, indent=1, sort_keys=True))
            print(f"built {argv[1]} -> {out}")
        else:
            print(json.dumps(spec, indent=1, sort_keys=True))
        return 0
    print("usage: python3 -m engine.grammars list | build <GRAMMAR> "
          "<content.json> [out.spec.json]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
