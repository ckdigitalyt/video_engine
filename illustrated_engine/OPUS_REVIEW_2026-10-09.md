# Opus architecture / algorithm review — 2026-10-09 (decision #18 item 0)

Question this review answers: **what has to change so a video that reaches
render reliably clears the video gate (judge, distinctness, captions), instead
of rendering and then holding?**

Grounded in dry run 5 (`build/v16/batches/daily_2026-10-04_031422/`, story
`t_the_dwarf_planet_s_disappearing_atmosphe`). Its HOLD was **not bad luck**.
Each of its three failures traces to a specific, reproducible gap in the code,
listed below with the evidence that ties it to that gap.

Evidence used:

- `judge_sheet.jpg` and `plate_sheet*.jpg` (viewed)
- `pipeline_report.json` (`subject_bible: {}`, `plate_qa`, shots meta)
- `visual_plan.json`
- `assembly_report.json` caption cues
- the plate cache metadata (provider/seconds per regen)
- `build/v16_distinctness_history.json`

---

## TL;DR — top findings

1. **The subject bible never ran for any auto-generated story.**
   `engine/subject_bible.main_concept()` requires `story["concepts"]`, which
   `engine/v16_autostory` never emits. Dry run 5 recorded `subject_bible: {}`.
   The image model got nothing beyond "a small icy world", so it drew Earth:
   continents and oceans on 8 of 21 plates. The judge flagged that as
   `not_story_specific` (#2, #4) and `template_feel`.

2. **Plate QA does not ask the questions the final judge fails on, and the
   regen loop ignores *why* a plate failed.**
   - `v15_plates.QA_QUESTION` explicitly forgives "artistic interpretation",
     has no `generic_subject` / `empty` / `near_duplicate` codes, and so passed
     every Earth-like "dwarf planet".
   - `v15_pipeline.run_pipeline`'s `MAX_PLATE_REGEN` loop reissues the
     **identical prompt** and only rotates the *provider*. On dry run 5 that
     rotation sent one plate to `sdcpp_local` for **1709 s (28.5 min)**,
     because gemini returned 429. The next round sent it to `pollinations`,
     which is `commercial_ok:false`. Of `plates_s=2040`, about 1750 s was that
     one regen.

3. **The distinctness check measures almost nothing.**
   - `v16_gate.template_signature()` is the per-shot `kind` sequence.
   - `v15_plan.SHOT_KINDS` only allows `plate|zoom_through|process`.
   - So every V15 video is about 95% `plate,plate,plate,…`, and any two
     videos land within Levenshtein 0.3 of each other.
   - WP7's 11-template library (`kinetic_claim`, `big_number`, `map_pin`,
     `timeline`, `scale_compare`, `parallax`, `loop_bridge` in
     `v15_shots.compile_shot`) is **unreachable**: the planner's validator
     rejects those kinds.
   - The 0.3 threshold is not the problem. The signature's vocabulary is.

