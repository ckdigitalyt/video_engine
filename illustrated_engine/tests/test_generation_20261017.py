"""2026-10-17 generation pass: ~6 batches since the first publish produced
zero passes. The owner's diagnosis -- the gate is fine, the generated
images and voice are not -- held up in the batch evidence
(build/v16/batches/live_20261016_204600 .. live_20261017_121500):

- plates that FAILED generation were never retried and became PROCEDURAL
  shots (B1 hook / B7-B8 payoff most of all: hero prompts may not use
  pollinations); Cloudflare 429s came from 3 workers bursting it; sdcpp_
  local ran 3 CPU jobs at once, each past its 1800 s timeout (plates_s up
  to 6570 s); NIM waited 180 s x 3 endpoints on hung reads;
- the archive tier searched for the VIEW phrase, never the subject;
- resubject prompts from pronoun-only narration had nothing to draw, and
  stripped the pronoun "one";
- one 2-word subject threw a whole LLM plan away for the fallback floor,
  whose identical subjects put one plate on 4 shots (internal_reuse);
- Kokoro read years as cardinals ("one thousand eight hundred ninety one"),
  misread "winds"/"supernovae"/"Laetoli"/"Uyuni", and the single voice retry
  (respell at 0.95x) almost never changed the outcome.

The quality bar (plate QA, max_wer 0.03, hard tokens, gate) is unchanged.

Run: python3 -m pytest -q tests/test_generation_20261017.py   (no network)
"""
import io
import sys
import threading
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v15_pipeline as P  # noqa: E402
from engine import v15_plan as PL  # noqa: E402
from engine.voice import qa  # noqa: E402
from engine.voice.lexicon import Lexicon  # noqa: E402
from engine.voice.text import norm_tokens, speakable_years, year_words  # noqa: E402
from src.providers import image_gen as G  # noqa: E402


# ------------------------------------------------- failed-generation retry --

def test_failed_plates_get_a_sequential_retry_hero_first_then_capped_floor():
    plates = {"a": {"ok": True}, "hook": {"ok": False}, "b": {"ok": False},
              "c": {"ok": False}, "d": {"ok": False}}
    calls, slept = [], []

    def regen(p):
        calls.append(("cloud", p))
        return {"ok": p in ("b",), "provider": "cloudflare_workers_ai"}

    def floor(p):
        calls.append(("floor", p))
        return {"ok": True, "provider": "sdcpp_local"}
    log = P.recover_failed_plates(plates, ["a", "b", "c", "hook", "d", "b"],
                                  regen, hero={"hook"}, floor=floor,
                                  floor_cap=2, sleep=slept.append)
    assert slept == [P.GEN_RETRY_COOLDOWN_S]          # cooled down once
    # every failed plate retried once on the cloud chain, the hook first
    assert [c for c in calls if c[0] == "cloud"] == [
        ("cloud", "hook"), ("cloud", "b"), ("cloud", "c"), ("cloud", "d")]
    # floor only for what is still failing, hero first, capped per video
    assert [c for c in calls if c[0] == "floor"] == [("floor", "hook"),
                                                     ("floor", "c")]
    assert plates["hook"]["ok"] and plates["b"]["ok"] and not plates["d"]["ok"]
    assert log == {"first_pass_failed": 4, "recovered": 1, "floor_tried": 2,
                   "floor_used": 2, "still_failed": 1}


def test_nothing_failed_means_no_cooldown_and_no_calls():
    slept = []
    log = P.recover_failed_plates({"a": {"ok": True}}, ["a"], None,
                                  sleep=slept.append)
    assert slept == [] and log["first_pass_failed"] == 0


def test_local_floor_is_out_of_the_parallel_first_pass():
    assert P.FLOOR_PROVIDERS == ("sdcpp_local",)
    src = Path(P.__file__).read_text()
    assert "x not in FLOOR_PROVIDERS" in src


# ------------------------------------------------------------- providers --

def _http(code, body=b""):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(body))


def test_cloudflare_rate_limit_429_is_retried(monkeypatch, tmp_path):
    import base64

    from PIL import Image
    buf = io.BytesIO()
    Image.effect_noise((256, 256), 80).convert("RGB").save(buf, "PNG")
    ok = ('{"result": {"image": "%s"}}' % base64.b64encode(buf.getvalue())
          .decode()).encode()
    n = {"calls": 0}

    def post(url, fields, headers, timeout):
        n["calls"] += 1
        if n["calls"] <= 2:
            raise _http(429, b'{"errors":[{"message":"Too many requests"}]}')
        return ok, "application/json"
    monkeypatch.setattr(G, "_multipart_post", post)
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    p = G.CloudflareWorkersAIProvider("acct", "tok")
    p.generate("x", str(tmp_path / "o.png"), 720, 1280, seed=1)
    assert n["calls"] == 3 and (tmp_path / "o.png").exists()


