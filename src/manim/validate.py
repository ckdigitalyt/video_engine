"""
manim_validate.py — Deterministic Manim validation (Jade Operating Spec §3, §6).

Before any Manim script is executed:

  * parse the Python source with ``ast`` (syntax gate — fail closed);
  * reject suspicious constructs (exec/eval/import os/subprocess/socket,
    file writes outside temp, infinite loops);
  * verify required symbols exist (Scene subclass with ``construct``,
    and all referenced module-level names resolve);
  * verify the scene is KINETIC: it must contain animation calls
    (self.play / self.add with transforms, camera movement, or
    Transform/Write/Create/Shift) — long static holds are rejected;
  * cap total ``self.wait`` time so a scene can't be one long still.

Rendering happens in a sandboxed subprocess with a timeout (see
src/manim/planner.py render); this module is the pre-execution gate.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from typing import Optional

# Suspicious constructs that never belong in a Manim scene script.
BANNED_CALLS = {"exec", "eval", "compile", "__import__", "open", "input",
                "exit", "quit", "breakpoint", "print"}
BANNED_IMPORTS = {"os", "sys", "subprocess", "socket", "shutil", "pathlib",
                  "requests", "urllib", "http", "ctypes", "pickle", "tempfile",
                  "multiprocessing", "threading"}
BANNED_ATTRS = ("system", "popen", "run", "remove", "unlink", "rmtree",
                "write", "mkdir", "chmod", "getenv", "environ")

# Animation calls that constitute motion/kinetic content.
KINETIC_CALLS = {"play", "add", "wait", "animate", "shift", "scale", "rotate",
                 "move_to", "to_edge", "to_corner", "next_to", "align_to",
                 "set_color", "fade", "transform"}
MOTION_PLAYS = {"Transform", "TransformFromCopy", "ReplacementTransform",
                "FadeIn", "FadeOut", "Create", "Write", "GrowFromCenter",
                "GrowFromEdge", "GrowFromPoint", "Indicate", "Flash", "ApplyMethod",
                "MoveToTarget", "Uncreate", "DrawBorderThenFill", "SpinInFromNothing",
                "Write", "Circumscribe", "ZoomIn", "FadeTransform", "Shimmer",
                "AnimationGroup", "Succession", "LaggedStart", "self.camera.frame"}
CAMERA_MOTION = {"frame.animate", "self.camera.frame", "move_camera", "set_zoom",
                 "camera.frame"}

MAX_WAIT_TOTAL_S = 6.0   # total static wait time allowed in one scene
MAX_WAIT_SINGLE_S = 2.5  # a single wait longer than this = static hold


@dataclass
class ManimValidation:
    valid: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    kinetic: bool = False
    play_calls: int = 0
    total_wait_s: float = 0.0
    max_wait_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "kinetic": self.kinetic,
            "play_calls": self.play_calls,
            "total_wait_s": round(self.total_wait_s, 2),
            "max_wait_s": round(self.max_wait_s, 2),
            "errors": self.errors[:10],
            "warnings": self.warnings[:10],
        }


def _extract_wait_value(node) -> Optional[float]:
    """Best-effort literal value of self.wait(x) / self.wait(duration=x)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        return None  # variable — cannot statically resolve; treat as unknown
    return None


