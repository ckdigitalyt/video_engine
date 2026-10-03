# Source check — topic `t_humans_are_closer_to_t_rex_than_t_rex_wa` (checked 2026-10-02)

Owner priority-override run (2026-10-02). Topic selected from `data/topic_history.jsonl`'s
existing `queued` set (highest score, 93, cluster `deep_time`, no LLM ideate call spent) —
not previously `published`/`uploaded`. Verified via direct Wikipedia fetch (`curl`), no
web-search API available in this session; Wikipedia used as secondary source per the
WP4 precedent in `bench/ab/source_check.md`.

Title: "Humans Are Closer to T-Rex Than T-Rex Was to Stegosaurus"
Claim: "Tyrannosaurus rex lived closer in time to modern humans than to Stegosaurus."

| id | verdict | corrected wording | URL | evidence |
|---|---|---|---|---|
| f_trex_range | SUPPORTED | - | https://en.wikipedia.org/wiki/Tyrannosaurus | "69 to 66 million years ago" (Maastrichtian, end-Cretaceous). |
| f_stego_range | SUPPORTED | - | https://en.wikipedia.org/wiki/Stegosaurus | "dating to between 155 and 145 million years ago" (Kimmeridgian–Tithonian). |
| f_gap_to_stego | SUPPORTED | Gap between T. rex's earliest appearance (~69 Mya) and Stegosaurus's latest (~145 Mya) is ~76 million years (up to ~89 My using the opposite ends of each range). | computed from the two rows above | 145−69 = 76 My (min); 155−66 = 89 My (max). |
| f_gap_to_humans | SUPPORTED | T. rex went extinct ~66 Mya; anatomically modern humans (Homo sapiens) are well-established as emerging within the last ~0.3 My (Jebel Irhoud fossils), a gap of ~65.7 million years — smaller than the T. rex–Stegosaurus gap under any combination of the ranges above. | https://en.wikipedia.org/wiki/Homo_sapiens | Page confirms human origin "several million years ago" for the broader hominin lineage; anatomically modern H. sapiens dating to ~300 kya is an independently well-sourced, uncontested figure not disputed by this page and not restated verbatim here since it wasn't the load-bearing number (the claim only needs humans to postdate 66 Mya by a wide margin, which is true regardless of the exact modern-human date). |

**Verdict: claim fully SUPPORTED.** Script must phrase the comparison using the
ranges above (T. rex 69–66 Mya; Stegosaurus 155–145 Mya), not a single invented
number, and must not claim a precise "humans appeared X years ago" figure beyond
what's needed (millions of years, not hundreds of millions).
