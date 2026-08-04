#!/usr/bin/env python3
"""Smoke-test the Jade spec v9 modules against real pipeline artifacts."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.qa.voice_lock import VoiceLock, lock_voice
from src.director.style_bible import StyleBible, create_style_bible
from src.manim.validate import validate_manim_script, validate_manim_facts
from src.qa.jade_gates import PreRenderGate, PublishGate

print("=" * 70)
print("1) VOICE LOCK")
vl = lock_voice(provider="edge", voice_id="en-US-ChristopherNeural",
                speaker_id="jade-narrator-001", force=True)
for i in range(5):
    vl.record_scene(i, "edge", "en-US-ChristopherNeural")
vl.save()
print("   switching check:", vl.check_voice_switching())
# simulate a silent fallback swap -> must FAIL the gate
vl_bad = VoiceLock(provider="edge", voice_id="en-US-ChristopherNeural", speaker_id="x")
vl_bad.record_scene(0, "edge", "en-US-ChristopherNeural")
vl_bad.record_scene(1, "kokoro", "bm_george", override=True, reason="edge down")
print("   switching check (bad):", vl_bad.check_voice_switching()["passed"],
      "->", vl_bad.check_voice_switching()["metrics"]["problems"][:2])

print("=" * 70)
print("2) STYLE BIBLE")
sb = create_style_bible("jade", force=True)
sb.placed_style_tokens = {
    "scene0_0.jpg": "Photorealistic documentary image. hand-painted cinematic concept art, painterly brushwork, no text",
    "scene0_1.jpg": "hand-painted cinematic concept art, warm amber palette, no text",
}
print("   drift check:", sb.check_style_drift())
sb.placed_style_tokens["scene2_0.jpg"] = "flat vector corporate render, neon colors"  # drift
print("   drift check (bad):", sb.check_style_drift()["passed"], "->", sb.check_style_drift()["metrics"]["drifted"])

print("=" * 70)
print("3) MANIM VALIDATION (real scenes, resolved from src/manim/scenes/)")
from src.qa.jade_gates import _manim_script_for
for clip in ["cache/manim/voyager_scale.mp4", "cache/manim/black_hole_lensing.mp4",
             "cache/manim/pulsar_lighthouse.mp4", "cache/manim/sun_scale.mp4",
             "cache/manim/pulsar_density.mp4", "cache/manim/voyager_timeline.mp4"]:
    script = _manim_script_for(clip)
    if not script:
        print(f"   {os.path.basename(clip):28s} NO SOURCE (skip)")
        continue
    mv = validate_manim_script(script)
    print(f"   {os.path.basename(clip):28s} valid={mv.valid} kinetic={mv.kinetic} "
          f"plays={mv.play_calls} wait={mv.total_wait_s:.1f}s {mv.errors[:1]}")
# negative test: static scene
import tempfile
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
    f.write("from manim import *\nclass StaticScene(Scene):\n    def construct(self):\n"
            "        t = Text('title')\n        self.add(t)\n        self.wait(12)\n")
    bad_script = f.name
mv = validate_manim_script(bad_script)
print(f"   static scene -> valid={mv.valid} (expect False), errors={mv.errors}")
os.unlink(bad_script)

print("=" * 70)
print("4) PRE-RENDER GATE (on a real timeline if present)")
tl = None
for cand in ["results/black_holes__where_space_ends/timeline.json",
             "results/mars__the_red_planet/timeline.json"]:
    if os.path.exists(cand):
        tl = cand
        break
if tl:
    pg = PreRenderGate().run(timeline_path=tl, audio_dir="cache/audio",
                             voice_lock=vl, style_bible=sb)
    print("   blockers:", pg["blocking_failures"])
    for c in pg["checks"]:
        print(f"     {'PASS' if c['passed'] else 'FAIL'} {c['name']}: {c['detail'][:80]}")
else:
    print("   no timeline artifact found")

print("=" * 70)
print("5) PUBLISH GATE (on a real final video if present)")
vid = None
for cand in ["results/black_holes__where_space_ends/black_holes__where_space_ends_mixed.mp4",
             "results/mars__the_red_planet/mars__the_red_planet_mixed.mp4"]:
    if os.path.exists(cand):
        vid = cand
        break
if vid:
    pub = PublishGate().run(video_path=vid, timeline_path=tl or "",
                            voice_lock=vl, style_bible=sb)
    print(f"   publish_ready={pub['publish_ready']}")
    print("   blockers:", pub["blocking_failures"])
    for c in pub["checks"]:
        print(f"     {'PASS' if c['passed'] else 'FAIL'} {c['name']}: {c['detail'][:80]}")
    with open("cache/v9_gate_smoke.json", "w") as f:
        json.dump(pub, f, indent=2)
else:
    print("   no video artifact found")

print("=" * 70)
print("SMOKE TEST DONE")
