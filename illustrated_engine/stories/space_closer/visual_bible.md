# VISUAL BIBLE — "Space Is Closer Than You Think" (v2, reference-aligned)

Source of truth derived from reference video (tmp/ReferenceVideo.MP4, 1290x2796@60, 54s, 2026-09-01) + program brief. One video, one bible. All assets, layout, typography obey this.

## Frame skeleton (locked, 1080x1920@30)
- **Base:** black background full-bleed.
- **Hook-title band:** y 120–440, solid deep navy `#1B2A4A`, full width. Title in 3 lines, Archivo Black, off-white `#F5F1E8`, centered: `SPACE IS / CLOSER THAN / YOU THINK`. Persistent the entire video (never animates out; subtle 2% brightness pulse allowed at beat changes).
- **Artwork panel:** y 460–1240 (1080x780 window). All illustrated plates live here, letterboxed. Camera moves happen INSIDE this window only (Ken Burns drifts, pushes, crop pans).
- **Caption zone:** y 1240–1580. Narration captions: Inter Black (fallback DejaVu Sans Bold), 62–70px, off-white, black stroke 5px, max 2 lines, phrase-synced (karaoke word-groups, one phrase at a time — never full sentences).
- **Footer:** y 1580–1920 black. Empty (breathing room). Optional tiny source line at final shot only.

## Art direction — "vintage scientific plates"
- **Style:** aged-paper scientific plates — parchment cream ground, ink/sepia line-and-wash illustration, faded hand-written style annotations, dimension lines, small measurement marks. Feels like a 1950s–60s aerospace research folio. Matte, no photorealism, no modern UI.
- **Palette (locked):**
  - Parchment cream `#E9DFC8` (plate ground)
  - Ink sepia `#2A2118` (linework, shadows, text on plate)
  - Deep navy `#1B2A4A` (title band, deep-space ink wash)
  - Rust `#B4552D` (accent: key objects, emphasis fills, the 100 KM emphasis)
  - Slate `#6E7F91` (secondary diagram lines, aurora wash)
- **Paper treatment:** subtle mottled aging, soft vignette on the plate, faint fold/foxing marks allowed. Edges of plate slightly darkened.
- **Annotations:** tiny faded handwritten-style labels + arrows/dimension lines ON the plate (baked by image gen, deliberately illegible or single legible words). In-engine overlays mimic this style: ink arrows, rust highlight circles.
- **Composition:** single strong subject per plate, generous parchment negative space for captions/crops, strong diagonals, low horizons. Each plate must contain ≥2 distinct croppable regions.

## Typography
- **Hook title:** Archivo Black, 3 lines, off-white on navy band (static).
- **Captions:** Inter Black, off-white + black stroke, phrase-synced at bottom (above footer).
- **Numbers:** Bebas Neue, huge (140–220px), rust or ink, pop-in scale 0.8→1.0 + fade 300ms.
- **Callouts/labels:** ink style, DejaVu Serif Italic fallback, small, with thin leader lines drawn in ink.
- **Rule:** text never covers the plate's subject focus; captions live in their zone; numbers sit in parchment negative space.

## Camera / motion grammar
- Slow, deliberate: drifts 1.0→1.15×, pushes to 1.4× over 4–6s, crop pans between labeled regions. NO whip moves, no bouncing.
- Cutting rhythm: mostly hard cuts between plates/crops (reference uses cuts), sparing 0.4s crossfade only at act changes (B2→B3, B5→B6). CROP_REVEAL for diagram draws.
- Diagram beats reveal bottom→top (altitude logic); highlight bar + rust circle travel to markers.
- Narrative-sequence plates (figure progression arcs) read left→right with a pan.

## Forbidden
- External footage, AI video clips (v1 disabled), modern clean backgrounds, photoreal faces, readable gibberish text walls, busy texture behind captions, fast camera moves.