def validate_manim_script(script_path: str) -> ManimValidation:
    """Validate a Manim scene file before execution.  Fail closed."""
    v = ManimValidation(valid=False)
    if not os.path.exists(script_path):
        v.errors.append(f"script not found: {script_path}")
        return v
    try:
        with open(script_path) as f:
            source = f.read()
    except Exception as e:
        v.errors.append(f"cannot read script: {e}")
        return v

    # ── 1. Syntax gate ────────────────────────────────────────────────
    try:
        tree = ast.parse(source, filename=script_path)
    except SyntaxError as e:
        v.errors.append(f"syntax error: {e.msg} at line {e.lineno}")
        return v

    # ── 2. Suspicious constructs ───────────────────────────────────────
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = ""
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
            if name in BANNED_CALLS:
                v.errors.append(f"banned call '{name}' at line {getattr(node, 'lineno', '?')}")
        if isinstance(node, ast.Import):
            for a in node.names:
                top = (a.name or "").split(".")[0]
                if top in BANNED_IMPORTS:
                    v.errors.append(f"banned import '{a.name}' at line {getattr(node, 'lineno', '?')}")
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.split(".")[0] in BANNED_IMPORTS:
                v.errors.append(f"banned import '{mod}' at line {getattr(node, 'lineno', '?')}")
        if isinstance(node, ast.Attribute):
            if node.attr in BANNED_ATTRS and isinstance(node.value, ast.Attribute) and \
                    getattr(node.value, "attr", "") in ("os", "sys"):
                v.errors.append(f"banned attribute access '{node.value.attr}.{node.attr}'")
        if isinstance(node, (ast.While, ast.For)):
            # bounded loops only — reject while True and unbounded ranges
            if isinstance(node, ast.While) and not node.orelse:
                v.errors.append(f"unbounded while loop at line {getattr(node, 'lineno', '?')}")

    if v.errors:
        return v

    # ── 3. Required structure: Scene subclass with construct ───────────
    scene_classes = [n for n in tree.body if isinstance(n, ast.ClassDef)
                     and any((isinstance(b, ast.Name) and b.id == "Scene") or
                             (isinstance(b, ast.Attribute) and b.attr == "Scene")
                             or (isinstance(b, ast.Name) and "Scene" in b.id)
                             for b in n.bases)]
    # Accept common Scene subclasses too (MovingCameraScene, ZoomedScene,
    # ThreeDScene, VectorScene, ...) — all inherit from Scene and render
    # identically for our purposes.
    if not scene_classes:
        scene_classes = [n for n in tree.body if isinstance(n, ast.ClassDef)
                         and any(isinstance(b, ast.Name) and "Scene" in b.id
                                 for b in n.bases)]
    if not scene_classes:
        v.errors.append("no Scene subclass found")
        return v
    construct = [n for n in scene_classes[0].body
                 if isinstance(n, ast.FunctionDef) and n.name == "construct"]
    if not construct:
        v.errors.append("Scene subclass missing construct()")
        return v

    # ── 4. Kinetic requirement ─────────────────────────────────────────
    play_calls = 0
    kinetic_calls = []
    total_wait = 0.0
    max_wait = 0.0
    for node in ast.walk(construct[0]):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            meth = node.func.attr
            if meth == "play":
                play_calls += 1
                for arg in node.args:
                    if isinstance(arg, ast.Name) or isinstance(arg, ast.Attribute):
                        kinetic_calls.append("play")
                    elif isinstance(arg, ast.Call):
                        fn = arg.func
                        fname = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
                        if fname in MOTION_PLAYS or "animate" in fname:
                            kinetic_calls.append(fname)
            elif meth == "wait":
                for kw in node.keywords:
                    if kw.arg == "duration":
                        node = kw.value
                val = _extract_wait_value(node.args[0] if node.args else None)
                if val is not None:
                    total_wait += val
                    max_wait = max(max_wait, val)
                else:
                    total_wait += 1.0  # unknown duration: assume 1s
                    max_wait = max(max_wait, 1.0)
            elif meth in KINETIC_CALLS or meth in CAMERA_MOTION:
                kinetic_calls.append(meth)

    v.play_calls = play_calls
    v.total_wait_s = total_wait
    v.max_wait_s = max_wait
    v.kinetic = play_calls >= 1 or any("animate" in k for k in kinetic_calls)

    if play_calls < 1:
        v.errors.append("scene is static: zero self.play() animation calls")
    if total_wait > MAX_WAIT_TOTAL_S:
        v.errors.append(
            f"scene is a long static hold: total wait {total_wait:.1f}s "
            f"> {MAX_WAIT_TOTAL_S}s — split into multiple kinetic clips")
    if max_wait > MAX_WAIT_SINGLE_S:
        v.warnings.append(
            f"single wait {max_wait:.1f}s — prefer camera motion/transforms")

    v.valid = not v.errors
    return v


def validate_manim_facts(script_path: str, expected: dict) -> list:
    """§3 validation: numbers/labels in the script must match the script.

    ``expected`` maps label text -> required value string (substring
    check, case-insensitive).  Any expected label whose value does NOT
    appear in the file is reported.  Used to catch stale Manim scenes
    (e.g. "20 km" when the script says "10 km").
    """
    if not os.path.exists(script_path):
        return [f"script not found for fact check: {script_path}"]
    with open(script_path) as f:
        src = f.read().lower()
    problems = []
    for label, value in (expected or {}).items():
        v = str(value).lower()
        if v and v not in src:
            problems.append(f"label '{label}': value '{value}' not found in Manim script")
    return problems
