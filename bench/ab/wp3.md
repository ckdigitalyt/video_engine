# WP3 acceptance: voice layer

Commit 45e69b5. Measurements: `bench/ab/wp3_voice_bench.py` (local Kokoro fp32 + faster-whisper, no network, no Claude calls, no renders). Raw output: `~/phase4_out/wp3/`.

## Acceptance (DESIGN 15.2, row WP3)

| Criterion | Result |
|---|---|
| Forced Fish failure -> whole-video Kokoro | PASS (unit test `test_forced_failure_switches_whole_video_to_fallback`: partial wavs discarded, whole script redone, switch recorded in `voice.switches`; `test_all_voices_failing_raises`) |
| Lexicon fixes "Tyrannosaurus" | PASS (live test): bare Kokoro reads "Tyrannosaurus rex had tiny arms." as "terenasaurus rex" (QA HOLD); with lexicon it is heard correctly (QA PASS). Mid-sentence and "Tyrannosaurus, gone." are read correctly even bare, so the failure is sentence-initial and context-dependent. |
| WER gate | Normalised WER <= 0.03 plus every hard token heard. Topic-1 script (73-word birds/dinosaurs script; the topic-1 pack has claims only): WER 0.000, PASS, 27.5 s, RTF 0.68 |
| Captions p90 <= 0.12 s | PARTIAL, see below |

### Caption timing (honest reading)
- Sentence onsets vs the synthesis-truth positions: p50 0.010 s, p90 0.024 s, max 0.057 s (10 anchors). Partly circular, because word times are clamped to sentence spans.
- Independent check, word starts vs faster-whisper `small.en`: p50 0.06 s, **p90 0.16 s**, max 0.38 s. This is disagreement between two ASR models, not ground truth, so it over-states the error of either one. It does not confirm p90 <= 0.12 s.
- Old `silence_v1` vs `small.en`: p50 0.14 s, p90 0.34 s, max 0.80 s. The new method is about 2x tighter at p90.
- No forced-alignment ground truth exists without Fish paid timestamps (disabled). Verifying the 0.12 s target needs a human-labelled clip or Fish paid word times; not done.

## Owner sample set (same 73-word script, -14 LUFS)
Files in `~/phase4_out/wp3/samples/`: `{am_michael, am_onyx, bm_lewis}_{1.0x,1.1x}.wav`.

Shortlist of 9 male Kokoro voices (all PASS the QA; `shortlist.json`): michael, fenrir, puck, onyx, adam, george, fable, daniel, lewis. I picked onyx (F0 88 Hz, the deepest) and lewis (F0 100 Hz, British, documentary register) as the two alternatives to michael (F0 119 Hz). This is a judgement call from the numbers only. **Nobody has listened to these; the owner's ears decide.**

| Voice | Speed | Dur s | WPM | WER | Peak dBTP |
|---|---|---|---|---|---|
| am_michael | 1.0 | 27.5 | 159 | 0.000 | -1.7 |
| am_michael | 1.1 | 26.0 | 169 | 0.000 | -1.7 |
| am_onyx | 1.0 | 26.0 | 168 | 0.027 | -2.3 |
| am_onyx | 1.1 | 24.8 | 177 | 0.027 | -2.3 |
| bm_lewis | 1.0 | 28.3 | 155 | 0.014 | -1.7 |
| bm_lewis | 1.1 | 26.5 | 165 | 0.014 | -1.8 |

Note: "1.0x"/"1.1x" is the voice's base speed; the per-role multipliers (hook 1.03, payoff 0.96) apply on top. At 1.1x the hook sentence therefore runs at about 1.13x and the payoff at about 1.06x. The 0.95-1.08 band is enforced on the role multiplier only, so 1.1x samples sit outside it on the hook by design (owner asked for 1.1x).

## Lexicon
`brand/ink_ember/lexicon.yaml`, 15 entries. Phoneme strings for 9 words were verified by ASR round trip, sentence-initial and mid-sentence (`lexicon_verify.txt`). Plain respellings are the retry path and often fail the round trip (e.g. "tie-ran-uh-sawr-us" -> "tie are in a sower us"), which is why the first attempt uses phonemes. The 6 entries with no phonemes (cenozoic, cepheid, furcula, theropod, betelgeuse, olbers) rely on the respelling or an alias only. Not listened to.

## Tests and gate
- New `illustrated_engine/tests/test_wp3_voice.py` 18 tests; `illustrated_engine/tests` 49/49 pass.
- Root suite: 58 failed / 5 errors before and after (63 identical failing test ids, diffed; `suite_{before,after}.txt` in `~/phase4_out/wp3/`). Before = clean worktree of 6576602. No new failures. The pass/skip counts differ (1259 pass/8 skipped before, 1263/4 after); I did not trace why, and the failing set is identical.
- Secret scan of the diff: clean. `.env` untouched. Fish key not used.
- `engine.v15_pipeline`, `engine.tts`, `engine.v15_gate` import; `mission_run.py --help` runs.
- Not run: a full V15 render with the new voice (needs Claude calls for plan/judge). The pipeline wiring is covered by unit tests only.

## Flags for the owner
1. **Policy change (DESIGN 15.3 item 3):** V15's "Fish only, no fallback, STOP" is replaced by Kokoro-first with a whole-video chain that currently holds only Kokoro. If Kokoro itself fails, the pipeline raises.
2. **Code removed:** `engine/tts.py` `_get_provider`, `_ensure_env_key`, `tts_story`, `ffprobe_duration` (the Fish free-tier-pinned path). It was not a fallback chain (Fish-only, STOP on failure), and its tier is non-commercial per the round-3 decision. No fallback or retry path was narrowed; `silence_v1` timing is kept as the offline last resort. Tag or revert commit 45e69b5 if you disagree.
3. `research/phase2/fish_check.py` is marked broken (one-off script).
4. Whisper model download: `base.en`/`small.en` come from the public Hugging Face cache; no credentials.