def test_cloudflare_daily_allocation_429_is_final(monkeypatch, tmp_path):
    n = {"calls": 0}

    def post(url, fields, headers, timeout):
        n["calls"] += 1
        raise _http(429, b'{"errors":[{"code":4006,"message":"you have used '
                         b'up your daily free allocation of 10,000 neurons"}]}')
    monkeypatch.setattr(G, "_multipart_post", post)
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    try:
        G.CloudflareWorkersAIProvider("acct", "tok").generate(
            "x", str(tmp_path / "o.png"))
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "daily allocation" in str(e)
    assert n["calls"] == 1


def test_nim_read_timeout_is_short():
    # every NIM plate in 3 days of cache landed in <= 17 s
    assert G.NvidiaNimProvider.READ_TIMEOUT_S <= 60


def test_sdcpp_runs_one_job_at_a_time(monkeypatch, tmp_path):
    live, peak = {"n": 0}, {"n": 0}
    lock = threading.Lock()

    class Proc:
        returncode = 0
        stderr = stdout = ""

    def run(cmd, **kw):
        with lock:
            live["n"] += 1
            peak["n"] = max(peak["n"], live["n"])
        time.sleep(0.05)
        with lock:
            live["n"] -= 1
        return Proc()
    monkeypatch.setattr(G.subprocess, "run", run)
    monkeypatch.setattr(G, "_looks_like_image", lambda p: True)
    prov = G.SDCppLocalProvider()
    monkeypatch.setattr(prov, "is_available", lambda: True)
    ts = [threading.Thread(target=prov.generate,
                           args=("x", str(tmp_path / f"{i}.png")))
          for i in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert peak["n"] == 1


# --------------------------------------------------------------- archive --

def test_archive_searches_the_subject_not_the_view_phrase():
    a = G.ArchiveProvider()
    prompt = ("vivid painting. Low ground-level view from right on the "
              "surface: fossilized rhino skeleton entombed in ash (A "
              "barrel-bodied rhino skeleton lying on its side). centered")
    subj = a._subject(prompt)
    assert subj == "fossilized rhino skeleton entombed in ash"
    assert a._query_terms(subj) == "fossilized rhino skeleton entombed"
    # the live_20261017 queries were the view boilerplate
    assert "close-up" not in a._query_terms(a._subject(
        "s. Extreme close-up of surface detail filling the whole frame: a "
        "meteorite fragment on sand. c"))


def test_archive_only_serves_plain_views(monkeypatch, tmp_path):
    a = G.ArchiveProvider()
    monkeypatch.setattr(a, "_search_nasa", lambda q: None)
    monkeypatch.setattr(a, "_search_met", lambda q: None)
    for view in ("Cutaway cross-section view", "Extreme close-up of surface "
                 "detail filling the whole frame", "Scroll-stopping opening shot"):
        try:
            a.generate(f"s. {view}: a meteorite on sand. c", str(tmp_path / "x"))
            raise AssertionError(view)
        except RuntimeError as e:
            assert "needs a drawn plate" in str(e)
    try:
        a.generate("s. Wide establishing view: a meteorite on sand. c",
                   str(tmp_path / "x"))
    except RuntimeError as e:
        assert "no PD/CC0 match for 'meteorite sand'" in str(e)


def test_archive_hit_must_be_relevant_and_unused():
    a = G.ArchiveProvider
    assert a._relevant("hubble space telescope orbit",
                       "The Hubble Space Telescope in orbit over Earth")
    assert not a._relevant("fossilized rhino skeleton entombed",
                           "Apollo 11 crew portrait")
    url = "https://images-assets.nasa.gov/test/unique-claim.jpg"
    assert a._claim(url) and not a._claim(url)      # never on two shots


# --------------------------------------------------------- resubject/plan --

IDENT = {"name": "the rocket exhaust plume with glowing shock diamonds",
         "aliases": ["shock diamonds", "the plume"],
         "description": "A cone-shaped translucent plume of blue-white "
                        "exhaust studded with glowing diamond-shaped nodes."}


def test_resubject_anchors_pronoun_narration_to_the_subject(monkeypatch):
    monkeypatch.setattr(P, "image_prompt",
                        lambda bible, subj, comp, view=None, hook=False: subj)
    _, subj = P.resubject_prompt({}, "The fire screams past them, yet they "
                                     "stay put.", IDENT)
    assert subj.startswith("the rocket exhaust plume with glowing shock "
                           "diamonds (A cone-shaped")
    assert subj.endswith("The fire screams past them, yet they stay put")
    # a narration that names the subject keeps the old splice
    _, subj2 = P.resubject_prompt({}, "Those shock diamonds hang still.", IDENT)
    assert subj2.startswith("Those shock diamonds (A cone-shaped")


def test_pronoun_one_survives_number_stripping():
    strip = lambda t: " ".join(P._NUMWORDS_RE.sub("", t).split())  # noqa: E731
    assert strip("it snaps, and a brand-new one forms") == \
        "it snaps, and a brand-new one forms"
    assert "hundred" not in strip("one hundred sixty-eight thousand cubic meters")
    assert not strip("one hundred").startswith("one")


NIAGARA = {"story_id": "t_niagara", "title": "Niagara Is Slowly Eating the Border",
           "beats": [
               {"beat_id": "B1", "function": "HOOK",
                "narration": "Niagara loses an estimated sixty tonnes of salts "
                             "and rock per minute."},
               {"beat_id": "B2", "function": "NORMAL",
                "narration": "That dissolved grit is what turns the water green."},
               {"beat_id": "B3", "function": "NORMAL",
                "narration": "Not meters per second. Kilometers per second."}]}
FALLS = {"name": "Horseshoe Falls", "aliases": ["niagara", "the falls"],
         "description": "A massive curved waterfall with a wide horseshoe-"
                        "shaped crest"}


def test_fallback_plan_gives_each_beat_its_own_subject():
    plan = PL.fallback_plan(NIAGARA, FALLS)
    assert PL.validate_plan(plan, NIAGARA) == []
    firsts = [b["shots"][0]["subject"] for b in plan["beats"]]
    assert firsts[0].startswith("Horseshoe Falls, Niagara loses")
    assert firsts[1] == "Horseshoe Falls, That dissolved grit is what turns the water green"
    assert len(set(firsts)) == 3
    assert "sixty" not in firsts[0]                  # figures stay out
    # nothing drawable in the narration -> the identity alone (2026-10-11)
    assert "meters" not in firsts[2].lower()


def test_salvage_replaces_a_bare_subject_instead_of_dropping_the_plan():
    plan = {"beats": [
        {"beat_id": "B1", "shots": [{"kind": "plate", "start_word": 0,
                                     "headline": "NIAGARA IS EATING",
                                     "subject": "a huge curved waterfall pouring "
                                                "into white mist", "view": "wide",
                                     "camera": "push_in"}]},
        {"beat_id": "B2", "shots": [{"kind": "plate", "start_word": 0,
                                     "subject": "Horseshoe Falls",
                                     "view": "medium", "camera": "rise"}]},
        {"beat_id": "B3", "shots": [{"kind": "plate", "start_word": 0,
                                     "subject": "a sheer limestone cliff behind "
                                                "the falls", "view": "cutaway",
                                     "camera": "pan_left"}]}]}
    assert PL.validate_plan(plan, NIAGARA)            # one bad subject
    sal, dropped = PL.salvage(plan, NIAGARA, FALLS)
    assert PL.validate_plan(sal, NIAGARA) == []
    assert sal["beats"][2]["shots"][0]["subject"].startswith("a sheer limestone")
    assert sal["beats"][1]["shots"][0]["subject"].startswith("Horseshoe Falls, ")
    assert any("subject replaced" in d for d in dropped)


def test_fallback_headline_drops_an_unspoken_title_figure():
    story = {"story_id": "t_log", "title": "This Log Is Only 10% Wood",
             "beats": [{"beat_id": "B1", "function": "HOOK",
                        "narration": "This log is only ten percent wood."}]}
    plan = PL.fallback_plan(story, None)
    assert PL.validate_plan(plan, story) == []


# ------------------------------------------------------------------ voice --

def test_years_are_spoken_as_years():
    assert speakable_years("On April 25th, 1891, Tesla") == \
        "On April 25th, eighteen ninety-one, Tesla"
    assert speakable_years("back in 1962, as INCOSPAR.") == \
        "back in nineteen sixty-two, as INCOSPAR."
    assert speakable_years("Since June 2022, Webb") == \
        "Since June twenty twenty-two, Webb"
    assert speakable_years("in the 1960s") == "in the nineteen sixties"
    assert year_words(1905) == "nineteen oh five"
    assert year_words(1900) == "nineteen hundred"
    assert year_words(2007) == "two thousand seven"
    # quantities stay quantities
    assert speakable_years("about 1500 meters down") == "about 1500 meters down"
    assert speakable_years("1,500 people") == "1,500 people"


def test_voice_cache_key_changes_with_speak_version():
    from engine import voice as V
    cfg = V.load_config()
    k1 = V._sidecar_key("kokoro_michael", cfg, "In 1891.", "normal", 1.0)
    old = V.SPEAK_VERSION
    try:
        V.SPEAK_VERSION = "speak/1"
        assert V._sidecar_key("kokoro_michael", cfg, "In 1891.", "normal", 1.0) != k1
    finally:
        V.SPEAK_VERSION = old


def test_isolate_breaks_before_the_misheard_word_only():
    from engine import voice as V
    assert V._isolate("Their descendants finish the trip, living on.", [2]) == \
        "Their descendants, finish the trip, living on."
    assert V._isolate("Ash, fine as powder.", [0, 1]) == "Ash, fine as powder."
    assert V._bad_words_by_sentence(["Not mud.", "Ash, fine as powder."],
                                    {"bad_word_idx": [4]}) == {1: [2]}


def test_retry_variants_run_until_one_passes_and_keep_the_best(tmp_path):
    import numpy as np

    from engine import voice as V

    class Prov:
        calls = []

        def synth(self, text, speed):
            Prov.calls.append((text, round(speed, 3)))
            return V.Clip(np.full(2400, 0.2, dtype=np.float32), 24000, None)
    cfg = V.load_config()
    script = "Their descendants finish the trip."
    heard = iter(["their descendants finished the trip",   # first pass
                  "their descendants finished the trip",   # respell_slow
                  "their descendants finish the trip"])    # isolate -> PASS

    def asr(wav):
        return [{"w": w, "t0": 0.2 * i, "t1": 0.2 * i + 0.1}
                for i, w in enumerate(next(heard).split())]
    r = V.synthesize([V.Sentence(script)], cfg, tmp_path / "v.wav",
                     provider=Prov(), lexicon=Lexicon(), asr_fn=asr)
    assert r.qa["verdict"] == "PASS" and r.qa["retry_variant"] == "isolate"
    assert Prov.calls[-1][0] == "Their descendants, finish the trip."
    assert len(Prov.calls) == 3


def _rt(script, heard):
    asr = [{"w": w, "t0": 0.3 * i, "t1": 0.3 * i + 0.25}
           for i, w in enumerate(heard.split())]
    return qa.round_trip(script, asr, Lexicon(), 0.03)


def test_exact_homophones_tonnes_and_tuff():
    assert norm_tokens("tonnes") == norm_tokens("tons")
    assert _rt("Niagara loses an estimated sixty tonnes of salts and rock "
               "per minute.", "niagara loses an estimated 60 tons of salts "
               "and rock per minute")["verdict"] == "PASS"
    assert _rt("It cemented the ash into solid rock called tuff.",
               "it cemented the ash into solid rock called tough")["verdict"] == "PASS"
    # a genuinely different word still fails
    assert _rt("sixty tonnes of rock", "sixty tunes of rock")["verdict"] == "FAIL"


def test_lexicon_carries_the_misread_words():
    from engine import voice as V
    lex = V.load_lexicon(V.load_config())
    assert lex.entries["winds"]["phonemes"] == "wˈɪndz"       # noun, not wind-up
    assert lex.entries["supernovae"]["phonemes"].endswith("viː")
    assert "laetoli" in lex.entries and "salar de uyuni" in lex.entries


# ------------------------------------------------------- plate info floor --

def _img(tmp_path, name, arr):
    import numpy as np
    from PIL import Image
    p = tmp_path / name
    Image.fromarray(np.clip(arr, 0, 255).astype("uint8")).convert("RGB").save(p)
    return p


def test_dark_flat_plate_is_flagged_before_render(tmp_path):
    import numpy as np
    rng = np.random.default_rng(0)
    # a near-black painting with one soft glow (the live_20261017 webb B7_S1
    # kind: mean luma ~19, edge 1.37) vs a lit, textured plate
    yy, xx = np.mgrid[0:1280, 0:720]
    glow = 18 + 60 * np.exp(-((xx - 360) ** 2 + (yy - 640) ** 2) / 2e5)
    dark = _img(tmp_path, "dark.png", glow)
    busy = _img(tmp_path, "busy.png", 120 + rng.normal(0, 50, (1280, 720)))
    m = P.plate_low_information(dark)
    assert m and m["edge"] < 2.2
    assert P.plate_low_information(busy) is None
    assert P.plate_low_information(tmp_path / "missing.png") is None


def test_low_information_steering_asks_for_a_lit_detailed_frame(monkeypatch):
    seen = {}

    def fake(bible, subj, comp, view=None, hook=False):
        seen.update(subj=subj, view=view)
        return subj
    monkeypatch.setattr(P, "image_prompt", fake)
    P.steer_prompt({}, {"subject": "a distant galaxy smudge", "view": "wide",
                        "composition": "centered"}, "low_information", 1)
    assert "Brightly lit" in seen["subj"] and "no large empty" in seen["subj"]
    assert seen["view"] == "medium"
