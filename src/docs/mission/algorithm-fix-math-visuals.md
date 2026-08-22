# Algorithm Fix — Math Topics Must Render the Math, Not Stock Footage

**Status:** Applied. Root cause fix for the 6174 v1 failure (space imagery
under a number-trap narration), validated via the reuseable math-render
pipeline.

## The failure (v1)
- Mission `6174: the number that eats every other number` routed the shots
  through the stock-footage director (Pexels) + AI still providers.
- Result: visuals were space footage, a vintage clock, a calculator — none
  of it showed the actual 4-digit Kaprekar arithmetic.
- Gemini end-to-end review scored **68/100**, flagged
  `new_asset[critical]: Replace generic space footage with dynamic
  on-screen mathematical animations (Manim-style) showing the
  step-by-step subtraction converging to 6174`, plus
  `shot_order[high]: Establish a consistent visual theme`.

## The fix (this deliverable)
For objective/mathematical topics, visuals must be **generated from the
narration's actual mathematical content** — real numerals and operations —
never generic stock footage. Implemented in the reusable math-render
pipeline (see `math_video/kaprekar/`):

1. **Scene visuals derive 1:1 from the script beats** (`render_kaprekar.py`):
   - S1 HOOK -> show 3524, sort desc 5432, asc 2345, subtract = 3087.
   - S2 INEVITABILITY -> chain 3524 -> 3087 -> 8352 -> 6174; "9,004 numbers".
   - S3 FIXED POINT -> 6174 self-loop 7641 - 1467 = 6174 (Kaprekar 1949).
   - S4 MULTI-DIGIT -> 3-digit -> 495 chain on left; 5-digit 2-cycle
     (53955 <-> 59994) on right.
   - S5 VORTEX -> every 4-digit number (except repdigits like 1111) swirls
     into glowing 6174 center + subscribe CTA.
2. **Correct arithmetic guaranteed by computing the Kaprekar chains in code**
   (not hardcoded/LLM-guessed): `3524`, `352 -> 495`, `53955 <-> 59994`
   all verified programmatically.
3. **Locked cartoon brand** (from `src/director/style_bible.py` v40/v42):
   flat-2D cartoon, thick dark ink outlines, cel shading, palette
   (navy #0A0E26 / orange #FF8A46 / blue #4682C8 / violet #B85CC8 /
   cyan #63DDF2), recurring green-alien mascot observer.
4. **QA gate that would have caught v1** (`gemini_review_kaprekar.py`):
   Gemini vision checks, frame-by-frame, that each rendered frame MATCHES
   its narration (numbers/operations present), is topic-correct, and is
   style-consistent — plus flags any generic/off-topic imagery.

## Codified rule for future math videos
- When script `topic` is math-formulaic/objective (Kaprekar, integrals,
  paradoxes, proofs), route to the **math-render pipeline** and build each
  scene's `visual_goal` directly from the equations/numbers in the
  narration. Do NOT send math topics to the stock-footage director.
- Structural pattern to copy per-video: `render_<topic>.py` (matplotlib,
  compute the math in code, render digits/ops), `gemini_review_<topic>.py`
  (frame-by-frame alignment), `extract_frames.sh` + `mux.sh`.

## Artifacts
- `math_video/kaprekar/render_kaprekar.py` — full 60s matplotlib renderer (kept for high-fps master renders).
- `math_video/kaprekar/render_kaprekar_stills.py` + `assemble_kenburns.sh` — fast stills + Ken-Burns assembly (used for this delivery).
- `math_video/kaprekar/gemini_review_kaprekar.py` — vision QA (this review; Gemini free-tier quota blocked, vision-model verdict recorded in `QA_VERDICT.md`).
- `math_video/kaprekar/script.json` — 60s script (154 words).
- **Final video: `math_video/kaprekar/kaprekar_6174_final.mp4`** (61.07s, H.264 1920x1080@30, AAC stereo + ducked ambient).
