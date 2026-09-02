# Storyboard — "The Tallest Mountain on Earth Is Hiding"

Visual Bible: `visual_bible.json` (v2) · Engine: v2 · 7 shots · 46.2 s · 1080×1920 @30

| # | Type | Asset | Camera | Editorial notes |
|---|------|-------|--------|-----------------|
| S01 | ESTABLISH | B1_everest_plate (generated) | push 1.00→1.10 | Opening title + number pop **8,849 m** at the peak. Curiosity hook. |
| S02 | REVEAL | B2_ocean_section_plate (generated) | push 1.04→1.22, focus below horizon | Contradiction beat: height depends on the starting line. Horizon highlight. |
| S03 | DIAGRAM | D1_scale_compare (programmatic) | near-static 1.00→1.05 | Scale visualisation: Everest 8,849 m vs Mauna Kea 10,210 m from the ocean floor, dashed below-sea outline. |
| S04 | TIMELINE | D2_timeline (programmatic) | lateral drift 0.25→0.72 | Hotspot origin: seafloor eruption → shield building → emergence → today. |
| S05 | COMPARE | D3_split_compare (programmatic composite) | gentle push 1.00→1.06 | Above/below waterline split: 4,207 m above / 6,003 m below. |
| S06 | DETAIL | B4_summit_plate (generated) | tight zoom 1.30→1.48 | Summit detail with highlight; supports "spends most of its life in the dark". |
| S07 | PAYOFF | D4_payoff (programmatic) | pull-back 1.16→1.00 | Scale payoff + "HIGHEST ≠ TALLEST" typography; loops back to the opening premise; brand endcard. |

Narration (6 beats, 42.0 s TTS + 0.7 s pads → 46.2 s timeline):

- **B1** — Mount Everest stands 8,849 metres above sea level — the highest point on Earth.
- **B2** — But height depends on where you start measuring. And Everest doesn't start from the bottom.
- **B3** — Measured from its base on the Pacific floor, Mauna Kea rises 10,210 metres — more than a kilometre taller than Everest.
- **B4** — It was built by a hotspot: eruptions stacked lava, layer upon layer, for around a million years.
- **B5** — Most of the mountain hides underwater. Only 4,207 metres breaks the surface — about 41 percent.
- **B6** — So Everest is the highest mountain. Mauna Kea is the tallest — and it spends most of its life in the dark.

Sources: China–Nepal joint survey 2020 (8,848.86 m); USGS (Mauna Kea 10,210 m base-to-peak, summit 4,207 m, shield stage ~1 Ma); NOAA (sea-level elevation convention).

Shot grammar: every shot type maps to fixed camera behaviour (grammar.py); visual novelty ≥ 1 meaningful event per 5 s (novelty controller auto-fills where authored events leave gaps).
