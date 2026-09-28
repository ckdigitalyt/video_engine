# WP4 acceptance report — story engine (S1-S4)

Verdict: **code DONE and tested; A/B #1 PARTIAL/PENDING.** Topic 2 (tunguska) was run live at script level and correctly **HOLDs at the critic gate** (best draft mean 3.75, bar 4.0). No video was rendered for any topic. Topics 1 and 3 were **not** run (see "Source check").

## What was built
- S1 `illustrated_engine/engine/v16_research.py`: `build_facts` (1 `research_extract` call over fetched source text; every claim's quote must exist in its source, and the claim may not add numbers the quote lacks; < 3 survivors = HOLD), `from_curated` (bench packs), `numbers_in` (digits + spelled numbers).
- S2-S4 `illustrated_engine/engine/v16_script.py`: `write_story` = script_write -> [rewrite on code errors] -> script_critic -> one rewrite -> fact_check (one rewrite) -> metadata_pack (one retry). PASS/HOLD with reasons; LLM outage = HOLD with `retry_at`. CLI: `python -m engine.v16_script --curated <topic dir> --topic ... --out DIR` (run from `illustrated_engine/`, with `venv/bin/python`).
- `llm/prompts.py`, `llm/prompts/*.md` (5 versioned prompts), `llm/schemas/*.json` (5 schemas). No config change (stages already existed).
- Tests: `illustrated_engine/tests/test_wp4_story.py`, 29 pure-code tests (fake `ask`): quote-exists, claim-adds-number, digit guard (per cited fact, spelled == digits, DESIGN §9.4 "2,150 vs roughly 2,000" case, on-screen digits), length, hook, roles/loop, voice-safe digits, title rules + batch share, hashtags, duration gate, critic bar, every orchestration branch (happy path 4 calls, code error, critic fail/pass/HOLD, fact-check fail/pass/HOLD, missing sentence, metadata retry, quota HOLD), prompt/schema validity.

## Tests
- `illustrated_engine/tests`: 78 passed (49 before + 29 new), via venv pytest.
- Root suite: **58 failed / 5 errors before (clean worktree of 6c8ec87) and after; the 63 failing ids are IDENTICAL** (`~/phase4_out/wp4/suite_{before,after}.txt`). Pass/skip counts differ as in WP3 (1259/8 vs 1263/4); not traced. The "after" run started at commit 81812b3; the later commits touched only WP4 files, the lexicon yaml and CHANGELOG.
- Secret scan over the diff: clean. `.env` untouched.

## Live run, topic 2 (tunguska, curated pack, 8 verified claims)
Three full runs (prompt/rule fixes between them, each found by the previous run): all HOLD at the critic.

| run | change | draft 1 mean | rewrite mean | result |
|---|---|---|---|---|
| 1 | initial prompts | (not kept) | 3.5 | HOLD |
| 2 | rewrite note carries the scores + the bar | 3.0 | 3.5 | HOLD |
| 3 | script_write v2: quantities as words, code digit rule | 3.5 | 3.75 (hook 5, loop 5, curiosity 3, escalation 3, voice 3, emotion 3) | HOLD |

Scripts, drafts, critic scores, calls: `~/phase4_out/wp4/tunguska/story_engine.json` (+ `script.txt`, `voice.wav`, `ab1_script_metrics.json`); earlier runs in `tunguska_v1`, `tunguska_run2`.

Rule metrics, final draft (code-computed) vs V15 `tunguska_1908` narration, same rules:

| | V15 | WP4 draft |
|---|---|---|
| words (75-140) | 199 -> FAIL | 136 |
| first sentence words (<= 12) | 10 (a dateline, no claim) | 9: "Something flattened eighty million trees and left no crater." |
| Kokoro duration (30-60 s) | 77.96 s (rendered) | 57.95 s |
| hook voice onset (<= 0.25 s) | not measured | 0.021 s |
| code checks | length fails | all pass |

- Every sentence cites a fact id; narration numbers are in the cited facts; no digit/hook/length errors.
- Fact check + metadata were smoke-tested live on the run-2 draft (Sonnet): metadata passed the title rules ("The Siberian Blast That Left No Crater"); fact_check labels were noisy until the prompt asked for the note first (v3: 12/12 supported on that draft, notes sensible). Not calibrated against labelled examples.
- Claude calls in this run: 15 fresh (10 Opus, 5 Sonnet), about $0.77 list-price equivalent; a single clean pass is 4 calls (~$0.26). Ledger: `~/phase4_out/wp4/llm_build/llm_ledger.jsonl`.

## Source check (A/B on topics 1 and 3): PENDING
`bench/ab/source_check.md` and `source_check` fields in the two packs appeared (uncommitted, written by the other agent) during this run. Only 4 of 6 claims per pack are `verified:true`; the 2 corrected claims in each stay `verified:false` (corrections not yet accepted), and the files are still uncommitted. I read that as not yet final, so I did **not** run topics 1 and 3 and did not commit those files. `from_curated` already honours `verified` and `correction`, so once the owner marks the packs final it is one command each (2 Opus + ~2 Sonnet calls). No render was done for any topic (V15 renders HOLD on the right rail until WP6/WP7, and a render costs 5-9 Claude calls plus ~17 min).

## Findings for the owner
1. **The critic bar (mean >= 4.0, none < 3, one rewrite) HOLDs 3/3 on tunguska.** Scores climb with the rewrite (3.0 -> 3.5, 3.5 -> 3.75) but not to 4.0; the weak dimensions are curiosity_gap / escalation / human_voice / emotional_charge, and the scripts are constrained to verified facts. Options (your call, I did not change the bar): allow a second rewrite (+2 Opus calls on failure), lower the bar to 3.75, or accept HOLD and review. The critic prompt says "be strict" and its scores were not calibrated against the channel's winners.
2. **Two voice-layer gaps found by the live script, not fixed here (WP3):** (a) the round-trip QA HOLDs (WER 0.06 > 0.03) on "fifteen hundred" because Whisper writes "1500" and the normaliser expects "one thousand five hundred"; Whisper also splits "2,000" as "2 ,000". The voice itself was fine on a read of the transcript. (b) Kokoro reads digits like "2,000" as "two zero zero zero", so WP4 now forbids comma/decimal/5+-digit numbers in narration (code rule + prompt).
3. Added lexicon entry `kulik` (ASR round trip passes; not listened to).
4. No web access this run, so `build_facts` (S1) is tested with fake ask and a synthetic source only; it has not seen a real fetched page. Fetching stays the caller's job.
5. Curated packs carry no verbatim quote, so their facts pass on `verified:true` alone; quote checking applies to LLM-extracted packs only.
6. The 30-60 s gate is tight: 136 words = 58 s with Kokoro (the 140-word cap is about 59 s).
