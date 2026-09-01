# Illustrated Engine — "Space Is Closer Than You Think"

Deterministic, ffmpeg-only illustrated-documentary engine. 1080x1920@30.
Stdlib + Pillow + numpy + ffmpeg 6.1. No network, no randomness, `-threads 1`.

## Artifact flow

```
stories/space_closer/story.json ─┐
stories/space_closer/visual_plan.json ─┤→ python3 cli.py validate --make-edit-plan
assets/<asset_id>.png (1536x1024 plates) ┘        │
                                                  ▼
                                       build/edit_plan.json  (authoritative render plan)
                                                  │
                     python3 cli.py render-shot <id> / render-video
                                                  │
              build/ass/<id>.ass + build/overlays/*.png + build/shots/<id>.mp4
                                                  │
                                       concat (transition_in chain) + audio
                                                  ▼
                                            output/final.mp4
                                                  │
                              python3 cli.py qa / contact-sheet
                                                  ▼
                                   build/qa/qa.json + qa/contact_sheet.jpg
```

## Frame layout (locked)

Black canvas; **title band** navy `#1B2A4A` y=120..440 (3-line Archivo Black,
off-white, static, built once to `build/overlays/title_band.png`); **panel**
y=460..1240 (1080x780) — all motion lives here; **captions** y=1240..1580
(ASS, Inter 64, off-white, 5px black outline, max 2 lines, phrase-synced);
**footer** y>1580 empty black. Palette: parchment `#E9DFC8`, ink `#2A2118`,
navy `#1B2A4A`, rust `#B4552D`, slate `#6E7F91`, off-white `#F5F1E8`
(single source: `templates/ass_style.json`).

## Coordinate conventions

- **Camera** (in `camera.from/to`): normalized to the 1536x1024 plate.
  `w` = visible width as a fraction of plate width; `cx`/`cy` = window
  center in [0,1]. Window keeps the panel aspect (18:13), so height fraction
  = w x 1.0833. `w <= 0.9231` fits fully in the plate; `w <= 1.0` letterboxes
  (thin black bars). Out-of-range values are **clamped** and validate prints
  each clamp as a warning.
- **Overlays** (`target`, arrow `from`/`to`, callout `anchor`): normalized to
  the **panel** (1080x780). NUMBER_POP `pos` is in **frame** coords
  (clamped into the panel). Perceived overlay scale is approximate on strong
  push-ins (overlays don't track camera) — keep targets generous.

## edit_plan.json schema

```jsonc
{
  "story_id": "...", "fps": 30, "size": [1080, 1920],
  "panel": {"x": 0, "y": 460, "w": 1080, "h": 780},
  "shots": [{
    "shot_id": "S01", "asset": "A1_earth_limb_plate",
    "camera": {"primitive": "ZOOM_IN",            // 11 primitives, engine/motion.py
               "from": {"w": 1.0, "cx": 0.5, "cy": 0.5},
               "to":   {"w": 0.78}},
    "duration_s": 5.0,
    "overlays": [   // HIGHLIGHT{target,style:rect|circle|ring,color,at,dur}
                    // ARROW_DRAW{from,to,at,dur(reveal),hold,color}
                    // CALLOUT{text,anchor,label,at,dur,color}
                    // LIGHT_SWEEP{at,dur}   NUMBER_POP -> typography (ASS)
      {"kind": "HIGHLIGHT", "style": "circle", "color": "rust",
       "target": {"x": 0.10, "y": 0.36, "w": 0.80, "h": 0.26}, "at": 0.35, "dur": 2.4}],
    "typography": [ // caption{t0,t1,mode?word_reveal} | number_pop{at,pos,color,dur}
                    // end_card{at,dur}
      {"kind": "number_pop", "text": "100 KM", "at": 0.6,
       "pos": [540, 1130], "color": "rust", "dur": 1.8}],
    "captions": [{"text": "Space is closer than you think", "t0": 0.0, "t1": 2.9}],
    "transition_in": "CUT" | "CROSSFADE" | "FADE" | "IMAGE_WIPE_UP",
    "end_card": true
  }],
  "audio_master": "build/audio_master.wav"   // optional; else silent track
}
```

`validate --make-edit-plan` builds it from visual_plan (pre-TTS): shot
`duration_est` scaled so each beat sums to its `duration_est`; captions are
the beat narration split into phrase groups (<= 9 words) laid across the
beat proportional to word count, assigned to the shot containing each
phrase midpoint (shot-local t0/t1). Symbolic visual_plan references
(key_regions names, `lower-left`, `panel-lower-third`) resolve to concrete
geometry in `engine/plan.py` tables — estimates, refine as plates land.

## Commands

```
python3 cli.py validate [--make-edit-plan]  # schema/primitives/assets/fonts; build edit_plan
python3 cli.py render-shot S03              # standalone one-shot re-render
python3 cli.py render-video                 # missing/outdated shots + concat -> output/final.mp4
python3 cli.py qa [path]                    # default output/final.mp4 -> build/qa/qa.json
python3 cli.py contact-sheet <path>         # 3x4 sheet -> build/qa/contact_sheet.jpg
python3 cli.py smoke                        # 2s deterministic test render x2 + sha256
python3 cli.py tts                          # wired at TTS stage (stub)
```

Shot re-render model: `render-video` re-renders a shot when its mp4 is older
than the plate, the .ass, or edit_plan.json. `render-shot` always re-renders.

## Determinism

No randomness, no clocks in content. libx264 `-threads 1`, `-preset medium
-crf 18`, bitexact muxing (`-fflags +bitexact -flags +bitexact`), metadata
stripped. `smoke` renders the same shot twice and sha256-compares.
