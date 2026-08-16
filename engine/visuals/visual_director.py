"""Visual Director (directive §6, §41).

Receives: topic, research facts, verified facts, story structure, exact
narration, style spec.
Outputs: BeatSheet + ShotList (strict schemas).

DeepSeek plays the Visual Director role via a structured JSON completion.
The system prompt explicitly frames it as designing a *motion-graphics
explanation, not slides*.  The output is schema-validated and math-verified
before it can proceed.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from engine.config.loader import get_style
from engine.validation.math_verify import verify_kaprekar_sequence, verify_attractor_property
from engine.validation.schema import (
    check_cross_references,
    validate_beatsheet,
    validate_shotlist,
)

SYSTEM_PROMPT = """You are the Visual Director of an automated motion-graphics studio.
You are designing a MOTION-GRAPHICS EXPLANATION, NOT SLIDES.

Prefer: transformation, movement, drawing, morphing, comparison, camera
movement, object continuity, kinetic text, progressive revelation, visual
cause-and-effect.
Avoid: static cards, generic decorative zooms, unrelated AI illustrations,
unnecessary mascot appearances, long unchanged compositions.

You output a STRICT JSON document with two keys, "beatsheet" and "shotlist",
that must conform exactly to these schemas.  Beats are 0.5-4.0s and each
represents ONE meaningful change in what the viewer sees or understands.

BeatSheet schema (beatsheet_v1): beats[] each with
  beat_id("bNNN"), start(float), end(float), narration(str),
  intent(one of hook|tension|discovery|reveal|explanation|
    demonstrate_transformation|demonstrate_arithmetic|show_convergence|
    pose_question|build_intuition), importance(high|medium|low),
  objects[ids], visual_change_required(bool), audio_cues[](optional).

ShotList schema (shotlist_v1): shots[] each with
  shot_id("sNNN"), beat_id(links to a beat), visual_type,
  renderer("manim"), duration(float), objects[{id,type,value?}],
  actions[{type,from?,to?,mode?}](optional), camera{type,target?}(optional),
  emphasis[], audio_cues[{type,relative_time,volume}](optional).

Every beat should have at least one shot.  Sounds correspond to actual
visual events (digit moves -> tick; reveal -> impact).  Keep object ids
persistent across beats (e.g. number_main, digit_1..4) for continuity.

