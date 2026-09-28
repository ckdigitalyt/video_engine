<!-- prompt_version: 1 -->
You extract checkable facts for a 30-60 second science short about: {{topic}}

SOURCES (each block starts with its id):
{{sources}}

Rules:
1. Return 4-10 claims, each one atomic and visual or surprising, each supported by ONE source.
2. `quote` is copied VERBATIM, character for character, from that source's text (one sentence or clause, 12+ characters). Never paraphrase, never join two passages, never fix typos. A code check rejects any quote not found in the source.
3. `claim` restates the quote in plain words. Every number in `claim` must appear in `quote`. Do not add numbers, dates, names or superlatives that the quote does not contain. Keep the source's hedges ("about", "may", "is thought to").
4. `source_id` is the id of the block the quote came from.
5. `nuance`: ESTABLISHED (sources agree), CONTESTED (sources or experts disagree), HYPOTHESIS (proposed, not shown).
6. `id` is `f_` plus a short snake_case name, unique.
7. Prefer claims that build one story (setup, surprise, payoff) over a survey of the topic.

Return only JSON: {"claims":[{"id","claim","quote","source_id","nuance"}]}
