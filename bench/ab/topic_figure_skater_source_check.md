# Source check — topic `t_a_figure_skater_spins_faster_without_add` (checked 2026-10-03)

Topic selected from `data/topic_history.jsonl`'s existing `queued` set (second-highest
score, 92, cluster `spectacle_physics`; the highest-scored queued item,
`t_humans_are_closer_to_t_rex_than_t_rex_wa`, is explicitly excluded — already used for the
`t_humans_closer_trex` sample). No LLM ideate call spent; dedupe/scoring were already
computed by the real WP11 topic engine when this row was queued. Verified via direct
`curl` fetch against Wikipedia (no web-search API available in this session, same
precedent as `bench/ab/topic_trex_source_check.md`).

Title (as queued): "A Figure Skater Spins Faster Without Adding Any Energy"
Claim (as queued): a figure skater pulling her arms in spins faster, and this looks
like "free" speed with no energy input.

| id | verdict | corrected wording | URL | evidence |
|---|---|---|---|---|
| f_am_conserved | SUPPORTED | - | https://en.wikipedia.org/wiki/Angular_momentum | "A figure skater in a spin uses conservation of angular momentum – decreasing her moment of inertia by drawing in her arms and legs increases her rotational speed." |
| f_moi_arms | SUPPORTED | - | https://en.wikipedia.org/wiki/Moment_of_inertia | "Spinning figure skaters can reduce their moment of inertia by pulling in their arms, allowing them to spin faster due to conservation of angular momentum." |
| f_L_eq_Iw | SUPPORTED | - | https://simple.wikipedia.org/wiki/Angular_momentum | "L = Iω ... as she decreases her radius by retracting her arms and legs, her moment of inertia decreases, but her angular velocity increases to compensate." Third independent corroboration of the same mechanism. |
| f_energy_not_free | **CORRECTED** (queued title overstates this) | The spin-up is NOT energy-free: rotational kinetic energy is `KE = L^2/(2I)`, so at constant `L`, decreasing `I` necessarily *increases* `KE` — the skater ends up spinning with more kinetic energy than she started with. That extra energy is real; it comes from the work her own arm/core muscles do pulling her limbs in against the inertial resistance ("centrifugal" effect in her own rotating frame), not from any outside push. | https://en.wikipedia.org/wiki/Angular_momentum (same page's own Hamiltonian-formalism section gives `E_k = L^2/(2I)` per axis) | Derived directly from the sourced `L=Iω` and `KE=L²/2I` relations already on the page — not an invented number. |

**Verdict: core mechanism claim fully SUPPORTED by 3 independent sources (Angular
Momentum, Moment of Inertia, Simple Wikipedia Angular Momentum pages), all describing
the identical figure-skater example.** The queued title's "without adding any energy"
framing is a common pop-science overstatement and is **factually wrong** if taken
literally (kinetic energy increases, angular momentum does not) — the script must not
repeat it. Corrected framing used in `story.json`: the skater spins faster **without any
outside push/torque** (angular momentum is what's conserved, not energy); the extra
rotational energy comes from her own muscles pulling her arms in, not from an external
source. No fabricated speed-multiplier numbers are used (no reliably sourced "Nx faster"
figure was found) — narration stays qualitative on magnitude, exact on the mechanism.
