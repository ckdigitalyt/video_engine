<!-- prompt_version: 2 -->
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
- still_image_fit: is the core payoff something a SINGLE STILL IMAGE can clearly show (a static subject, creature, place, or object — this channel's actual niche: mysteries, natural wonders, animals, places, history)? Score LOW (0-1) if the core payoff is a dynamic physical process or mechanism that only makes sense in motion (a chemical reaction, something spinning/falling/exploding mid-action) and can't be conveyed by a still frame.

Return only JSON: {"scores":[{"id","counter_intuitive","visualisability","hook_strength","series_potential","evidence_strength","still_image_fit","best_hook"}]}
