# V15 baseline (frozen in WP0)

Source: existing V15 `pipeline_report.json` + `final.mp4` (no re-render). Reference for every later A/B.

| story | verdict | dur s | shots | median shot s | max hold s | LUFS | plate QA ran | hook stops scroll | template feel | total s |
|---|---|---|---|---|---|---|---|---|---|---|
| ice_slippery | PASS | 50.4 | 11 | 4.39 | 3.86 | -14.3 | True | True | False | 255.9 |
| cell_scale_dive | PASS | 54.5 | 15 | 2.84 | 3.78 | -14.1 | True | True | False | 345.5 |
| blackhole_clocks | PASS | 56.4 | 17 | 3.41 | 4.26 | -14.2 | False | True | False | 1032.8 |

## Known baseline defects (do not read PASS as good)

- **ice_slippery**: judge flagged frame 4: text_garbled (gate still PASS).
- **ice_slippery** judge note: Strong story-specific visuals throughout, but frame 4's label reads 'MELTS AND SQUEEZED OUT' — garbled phrasing that must be fixed.
- **cell_scale_dive**: judge flagged frame 4: no_change (gate still PASS).
- **cell_scale_dive**: judge flagged frame 12: no_change (gate still PASS).
- **cell_scale_dive** judge note: Strong watercolor visuals tied to the scale narrative with a punchy hook and payoff, but frames 4 and 12 linger on near-identical imagery from the preceding beats and need a visual beat change.
- **blackhole_clocks**: plate QA silently skipped (Gemini quota); watermark/garbled plates shipped (RESEARCH §2.3). WP2 makes this a HOLD.
- **blackhole_clocks** judge note: Every frame carries story-specific imagery (black hole, warped grid, GPS satellites, falling clock at the horizon) with clean legible labels, the opening question is answered by the frozen-clock finale, and the visuals are too topic-bound to reuse as a template.
