"""S2-S4: script (hook/length/loop rules) -> critic -> rewrite -> fact_check -> metadata.

    write_story(topic, facts)  -> story dict, verdict PASS | HOLD (never raises for
                                  LLM outages or exhausted rewrites; the reason is recorded)

Pure-code checks (no LLM, unit-tested): check_script (length, hook, roles, loop
formula), check_facts, check_digits (narration numbers vs the CITED facts;
on-screen numbers vs narration), check_title, check_title_batch, check_metadata,
check_duration (post-TTS 30-60 s gate). LLM calls, in order: script_write,
[script_critic], [rewrite = script_write], fact_check, metadata_pack. Rewrite
budget: up to TWO for script quality (code errors and/or critic, shared
pool — decision #14) and ONE for fact-check.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from engine.v16_research import numbers_in, usable  # noqa: E402
from llm import client as llm  # noqa: E402
from llm.prompts import render  # noqa: E402
from llm.types import LLMSchemaError, LLMUnavailable  # noqa: E402

# 2026-10-15 review: 125-128-word scripts ran 51-63 s at a measured 122-146
# wpm and felt slow for the niche. Target is 25-40 s spoken (~60-95 words at
# the new ~180 wpm delivery); the hard floor stays a little above 60 so a
# finished cut (lead + gaps + sting) still clears check_duration's floor.
MIN_WORDS, MAX_WORDS = 65, 100
HOOK_MAX_WORDS = 12
HEADLINE_WORDS = (2, 5)
TITLE_WORDS = (4, 8)
# 2026-10-15 review: floor lowered 30 -> 25 s to match the new 25-40 s
# spoken target (a 30 s floor would HOLD most scripts written to it).
DURATION_S = (25.0, 60.0)
CRITIC_MEAN_MIN, CRITIC_FLOOR = 4.0, 3
# 2026-10-15 review: decision #17 made the critic a pure ranker, so a weak
# hook or a payoff that never resolves still shipped if it out-ranked its
# siblings. A narrow floor is restored on ONLY the two dimensions the review
# names (0-5 scale, 3 = "acceptable" per the critic prompt). Below it, the
# candidate gets its targeted rewrite; still below after that -> HOLD,
# never picked. (Mean/other-dimension floors stay removed, per decision #17.)
CRITIC_HARD_FLOORS = {"hook_strength": 3, "payoff_clarity": 3}
MAX_SCRIPT_REWRITES = 2  # decision #14: shared pool across code-error + critic rewrites
RANK_REWRITE_BUDGET = 1  # decision #15 item 2: one CRITIC rewrite per topic in the rank-not-block flow
# 2026-10-16: a code-rule fix no longer spends the critic rewrite (see
# _rank_one) -- one targeted code-fix per draft (first draft, critic rewrite).
RANK_CODE_FIX_BUDGET = 1
# decision #15 step 1: real critic score (prompt_version 1, unchanged) measured against
# the owner's own ACCEPTABLE sample (t_figure_skater_spin, commit 56b4955) --
# illustrated_engine/build_reports/decision15/step1_calibration.json. The old uniform
# CRITIC_MEAN_MIN=4.0/RANK_FLOOR_DIM=3 bars (decision #15) and the mean+per-dimension
# floor map (decision #16: mean>=3.0, dims>=2 except payoff_clarity/one_idea_only>=3)
# both failed the owner's own accepted sample and trended down on objectively stronger
# topics -- the critic itself is not a reliable pass/fail gate. decision #17: floor
# removed entirely; the critic is now a pure ranker (see `rank_write_story`).
SKATER_CALIBRATION_MEAN = 2.75


AI_NOTE = "Illustrations are AI-generated in our house style; narration uses a synthetic voice."

BAD_OPENERS = re.compile(r"^\s*(did you know|imagine|let'?s|have you ever|ever wonder|"
                         r"what if you|today we)", re.I)
CTA = re.compile(r"\b(subscribe|follow|like and|thanks for watching|see you|"
                 r"next time on|link in|comment below|goodbye)\b", re.I)
TITLE_TROPES = re.compile(r"shocked|you won'?t believe|scientists baffled|baffled|mind-?blowing|"
                          r"gone wrong|will blow your mind|what happens next|jaw-?dropping", re.I)
# decision #16 item 2: absolute/superlative claim words. Multi-word phrases first
# (alternation is first-match, not longest-match) so "no one"/"the first" aren't
# shadowed by a later single-word alternative matching part of them first.
ABSOLUTE_CLAIM_RE = re.compile(
    r"\b(no\s+one|nobody|the\s+only|the\s+first|only\s+one|"
    r"only|sole|solely|first|never|always|every\s+time|everyone|"
    r"biggest|largest|smallest|tallest|shortest|fastest|slowest|"
    r"best|worst|most|least|unique|uniquely|unprecedented)\b", re.I)
ACRONYMS = {"DNA", "RNA", "NASA", "ESA", "UFO", "GPS", "AI", "USA", "UK", "US", "UN",
            "TV", "CERN", "LIGO", "CO2", "LED", "MRI", "CT", "PH"}
QUESTION_WORDS = ("how", "why", "what")

# 2026-10-15 review: two scripts echoed the prompt's OWN example phrasing
# near-verbatim ("but here's the part that breaks it", "that's why you
# should remember this:"). The examples are gone from script_write.md; this
# list is the code-level backstop -- phrases that were (or still read like)
# prompt scaffolding. Matched after _canon() normalisation (case,
# punctuation, common contractions), so "That's why you should remember"
# and "that is why you should remember" both hit.
PROMPT_ECHO_PHRASES = (
    "here is the part that breaks it",
    "the part that breaks it",
    "that is why you should remember",
    "why you should remember this",
    "remember what it is",
    "that pigeon is a dinosaur",
    "next time one struts past you",
    "and that is why you should",
    "one quiet truth",
)
_CONTRACTIONS = (("here's", "here is"), ("that's", "that is"), ("it's", "it is"),
                 ("what's", "what is"), ("there's", "there is"))


def _canon(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower().replace("’", "'")
    for a, b in _CONTRACTIONS:
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", t)).strip()


def check_prompt_echo(script: dict) -> list:
    """Flag scripts that copy prompt scaffolding instead of writing their own
    line (substring match on canonicalised text)."""
    body = _canon(narration(script))
    hits = [p for p in PROMPT_ECHO_PHRASES if p in body]
    return [f"echo: copies stock/prompt phrasing {hits}; write an original line "
            f"specific to this topic"] if hits else []


def words(text: str) -> list:
    return text.split()


def narration(script: dict) -> str:
    return " ".join(s["text"] for s in script["sentences"])


# --------------------------------------------------------- script checks --

def check_script(script: dict) -> list:
    """Length, hook, roles and loop-formula rules -> list of error strings."""
    errs, sents = [], script["sentences"]
    n = len(words(narration(script)))
    if not MIN_WORDS <= n <= MAX_WORDS:
        errs.append(f"length: {n} words, need {MIN_WORDS}-{MAX_WORDS}")
    first = sents[0]["text"]
    if len(words(first)) > HOOK_MAX_WORDS:
        errs.append(f"hook: first sentence has {len(words(first))} words, max {HOOK_MAX_WORDS}")
    if first.rstrip().endswith("?"):
        errs.append("hook: first sentence is a bare question; state a concrete claim")
    if BAD_OPENERS.match(first):
        errs.append("hook: filler opener (Did you know / Imagine / Let's ...)")
    if not HEADLINE_WORDS[0] <= len(words(script["hook_headline"])) <= HEADLINE_WORDS[1]:
        errs.append(f"hook_headline: must be {HEADLINE_WORDS[0]}-{HEADLINE_WORDS[1]} words")
    roles = [s["role"] for s in sents]
    if roles[0] != "hook" or roles.count("hook") != 1:
        errs.append("roles: exactly one hook role, on the first sentence")
    if roles[-1] != "payoff":
        errs.append("roles: the last sentence must have role payoff")
    bad = [t for t in re.findall(r"\d[\d,.]*\d|\d", narration(script))
           if "," in t or "." in t or len(t) > 4]
    if bad:
        errs.append(f"digits: write quantities as words, the voice misreads {bad}")
    if CTA.search(sents[-1]["text"]):
        errs.append("loop: the last sentence is a goodbye/call to action; it must flow into the first")
    if sents[-1]["text"].rstrip().endswith("?"):
        errs.append("loop: the last sentence must resolve, not ask a question")
    # 2026-10-15 review: two shipped scripts ended mid-thought on a colon
    # ("...remember this:", "...one quiet truth:") -- the loop trick taken
    # too literally; on screen it reads as a cut-off sentence.
    if sents[-1]["text"].rstrip().endswith((":", ";", ",", "-", "—")):
        errs.append("loop: the last sentence ends on a colon/dangling "
                    "punctuation; end on a complete sentence")
    errs += check_prompt_echo(script)
    return errs


def check_facts(script: dict, facts: dict) -> list:
    """Every sentence cites at least one existing, usable fact."""
    ok = {f["id"] for f in facts["claims"] if usable(f)}
    errs = []
    for i, s in enumerate(script["sentences"], 1):
        bad = [f for f in s["fact_ids"] if f not in ok]
        if bad or not s["fact_ids"]:
            errs.append(f"sentence {i}: cites missing/unusable fact ids {bad or '(none)'}")
    return errs


def _fact_numbers(f: dict) -> set:
    return numbers_in(" ".join(str(f.get(k) or "") for k in ("claim", "evidence", "quote")))


def check_digits(script: dict, facts: dict) -> list:
    """Narration numbers must appear in the facts the sentence cites (spelled 1-10
    are idiom and skipped); on-screen numbers must be spoken (V15 guard)."""
    by_id = {f["id"]: f for f in facts["claims"]}
    errs, spoken = [], numbers_in(narration(script))
    for i, s in enumerate(script["sentences"], 1):
        allowed = set()
        for fid in s["fact_ids"]:
            if fid in by_id:
                allowed |= _fact_numbers(by_id[fid])
        extra = numbers_in(s["text"], min_spelled=11) - allowed
        if extra:
            errs.append(f"sentence {i}: numbers {sorted(extra)} are not in its cited facts")
        for label in s.get("on_screen", []):
            miss = numbers_in(label) - spoken
            if miss:
                errs.append(f"sentence {i}: on-screen '{label}' shows {sorted(miss)} never spoken")
    return errs


def _magnitude_only(text: str, m: "re.Match") -> bool:
    """True when an "only" is a magnitude qualifier directly on a sourced
    figure ("rocks only three point seven billion years old") -- not an
    exclusivity claim. 2026-10-16 (live_20261015_104500, Oldest Rock draft 1)
    this tripped the absolute-claim rule. Narrow on purpose: the figure must
    be >= 11 / a decimal / a scale, i.e. one check_digits must itself find in
    the sentence's cited facts; "only one" / "only two people" (counts) stay
    absolute claims."""
    if m.group(0).lower() != "only":
        return False
    nxt = " ".join(text[m.end():].split()[:6])
    first = (nxt.split() or [""])[0].lower().strip(",.;:")
    if not (first[:1].isdigit() or first in _SPELLED_NUMBER_START):
        return False
    return any(v >= 11 or v != int(v) for v in numbers_in(nxt, min_spelled=0))


_SPELLED_NUMBER_START = frozenset(
    "two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty "
    "fifty sixty seventy eighty ninety hundred thousand million billion".split())


def check_absolute_claims(script: dict, facts: dict) -> list:
    """decision #16 item 2: a sentence making an absolute/superlative claim
    ("only", "first", "never", "always", "biggest", "no one", ...) must be
    backed by one of its OWN cited facts explicitly stating that specific
    uniqueness/exclusivity -- the same "the support has to actually say it"
    bar `check_digits` applies to numbers, not just a related fact in the
    topic. Pure-code heuristic (no LLM): the cited fact's own claim/evidence/
    quote text must itself carry a matching absolute marker. Worked example
    (decision #15 step 3's real Everest script): "That's been done only
    once, by Tim Macartney-Snape's team in 1990" cites a fact about
    Macartney-Snape's 1990 climb -- but that fact (correctly) does not claim
    nobody else has done a full sea-level ascent (Kropp did one in 1996), so
    the fact doesn't carry an exclusivity marker and this check fails,
    forcing a rewrite that softens the claim (e.g. to "solo") instead of
    asserting exclusivity the facts don't support."""
    by_id = {f["id"]: f for f in facts["claims"]}
    errs = []
    for i, s in enumerate(script["sentences"], 1):
        m = next((x for x in ABSOLUTE_CLAIM_RE.finditer(s["text"])
                  if not _magnitude_only(s["text"], x)), None)
        if not m:
            continue
        supported = False
        for fid in s["fact_ids"]:
            f = by_id.get(fid)
            if not f:
                continue
            blob = " ".join(str(f.get(k) or "") for k in ("claim", "evidence", "quote"))
            if ABSOLUTE_CLAIM_RE.search(blob):
                supported = True
                break
        if not supported:
            errs.append(f"sentence {i}: absolute/superlative claim {m.group(0)!r} has no cited "
                        f"fact stating that exact uniqueness/exclusivity -- soften it to what's "
                        f"actually supported (e.g. describe it as a notable/solo instance and "
                        f"note if others have done something similar) instead of claiming "
                        f"exclusivity the facts don't back")
    return errs


def code_checks(script: dict, facts: dict) -> list:
    return (check_script(script) + check_facts(script, facts) + check_digits(script, facts)
           + check_absolute_claims(script, facts))


def check_duration(seconds: float, script: dict | None = None) -> list:
    """Post-TTS hard gate: 30-60 s; >60 s only with a length_justification (and
    then it is flagged for the owner, see 'flag')."""
    lo, hi = DURATION_S
    if seconds < lo:
        return [f"duration: {seconds:.1f}s < {lo:.0f}s"]
    if seconds > hi and not (script or {}).get("length_justification"):
        return [f"duration: {seconds:.1f}s > {hi:.0f}s without length_justification"]
    return []


# ---------------------------------------------------------- title rules --

def _emoji(ch: str) -> bool:
    return unicodedata.category(ch) == "So" or ord(ch) >= 0x1F000


def check_title(title: str, fact_numbers: set | None = None) -> list:
    """DESIGN §9.4 title rules. `fact_numbers`: numbers of the title's cited facts."""
    errs, w = [], words(title)
    if not TITLE_WORDS[0] <= len(w) <= TITLE_WORDS[1]:
        errs.append(f"title: {len(w)} words, need {TITLE_WORDS[0]}-{TITLE_WORDS[1]}")
    if "#" in title:
        errs.append("title: hashtag")
    if any(_emoji(c) for c in title):
        errs.append("title: emoji")
    caps = [x for x in re.findall(r"[A-Za-z0-9']+", title)
            if len(x) > 1 and x.isupper() and x.isalpha() and x not in ACRONYMS]
    if caps:
        errs.append(f"title: ALL-CAPS words {caps}")
    if TITLE_TROPES.search(title):
        errs.append("title: banned clickbait trope")
    if fact_numbers is not None:
        extra = numbers_in(title) - fact_numbers
        if extra:
            errs.append(f"title: numbers {sorted(extra)} not in its cited facts")
    return errs


def check_title_batch(titles: list) -> list:
    """How/Why/What openers in at most 50% of a batch."""
    if not titles:
        return []
    q = sum(1 for t in titles if words(t) and words(t)[0].lower().strip(",:") in QUESTION_WORDS)
    return [f"batch: {q}/{len(titles)} titles open with How/Why/What (max 50%)"] \
        if q * 2 > len(titles) else []


def check_metadata(meta: dict, facts: dict, batch_titles: list = ()) -> list:
    ok = {f["id"]: f for f in facts["claims"] if usable(f)}
    cited = [ok[i] for i in meta["title_fact_ids"] if i in ok]
    errs = []
    if len(cited) != len(meta["title_fact_ids"]):
        errs.append("title: cites missing/unusable fact ids")
    nums = set().union(*[_fact_numbers(f) for f in cited]) if cited else set()
    errs += check_title(meta["title"], nums)
    errs += check_title_batch([*batch_titles, meta["title"]])
    tags = meta["hashtags"]
    if not 3 <= len(tags) <= 5 or not all(re.fullmatch(r"#\w+", t) for t in tags):
        errs.append("hashtags: need 3-5 tags of the form #word")
    return errs


def build_description(meta: dict, facts: dict, ids: list) -> str:
    """Body + sources + AI note + hashtags (DESIGN §9.4, §11)."""
    by_id = {f["id"]: f for f in facts["claims"]}
    seen, lines = set(), []
    for i in ids:
        f = by_id.get(i)
        ref = (f or {}).get("source_url") or (f or {}).get("source_id")
        if ref and ref not in seen:
            seen.add(ref)
            lines.append(f"- {ref}")
    parts = [meta["description"].strip()]
    if lines:
        parts.append("Sources:\n" + "\n".join(lines))
    parts += [AI_NOTE, " ".join(meta["hashtags"])]
    return "\n\n".join(parts)


# -------------------------------------------------------------- critic --

def critic_pass(scores: dict) -> bool:
    v = list(scores.values())
    return sum(v) / len(v) >= CRITIC_MEAN_MIN and min(v) >= CRITIC_FLOOR


def critic_floor_misses(scores: dict) -> list:
    """-> ["hook_strength=2 < 3", ...] for the CRITIC_HARD_FLOORS dimensions
    (a missing dimension counts as a miss: the critic schema requires it)."""
    out = []
    for dim, lo in CRITIC_HARD_FLOORS.items():
        v = scores.get(dim)
        if not isinstance(v, (int, float)) or v < lo:
            out.append(f"{dim}={v} < {lo}")
    return out


# -------------------------------------------------------- orchestration --

def _facts_block(facts: dict, with_quote: bool = False) -> str:
    rows = []
    for f in facts["claims"]:
        if not usable(f):
            continue
        rows.append(f"{f['id']} | {f['claim']} | {f['evidence']}" if with_quote
                    else f"{f['id']}: {f['claim']} | {f.get('nuance', 'ESTABLISHED')}"
                    + (f" | about: {f['about']}" if f.get("about") else ""))
    # for a quote-checked fact `evidence` is the verbatim source quote (it governs the
    # claim wording); for a curated fact it is the pack's measured values beside the vetted claim
    return "\n".join(rows)


def _numbered(script: dict) -> str:
    return "\n".join(f"{i}. {s['text']}  [{','.join(s['fact_ids'])}]"
                     for i, s in enumerate(script["sentences"], 1))


class _Run:
    def __init__(self, ask):
        self.ask, self.calls = ask, []

    def call(self, stage: str, prompt: str, ver: str):
        res = self.ask(stage, prompt, schema=stage, prompt_version=ver)
        self.calls.append({"stage": stage, "model": res.model, "cached": res.cached,
                           "attempts": res.attempts, "prompt_version": ver,
                           "cost_usd": (res.usage or {}).get("cost_usd")})
        return res.data


def _write(run: _Run, topic: str, facts: dict, series_note: str, critique: str = "",
           previous: dict | None = None) -> dict:
    note = ""
    if critique:
        note = ("\nREWRITE. Your previous script:\n" + _numbered(previous)
                + "\n\nFix ALL of these problems, keep what already works:\n" + critique + "\n")
    prompt, ver = render("script_write", topic=topic, facts=_facts_block(facts),
                         series_note=series_note, min_words=MIN_WORDS, max_words=MAX_WORDS,
                         critique_note=note)
    return run.call("script_write", prompt, ver)


def _fact_check(run: _Run, script: dict, facts: dict) -> list:
    """-> list of problem strings (empty = every sentence supported)."""
    prompt, ver = render("fact_check", facts=_facts_block(facts, with_quote=True),
                         sentences=_numbered(script))
    data = run.call("fact_check", prompt, ver)
    labels = {r["n"]: r for r in data["sentences"]}
    probs = []
    for i in range(1, len(script["sentences"]) + 1):
        r = labels.get(i)
        if r is None:
            probs.append(f"sentence {i}: not judged by fact_check")
        elif r["label"] != "supported":
            probs.append(f"sentence {i} is {r['label']}: {r.get('note', '')}")
    return probs


def write_story(topic: str, facts: dict, *, series_note: str = "", batch_titles: list = (),
                ask=None) -> dict:
    run = _Run(ask or llm.ask)
    story = {"topic": topic, "verdict": "HOLD", "holds": [], "script": None, "critic": None,
             "fact_check": None, "metadata": None, "calls": run.calls, "drafts": []}
    try:
        _pipeline(run, story, topic, facts, series_note, list(batch_titles))
    except (LLMUnavailable, LLMSchemaError) as e:
        story["holds"].append(f"llm: {type(e).__name__}: {str(e)[:200]}")
        if isinstance(e, LLMUnavailable) and e.retry_at:
            story["retry_at"] = e.retry_at.isoformat()
    if not story["holds"]:
        story["verdict"] = "PASS"
    story["llm_calls"] = len(run.calls)
    return story


def _pipeline(run: _Run, story: dict, topic: str, facts: dict, series_note: str,
              batch_titles: list) -> None:
    hold = story["holds"].append
    script = _write(run, topic, facts, series_note)
    story["script"] = script
    story["drafts"].append({"script": script})           # every draft + its critic scores, for review

    # ---- script quality: up to MAX_SCRIPT_REWRITES rewrites shared by
    # code errors and the critic (decision #14: raised from 1 to 2)
    rewrites = 0
    errs = code_checks(script, facts)
    if errs:
        script = story["script"] = _write(run, topic, facts, series_note,
                                          "\n".join(errs), script)
        story["drafts"].append({"script": script, "after": "code errors"})
        rewrites += 1
        errs = code_checks(script, facts)
        if errs:
            hold("script rules still failing after the rewrite: " + "; ".join(errs))
            return
    while True:
        prompt, ver = render("script_critic", script=_numbered(script))
        crit = story["critic"] = run.call("script_critic", prompt, ver)
        story["drafts"][-1]["critic"] = crit
        if critic_pass(crit["scores"]):
            break
        if rewrites >= MAX_SCRIPT_REWRITES:
            hold(f"critic below bar after {rewrites} rewrite(s): {crit['scores']}")
            return
        bar = (f"Critic scores: {crit['scores']}. The bar is a mean of {CRITIC_MEAN_MIN} or "
               f"better with no score below {CRITIC_FLOOR}; lift every score under 4.")
        script = story["script"] = _write(run, topic, facts, series_note,
                                          crit["critique"] + "\n" + bar, script)
        story["drafts"].append({"script": script})
        rewrites += 1
        errs = code_checks(script, facts)
        if errs:
            hold("script rules failing after the critic rewrite: " + "; ".join(errs))
            return

    _finalize(run, story, topic, facts, series_note, batch_titles)


def _finalize(run: _Run, story: dict, topic: str, facts: dict, series_note: str,
              batch_titles: list) -> None:
    """Fact-check (ONE rewrite) + metadata_pack, given a `story["script"]`
    that already cleared code-checks + the critic. Mutates `story` in
    place (holds/fact_check/metadata). Factored out of `_pipeline` so
    decision #15's rank-not-block flow can reuse the exact same tail for
    its single winning candidate instead of duplicating it."""
    hold = story["holds"].append
    script = story["script"]

    # ---- fact check: ONE rewrite, then HOLD
    probs = _fact_check(run, script, facts)
    if probs:
        script = story["script"] = _write(run, topic, facts, series_note, "\n".join(probs), script)
        errs = code_checks(script, facts)
        if errs:
            hold("script rules failing after the fact-check rewrite: " + "; ".join(errs))
            return
        probs = _fact_check(run, script, facts)
    story["fact_check"] = {"problems": probs}
    if probs:
        hold("fact_check still failing after the rewrite: " + "; ".join(probs))
        return

    # ---- metadata (title rules in code; title claim entailed via cited fact ids)
    prompt, ver = render("metadata_pack", script=_numbered(script),
                         facts="\n".join(f"{f['id']} | {f['claim']}" for f in facts["claims"]
                                         if usable(f)),
                         series_note=series_note)
    meta = run.call("metadata_pack", prompt, ver)
    merrs = check_metadata(meta, facts, batch_titles)
    if merrs:
        prompt2 = prompt + "\nYour previous metadata failed these code checks; fix them:\n" \
            + "\n".join(merrs) + "\nPrevious title: " + meta["title"] + "\n"
        meta = run.call("metadata_pack", prompt2, ver)
        merrs = check_metadata(meta, facts, batch_titles)
    if merrs:
        hold("metadata rules failing: " + "; ".join(merrs))
    cited = list(dict.fromkeys(f for s in script["sentences"] for f in s["fact_ids"]))
    meta["description_full"] = build_description(meta, facts, cited)
    story["metadata"] = meta


# ============================================= decision #15: rank, don't block

def _rank_key(crit: dict) -> tuple:
    """Draft preference: clears CRITIC_HARD_FLOORS first, then critic mean."""
    s = crit["scores"]
    return (not critic_floor_misses(s), sum(s.values()) / len(s))


def _critic_bar(crit: dict) -> str:
    bar = (f"Critic scores: {crit['scores']}. The bar is a mean of {CRITIC_MEAN_MIN} or "
           f"better with no score below {CRITIC_FLOOR}; lift every score under 4.")
    misses = critic_floor_misses(crit["scores"])
    if misses:
        bar += (" HARD REQUIREMENT (the script is rejected otherwise): "
                + ", ".join(misses) + ". Make sentence 1 a specific number or "
                "impossible-sounding claim in its first six words, and make the "
                "last line answer the hook's question directly.")
    return crit["critique"] + "\n" + bar


def _rank_one(topic: str, facts: dict, series_note: str, ask) -> dict:
    """One topic's draft -> (code-fix) -> critic -> (critic rewrite ->
    code-fix) -> best draft. -> a rank_write_story candidate dict.

    2026-10-16 (zero-publish day, 4 batches / ~12 topics): two structural
    losses in the old single-budget loop, neither a quality call:
      1. RANK_REWRITE_BUDGET=1 was SHARED: a first draft that needed a code
         fix (live_20261015_093943 prism: "you'll never see") spent it, so a
         hook_strength=2 critic score got no rewrite at all -> hold. The
         code-fix and the critic rewrite now have separate budgets
         (RANK_CODE_FIX_BUDGET per draft, RANK_REWRITE_BUDGET critic
         rewrites) -- 2 rewrites total, the same cap decision #14 gives
         write_story (MAX_SCRIPT_REWRITES=2).
      2. The critic rewrite is an optional polish (it fires below the
         critic_pass mean-4 bar, far above the 3/5 floors). When it broke a
         code rule, the topic HELD and the already-valid draft was thrown
         away (live_20261015_202500 warp bubble: draft 1 was code-clean with
         hook 4 / payoff 3 -- above both floors -- and was lost because the
         rewrite added "never" and an unspoken "Zero g-force"). The rewrite
         now gets its own code-fix; if it still fails, or scores lower, the
         previous valid draft is kept. Floors and code checks are unchanged:
         only a draft that clears both can be "scored"."""
    run = _Run(ask)
    rewrites = 0

    def _clean(script):
        """-> (code-clean script | None, remaining errors)."""
        nonlocal rewrites
        errs = code_checks(script, facts)
        for _ in range(RANK_CODE_FIX_BUDGET):
            if not errs:
                break
            script = _write(run, topic, facts, series_note, "\n".join(errs), script)
            rewrites += 1
            errs = code_checks(script, facts)
        return (None if errs else script), errs

    script, errs = _clean(_write(run, topic, facts, series_note))
    if script is None:
        return {"topic": topic, "status": "hold",
                "reason": "script rules still failing after the rewrite: " + "; ".join(errs),
                "_run": run}

    def _critic(s):
        prompt, ver = render("script_critic", script=_numbered(s))
        return run.call("script_critic", prompt, ver)

    crit = _critic(script)
    notes = []
    for _ in range(RANK_REWRITE_BUDGET):
        if critic_pass(crit["scores"]):
            break
        draft = _write(run, topic, facts, series_note, _critic_bar(crit), script)
        rewrites += 1
        draft, errs = _clean(draft)
        if draft is None:
            notes.append("critic rewrite kept failing script rules ("
                         + "; ".join(errs)[:300] + "); kept the previous valid draft")
            break
        crit2 = _critic(draft)
        if _rank_key(crit2) >= _rank_key(crit):
            script, crit = draft, crit2
        else:
            notes.append(f"critic rewrite scored lower ({crit2['scores']}); "
                         "kept the previous draft")
    scores = crit["scores"]
    mean = sum(scores.values()) / len(scores)
    misses = critic_floor_misses(scores)
    out = {"topic": topic, "critic": crit, "mean": mean, "min": min(scores.values()),
           "rewrites": rewrites, "_run": run}
    if notes:
        out["notes"] = notes
    if misses:
        return {**out, "status": "hold",
                "reason": "critic floor (weak hook / unresolved payoff) "
                          f"after {rewrites} rewrite(s): " + ", ".join(misses)}
    return {**out, "status": "scored", "script": script, "facts": facts}


def rank_write_story(topics_facts: list, *, series_note: str = "", batch_titles: list = (),
                     ask=None) -> dict:
    """decision #15 item 2: instead of generating one topic's script and
    falling back to the next topic only on a HOLD, generate scripts for
    every `(topic, facts)` pair up front (one code-fix rewrite per draft plus
    up to RANK_REWRITE_BUDGET=1 critic rewrite each if the first draft fails
    the critic's own `critic_pass` bar -- see `_rank_one`), score all of them with the real script critic, and pick the
    HIGHEST-scoring one. decision #17: that pick is ALWAYS finalized
    (fact_check + metadata via `_finalize`) and returned as the producible
    story -- there is no mean floor on the critic score; the critic is a
    ranker, EXCEPT for the narrow CRITIC_HARD_FLOORS (hook_strength,
    payoff_clarity >= 3; restored 2026-10-15 review): a candidate below
    either after its rewrite is a "hold", never picked. The only way this can come back
    with no pick (`picked_topic` None, verdict "HOLD") is if every topic's
    candidate never reaches "scored" status at all -- it HOLDs on a
    script-rule code-check failure (`code_checks`: facts, digits,
    absolute-claims, ...) that survives its rewrite budget. Every
    candidate's full critic scores (or hold reason, if it never reached a
    scored state) are returned in "candidates" regardless of the outcome,
    so a HOLD slot stays fully auditable.

    -> {"verdict": "PASS"|"HOLD", "picked_topic": str|None, "story": dict|None,
        "candidates": [{"topic", "status": "scored"|"hold", ...}]}
    """
    candidates = []
    for topic, facts in topics_facts:
        candidates.append(_rank_one(topic, facts, series_note, ask or llm.ask))

    scored = [c for c in candidates if c["status"] == "scored"]
    picked = max(scored, key=lambda c: c["mean"]) if scored else None
    public_candidates = [{k: v for k, v in c.items() if k not in ("_run", "script", "facts")}
                         for c in candidates]
    result = {"verdict": "HOLD", "picked_topic": None, "story": None,
              "candidates": public_candidates}

    if picked is not None:
        story = {"topic": picked["topic"], "verdict": "HOLD", "holds": [],
                 "script": picked["script"], "critic": picked["critic"], "fact_check": None,
                 "metadata": None, "calls": picked["_run"].calls,
                 "drafts": [{"script": picked["script"], "critic": picked["critic"]}]}
        try:
            _finalize(picked["_run"], story, picked["topic"], picked["facts"], series_note,
                     list(batch_titles))
        except (LLMUnavailable, LLMSchemaError) as e:
            story["holds"].append(f"llm: {type(e).__name__}: {str(e)[:200]}")
            if isinstance(e, LLMUnavailable) and e.retry_at:
                story["retry_at"] = e.retry_at.isoformat()
        story["verdict"] = "PASS" if not story["holds"] else "HOLD"
        story["llm_calls"] = len(picked["_run"].calls)
        result["picked_topic"] = picked["topic"]
        result["story"] = story
        result["verdict"] = story["verdict"]
    return result


# ------------------------------------------------------------------ CLI --

def main(argv=None) -> int:
    """python -m engine.v16_script --curated bench/quality/topics/02_tunguska --topic "..." --out DIR"""
    import argparse
    import json
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--curated", required=True, help="dir holding a curated facts.json pack")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--series-note", default="")
    a = ap.parse_args(argv)
    from engine.v16_research import from_curated
    facts = from_curated(json.loads((Path(a.curated) / "facts.json").read_text()))
    story = write_story(a.topic, facts, series_note=a.series_note)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "facts.json").write_text(json.dumps(facts, indent=1))
    (out / "story_engine.json").write_text(json.dumps(story, indent=1))
    if story["script"]:
        (out / "script.txt").write_text(narration(story["script"]) + "\n")
    print(json.dumps({"verdict": story["verdict"], "holds": story["holds"],
                      "llm_calls": story["llm_calls"]}, indent=1))
    return 0 if story["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