4. **Visual variety is enforced nowhere, per shot or per video.**
   - The plan prompt never asks for varied scale or viewpoint. 15 of 21 plan
     subjects in dry run 5 are "a small icy world floating in space".
   - The B3 punch-in split appends ", tight close-up detail crop" to the *end*
     of the same subject. The image model ignores it and redraws the whole
     planet, so the derived shot becomes the judge's `no_change` frames
     (#3, #15).
   - The `subject_low` composition hint asks for a "wide quiet open background
     across the upper third". Combined with `pull_out`, that produced the
     `empty_or_flat` frame (#11).

5. **The caption-clause failures are two code bugs plus one gate false
   positive.**
   - `v15_pipeline.caption_cues`' 4-word backtrack can walk back to `k=1` and
     emit a one-word cue that *is* a function word (`"to"`, `"up"`).
   - `voice.text.numeralize_cue_words` renders "one hundred to one thousand"
     as `"100-1 thousand"`, which reads as a subtraction.
   - `v15_gate.check_caption_clause_breaks` flags `"that breaks it:"` even
     though the colon ends the clause. The pipeline's own `_binds_forward`
     already treats terminal punctuation as a clause end.

---

## 1. Judge frame quality (`subject_unrecognizable`, `empty_or_flat`, 6/15 flagged)

How the judge fails, from `v15_gate.run_judge`:

- It fails if more than 25% of frames are flagged (≤3 of 15 allowed).
- It fails on ≥2 frames in the "crit" set (`empty_or_flat`,
  `subject_unrecognizable`, …).
- It fails on `template_feel`.

Dry run 5 tripped all three. The six flagged frames map to the root causes
like this:

| judge frame | issue | plate / shot | root cause |
|---|---|---|---|
| #2 | not_story_specific | B2_S1 (Earth-like) | no subject identity (R1) |
| #3 | no_change | B2_S3 = derived punch-in of B2_S1 | derived shot redraws same image (R4) |
| #4 | not_story_specific | B3 (Earth + Saturn) | no subject identity (R1) |
| #9 | subject_unrecognizable | B8 "two atmospheric layers compared" → model invented a man on ice | abstract, undrawable subject; QA forgave it (R2, R3) |
| #11 | empty_or_flat | B9_S2 horizon + empty sky, `subject_low` + `pull_out` | composition hint asks for emptiness (R4) |
| #15 | no_change | B11_S2 = derived punch-in of B11_S1 | (R4) |

**Why 3 regen rounds did not help.** Only one plate (`#20`,
`narration_mismatch`) ever failed plate QA. The loop regenerates the same
prompt string with a new salt on a *different provider*, so it neither steers
toward the fix nor stays on the commercial-OK fast model. None of the six
judge-flagged frames were plate-QA failures at all, because QA's rubric is
looser than the judge's.

### Recommendations, in priority order

- **R1 — subject identity for every story** (`engine/subject_bible.py`,
  `engine/v15_pipeline.py`, `engine/v15_plan.py`).
  - When `story["concepts"]` is absent, derive the recurring subject from the
    title and full narration. Use one cached `text_ask` returning
    `{name, aliases[], description, not_like}`.
  - Build the bible **before** the visual plan, and pass name + description
    into `v15_plan.build_prompt`. The planner then describes the subject
    concretely in every shot, and the plan cache key includes it.
  - `inject_subject` matches any alias (word-boundary regex, not raw
    substring), not just a concept id.
  - `not_like` (e.g. "Earth with blue oceans and green continents") goes
    **only** to plate QA, never into the FLUX prompt. FLUX has no negative
    prompt, so naming the wrong thing summons it (`v15_style` comment).
- **R2 — align plate QA with the final judge** (`v15_plates.QA_QUESTION`,
  `llm/schemas/plate_qa.json`).
  - Add fail codes:
    - `generic_subject`: a generic stand-in instead of the specific subject;
      checked against the identity block and its `not_like`.
    - `empty`: mostly blank or featureless, subject tiny.
    - `near_duplicate`: nearly the same picture as an earlier plate on the
      sheet. The last plate may echo #1 (intentional loop).
  - Order the sheet in **timeline order**, not `sorted(uniq)`, so "earlier"
    and "first/last" mean something.
  - Add the new codes to the schema enum. Decision #13 found that a missing
    enum value silently degrades the whole call to `checked:false`.
- **R3 — reason-steered regen** (`v15_pipeline.run_pipeline` regen loop).
  - Rebuild the prompt from the failure reason, phrased positively:
    - identity-led subject for `wrong_subject`/`generic_subject`;
    - "large, filling the frame" + centered for `empty`;
    - a different view for `near_duplicate`;
    - the narrated action made explicit for `narration_mismatch`.
  - Keep the plate keyed by the original prompt so the shot→plate map is
    unchanged.
  - **Stay on the production chain order** (Cloudflare first). Do not rotate
    to `sdcpp_local`/`pollinations`. The steered prompt is what changes the
    image, and descending the chain only on provider failure is the existing
    `generate_plate` behaviour.
  - Record `shows` and the steering applied in `plate_qa` for audit.
- **R4 — per-shot visual variety, enforced deterministically** (`v15_plan`,
  `v15_style.image_prompt`, `v15_pipeline._split_one`).
  - Add a `view` enum per shot: `wide`, `medium`, `close`, `surface`,
    `cutaway`, `comparison`, `observer`.
  - `image_prompt` **prepends** the view's framing phrase. FLUX weighs early
    tokens; the current trailing "tight close-up detail crop" is ignored.
  - The planner prompt requires varied views and drawable physical scenes
    (no abstract "comparisons of layers"), and no invented people unless the
    narration mentions people.
  - A deterministic `variety_errors()` check:
    - no two consecutive shots with the same view;
    - no view on more than 40% of shots;
    - at least 4 distinct views when there are 8 or more shots.
  - The check feeds the existing one-retry loop. If only variety errors
    remain after the retry, accept the plan with a recorded warning rather
    than dropping to salvage/fallback (a worse floor).
  - Derived punch-in shots take a *different* view from their parent
    (`close`, or `medium` if the parent was already `close`), prepended.
  - The `subject_low` hint becomes "main subject large in the lower two
    thirds, calm darker background across the top third".

## 2. "Scenes feel templated (noun-swap reusable)"

**Variety is enforced per video only for shot duration** (`split_long_holds`,
`MAX_HOLD_S`). Nothing enforces it per shot for content, scale or viewpoint.

The "template library" is **not** what collides across topics: it is unused.
What is shared across topics is the planner's default habit of one hero object
centered in a void, with push_in/pull_out, in the same deck (space topics
always get `nocturne_gouache`). That is the noun-swap feel.

The fix is R1 + R4, which make shots topic-specific and varied. Adding more
templates alone would not fix the judge's complaint.

**R5 — follow-up, not in this package:** wire WP7's `kinetic_claim` (and later
`big_number`) into `v15_plan.SHOT_KINDS` with validation rules.

- `big_number` cannot work for auto-stories yet. Their narration spells
  numbers out for TTS, and `_check_copy` requires on-screen digits to appear
  *verbatim* in the narration. The digit check needs the same numeralized
  comparison `check_caption_identity` already uses.
- `scale_compare` draws rounded rectangles as silhouettes, which looks
  unfinished. Do not enable it until it has real cutouts.

## 3. Distinctness check

- **Comparing the wrong thing.** `template_signature(meta)` is `kind`-only, so
  for this pipeline it is close to constant. 0.10, 0.23 and 0.29 between a
  space story, a skater story and Tunguska is a property of the vocabulary,
  not of the videos.
- **Is 0.3 sane?** Yes, on a meaningful vocabulary. With per-shot tokens of
  `kind/camera/overlay` (camera from 7 values, overlay one of
  headline/label/number/steps/none), unrelated videos sit around 0.7-0.9.
  Below 0.3 then means "about 70% of shots have the same edit grammar in the
  same order", which is a real template signal.
- **Is three collisions a sign the template pool is too small?** Not in the
  sense of "add more templates". It is a sign the signature is degenerate.
  With 4 history entries every pair collided.

**R6** (`engine/v16_gate.py`, `engine/v15_pipeline.py`,
`engine/v16_manifest.py`):

- Add a v2 signature derived from the compiled scene specs. Each token is
  `shot_kind/camera.type/overlay`, which is what actually appears on screen.
- Store it in history as `signature_v2`.
- Compare v2 against v2. Report history entries that only have the legacy
  kind-only signature as `legacy_uncomparable`, rather than flagging them on
  a measure known to be meaningless.
- Backfill `signature_v2` for history entries whose scene specs still exist
  on disk:
  - backfilled: `t_figure_skater_spin` (`results/`) and dry run 5;
  - not backfillable: `tunguska_1908` and `t_humans_closer_trex` (specs
    gone).
- Keep the plate dHash comparison unchanged. That is the content-level check.
- Distinctness stays a warning (decision #13).

## 4. Caption clause breaks

These are real chunking bugs, and the fixes are small (**R7**):

- **`v15_pipeline.caption_cues`.**
  - When the 4-word backtrack would strand fewer than 2 words, keep growing
    the cue to a hard cap of 6 words, then break at the last non-binding
    position.
  - Treat quantifier lead-ins as binding forward when followed by `to` or a
    digit: `up`, `about`, `around`, `nearly`, `roughly`, `almost`, `over`,
    `under`, `only`, `just`.
  - Never let a pause/comma break end a cue on a binding word.
- **`voice.text.numeralize_cue_words`.**
  - Multiply `thousand` out to comma-grouped digits: `1,000`,
    `100-1,000`, `2,000-3,000`. Keep `million`/`billion` as unit words per
    the B1 spec.
  - For mismatched scales, write "X to Y".
  - The same function feeds both sides of `check_caption_identity`, so
    identity stays consistent.
- **`v15_gate.check_caption_clause_breaks`.**
  - A cue whose last token ends in clause punctuation (`, . ; : ! ? —`) is not
    a mid-clause break. This matches `_binds_forward`.
  - Share one function-word set between pipeline and gate. There are two
    copies today.

## 5. Blocking publishability, not surfaced by the HOLD list

- **Regen wall-clock / licence risk** (covered by R3). One 429 can turn a
  20-minute plate stage into 50 minutes, and quietly put a
  `commercial_ok:false` Pollinations plate into a video.
- **`engine/species.py` substring match** (`alias in low`). "rex" matches
  inside unrelated words, and "ant" inside "giant". **R8:** a word-boundary
  regex in `species_for` and the new alias matcher.
- **Script names nothing concrete.** Dry run 5's script never names the object
  (only "this tiny world", "one-fifth the width of Pluto"). The image model then has only
  "tiny world" to draw.
  - R1 compensates on the visual side.
  - Recommended follow-up, not done here: a `script_write` rule that the hook
    or second beat names the specific subject.
- **Ending.** The PAYOFF line trails off ("…and that's why astronomers
  say…"), by design so it loops back into the hook. The judge marked
  `ending_resolves:false`. That is not a fail condition today. It should be
  reviewed by the owner on the next video, not silently tuned.
- **Judge vs plate-QA input mismatch.** Plate QA sees full plates. The judge
  sees composited, cropped and captioned frames. Some issues (empty upper
  third after `pull_out`; overlapping headline + label, as in dry-run-5 frame
  #7 "LIGHT DIMS SLOWLY" over "NOT INSTANTLY") only exist after composition.
  - Recommended follow-up: a free, deterministic pre-assembly check on the
    rendered scene's mid-frame using `frame_information`. No new LLM call.
- **Voice / pacing.** Voice WER passed on dry run 5. The median shot length
  is about 2.5 s against DESIGN's 1.2-2.0 s; the `MAX_HOLD_1_8_S` pacing check
  exists but is unwired. Not a HOLD cause; leave it until visuals clear.
- **Critic.** It is now only a ranker (decision #17). Out of scope here.

## Implementation order (decision #18)

| item | rec | addresses |
|---|---|---|
| 1 | R7 captions (cue builder + numeral range + gate false positive) | caption_clause_breaks |
| 2 | R1 + R8 subject identity for auto-stories, fed into the planner | judge: not_story_specific / template_feel |
| 3 | R4 per-shot `view` variety + prepended framing + derived-shot view + composition hint | judge: no_change / empty_or_flat / template_feel |
| 4 | R2 + R3 judge-aligned plate QA + reason-steered regen on the production chain | judge: all frame codes; regen time / licence |
| 5 | R6 distinctness signature v2 + backfill | distinctness |
| — | R5, script-names-subject, post-composition frame check | follow-ups, not in this package |
