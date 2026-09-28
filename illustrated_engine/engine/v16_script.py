"""S2-S4: script (hook/length/loop rules) -> critic -> rewrite -> fact_check -> metadata.

    write_story(topic, facts)  -> story dict, verdict PASS | HOLD (never raises for
                                  LLM outages or exhausted rewrites; the reason is recorded)

Pure-code checks (no LLM, unit-tested): check_script (length, hook, roles, loop
formula), check_facts, check_digits (narration numbers vs the CITED facts;
on-screen numbers vs narration), check_title, check_title_batch, check_metadata,
check_duration (post-TTS 30-60 s gate). LLM calls, in order: script_write,
[script_critic], [rewrite = script_write], fact_check, metadata_pack. Rewrite
budget: ONE for script quality (code errors or critic) and ONE for fact-check.
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

MIN_WORDS, MAX_WORDS = 75, 140          # DESIGN §4: ~145 wpm => 31-58 s
HOOK_MAX_WORDS = 12
HEADLINE_WORDS = (2, 5)
TITLE_WORDS = (4, 8)
DURATION_S = (30.0, 60.0)
CRITIC_MEAN_MIN, CRITIC_FLOOR = 4.0, 3
AI_NOTE = "Illustrations are AI-generated in our house style; narration uses a synthetic voice."

BAD_OPENERS = re.compile(r"^\s*(did you know|imagine|let'?s|have you ever|ever wonder|"
                         r"what if you|today we)", re.I)
CTA = re.compile(r"\b(subscribe|follow|like and|thanks for watching|see you|"
                 r"next time on|link in|comment below|goodbye)\b", re.I)
TITLE_TROPES = re.compile(r"shocked|you won'?t believe|scientists baffled|baffled|mind-?blowing|"
                          r"gone wrong|will blow your mind|what happens next|jaw-?dropping", re.I)
ACRONYMS = {"DNA", "RNA", "NASA", "ESA", "UFO", "GPS", "AI", "USA", "UK", "US", "UN",
            "TV", "CERN", "LIGO", "CO2", "LED", "MRI", "CT", "PH"}
QUESTION_WORDS = ("how", "why", "what")


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
    if CTA.search(sents[-1]["text"]):
        errs.append("loop: the last sentence is a goodbye/call to action; it must flow into the first")
    if sents[-1]["text"].rstrip().endswith("?"):
        errs.append("loop: the last sentence must resolve, not ask a question")
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


def code_checks(script: dict, facts: dict) -> list:
    return check_script(script) + check_facts(script, facts) + check_digits(script, facts)


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


# -------------------------------------------------------- orchestration --

def _facts_block(facts: dict, with_quote: bool = False) -> str:
    rows = []
    for f in facts["claims"]:
        if not usable(f):
            continue
        rows.append(f"{f['id']} | {f['claim']} | {f['evidence']}" if with_quote
                    else f"{f['id']}: {f['claim']} | {f.get('nuance', 'ESTABLISHED')}")
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
             "fact_check": None, "metadata": None, "calls": run.calls}
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

    # ---- script quality: ONE rewrite shared by code errors and the critic
    rewrote = False
    errs = code_checks(script, facts)
    if errs:
        script = story["script"] = _write(run, topic, facts, series_note,
                                          "\n".join(errs), script)
        rewrote = True
        errs = code_checks(script, facts)
        if errs:
            hold("script rules still failing after the rewrite: " + "; ".join(errs))
            return
    for _ in (1, 2):
        prompt, ver = render("script_critic", script=_numbered(script))
        crit = story["critic"] = run.call("script_critic", prompt, ver)
        if critic_pass(crit["scores"]):
            break
        if rewrote:
            hold(f"critic below bar after the rewrite: {crit['scores']}")
            return
        script = story["script"] = _write(run, topic, facts, series_note, crit["critique"], script)
        rewrote = True
        errs = code_checks(script, facts)
        if errs:
            hold("script rules failing after the critic rewrite: " + "; ".join(errs))
            return

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