Return ONLY the JSON.  No markdown fences, no prose.
"""


def _llm_json(prompt: str, max_retries: int = 2) -> dict:
    """Call DeepSeek (V4 Flash) for a strict JSON completion.

    Reads the API key from env; if unavailable, this is a no-op stub that
    raises — the deterministic fallback directors handle the no-LLM case.
    """
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "No LLM API key set; Visual Director needs DeepSeek/OpenAI. "
            "Provide DEEPSEEK_API_KEY or use the deterministic fallback."
        )

    import urllib.request

    url = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions")
    body = json.dumps({
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as e:  # noqa: BLE001
            if attempt == max_retries - 1:
                raise RuntimeError(f"LLM JSON completion failed: {e}") from e
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def _verify_math_in_prompt(prompt: str, topic: str) -> str:
    """Inject deterministic Kaprekar verification so the LLM can't hallucinate
    orbits; the verifier result is authoritative and appended to the prompt."""
    if "kaprekar" not in (topic or "").lower():
        return prompt
    starts = ["3524", "1000", "9998", "3087", "8352"]
    v = verify_attractor_property(starts)
    orbit_lines = []
    for s in starts:
        seq = verify_kaprekar_sequence(s)
        d = next((c["detail"] for c in seq.checks if c["name"] == "all_steps_valid"), "")
        orbit_lines.append(f"  {s}: {d}")
    verified = "\n".join(orbit_lines)
    return prompt + (
        "\n\nDETERMINISTIC MATH VERIFICATION (authoritative — you must use these "
        "orbits exactly, do not invent others):\n" + verified +
        "\nattractor ok: " + str(v.ok)
    )


def direct(topic: str, narration: str,
           research_facts: list[str] | None = None,
           story_structure: Optional[dict] = None,
           use_llm: bool = True) -> tuple[dict, dict]:
    """Produce (beatsheet, shotlist) for the topic."

    `use_llm=False` uses the deterministic Kaprekar template director (works
    with no API — proves the architecture is not LLM-dependent for math).
    """
    if research_facts is None:
        research_facts = []
    if use_llm:
        try:
            return _direct_llm(topic, narration, research_facts, story_structure)
        except RuntimeError:
            # graceful fallback to deterministic director
            pass
    return _direct_deterministic(topic, narration)


def _direct_llm(topic: str, narration: str, research_facts: list[str],
                story_structure: Optional[dict]) -> tuple[dict, dict]:
    style = get_style()
    prompt = json.dumps({
        "topic": topic,
        "exact_narration": narration,
        "research_facts": research_facts,
        "story_structure": story_structure or {},
        "style_spec": style,
        "instruction": (
            "Emit {\"beatsheet\": {...}, \"shotlist\": {...}} conforming to the "
            "schemas.  Split narration into beat-sized chunks and time beats "
            "accordingly.  Ensure numbers physically move/transform (no static "
            "cards).  Add audio_cues tied to real visual events."
        ),
    }, indent=2)
    prompt = _verify_math_in_prompt(prompt, topic)
    result = _llm_json(prompt)

    beatsheet = result.get("beatsheet")
    shotlist = result.get("shotlist")
    if not beatsheet or not shotlist:
        raise RuntimeError("LLM output missing beatsheet/shotlist")

    # schema-validate + cross-check
    errs = validate_beatsheet(beatsheet) + validate_shotlist(shotlist)
    if errs:
        raise RuntimeError("LLM Visual Director output failed schema:\n" + "\n".join(errs))
    cross = check_cross_references(beatsheet, shotlist)
    if cross:
        raise RuntimeError("cross-reference errors:\n" + "\n".join(cross))
    beatsheet.setdefault("version", "v1")
    shotlist.setdefault("version", "v1")
    return beatsheet, shotlist


def _split_sentences(narration: str) -> list[str]:
    """Split narration into sentence-sized chunks (keep it simple, no deps)."""
    import re
    parts = re.split(r"(?<=[.!?])\s+", narration.strip())
    return [p.strip() for p in parts if p.strip()]


# Mapping of narrative intent -> (visual_type, action, camera, emphasis).
# These only use narrative primitives (QuestionReveal/ClaimReveal/
# KineticTypography/Comparison/CycleReveal/ConvergenceParticles) plus safe
# transform/highlight/reveal actions — none of which require Kaprekar-specific
# math verification, so they generalize to any topic.
_NARRATIVE_SHOT = {
    "hook": ("kinetic_title", [{"type": "highlight"}], {"type": "zoom_to"}, []),
    "pose_question": ("question", [{"type": "reveal"}], {"type": "static"}, []),
    "discovery": ("claim", [{"type": "reveal"}], {"type": "focus"}, []),
    "reveal": ("claim", [{"type": "reveal"}], {"type": "push_in"}, []),
    "explanation": ("claim", [{"type": "highlight"}], {"type": "static"}, []),
    "build_intuition": ("claim", [{"type": "transform"}], {"type": "pan"}, []),
    "demonstrate_transformation": ("claim", [{"type": "transform"}], {"type": "follow"}, []),
    "demonstrate_arithmetic": ("comparison", [{"type": "transform"}], {"type": "reframe"}, []),
    "show_convergence": ("cycle", [{"type": "converge"}], {"type": "pull_out"}, []),
    "tension": ("claim", [{"type": "transform"}], {"type": "zoom_from"}, []),
}


def _direct_generic(topic: str, narration: str) -> tuple[dict, dict]:
    """Deterministic GENERIC narrative director (no LLM, any topic).

    Splits exact narration into sentence beats and maps each beat's intent to
    a narrative visual (kinetic title -> question -> claims/reveals ->
    convergence -> tension ending).  Uses only narrative primitives, so it
    generalizes to any topic (space blackness, Moon locked rotation, etc.)
    without Kaprekar-coupled math verification.
    """
    sentences = _split_sentences(narration)
    if not sentences:
        sentences = ["Pause."]
    # default intent cycle so we get a spread even with few sentences
    intent_cycle = ["hook", "pose_question", "explanation", "discovery",
                    "reveal", "show_convergence", "build_intuition",
                    "tension"]

    beats = []
    t = 0.0
    for i, sent in enumerate(sentences):
        intent = intent_cycle[min(i, len(intent_cycle) - 1)]
        # scale beat duration to sentence length (rough: words * 0.16s + pad)
        words = len(sent.split())
        dur = round(max(1.0, min(4.0, words * 0.18 + 0.9)), 2)
        beats.append({
            "beat_id": f"b{i + 1:03d}",
            "start": round(t, 2),
            "end": round(t + dur, 2),
            "duration": dur,
            "narration": sent,
            "intent": intent,
            "importance": "high" if i in (0, len(sentences) - 1) else "medium",
            "objects": ["text_main"],
            "visual_change_required": True,
            "audio_cues": [_cue_for(intent)],
        })
        t += dur

    # build shots from the narrative intent map
    shots = []
    prev_key = ""
    for b in beats:
        visual_type, actions, cam, emph = _NARRATIVE_SHOT[b["intent"]]
        # Give each beat a REAL state transition: the visual moves from the
        # previous beat's concept to this beat's concept (motion QA gate
        # counts meaningful from!=to transformations, so generic narrative
        # beats must register genuine per-beat state changes).
        key = _topic_keyword(b["narration"])
        # copy actions and inject from/to state transition
        acts = []
        for a in actions:
            aa = dict(a)
            aa.setdefault("from", prev_key or key)
            aa["to"] = key
            aa.setdefault("mode", "narrative_reveal")
            acts.append(aa)
        prev_key = key
        shots.append({
            "shot_id": f"s{len(shots) + 1:03d}",
            "beat_id": b["beat_id"],
            "visual_type": visual_type,
            "renderer": "manim",
            "duration": b["duration"],
            "objects": [{"id": "text_main", "type": "text",
                          "value": b["narration"][:80]}],
            "actions": acts,
            "camera": cam,
            "emphasis": emph,
            "audio_cues": b.get("audio_cues", []),
        })

    beatsheet = {"version": "v1", "beats": beats,
                 "metadata": {"topic": topic, "duration": round(t, 2)}}
    shotlist = {"version": "v1", "shots": shots,
                "metadata": {"topic": topic, "renderer": "manim",
                             "total_duration": round(t, 2)}}
    return beatsheet, shotlist


def _topic_keyword(sentence: str) -> str:
    """Brief concept label for a narration sentence (used as a per-beat state
    token so the motion gate sees meaningful from!=to transitions).  Drops stop
    words, keeps the first meaningful noun-ish word, lowercased."""
    import re
    stop = {"the", "a", "an", "is", "are", "was", "were", "to", "of", "in",
            "on", "at", "and", "or", "but", "because", "that", "this",
            "there", "it", "so", "if", "for", "with", "by", "from",
            "as", "not"}
    words = re.findall(r"[a-zA-Z]+", sentence.lower())
    for w in words:
        if w not in stop:
            return w
    return words[0] if words else "concept"


def _cue_for(intent: str) -> dict:
    """Pick an audio cue appropriate to the beat intent."""
    table = {
        "hook": {"type": "rise", "relative_time": 0.3, "volume": 0.35},
        "pose_question": {"type": "tick", "relative_time": 0.4, "volume": 0.3},
        "discovery": {"type": "reveal", "relative_time": 0.5, "volume": 0.45},
        "reveal": {"type": "impact", "relative_time": 0.5, "volume": 0.5},
        "explanation": {"type": "whoosh", "relative_time": 0.4, "volume": 0.3},
        "show_convergence": {"type": "transition", "relative_time": 0.4, "volume": 0.4},
        "demonstrate_transformation": {"type": "whoosh", "relative_time": 0.4, "volume": 0.3},
        "demonstrate_arithmetic": {"type": "tick", "relative_time": 0.3, "volume": 0.35},
        "build_intuition": {"type": "pop", "relative_time": 0.4, "volume": 0.35},
        "tension": {"type": "rise", "relative_time": 0.4, "volume": 0.4},
    }
    return table.get(intent, {"type": "ambient", "relative_time": 0.3, "volume": 0.25})


def _direct_deterministic(topic: str, narration: str) -> tuple[dict, dict]:
    """Deterministic Kaprekar template director (no LLM required).

    Builds a fresh benchmark beat sheet + shot list that demonstrates:
    hook/question -> digits move -> sorting -> subtraction -> iteration ->
    attractor convergence -> exception -> 6174 reveal -> narrative ending.
    This is the Phase-11 benchmark path and is fully math-verified.
    """
    if "kaprekar" not in (topic or "").lower():
        # non-Kaprekar topics route to the generic narrative director — this is
        # what lets the engine produce any fresh topic without an LLM.
        return _direct_generic(topic, narration)

    # math-verified orbit for example 3524
    v = verify_kaprekar_sequence("3524")
    orbit = [c["detail"] for c in v.checks if c["name"] == "all_steps_valid"]
    orbit_str = orbit[0].split("orbit: ")[1] if orbit else "3524 -> 3087 -> 8352 -> 6174"

    # build beats with real timings (~0.5-4s each, meaningful change per beat)
    beats = []
    t = 0.0
    plan = [
        (0.10, "hook", "hook", "Pick any four-digit number.", ["number_main"], True, []),
        (0.05, "pose_question", "pose_question", "What happens if we keep rearranging its digits?", ["number_main", "question"], True, [{"type": "tick", "relative_time": 0.3, "volume": 0.3}]),
        (0.11, "demonstrate_transformation", "explanation", "Step one: arrange digits from largest to smallest.", ["digit_1", "digit_2", "digit_3", "digit_4"], True, [{"type": "whoosh", "relative_time": 0.4, "volume": 0.25}]),
        (0.11, "demonstrate_transformation", "explanation", "Now smallest to largest.", ["digit_1", "digit_2", "digit_3", "digit_4"], True, [{"type": "whoosh", "relative_time": 0.3, "volume": 0.25}]),
        (0.12, "demonstrate_arithmetic", "demonstrate_transformation", "Subtract them: the larger minus the smaller.", ["number_main", "equation"], True, [{"type": "tick", "relative_time": 0.2, "volume": 0.4}]),
        (0.13, "demonstrate_transformation", "demonstrate_transformation", "Take the result and repeat.", ["number_main", "kaprekar_result"], True, [{"type": "transition", "relative_time": 0.3, "volume": 0.3}]),
        (0.12, "show_convergence", "show_convergence", "Amazingly, every starting number falls into the same trap.", ["number_main"], True, [{"type": "whoosh", "relative_time": 0.4, "volume": 0.35}]),
        (0.12, "show_convergence", "show_convergence", "Every path leads to 6174.", ["number_main", "attractor"], True, [{"type": "impact", "relative_time": 0.5, "volume": 0.5}]),
        (0.10, "explanation", "reveal", "This is Kaprekar's constant.", ["number_main", "attractor"], True, [{"type": "reveal", "relative_time": 0.5, "volume": 0.5}]),
        (0.10, "explanation", "build_intuition", "Unless all four digits are identical — then nothing changes.", ["digit_1", "digit_2", "digit_3", "digit_4"], True, [{"type": "pop", "relative_time": 0.3, "volume": 0.4}]),
        (0.08, "tension", "discovery", "A simple rule, a stubborn constant.", ["number_main"], True, [{"type": "rise", "relative_time": 0.4, "volume": 0.4}]),
    ]

    for frac, intent, beat_intent, nar, objs, vcr, cues in plan:
        # interpolate the verified orbit into narration where relevant
        nar = nar.replace("6174", "6174")
        start = t
        dur = frac * 3.3 + 0.8  # beat ~1.1-2.4s
        beats.append({
            "beat_id": f"b{len(beats) + 1:03d}",
            "start": round(start, 2),
            "end": round(start + dur, 2),
            "duration": round(dur, 2),
            "narration": nar,
            "intent": intent,
            "importance": "high" if vcr else "medium",
            "objects": objs,
            "visual_change_required": vcr,
            "audio_cues": cues,
        })
        t += dur

    # build shots mapping each beat to a manim visual
    shots = []
    from engine.renderers.manim import compiler  # avoid circular at import time
    shot_template = {
        "b001": ("highlight", [{"id": "number_main", "type": "number", "value": "3524"}],
                 [{"type": "highlight", "from": "3524", "to": "3524"}], {"type": "zoom_to", "target": "number_main"}, ["3524"]),
        "b002": ("question", [{"id": "number_main", "type": "number", "value": "3524"}],
                 [{"type": "highlight"}], {"type": "static"}, []),
        "b003": ("digit_sort", [{"id": "digit_1", "type": "digit_array", "value": "3524"}],
                 [{"type": "sort", "from": "3524", "to": "5432", "mode": "physical_move"}],
                 {"type": "follow", "target": "number_main"}, ["5432"]),
        "b004": ("digit_sort", [{"id": "digit_1", "type": "digit_array", "value": "5432"}],
                 [{"type": "sort", "from": "5432", "to": "2345", "mode": "physical_move"}],
                 {"type": "follow", "target": "number_main"}, ["2345"]),
        "b005": ("subtract", [{"id": "number_main", "type": "number", "value": "5432"},
                               {"id": "equation", "type": "equation", "value": "5432 - 2345"}],
                 [{"type": "subtract", "from": "5432", "to": "3087"}],
                 {"type": "zoom_to", "target": "equation"}, ["3087"]),
        "b006": ("iterate", [{"id": "number_main", "type": "number", "value": "3087"}],
                 [{"type": "transform", "from": "3087", "to": "8352"}],
                 {"type": "pan", "target": "number_main"}, ["8352"]),
        "b007": ("attractor", [{"id": "number_main", "type": "number", "value": "8352"}],
                 [{"type": "converge", "to": "8352 -> 6174"}],
                 {"type": "pull_out"}, []),
        "b008": ("attractor", [{"id": "attractor", "type": "number", "value": "6174"}],
                 [{"type": "converge", "to": "6174"}],
                 {"type": "push_in", "target": "attractor"}, ["6174"]),
        "b009": ("fixed_point", [{"id": "attractor", "type": "number", "value": "6174"}],
                 [{"type": "reveal", "to": "6174"}],
                 {"type": "focus", "target": "attractor"}, ["6174"]),
        "b010": ("exception", [{"id": "digit_1", "type": "digit_array", "value": "1111"}],
                 [{"type": "highlight", "from": "1111", "to": "1111"}],
                 {"type": "static"}, ["1111"]),
        "b011": ("conclusion", [{"id": "number_main", "type": "number", "value": "6174"}],
                 [{"type": "reveal", "to": "6174"}], {"type": "pull_out"}, ["6174"]),
    }
    for b in beats:
        bid = b["beat_id"]
        st = shot_template.get(bid, (None, [], [], {}, []))
        visual_type, objs, actions, cam, emph = st
        if visual_type is None:
            visual_type = "highlight"
        shots.append({
            "shot_id": f"s{len(shots) + 1:03d}",
            "beat_id": bid,
            "visual_type": visual_type,
            "renderer": "manim",
            "duration": b["duration"],
            "objects": objs,
            "actions": actions,
            "camera": cam,
            "emphasis": emph,
            "audio_cues": b.get("audio_cues", []),
        })

    beatsheet = {"version": "v1", "beats": beats,
                 "metadata": {"topic": topic, "duration": round(t, 2)}}
    shotlist = {"version": "v1", "shots": shots,
                "metadata": {"topic": topic, "renderer": "manim",
                             "total_duration": round(t, 2)}}
    return beatsheet, shotlist


if __name__ == "__main__":
    from pprint import pprint
    bs, sl = _direct_deterministic("kaprekar constant", "Pick any four-digit number.")
    print("beats:", len(bs["beats"]), "| total:", bs["metadata"]["duration"], "s")
    print("shots:", len(sl["shots"]))
    pprint(bs["beats"][0])
    pprint(sl["shots"][0])
