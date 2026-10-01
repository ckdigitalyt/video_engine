<!-- prompt_version: 1 -->
Score each topic candidate below on 5 rubrics, 0-5 each (0 weak, 5
excellent). Anchor your scoring on these real channel outcomes: winners
"Dinosaurs Were Thriving" (1,360 views) and "How Scientists Created a Time
Crystal" (1,093 views); losers "Underwater rivers flowing across the ocean
floor" (6 views) and "Blood Falls" (136 views).

CANDIDATES:
{{candidates}}

Rubrics:
- counter_intuitive: is this one sharp, surprising idea, not a survey?
- visualisability: can a fixed template library show it in striking frames?
- hook_strength: pick the strongest of the 3 given hooks and score it (return it as `best_hook`).
- series_potential: could this split into 2-3 standalone parts, each with its own payoff?
- evidence_strength: would 2 or more reputable sources plausibly exist and mostly agree?

Return only JSON: {"scores":[{"id","counter_intuitive","visualisability","hook_strength","series_potential","evidence_strength","best_hook"}]}
