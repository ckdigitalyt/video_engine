"""V14 Stage 10 — extended cache invalidation + partial rerender (§24/§25).

Cache keys per §24: every scene key binds
  scene-spec hash (normalized, canonical — includes camera choreography and,
  after asset staging, content-addressed asset paths so ASSET BYTES bind)
  + style-bible hash + renderer backend name + renderer version
  + render configuration hash.

Partial rerender per §25 (V14 burns captions and mixes audio at ASSEMBLY):
  scene-spec / camera / asset change  -> that scene re-renders, others reused
  caption timing change               -> ZERO scene renders, composite rebuild
  narration / bed change              -> audio rebuild + composite, no renders
  backend / config change             -> all scenes re-render
  missing or tampered scene output    -> that scene re-renders (sha16 check)

The stale-render failure mode from V13 is structurally closed: an index entry
is keyed by the full §24 key, and the stored output sha16 is re-verified
against the file on every plan — a hit with a changed/mutated file re-renders.

Index: <work_dir>/render_index.json
  {"scenes": {"<key>": {scene_id, output, sha16, duration_s}},
   "assembly": {key, output, sha16, captions_hash, narration_hash, bed_hash}}

CLI: python3 -m engine.v14_cache show <work_dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

INDEX_NAME = "render_index.json"


def _sha16_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def _sha16_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()[:16]


def _hash_obj(obj) -> str:
    return _sha16_bytes(json.dumps(obj, sort_keys=True,
                                   separators=(",", ":")).encode())


def style_hash(bible: dict) -> str:
    return _hash_obj(bible or {})


def render_config_hash(config: dict) -> str:
    return _hash_obj(config or {})


def scene_cache_key(spec_hash: str, style_h: str, backend_name: str,
                    backend_version: str, config: dict) -> str:
    """Full §24 key. spec_hash covers spec + camera + staged asset bytes."""
    parts = "|".join([spec_hash, style_h, backend_name, backend_version,
                      render_config_hash(config)])
    return _sha16_bytes(parts.encode())


def caption_plan_hash(captions: dict, bible: dict) -> str:
    """Captions burned at assembly -> their own hash (§25 caption-timing rule)."""
    return _hash_obj({"captions": captions, "bible": bible})


def narration_plan_hash(narrations: dict) -> str:
    return _hash_obj(narrations or {})


def bed_plan_hash(beds: dict) -> str:
    return _hash_obj(beds or {})


def assembly_key(scene_keys: list, captions_h: str, narration_h: str,
                 bed_h: str) -> str:
    """Final-composite key: ordered scene render keys + caption + audio plans."""
    parts = "|".join(["|".join(scene_keys), captions_h, narration_h, bed_h])
    return _sha16_bytes(parts.encode())


def load_index(work_dir: Path) -> dict:
    p = Path(work_dir) / INDEX_NAME
    if p.exists():
        return json.loads(p.read_text())
    return {"scenes": {}, "assembly": {}}


def save_index(work_dir: Path, index: dict) -> Path:
    p = Path(work_dir) / INDEX_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(index, indent=1))
    return p


def record_scene(index: dict, key: str, scene_id: str, output: Path,
                 duration_s: float | None = None) -> None:
    index["scenes"][key] = {"scene_id": scene_id, "output": str(output),
                            "sha16": _sha16_file(output),
                            "duration_s": duration_s}


def record_assembly(index: dict, key: str, output: Path, captions_h: str,
                    narration_h: str, bed_h: str) -> None:
    index["assembly"] = {"key": key, "output": str(output),
                         "sha16": _sha16_file(output),
                         "captions_hash": captions_h,
                         "narration_hash": narration_h, "bed_hash": bed_h}


def _scene_verdict(index: dict, scene_id: str, key: str, output: Path) -> tuple:
    """-> (needs_render: bool, reason: str)."""
    entry = index["scenes"].get(key)
    if entry is None:
        return True, "no_index_entry"
    if entry.get("output") != str(output):
        return True, "output_path_changed"
    output = Path(output)
    if not output.exists():
        return True, "output_missing"
    if entry.get("sha16") != _sha16_file(output):
        return True, "output_tampered"
    # same key rendered elsewhere (scene_id drift) -> re-render for identity
    if entry.get("scene_id") != scene_id:
        return True, "scene_id_changed"
    return False, "hit"


def plan_rerender(index: dict, scenes: dict) -> dict:
    """scenes: {scene_id: {"key": cache_key, "output": path}}.

    -> {"render": [...], "reuse": [...], "reasons": {scene_id: reason}}.
    Duplicate keys across scene_ids (identical scene reused in a video) render
    once and are treated as reuse for the second id.
    """
    render, reuse, reasons, seen = [], [], {}, {}
    for scene_id in sorted(scenes):
        key = scenes[scene_id]["key"]
        out = scenes[scene_id]["output"]
        if key in seen:
            reuse.append(scene_id)
            reasons[scene_id] = "duplicate_key"
            continue
        needs, why = _scene_verdict(index, scene_id, key, out)
        if needs:
            render.append(scene_id)
            seen[key] = scene_id
        else:
            reuse.append(scene_id)
        reasons[scene_id] = why
    return {"render": render, "reuse": reuse, "reasons": reasons}


def plan_production(index: dict, scene_inputs: dict, captions_h: str,
                    narration_h: str, bed_h: str, out_path: Path) -> dict:
    """Full §25 production plan.

    scene_inputs: {scene_id: {"key", "output"}} (scene cache keys per §24).
    Composite rebuilds when: any scene re-renders, or the assembly key changed
    (captions/audio/style/order), or the composite file is missing/tampered.
    Audio rebuilds only when the narration or bed plan hash changed.
    """
    scenes_plan = plan_rerender(index, scene_inputs)
    asm = index.get("assembly") or {}
    key = assembly_key([scene_inputs[sid]["key"] for sid in sorted(scene_inputs)],
                       captions_h, narration_h, bed_h)
    rebuild_audio = (asm.get("narration_hash") != narration_h
                     or asm.get("bed_hash") != bed_h)
    out_path = Path(out_path)
    composite_stale = (
        bool(scenes_plan["render"])
        or asm.get("key") != key
        or asm.get("output") != str(out_path)
        or not out_path.exists()
        or (out_path.exists() and asm.get("sha16") != _sha16_file(out_path))
    )
    return {"render": scenes_plan["render"], "reuse": scenes_plan["reuse"],
            "reasons": scenes_plan["reasons"],
            "rebuild_audio": rebuild_audio,
            "rebuild_composite": composite_stale,
            "assembly_key": key}


def main() -> int:
    ap = argparse.ArgumentParser(description="V14 Stage 10 render index")
    ap.add_argument("cmd", choices=["show"])
    ap.add_argument("work_dir")
    args = ap.parse_args()
    if args.cmd == "show":
        print(json.dumps(load_index(args.work_dir), indent=1))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
