"""
script_review.py — Multi-reviewer script review stage.

Runs four independent reviewer personas against a documentary script,
consolidates their feedback, and revises the script.  Up to ``max_passes``
passes (default 3) or until the quality gate is met — never infinite.

Personas (independent objectives):
  1. Fact Reviewer       — claim-level accuracy vs research facts
  2. Documentary Editor  — structure, pacing, transitions, clarity
  3. Audience Retention  — hook strength, curiosity gaps, drop-off risk
  4. Storytelling        — emotional arc, memorable moments, spoken-style prose

Outputs:
  - final script (list of scene narrations)
  - review report (per-pass scores, resolved/unresolved issues, confidence)
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.providers.factory import ProviderFactory
from src.utils.config import get_config

# ═══════════════════════════════════════════════════════════════════════ #
# Review scaffolding
# ═══════════════════════════════════════════════════════════════════════ #


@dataclass
class ReviewIssue:
    persona: str
    severity: str          # critical | major | minor | nit
    location: str          # e.g. "scene 2" or "whole script"
    issue: str
    suggestion: str


@dataclass
class PersonaScore:
    persona: str
    score: float           # 0-10
    confidence: float      # 0-1
    summary: str
    issues: list[ReviewIssue] = field(default_factory=list)


@dataclass
class ReviewResult:
    pass_number: int
    scores: dict[str, PersonaScore]
    revised_scenes: list[str]
    passed: bool
    notes: str = ""


# ═══════════════════════════════════════════════════════════════════════ #
# Persona definitions
# ═══════════════════════════════════════════════════════════════════════ #

PERSONAS: dict[str, dict] = {
    "fact_reviewer": {
        "label": "Fact Reviewer",
        "brief": (
            "You are a ruthless science fact-checker for a documentary studio. "
            "Check EVERY claim against the provided research facts and sources. "
            "Flag unsupported claims, exaggerations, false precision, and "
            "outdated figures. Cite which research fact supports or contradicts "
            "each claim. Never let an unverified number reach air.\n"
            "Pay special attention to: (1) named nicknames and quotations — the "
            "chart anomaly Jocelyn Bell noticed was called 'scruff', but the "
            "signal itself was jokingly nicknamed LGM-1 ('Little Green Men'); "
            "do not conflate the two. (2) attribution — who said/did what, when. "
            "(3) units and magnitudes (radius vs diameter, km vs miles). "
            "(4) dates. When a claim is a paraphrase of a source, ensure the "
            "paraphrase preserves the source's meaning exactly."
        ),
    },
    "documentary_editor": {
        "label": "Documentary Editor",
        "brief": (
            "You are a veteran documentary editor (BBC/NOVA standard). Evaluate "
            "structure, logical flow, pacing, transitions between scenes, clarity, "
            "grammar, and narration suitability. Cut filler. Every sentence must "
            "move the story forward. Mark line-level edits."
        ),
    },
    "retention_reviewer": {
        "label": "Audience Retention Reviewer",
        "brief": (
            "You are a YouTube retention analyst. Evaluate hook strength in the "
            "first 5 seconds, curiosity gaps, momentum, and 15-second drop-off "
            "risk. Recommend concrete rewrites that create curiosity without "
            "clickbait. The audience is curious general viewers, not scientists."
        ),
    },
    "storytelling_reviewer": {
        "label": "Storytelling Reviewer",
        "brief": (
            "You are a narrative architect. Evaluate emotional progression, "
            "narrative arc (setup->journey->revelation->resonance), memorable "
            "conclusions, and spoken-language quality. Flag generic AI phrasing "
            "(e.g. 'delve', 'unlock the secrets', 'in the vast tapestry'), "
            "repetition, and written-style sentences that won't sound natural "
            "when narrated."
        ),
    },
}

# Quality gate thresholds (0-10)
GATE = {
    "hook": 8.0,          # retention_reviewer score
    "retention": 7.0,     # retention_reviewer score
    "facts": 9.0,         # fact_reviewer score
    "story": 7.5,         # storytelling_reviewer score
    "edit": 7.0,          # documentary_editor score
}


def _persona_prompt(persona_key: str, script_text: str, facts_text: str) -> str:
    p = PERSONAS[persona_key]
    return f"""{p['brief']}

