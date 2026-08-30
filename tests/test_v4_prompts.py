"""test_v4_prompts.py — Golden tests for the §11 cinematic prompt builder.

Deterministic by contract: same ShotSpec → same prompt, no LLM.
"""

import pytest

from engine.v4.prompts import (
    ShotSpec,
    build_cinematic_prompt,
    build_negative_prompt,
    build_shot_bundle,
)

DINO = dict(
    subject="A herd of hadrosaurs",
    action="moves rapidly between towering cycads while a Tyrannosaurus "
           "emerges in the deep background",
    environment="Late Cretaceous forest",
    camera_move="tracking",
    shot_scale="wide",
    lighting_change="warm late-afternoon sunlight filtering through vegetation",
    motion="leaves and dust moving through the foreground",
    sequence="escalating urgency as the herd rushes toward the lens",
    duration_sec=6.0,
)


# ── Goldens ──────────────────────────────────────────────────────────────


def test_ltx_golden_dino_herd():
    spec = ShotSpec(**DINO)
    prompt = build_cinematic_prompt(spec, variant="ltx")
    # §10: subject, action, environment, camera, movement, lighting, sequence —
    # each clause explicitly present, in that order.
    assert prompt == (
        "A herd of hadrosaurs moves rapidly between towering cycads while a "
        "Tyrannosaurus emerges in the deep background, Set in Late Cretaceous "
        "forest, Wide establishing shot, tracking shot following the subject, "
        "leaves and dust moving through the foreground, warm late-afternoon "
        "sunlight filtering through vegetation, escalating urgency as the "
        "herd rushes toward the lens, cinematic, photorealistic, high "
        "detail, natural motion, shallow depth of field."
    )


def test_generic_golden_asteroid():
    spec = ShotSpec(
        subject="A mountain-sized asteroid",
        action="streaks into the frame against the black of space",
        environment="deep space above the Earth's limb",
        camera_move="push_in",
        shot_scale="wide",
        lighting_change="harsh sunlight glinting off the asteroid's pits",
        duration_sec=4.0,
    )
    prompt = build_cinematic_prompt(spec, variant="generic")
    assert prompt.startswith("Wide establishing shot.")
    assert "The camera pushes in steadily toward the subject." in prompt
    assert "A mountain-sized asteroid streaks into the frame" in prompt
    assert "in deep space above the Earth's limb." in prompt
    assert "harsh sunlight glinting" in prompt
    assert prompt[0].isupper()


# ── Structure guarantees ─────────────────────────────────────────────────


def test_all_clause_families_present_in_ltx_variant():
    spec = ShotSpec(**DINO)
    p = build_cinematic_prompt(spec, variant="ltx")
    for clause in ("Set in ", "Wide establishing shot", "tracking shot",
                   "sunlight", "escalating urgency"):
        assert clause in p


def test_deterministic_repeated_calls():
    spec = ShotSpec(**DINO)
    assert build_cinematic_prompt(spec, variant="ltx") == \
        build_cinematic_prompt(spec, variant="ltx")
    assert build_cinematic_prompt(spec, variant="generic") == \
        build_cinematic_prompt(spec, variant="generic")


def test_invalid_camera_move_and_scale_rejected():
    with pytest.raises(ValueError):
        ShotSpec(subject="x", camera_move="teleport")
    with pytest.raises(ValueError):
        ShotSpec(subject="x", shot_scale="panoramic")
    with pytest.raises(ValueError):
        ShotSpec(subject="")


def test_unknown_variant_rejected():
    with pytest.raises(ValueError):
        build_cinematic_prompt(ShotSpec(subject="x"), variant="midjourney")


def test_optional_llm_polish_pass():
    spec = ShotSpec(subject="a fox", action="leaps over a log")

    def polish(prompt: str) -> str:
        return prompt + " POLISHED"

    assert build_cinematic_prompt(spec, polish_fn=polish).endswith("POLISHED")
    # Default: no LLM, deterministic.
    assert not build_cinematic_prompt(spec).endswith("POLISHED")


def test_bundle_includes_negative_and_metadata():
    spec = ShotSpec(**DINO)
    bundle = build_shot_bundle(spec, variant="ltx")
    assert bundle["prompt"] == build_cinematic_prompt(spec, variant="ltx")
    assert "watermark" in bundle["negative_prompt"]
    assert bundle["camera_move"] == "tracking"
    assert bundle["shot_scale"] == "wide"
    assert bundle["duration_sec"] == 6.0
    assert build_negative_prompt(spec).startswith("blurry, low quality")
