"""B2 (VIS): species anatomy library — brand/ink_ember/species.yaml.

An image model left to generic training priors routinely draws a plausible
but WRONG animal (a Stegosaurus with a frill, a three-fingered T. rex):
`anatomy_for` finds the species an image subject names and returns its
non-negotiable anatomical fragment, spliced into BOTH the image-generation
prompt (engine.v15_style.image_prompt via engine.v15_pipeline) and the
vision judge's checklist (engine.v15_plates.plate_qa) so the same anatomy
claim is asked for and checked for.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent.parent
SPECIES_PATH = REPO / "brand" / "ink_ember" / "species.yaml"


@lru_cache(maxsize=1)
def load_species() -> dict:
    if not SPECIES_PATH.exists():
        return {}
    return (yaml.safe_load(SPECIES_PATH.read_text()) or {}).get("species") or {}


def species_for(subject: str) -> list:
    """subject text -> [(species_id, anatomy_fragment), ...] for every
    species whose `match` alias appears in it (order: library order)."""
    low = str(subject).lower()
    out = []
    for sid, spec in load_species().items():
        if any(alias.lower() in low for alias in spec.get("match") or [sid]):
            out.append((sid, spec.get("anatomy", "")))
    return out


def augment_subject(subject: str) -> str:
    """Append every matched species' anatomy fragment to an image-gen
    subject string; subjects naming no known species pass through."""
    hits = [a for _, a in species_for(subject) if a]
    if not hits:
        return subject
    return subject.rstrip(". ") + ". " + " ".join(hits)