== RESEARCH FACTS (authoritative, verified) ==
{facts_text[:6000]}

== SCRIPT DRAFT ==
{script_text}

Respond in STRICT JSON with this exact schema (no markdown fences):
{{
  "score": <float 0-10>,
  "confidence": <float 0-1>,
  "summary": "<2-3 sentence assessment>",
  "issues": [
    {{
      "severity": "critical|major|minor|nit",
      "location": "<scene id or 'whole script'>",
      "issue": "<what is wrong>",
      "suggestion": "<concrete fix, with exact replacement wording where possible>"
    }}
  ],
  "passed": <true|false — true only if this persona's gate is met>
}}"""


# ═══════════════════════════════════════════════════════════════════════ #
# Reviewer
# ═══════════════════════════════════════════════════════════════════════ #


def _active_personas() -> list[str]:
    """Personas to run per pass — configurable, 2 by default (cost guardrail).

    Set ``pipeline.script_review.personas`` to a list of persona keys, or
    ``["all"]`` to run the full 4-persona suite (~2x the LLM calls).
    """
    cfg = get_config("pipeline.script_review.personas",
                     ["fact_reviewer", "storytelling_reviewer"])
    if isinstance(cfg, str):
        cfg = [p.strip() for p in cfg.split(",") if p.strip()]
    if "all" in cfg:
        return list(PERSONAS.keys())
    active = [k for k in cfg if k in PERSONAS]
    return active or ["fact_reviewer", "storytelling_reviewer"]


class ScriptReviewer:
    """Runs the multi-persona script review loop (bounded passes)."""

    def __init__(
        self,
        provider_name: Optional[str] = None,
        max_passes: Optional[int] = None,
        verbose: bool = True,
    ):
        factory = ProviderFactory()
        self._provider_name = provider_name or get_config("pipeline.roles.default", "gemini")
        # v19g (ckdigital direction): script review uses the SAME cost chain
        # as the rest of the pipeline — Gemini -> Groq -> OpenRouter ->
        # DeepSeek LAST.  Mistral is deliberately EXCLUDED (small model,
        # not good enough for script work).  ChainLLMProvider falls through
        # per-call and logs which provider answered.
        self._provider = factory.get_cost_chain_llm_provider(self._provider_name)
        # v12.6 legacy fallbacks removed in v19g — the cost chain handles
        # fallthrough internally.
        self._fallbacks: list = []
        # v12.5: default 2 passes (was 3); a 2nd pass only runs if the gate fails.
        self._max_passes = max(1, min(
            max_passes or get_config("pipeline.script_review.max_passes", 2), 3))
        self._verbose = verbose

    # ── Public API ─────────────────────────────────────────────────────

    def review(
        self,
        scenes: list[str],
        facts: Optional[list] = None,
        topic: str = "",
    ) -> tuple[list[str], list[ReviewResult]]:
        """Review *scenes* (list of narration strings) against *facts*.

        Returns (final_scenes, results) where results contains one
        ReviewResult per pass.
        """
        facts_text = self._format_facts(facts, topic)
        script_text = self._format_script(scenes)
        results: list[ReviewResult] = []
        current = scenes[:]

        for pass_no in range(1, self._max_passes + 1):
            self._log(f"\n── Script Review pass {pass_no}/{self._max_passes} ──")
            scores: dict[str, PersonaScore] = {}
            consolidated: list[ReviewIssue] = []

            for key in _active_personas():
                scores[key], issues = self._run_persona(
                    key, self._format_script(current), facts_text
                )
                consolidated.extend(issues)
                self._log(
                    f"  [{PERSONAS[key]['label']:>26}] score={scores[key].score:.1f}/10 "
                    f"conf={scores[key].confidence:.2f} "
                    f"issues={len(issues)} ({self._sev_counts(issues)})"
                )

            passed = self._gate_met(scores)
            self._log(f"  Gate: {'PASS' if passed else 'FAIL'} "
                      f"(scores={ {k: round(v.score,1) for k,v in scores.items()} })")

            if passed or pass_no == self._max_passes:
                results.append(ReviewResult(
                    pass_number=pass_no, scores=scores,
                    revised_scenes=current, passed=passed,
                    notes="final pass" if pass_no == self._max_passes else "gate met",
                ))
                if passed:
                    self._log("  Quality gate met — script approved.")
                else:
                    self._log("  Max passes reached — using best available script.")
                break

            # Revise using consolidated feedback
            revised = self._revise(current, consolidated, facts_text, pass_no)
            results.append(ReviewResult(
                pass_number=pass_no, scores=scores,
                revised_scenes=revised, passed=False,
                notes="revised for next pass",
            ))
            current = revised

        return current, results

    # ── Internals ──────────────────────────────────────────────────────

    def _run_persona(self, persona_key: str, script_text: str, facts_text: str):
        prompt = _persona_prompt(persona_key, script_text, facts_text)
        try:
            raw = self._provider.generate_json(prompt)
        except Exception as e:
            # v12.6: Gemini flash first, then Mistral free, then DeepSeek v4 flash.
            raw = None
            last_err = e
            for fb in self._fallbacks:
                try:
                    self._log(f"    !! primary provider failed ({str(e)[:80]}) — "
                              f"retrying via {type(fb).__name__}")
                    raw = fb.generate_json(prompt)
                    break
                except Exception as e2:  # noqa: BLE001
                    last_err = e2
                    continue
            if raw is None:
                raise last_err
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._log(f"    !! JSON parse failed for {persona_key}, retrying once")
            raw = self._provider.generate_json(prompt + "\nReturn ONLY valid JSON.")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"score": 0.0, "confidence": 0.0,
                        "summary": "unparseable reviewer output",
                        "issues": [], "passed": False}

        issues = [
            ReviewIssue(
                persona=persona_key,
                severity=str(i.get("severity", "minor")),
                location=str(i.get("location", "")),
                issue=str(i.get("issue", "")),
                suggestion=str(i.get("suggestion", "")),
            )
            for i in data.get("issues", [])
        ]
        score = PersonaScore(
            persona=persona_key,
            score=float(data.get("score", 0.0)),
            confidence=float(data.get("confidence", 0.0)),
            summary=str(data.get("summary", "")),
            issues=issues,
        )
        return score, issues

    def _revise(self, scenes: list[str], issues: list[ReviewIssue],
                facts_text: str, pass_no: int) -> list[str]:
        """Ask the editor persona (via LLM) to rewrite scenes per feedback."""
        script_text = self._format_script(scenes)
        # Keep only actionable issues (drop nits, dedupe)
        actionable = [i for i in issues if i.severity in ("critical", "major", "minor")]
        if not actionable:
            return scenes[:]

        issues_text = "\n".join(
            f"[{i.severity.upper()}][{i.location}] {i.issue} → {i.suggestion}"
            for i in actionable[:40]
        )
        prompt = f"""You are the head writer of a documentary studio. Rewrite the script
