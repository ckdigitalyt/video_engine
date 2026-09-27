# V15 Upgrade Log (running checkpoint)

Resume rule: read V15_PLAN.md, then the last entry here; continue at "next".

| # | Milestone | Commit | Tests / evidence | Next |
|---|---|---|---|---|
| 0 | Research + plan (V15_PLAN.md); before sheets in evidence/ | (plan only) | NIM probe 2.9 s; Remotion cost 6.5 s + 2.2 s/s; judge chain live | M1 |
| 1 | M1+M2a correctness + renderer art-direction plumbing | 7645337 | v14_pipeline e2e still PASS (9m38s), captions now per-beat; tests/test_v15.py | M3-M6 |
| 2 | M3 timing, M4 BVP, M5 plates, M6 shots+pipeline, M7 gate (first e2e run on ice: HOLD — gate caught a real caption-grouping bug, over-strict plate QA, 5.3 s hold, 287 s assembly) | (uncommitted WIP) | fixes: cue grouping, plate-QA recalibration ("shows"+narrow fail enum), punch-in split for long holds, single-pass concat+burn | rerun ice, then cell |
| 3 | M3-M7 committed | 7f4e769 | first ice e2e PASS after fixes; cell HOLD (judge: garbled caption claims, level-label overlap, dark accent) | gate-driven fixes |
| 4 | M7b gate-driven fixes (cue grouping, plate-QA calibration, plan salvage, GLM reasoning budget, portal mask, accent lightening, single-pass assembly) | e4c42c0, 00589bd | tests/test_v15.py ALL PASS (11); V14 finals FAIL new gate (evidence json) | 3-story batch (ice, cell, tunguska unseen) -> report |
