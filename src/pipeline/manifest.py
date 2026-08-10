"""Content-addressed artifact manifest + dependency-aware invalidation.

Phase 1 of the modular pipeline (expert-endorsed design, 2026-08-10):
the manifest is the PRIMARY abstraction.  Every generated artifact gets a
content hash; dependency rules decide what must regenerate when an input
changes; scene/asset selection (``--scenes`` / ``--assets``) are operations
on the dependency graph, not separate mechanisms.

Dependency graph (input change -> invalidated downstream artifacts):
    script          -> voice, subtitles, scene_render
    voice           -> subtitles, scene_render
    visual / asset  -> scene_render
    subtitle_style  -> subtitles, scene_render
    transitions/global -> final_assembly
    nothing changed -> reuse everything

Side effect: fixes the latent cross-topic audio-cache bug.  ``cache/audio``
was global and ``--reuse`` was all-or-nothing, so a topic whose scene count
matched a previous topic could silently reuse the WRONG narration.  The
manifest scopes every hash to this topic's out_dir and only reuses a voice
track when BOTH the script hash and the file hash match.
"""

import hashlib
import json
import os
from typing import Any, Optional

MANIFEST_VERSION = 1

# input change -> downstream artifacts that must regenerate
DEPENDENCY_ACTIONS: dict[str, list[str]] = {
    "script": ["regenerate_voice", "regenerate_subtitles",
               "regenerate_scene_render"],
    "voice": ["regenerate_subtitles", "regenerate_scene_render"],
    "visual": ["regenerate_scene_render"],
    "subtitles": ["regenerate_scene_render"],
    "global": ["reassemble"],
}


def hash_file(path: str, chunk: int = 1 << 20) -> str:
    """SHA-256 of file bytes; empty string if the file is missing."""
    if not path or not os.path.exists(path):
        return ""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()
    except OSError:
        return ""


def hash_text(text: Optional[str]) -> str:
    """SHA-256 of normalized script text ('' for empty/None)."""
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def shot_id(scene_idx: int, idx: int) -> str:
    """Canonical shot id: s06_sh01 = scene 6, shot 1."""
    return f"s{int(scene_idx):02d}_sh{int(idx):02d}"


def parse_shot_id(sid: str) -> Optional[tuple[int, int]]:
    """'s06_sh01' -> (6, 1); None if malformed."""
    try:
        if not sid.startswith("s") or "_sh" not in sid:
            return None
        scene, shot = sid[1:].split("_sh")
        return int(scene), int(shot)
    except (ValueError, AttributeError):
        return None


def compute_diff(prev: dict, curr: dict) -> list[dict]:
    """Compare a previously saved manifest against the current computed
    state.  Returns a list of changes:

        [{"scene": 3, "changed": ["script"], "actions": [...]},
         {"scene": None, "changed": ["global"], "actions": ["reassemble"]}]

    Scenes identical in both manifests produce no entry (reuse everything).
    """
    changes: list[dict] = []
    prev_scenes = prev.get("scenes", {}) if isinstance(prev, dict) else {}
    curr_scenes = curr.get("scenes", {}) if isinstance(curr, dict) else {}
    scene_ids = set(prev_scenes) | set(curr_scenes)

    def _num(s: str) -> int:
        try:
            return int(s)
        except (TypeError, ValueError):
            return 0

    for sid in sorted(scene_ids, key=_num):
        p = prev_scenes.get(sid, {}) or {}
        c = curr_scenes.get(sid, {}) or {}
        changed: list[str] = []
        actions: set[str] = set()
        if p.get("script_hash") != c.get("script_hash"):
            changed.append("script")
            actions.update(DEPENDENCY_ACTIONS["script"])
        if (p.get("voice") or {}).get("hash") != (c.get("voice") or {}).get("hash"):
            changed.append("voice")
            actions.update(DEPENDENCY_ACTIONS["voice"])
        p_shots = {s.get("id"): s for s in p.get("shots", []) if isinstance(s, dict)}
        c_shots = {s.get("id"): s for s in c.get("shots", []) if isinstance(s, dict)}
        for sh_id, cs in c_shots.items():
            ps = p_shots.get(sh_id)
            # Only the durable still asset drives visual-change detection:
            # Ken Burns clip files live in out_dir/shots/ and are deleted by
            # the run-end cleanup, so comparing clip hashes would flag every
            # scene as "visual changed" on every rerun.
            if ps is None or ps.get("asset_hash") != cs.get("asset_hash"):
                changed.append(f"visual:{sh_id}")
                actions.update(DEPENDENCY_ACTIONS["visual"])
        if p.get("subtitles_hash") != c.get("subtitles_hash"):
            changed.append("subtitles")
            actions.update(DEPENDENCY_ACTIONS["subtitles"])
        if changed:
            changes.append({
                "scene": _num(sid),
                "changed": changed,
                "actions": sorted(actions),
            })
    if (prev.get("global") or {}) != (curr.get("global") or {}):
        changes.append({"scene": None, "changed": ["global"],
                        "actions": ["reassemble"]})
    return changes