to resolve the reviewers' feedback. PRESERVE all verified facts. Keep the same
scene structure and approximately the same total length. Write for SPOKEN
narration. No filler, no generic AI phrases. Output ONLY the revised scenes,
one per line, numbered "SCENE N: <narration>".

== REVIEWER FEEDBACK (pass {pass_no}) ==
{issues_text}

== RESEARCH FACTS ==
{facts_text[:4000]}

== CURRENT SCRIPT ==
{script_text}

== REVISED SCENES (SCENE N: ... per line) ==
"""
        raw = None
        last_err = None
        try:
            raw = self._provider.generate_text(prompt)
        except Exception as e:  # noqa: BLE001
            last_err = e
        # v13.1: primary provider may be quota-limited (Gemini free tier is 20
        # req/day) — fall back to Mistral free, then DeepSeek, for TEXT stages
        # only (vision review remains Gemini-locked in review_video.py).
        if not raw:
            for fb in self._fallbacks:
                try:
                    self._log(f"    !! revise primary failed ({str(last_err or 'empty')[:60]}) — "
                              f"retrying via {type(fb).__name__}")
                    raw = fb.generate_text(prompt)
                    break
                except Exception as e2:  # noqa: BLE001
                    last_err = e2
                    continue
            if raw is None and last_err is not None:
                raise last_err
        revised = self._parse_scene_lines(raw)
        if len(revised) == len(scenes) and all(revised):
            self._log(f"  Revised {len(revised)} scenes from consolidated feedback.")
            return revised
        self._log("  Revision output malformed — keeping current script.")
        return scenes[:]

    @staticmethod
    def _parse_scene_lines(raw: str) -> list[str]:
        lines = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            # Strip "SCENE N:" prefix if present
            import re
            m = re.match(r"^(?:scene\s*)?(\d+)[:.)]\s*(.*)$", line, re.IGNORECASE)
            if m:
                lines.append(m.group(2).strip())
            elif line.startswith(("-", "*", "•")):
                lines.append(line.lstrip("-*• ").strip())
        return [l for l in lines if l]

    @staticmethod
    def _format_script(scenes: list[str]) -> str:
        return "\n".join(f"SCENE {i}: {s}" for i, s in enumerate(scenes))

    @staticmethod
    def _format_facts(facts, topic: str) -> str:
        if not facts:
            return f"(No structured facts provided; topic: {topic})"
        lines = []
        for f in facts:
            if isinstance(f, dict):
                claim = f.get("claim") or f.get("fact") or f.get("text") or ""
                conf = f.get("confidence")
                src = f.get("source") or f.get("sources") or ""
                lines.append(f"- {claim} [conf={conf}, source={src}]")
            else:
                lines.append(f"- {f}")
        return "\n".join(lines[:80])

    @staticmethod
    def _sev_counts(issues: list[ReviewIssue]) -> str:
        from collections import Counter
        c = Counter(i.severity for i in issues)
        return " ".join(f"{k}:{v}" for k, v in sorted(c.items()))

    @staticmethod
    def _gate_met(scores: dict[str, PersonaScore]) -> bool:
        """Gate checks only the active personas (configurable, 2 by default)."""
        active = _active_personas()
        key_to_gate = {
            "fact_reviewer": "facts",
            "retention_reviewer": "retention",
            "storytelling_reviewer": "story",
            "documentary_editor": "edit",
        }
        checks = []
        for k in active:
            if k not in scores:
                return False
            gate_key = key_to_gate.get(k)
            if gate_key and gate_key in GATE:
                checks.append(scores[k].score >= GATE[gate_key])
        return bool(checks) and all(checks)

    def _log(self, msg: str):
        if self._verbose:
            print(msg, flush=True)


# ═══════════════════════════════════════════════════════════════════════ #
# CLI
# ═══════════════════════════════════════════════════════════════════════ #

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Multi-persona script review")
    ap.add_argument("--script", required=True, help="JSON file: {\"scenes\": [...], \"facts\": [...]}")
    ap.add_argument("--provider", default=None)
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--out", default="script_review_report.json")
    args = ap.parse_args()

    with open(args.script) as f:
        data = json.load(f)
    reviewer = ScriptReviewer(provider_name=args.provider, max_passes=args.passes)
    t0 = time.time()
    final, results = reviewer.review(data.get("scenes", []), data.get("facts"))
    elapsed = time.time() - t0

    report = {
        "elapsed_s": round(elapsed, 1),
        "passes": [
            {
                "pass": r.pass_number,
                "passed": r.passed,
                "scores": {k: {"score": v.score, "confidence": v.confidence,
                               "summary": v.summary} for k, v in r.scores.items()},
                "issues": [
                    {"persona": i.persona, "severity": i.severity,
                     "location": i.location, "issue": i.issue,
                     "suggestion": i.suggestion}
                    for r_ in [r] for i in
                    [i for p in r_.scores.values() for i in p.issues]
                ],
            }
            for r in results
        ],
        "final_scenes": final,
    }
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Review complete: {len(results)} pass(es) in {elapsed:.1f}s → {args.out}")
