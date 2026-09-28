<!-- prompt_version: 1 -->
Write upload metadata for a 30-60 second vertical science short on @most.amazing.wonders.

SCRIPT:
{{script}}

FACTS (id | claim):
{{facts}}
{{series_note}}
Rules:
1. `title`: 4-8 words (aim for 5-7), a concrete noun plus a twist. No hashtags, no emoji, no ALL-CAPS words except acronyms. Do not start with How/Why/What unless nothing else works. Never use "shocked", "you won't believe", "scientists baffled", "mind-blowing", "gone wrong". The title must be true under the cited facts.
2. `title_fact_ids`: ids of the facts that entail the title's claim (from the list only).
3. `description`: 2 short sentences that add curiosity without spoiling the payoff and without new claims. Do not include hashtags, sources or AI notes; code appends them.
4. `hashtags`: 3-5, each starting with #, no spaces.
5. `series_tag`: a short slug for the series or "standalone".
6. `pinned_comment`: one question that invites a guess or an opinion, under 20 words.

Return only JSON: {"title","title_fact_ids","description","hashtags","series_tag","pinned_comment"}