class Manifest:
    """Per-run content-addressed manifest, persisted to ``out_dir``.

    The pipeline mutates entries with CURRENT hashes as it goes, then calls
    ``save()``.  ``diff()`` compares the previously-saved state (if any)
    against the current in-memory state to drive selective rebuilds.
    """

    def __init__(self, out_dir: str):
        self.out_dir = out_dir
        self.path = os.path.join(out_dir, "manifest.json")
        self.data: dict[str, Any] = {
            "version": MANIFEST_VERSION,
            "scenes": {},
            "global": {},
            "final": {},
        }
        self._prev: dict = {}

    def load(self) -> "Manifest":
        """Load a previously saved manifest (best-effort)."""
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict) and "scenes" in loaded:
                    self._prev = loaded
                    self.data = {
                        "version": loaded.get("version", MANIFEST_VERSION),
                        "scenes": dict(loaded.get("scenes", {})),
                        "global": dict(loaded.get("global", {})),
                        "final": dict(loaded.get("final", {})),
                    }
            except (OSError, ValueError):
                pass
        return self

    def save(self) -> str:
        os.makedirs(self.out_dir, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)
        return self.path

    # ── scene-level setters ──────────────────────────────────────────
    def _scene(self, i: int) -> dict:
        return self.data["scenes"].setdefault(str(i), {})

    def set_script(self, i: int, text: Optional[str]) -> str:
        h = hash_text(text)
        self._scene(i)["script_hash"] = h
        return h

    def set_voice(self, i: int, wav_path: str, duration: float) -> str:
        h = hash_file(wav_path)
        self._scene(i)["voice"] = {
            "file": wav_path, "hash": h, "duration": round(duration, 3),
        }
        return h

    def add_shot(self, i: int, idx: int, *, file: str, asset: str = "",
                 kind: str = "", verification_passed: bool = True,
                 camera: str = "", query: str = "") -> str:
        sid = shot_id(i, idx)
        entry = {
            "id": sid,
            "file": file,
            "clip_hash": hash_file(file),
            "kind": kind,
            "camera": camera,
            "query": query,
            "verification_passed": bool(verification_passed),
        }
        if asset:
            entry["asset"] = asset
            entry["asset_hash"] = hash_file(asset)
        self._scene(i).setdefault("shots", []).append(entry)
        return sid

    def set_subtitles_hash(self, i: int, h: str) -> None:
        self._scene(i)["subtitles_hash"] = h

    # ── global / final ───────────────────────────────────────────────
    def set_global(self, key: str, value: Any) -> None:
        self.data["global"][key] = value

    def set_final(self, **kw: Any) -> None:
        self.data["final"].update(kw)

    # ── diff / reuse decisions ───────────────────────────────────────
    def diff(self) -> list[dict]:
        return compute_diff(self._prev, self.data)

    def voice_reusable(self, i: int, wav_path: str,
                       script_text: Optional[str]) -> bool:
        """Reuse a cached voice track only when the script hash AND the
        wav file hash both match what this topic's manifest recorded."""
        if not os.path.exists(wav_path):
            return False
        p = self._prev.get("scenes", {}).get(str(i), {})
        if not p:
            return False
        if p.get("script_hash") != hash_text(script_text):
            return False
        if (p.get("voice") or {}).get("hash") != hash_file(wav_path):
            return False
        return True

    def still_reusable(self, i: int, still_path: str,
                       expected_asset_hash: str = "") -> bool:
        """Reuse a cached still when it exists and (if recorded) its hash
        matches the manifest.  Empty expected hash = no prior record."""
        if not os.path.exists(still_path):
            return False
        if not expected_asset_hash:
            return False
        return hash_file(still_path) == expected_asset_hash
