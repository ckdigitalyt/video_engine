"""2026-10-15 review, priority 4: one-frame comparison wording, no repeated
plate / re-cropped plate within a video, prompt dedupe, research context
threaded to the planner.

Run: python3 -m pytest -q tests/test_image_consistency_20261015.py   (no network)
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v15_pipeline as P  # noqa: E402
from engine import v15_plan as PL  # noqa: E402
from engine import v16_gate as g  # noqa: E402
from engine.v15_style import derive_bible, image_prompt  # noqa: E402


def test_comparison_prompt_asks_for_one_continuous_frame():
    b = derive_bible({})
    p = image_prompt(b, "the asteroid beside a city skyline", view="comparison")
    assert "Side-by-side" not in p
    assert "Single unified frame" in p and "one seamless continuous scene" in p


def _img(path, seed):
    im = Image.new("RGB", (540, 960), (10, 20, 30))
    d = ImageDraw.Draw(im)
    for k in range(12):
        x = (seed * 37 + k * 53) % 500
        y = (seed * 91 + k * 71) % 900
        d.ellipse([x, y, x + 40 + k * 6, y + 30 + k * 9],
                  fill=((seed * 40 + k * 20) % 255, (k * 30) % 255, 200))
    im.save(path)
    return str(path)


def _spec(path):
    return {"duration_s": 2.0, "layers": [{"source": "ai_image",
                                           "payload": {"path": path}}]}


def test_internal_reuse_flags_same_plate_and_recrop(tmp_path):
    a = _img(tmp_path / "a.png", 1)
    b = _img(tmp_path / "b.png", 7)
    meta = {"B1_S1": {}, "B2_S1": {}}
    assert g.check_internal_reuse(meta, {"B1_S1": _spec(a), "B2_S1": _spec(b)})["ok"]
    # same plate on two shots
    r = g.check_internal_reuse(meta, {"B1_S1": _spec(a), "B2_S1": _spec(a)})
    assert not r["ok"] and "2 shots" in r["fails"][0]
    # a centred 70% re-crop of the same image, upscaled back
    im = Image.open(a)
    W, H = im.size
    crop = im.crop((int(W * .15), int(H * .15), int(W * .85), int(H * .85))).resize((W, H))
    c = tmp_path / "c.png"
    crop.save(c)
    r = g.check_internal_reuse(meta, {"B1_S1": _spec(a), "B2_S1": _spec(str(c))})
    assert not r["ok"] and "re-cropped" in r["fails"][0], r


def test_dedupe_shot_prompts_gives_each_shot_its_own_image():
    bible = derive_bible({})
    beat = {"beat_id": "B9", "narration": "x"}
    shot = {"kind": "plate", "subject": "a droplet floating between two speakers",
            "view": "medium", "composition": "centered"}
    shots = [{"beat": beat, "idx": i, "shot": dict(shot), "hook": False,
              "prompts": P._prompts_for(shot, bible)} for i in range(3)]
    log = P.dedupe_shot_prompts(shots, bible)
    prompts = [s["prompts"][0] for s in shots]
    assert len(set(prompts)) == 3 and len(log) == 2
    views = [s["shot"]["view"] for s in shots]
    assert all(a != b for a, b in zip(views, views[1:])), views


def test_research_context_reaches_planner_prompt():
    from engine.v16_autostory import script_to_story
    eng = {"script": {"sentences": [
        {"text": "In 1933, scientists floated droplets.", "role": "hook",
         "fact_ids": ["f_1933"]}]}, "metadata": {"title": "Sound That Lifts Things"}}
    facts = {"claims": [{"id": "f_1933", "claim": "In 1933 a quartz crystal "
                         "levitated alcohol droplets in a laboratory."}]}
    story = script_to_story({"title": "t"}, eng, facts)
    assert "quartz crystal" in story["beats"][0]["context"]
    prompt = PL.build_prompt(story, derive_bible(story))
    assert "research facts" in prompt and "quartz crystal" in prompt
    assert "SPECIFIC SETTING" in prompt
