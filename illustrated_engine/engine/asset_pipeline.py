"""V14 Stage 7 — asset/layer pipeline (directive §11, §12, §24).

Assets are layer sources, not scenes: a manifest binds asset ids to files
with content hashes; scene specs reference assets by id; renderers stage
hashed copies into their serving roots. Content hashing here is the ground
truth the §24 scene cache keys will build on (Stage 10).

Manifest shape (v14.asset_manifest/1.0):
    {"schema": ..., "assets": [{asset_id, path, sha256, role, source,
                                 width, height, bytes}]}
`path` is stored relative to the manifest file (portable, forward slashes).

CLI:
    python3 -m engine.asset_pipeline register <file> <asset_id> \
        --manifest M --role subject --source raster
    python3 -m engine.asset_pipeline list --manifest M
    python3 -m engine.asset_pipeline verify --manifest M
    python3 -m engine.asset_pipeline resolve <asset_id> --manifest M
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path

from PIL import Image

MANIFEST_SCHEMA = "v14.asset_manifest/1.0"
_STAGED_DIR = "assets"


# ---------------------------------------------------------------- hashing

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- manifest

class AssetManifest:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.data: dict = {"schema": MANIFEST_SCHEMA, "assets": []}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            if self.data.get("schema") != MANIFEST_SCHEMA:
                raise ValueError(f"{self.path}: unsupported manifest schema "
                                 f"{self.data.get('schema')!r}")

    # -- persistence ------------------------------------------------------
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data["assets"].sort(key=lambda a: a["asset_id"])
        self.path.write_text(json.dumps(self.data, indent=1, sort_keys=True))

    def _find(self, asset_id: str) -> dict | None:
        return next((a for a in self.data["assets"]
                     if a["asset_id"] == asset_id), None)

    # -- mutation ---------------------------------------------------------
    def register(self, file_path: str | Path, asset_id: str,
                 role: str, source: str = "raster") -> dict:
        p = Path(file_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"asset file not found: {p}")
        with Image.open(p) as im:
            w, h = im.size
        rel = Path(__import__("os").path.relpath(p, self.path.parent)
                   ).as_posix()
        entry = {"asset_id": asset_id, "path": rel,
                 "sha256": sha256_file(p), "role": role, "source": source,
                 "width": int(w), "height": int(h), "bytes": p.stat().st_size}
        old = self._find(asset_id)
        if old:
            self.data["assets"].remove(old)
        self.data["assets"].append(entry)
        return entry

    # -- lookup -----------------------------------------------------------
    def resolve(self, asset_id: str) -> dict:
        e = self._find(asset_id)
        if e is None:
            known = sorted(a["asset_id"] for a in self.data["assets"])
            raise KeyError(f"unknown asset_id {asset_id!r}; "
                           f"manifest has {known or 'no assets'}")
        out = dict(e)
        out["abs_path"] = (self.path.parent / e["path"]).resolve()
        return out

    def verify(self) -> tuple[bool, list[str]]:
        problems: list[str] = []
        for e in self.data["assets"]:
            p = self.path.parent / e["path"]
            if not p.is_file():
                problems.append(f"{e['asset_id']}: missing file {p}")
                continue
            got = sha256_file(p)
            if got != e["sha256"]:
                problems.append(f"{e['asset_id']}: sha256 mismatch "
                                f"(manifest {e['sha256'][:12]}, file {got[:12]})")
        return (not problems), problems


# ---------------------------------------------------------------- emitters

def raster_layer(layer_id: str, asset_id: str,
                 layer_type: str = "subject",
                 semantic_role: str = "hero_plate", *,
                 position: tuple[float, float] | None = None,
                 z: int = 5, depth: float = 0.3, opacity: float = 1.0,
                 visibility: list | None = None, fit: str = "cover",
                 extra_payload: dict | None = None) -> dict:
    """Scene IR layer whose visual source is a manifest-registered asset.
    Full-bleed plates use position [0,0] + fit cover (frame-anchored)."""
    if fit not in ("cover", "contain"):
        raise ValueError(f"fit must be cover|contain, got {fit!r}")
    payload = {"asset_id": asset_id, "fit": fit}
    if extra_payload:
        payload.update(extra_payload)
    lay: dict = {
        "id": layer_id, "type": layer_type, "semantic_role": semantic_role,
        "source": "raster", "position": list(position or [0.0, 0.0]),
        "scale": 1.0, "rotation": 0.0, "opacity": float(opacity),
        "z": int(z), "depth": float(depth), "payload": payload,
    }
    if visibility:
        lay["visibility"] = list(visibility)
    return lay


# ---------------------------------------------------------------- spec-side

def resolve_spec_assets(spec: dict, manifest: AssetManifest) -> dict:
    """Return a copy of spec with payload.path injected wherever a layer
    payload references payload.asset_id. Pure: input spec is not mutated.
    Raises KeyError on unknown asset ids (loud failure at compile time)."""
    out = deepcopy(spec)
    hits = 0
    for lay in out.get("layers", []):
        p = lay.get("payload") or {}
        if "asset_id" in p:
            entry = manifest.resolve(p["asset_id"])
            if not entry["abs_path"].is_file():
                raise FileNotFoundError(
                    f"asset {p['asset_id']!r} file missing: {entry['abs_path']}")
            p["path"] = str(entry["abs_path"])
            hits += 1
    if hits == 0:
        raise ValueError("resolve_spec_assets: no layer payload references "
                         "an asset_id — nothing to resolve")
    return out


def stage_assets(spec: dict, public_dir: str | Path) -> tuple[dict, list[dict]]:
    """Copy every referenced asset file into <public_dir>/assets/<sha12>.<ext>
    and rewrite payload.path to the served-relative path (Remotion staticFile).
    Content is hashed during staging — a file that no longer matches its
    manifest sha fails loudly here. Returns (staged_spec_copy, staged_list)."""
    out = deepcopy(spec)
    public = Path(public_dir)
    staged: list[dict] = []
    for lay in out.get("layers", []):
        p = lay.get("payload") or {}
        src = p.get("path")
        if not src:
            continue
        src_p = Path(src)
        if not src_p.is_file():
            raise FileNotFoundError(f"layer {lay['id']!r} asset missing: {src_p}")
        sha = sha256_file(src_p)
        dest_dir = public / _STAGED_DIR
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{sha[:12]}{src_p.suffix.lower()}"
        if not dest.exists():
            shutil.copyfile(src_p, dest)
        elif sha256_file(dest) != sha:
            dest.unlink()
            shutil.copyfile(src_p, dest)
        p["path"] = f"{_STAGED_DIR}/{dest.name}"
        staged.append({"layer": lay["id"], "sha256": sha,
                       "served_path": p["path"], "bytes": dest.stat().st_size})
    return out, staged


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.asset_pipeline")
    ap.add_argument("cmd", choices=["register", "list", "verify", "resolve"])
    ap.add_argument("pos", nargs="*")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--role", default="subject")
    ap.add_argument("--source", default="raster")
    args = ap.parse_args(argv)

    m = AssetManifest(args.manifest)
    if args.cmd == "register":
        if len(args.pos) != 2:
            ap.error("register <file> <asset_id>")
        e = m.register(args.pos[0], args.pos[1], args.role, args.source)
        m.save()
        print(json.dumps(e, indent=1, sort_keys=True))
    elif args.cmd == "list":
        for e in m.data["assets"]:
            print(f"{e['asset_id']:28s} {e['role']:12s} {e['source']:10s} "
                  f"{e['width']}x{e['height']} {e['sha256'][:12]} {e['path']}")
    elif args.cmd == "verify":
        ok, problems = m.verify()
        for pr in problems:
            print("FAIL", pr, file=sys.stderr)
        print("manifest OK" if ok else f"{len(problems)} problem(s)")
        return 0 if ok else 1
    elif args.cmd == "resolve":
        if len(args.pos) != 1:
            ap.error("resolve <asset_id>")
        print(json.dumps(m.resolve(args.pos[0]), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
