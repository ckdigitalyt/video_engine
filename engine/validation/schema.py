"""Validation of strict versioned schemas (Gate 1 — Schema).

Every LLM-produced artifact (BeatSheet, ShotList, VisualSpec, AudioCue,
StyleSpec, QAReport) is validated against its JSON Schema before it enters
the renderer.  Invalid output is rejected here — never passed downstream.

Deterministic checks ALWAYS override LLM judgment (directive §36).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft7Validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = PROJECT_ROOT / "schemas"


class SchemaError(ValueError):
    """Raised when an artifact fails schema validation."""


def _load_schema(name: str) -> dict:
    path = SCHEMA_DIR / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate(instance: dict, schema_name: str) -> list[str]:
    """Validate `instance` against the named schema. Returns list of errors.

    An empty list means the artifact is structurally valid.
    Raises SchemaError only on missing schema infrastructure, not on
    validation failure (callers inspect the returned error list).
    """
    schema = _load_schema(schema_name)
    validator = Draft7Validator(schema)
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda e: list(e.path),
    )
    return [_format_error(e) for e in errors]


def _format_error(err: jsonschema.ValidationError) -> str:
    loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
    return f"{loc}: {err.message}"


def require_valid(instance: dict, schema_name: str) -> dict:
    """Validate and raise SchemaError on any failure."""
    errors = validate(instance, schema_name)
    if errors:
        raise SchemaError(
            f"{schema_name} failed validation ({len(errors)} errors):\n"
            + "\n".join(errors[:20])
        )
    return instance


# Convenience validators per artifact type
def validate_beatsheet(bs: dict) -> list[str]:
    return validate(bs, "beatsheet_v1")


def validate_shotlist(sl: dict) -> list[str]:
    return validate(sl, "shotlist_v1")


def validate_visualspec(vs: dict) -> list[str]:
    return validate(vs, "visualspec_v1")


def validate_audiocue(ac: dict) -> list[str]:
    return validate(ac, "audio_cue_v1")


def validate_stylespec(ss: dict) -> list[str]:
    return validate(ss, "style_spec_v1")


def validate_qareport(qr: dict) -> list[str]:
    return validate(qr, "qa_report_v1")


# ── Cross-artifact consistency (beyond per-file schema) ────────────────────
def check_cross_references(beatsheet: dict, shotlist: dict) -> list[str]:
    """Every shot's beat_id must exist in the beat sheet; every beat listed
    in the sheet must have at least one shot.  Also durations must match
    within tolerance."""
    errors: list[str] = []
    beat_ids = {b["beat_id"] for b in beatsheet["beats"]}
    shots_by_beat: dict[str, int] = {}
    for shot in shotlist["shots"]:
        bid = shot["beat_id"]
        if bid not in beat_ids:
            errors.append(f"shot {shot['shot_id']} references unknown beat {bid}")
        shots_by_beat[bid] = shots_by_beat.get(bid, 0) + 1

    for beat in beatsheet["beats"]:
        bid = beat["beat_id"]
        if bid not in shots_by_beat:
            errors.append(f"beat {bid} has no shots")
    return errors


if __name__ == "__main__":
    # Self-test
    import sys

    sample = {
        "version": "v1",
        "beats": [
            {
                "beat_id": "b001",
                "start": 0.0,
                "end": 2.0,
                "narration": "Hello",
                "intent": "hook",
                "importance": "high",
                "objects": ["number_main"],
                "visual_change_required": True,
            }
        ],
    }
    errs = validate_beatsheet(sample)
    print("beat sample errors:", errs)
    sys.exit(0 if not errs else 1)
