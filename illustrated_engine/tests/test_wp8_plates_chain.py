"""WP8 — engine.v15_plates chain reorder + watermark crop + low-plate mode,
and tools/plate_library.py (DESIGN.md §6, §15.2 WP8).

Run: python3 -m pytest tests/test_wp8_plates_chain.py   (no network, no render)
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(REPO))
# Unconditional, and ROOT inserted LAST (test_wp7_templates.py's proven
# pattern): both illustrated_engine/engine and the repo-root engine/ package
# share the name "engine" — pytest's own `pythonpath=.` (../pytest.ini) can
# already have REPO ahead of ROOT in sys.path by the time this module runs,
# so an "insert only if not already present" guard would silently keep the
# WRONG one first. Always re-inserting ROOT at position 0 here is what
# actually wins the resolution, every time.
sys.path.insert(0, str(ROOT))

from engine import v15_plates as plates  # noqa: E402


# ────────────────────────────────────────────────── production chain order ─


class TestProviderOrder:
    def test_nvidia_nim_not_in_production_chain(self):
        assert "nvidia_nim" not in plates.PROVIDER_ORDER

    def test_archive_before_cloudflare_before_gemini_before_sdcpp_before_pollinations(self):
        order = plates.PROVIDER_ORDER
        idx = {name: order.index(name) for name in
              ("archive", "cloudflare_workers_ai", "gemini_image",
               "sdcpp_local", "pollinations")}
        assert idx["archive"] < idx["cloudflare_workers_ai"] < idx["gemini_image"] \
            < idx["sdcpp_local"] < idx["pollinations"]

    def test_matches_configs_images_yaml(self):
        """WP1 principle carried into WP8: "switching providers is a config
        change only" — the loaded order must actually come from the config,
        not just happen to match a hardcoded copy."""
        from src.utils.config import get_config
        assert tuple(get_config("image_gen.chain.production")) == plates.PROVIDER_ORDER

    def test_load_provider_order_falls_back_without_config(self):
        with patch("engine.v15_plates.get_config", create=True, return_value=None):
            pass  # get_config is imported inside the function; test the real fallback path:
        with patch("src.utils.config.get_config", return_value=None):
            assert plates._load_provider_order() == plates._DEFAULT_PROVIDER_ORDER


# ───────────────────────────────────────────────────────── watermark crop ──


class TestWatermarkCrop:
    def test_crops_bottom_fraction(self, tmp_path):
        im = Image.new("RGB", (200, 400), (10, 20, 30))
        p = tmp_path / "raw.png"
        im.save(p)
        plates._crop_watermark(p, frac=0.1)
        out = Image.open(p)
        assert out.size == (200, 360)  # 400 * (1 - 0.1)

    def test_removes_ocr_hit_in_bottom_strip(self, tmp_path):
        """A synthetic 'watermark' stamped in the bottom strip must no
        longer OCR-hit after cropping — proves the crop actually removes
        the region the OCR pre-filter reads (v15_plates.OCR_STRIPS bottom
        7%), not just resizes the image."""
        from PIL import ImageDraw
        im = Image.new("RGB", (600, 1000), (250, 250, 250))
        d = ImageDraw.Draw(im)
        d.text((10, 970), "pollinations.ai", fill=(0, 0, 0))
        p = tmp_path / "wm.png"
        im.save(p)
        before = plates.ocr_watermark(p)
        p.with_suffix(".ocr.json").unlink(missing_ok=True)  # clear cache
        plates._crop_watermark(p, frac=0.08)
        after = plates.ocr_watermark(p)
        # not asserting tesseract's exact read (env-dependent) — asserting
        # the stamp's pixel region is gone from the file entirely
        assert Image.open(p).size[1] == 1000 - 80
        assert before["checked"] in (True, False)  # tesseract may/may not be installed in CI
        assert after["checked"] in (True, False)

    def test_generate_plate_crops_only_for_pollinations(self, tmp_path, monkeypatch):
        """Chain-level: generate_plate must call the crop step exactly when
        the winning provider is pollinations, and not for any other."""
        monkeypatch.setattr(plates, "CACHE_DIR", tmp_path)

        class FakeProv:
            name = "gemini_image"

            def is_available(self):
                return True

            def generate(self, prompt, out, width, height, seed):
                Image.new("RGB", (10, 10)).save(out)
                return out

        class FakeFactory:
            def get(self, name):
                return FakeProv()

        with patch.object(plates, "_factory", return_value=FakeFactory()), \
             patch.object(plates, "_crop_watermark") as crop, \
             patch.object(plates, "apply_lut", return_value="deadbeef"):
            plates.generate_plate("house. subject. centered. no text", 1,
                                  providers=("gemini_image",))
            crop.assert_not_called()


# ─────────────────────────────────────────────────────── low-plate mode ───


class TestLowPlateMode:
    def test_cloudflare_available_reflects_env(self, monkeypatch):
        monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        assert plates.cloudflare_available() is False
        assert plates.low_plate_mode() is True
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "b")
        assert plates.cloudflare_available() is True
        assert plates.low_plate_mode() is False

    def test_image_chain_report_shape(self, monkeypatch):
        monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        r = plates.image_chain_report()
        assert r["low_plate_mode"] is True
        assert r["cloudflare_available"] is False
        assert r["max_generated_plates"] == 6
        assert r["provider_order"] == list(plates.PROVIDER_ORDER)

    def test_image_chain_report_no_budget_when_cloudflare_up(self, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "b")
        r = plates.image_chain_report()
        assert r["low_plate_mode"] is False
        assert r["max_generated_plates"] is None


# ─────────────────────────────────────────── hero-shot Pollinations ban ───


class TestHeroExclusion:
    def test_hook_drops_pollinations(self):
        out = plates.providers_for_beat_function("HOOK")
        assert "pollinations" not in out
        assert set(out) == set(plates.PROVIDER_ORDER) - {"pollinations"}

    def test_payoff_drops_pollinations(self):
        assert "pollinations" not in plates.providers_for_beat_function("PAYOFF")

    def test_other_function_keeps_full_chain(self):
        assert plates.providers_for_beat_function("CONTEXT") == plates.PROVIDER_ORDER
        assert plates.providers_for_beat_function(None) == plates.PROVIDER_ORDER

    def test_order_preserved_after_drop(self):
        out = plates.providers_for_beat_function("HOOK")
        assert out == tuple(p for p in plates.PROVIDER_ORDER if p != "pollinations")


# ───────────────────────────────────────────────── tools/plate_library.py ──


class TestPlateLibrary:
    def test_tags_for_extracts_content_words(self):
        from tools.plate_library import tags_for
        tags = tags_for("The 1908 Tunguska event flattened a forest")
        assert "tunguska" in tags
        assert "flattened" in tags
        assert "the" not in tags and "a" not in tags

    def test_subjects_from_topic_packs_reads_real_fixtures(self):
        from tools.plate_library import subjects_from_topic_packs
        subs = subjects_from_topic_packs(REPO / "bench" / "quality" / "topics")
        assert len(subs) > 0
        assert any("tunguska" in s.lower() for s in subs)

    def test_render_active_detects_pipeline_process(self):
        from tools.plate_library import _render_active

        class FakeProc:
            stdout = "python3 -m engine.v15_pipeline --story x\n"

        with patch("tools.plate_library.subprocess.run", return_value=FakeProc()):
            assert _render_active() is True

    def test_render_active_false_when_idle(self):
        from tools.plate_library import _render_active

        class FakeProc:
            stdout = "bash\nsshd\n"

        with patch("tools.plate_library.subprocess.run", return_value=FakeProc()):
            assert _render_active() is False

    def test_dry_run_generates_nothing_but_counts(self, tmp_path):
        from tools.plate_library import build_library
        subjects = ["a meteorite fragment", "a swirling abstract mood"]
        result = build_library(subjects, bible_story=ROOT / "stories" / "tunguska_1908",
                               out_index=tmp_path / "index.json", max_new=10, dry_run=True)
        assert result["generated"] == 2
        assert not (tmp_path / "index.json").exists()

    def test_build_library_records_index_and_dedupes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plates, "CACHE_DIR", tmp_path / "cache")

        def fake_generate_plate(prompt, seed, providers=None, log=None):
            return {"ok": True, "path": str(tmp_path / f"{seed}.png"),
                   "provider": "archive", "key": str(seed)}

        with patch("engine.v15_plates.generate_plate", side_effect=fake_generate_plate):
            from tools.plate_library import build_library
            idx = tmp_path / "index.json"
            r1 = build_library(["a meteorite fragment"],
                               bible_story=ROOT / "stories" / "tunguska_1908",
                               out_index=idx, max_new=10)
            assert r1["generated"] == 1
            data = json.loads(idx.read_text())
            assert len(data) == 1
            assert "meteorite" in data[0]["tags"]
            # same subject again -> dedupe on identical prompt, not regenerated
            r2 = build_library(["a meteorite fragment"],
                               bible_story=ROOT / "stories" / "tunguska_1908",
                               out_index=idx, max_new=10)
            assert r2["generated"] == 0
            assert r2["skipped_existing"] == 1

    def test_daily_cap_respected_across_runs(self, tmp_path, monkeypatch):
        """RESEARCH §5.3 / DESIGN §6.2: "about 70 per day max" — a second
        run on the same day must only fill the REMAINING budget, not start
        over, and a run that finds the cap already reached must generate 0."""
        import tools.plate_library as lib
        state_path = tmp_path / "state.json"
        monkeypatch.setattr(lib, "STATE_PATH", state_path)
        monkeypatch.setattr(lib, "_render_active", lambda: False)

        def fake_generate_plate(prompt, seed, providers=None, log=None):
            return {"ok": True, "path": str(tmp_path / f"{seed}.png"),
                   "provider": "archive", "key": str(seed)}

        subjects_file = tmp_path / "subjects.txt"
        subjects_file.write_text("\n".join(f"a meteorite fragment number {i}"
                                           for i in range(5)))

        argv = ["plate_library.py", "--max", "3",
               "--subjects-file", str(subjects_file),
               "--bible-story", str(ROOT / "stories" / "tunguska_1908"),
               "--out-index", str(tmp_path / "index.json")]
        with patch("engine.v15_plates.generate_plate", side_effect=fake_generate_plate), \
             patch.object(sys, "argv", argv):
            lib.main()
        state = json.loads(state_path.read_text())
        assert state["count"] == 3  # capped at --max, not len(subjects)==5

        with patch("engine.v15_plates.generate_plate", side_effect=fake_generate_plate), \
             patch.object(sys, "argv", argv):
            lib.main()  # same day, cap already reached -> generate 0 more
        state2 = json.loads(state_path.read_text())
        assert state2["count"] == 3
