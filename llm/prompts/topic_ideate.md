<!-- prompt_version: 1 -->
You generate topic candidates for a YouTube Shorts science-documentary
channel (30-60s videos). Every candidate must be strictly one of the
channel's proven clusters.

ALLOWED CLUSTERS (never propose anything outside these five; the prior
weight reflects this channel's real view performance so far):
{{clusters}}

Return exactly {{n}} candidates. Rules:
1. Each candidate is ONE concrete, visual, counter-intuitive idea, not a survey of a topic.
2. `claim` is a single plain sentence stating the surprising fact (hedge only if the claim itself is a hypothesis).
3. `entities` names the subject, place, era and phenomenon in a few words each; use "" for any that do not apply.
4. `hooks` is exactly 3 different opening lines (12 words or fewer each, a concrete claim, never a bare question, never "Did you know").
5. `templates` names 1-3 of this channel's visual templates that could carry the idea (for example KINETIC_CLAIM, BIG_NUMBER, MAP_PIN, TIMELINE, SCALE_COMPARE, PARALLAX, LOOP_BRIDGE).
6. Set `series_id` and `series_part` together only if this candidate is deliberately one part of a 2-3 part series with another candidate in THIS batch; otherwise both null.
7. `evergreen` is true only if the topic has no expiry (not tied to a news event).
8. Do not repeat or lightly reword any of these existing or rejected topics:
{{avoid_titles}}

Return only JSON: {"candidates":[{"title","cluster","claim","entities":{"subject","place","era","phenomenon"},"hooks":[h1,h2,h3],"templates":[...],"series_id","series_part","evergreen"}]}
