<!-- prompt_version: 4 -->
Score each topic candidate below on 5 rubrics, 0-5 each (0 weak, 5
excellent). Anchor your scoring on these real channel outcomes (audience
retention = share of the video the average viewer watched): winners
"Sound Waves That Levitate Objects" (72% retention, most subscribers gained),
"The Frog That Breaks Magnet Physics" (82%) and "Why Pilots Train To Black
Out On Purpose" (67%, most views); losers "This White Redwood Can't Feed
Itself" (44%) and "Why This Black Hole Burns Hotter Dying" (47%) -- both
opened on an abstract state instead of something you can see.

CANDIDATES:
{{candidates}}

Rubrics:
- counter_intuitive: is this one sharp, surprising idea, not a survey?
- visualisability: can a fixed template library show it in striking frames?
- hook_strength: pick the strongest of the 3 given hooks and score it (return it as `best_hook`).
- series_potential: could this split into 2-3 standalone parts, each with its own payoff?
- evidence_strength: would 2 or more reputable sources plausibly exist and mostly agree?
- still_image_fit: is the core payoff something a SINGLE STILL IMAGE can clearly show (a static subject, creature, place, or object — this channel's actual niche: mysteries, natural wonders, animals, places, history)? Score LOW (0-1) if the core payoff is a dynamic physical process or mechanism that only makes sense in motion (a chemical reaction, something spinning/falling/exploding mid-action) and can't be conveyed by a still frame. A striking suspended or frozen STATE is still-image friendly and scores high (an object or frog hanging in midair, liquid frozen into spikes, a body pinned by g-force) -- those are this channel's best performers. A side-by-side SCALE COMPARISON (two things drawn at true relative size, such as a pyramid next to a volcano, or a horse next to a dog) is also still-image friendly.

Return only JSON: {"scores":[{"id","counter_intuitive","visualisability","hook_strength","series_potential","evidence_strength","still_image_fit","best_hook"}]}
