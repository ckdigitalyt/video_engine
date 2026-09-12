"""V11 P1 §1 — Visual contradiction engine (reusable story primitive).

For suitable stories the planner explicitly declares:

    WHAT THE VIEWER THINKS IS HAPPENING
  vs
    WHAT IS ACTUALLY HAPPENING

Directive examples: ice ("you think you're skating on solid ice" →
microscopic surface/interface reveal), black hole ("you think the clock
stops" → local vs distant observer split), phone ("you think the battery
simply gets hot" → energy-flow decomposition).

Declaration (story.json, beat level — typically on the HOOK beat):

  "contradiction": {
      "viewer_thinks": "you are skating on solid ice",
      "actually": "you glide on a microscopic quasi-liquid water film "
                  "on the ice surface",
      "reveal_beat": "B4"          # beat that reveals the actual state
  }

Editorial check (`run`): the declared contradiction is visually honored
when (a) the viewer-thinks state is SHOWN by the declaring beat's shot
(the shot's authored text matches the misconception — the viewer must see
the plausible-but-wrong world first), and (b) the actual state is
REVEALED by the reveal beat's shot (text matches AND the shot carries an
explanatory living event: reveal / isolate / flow / fill_state /
consequence — the reveal must be visual, not narration-only).

This module is pure construction-level measurement over the plan + story.
It never edits shots; it stamps `s["v8"]["contradiction"]` annotations and
returns a report for planv8's `v8` block.
"""

from __future__ import annotations

import re

# Living-event kinds that count as a VISUAL reveal (planv8-stamped kinds).
_REVEAL_EVENTS = {"reveal", "isolate", "flow", "fill_state", "consequence"}

_STOP = {"the", "a", "an", "of", "on", "in", "is", "are", "you", "your",
         "it", "its", "that", "this", "to", "and", "at", "by", "with",
         "what", "think", "actually", "really", "just", "simply"}


def _toks(text: str) -> set:
    """Lowercase content tokens with crude stemming (skating→skat)."""
    out = set()
    for w in re.findall(r"[a-z]{3,}", str(text or "").lower()):
        if w in _STOP:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if w.endswith(suf) and len(w) > len(suf) + 2:
                w = w[: -len(suf)]
                break
        out.add(w)
    return out


def _shot_text(s: dict) -> str:
    """All authored text a shot shows (purpose/evidence/claim/one_second)."""
    one = s.get("one_second") or {}
    labels = " ".join(str(x) for x in (one.get("labels") or []))
    return " ".join(str(s.get(k) or "") for k in
                    ("purpose", "evidence", "claim")) + " " + labels


def _beat_shots(plan: dict, beat_id: str) -> list:
    return [s for s in plan.get("shots", [])
            if str(s.get("beat_id")) == str(beat_id)]


def collect(story: dict) -> list:
    """Declared contradictions: [{beat, viewer_thinks, actually,
    reveal_beat}]. Malformed declarations are surfaced, not silently
    dropped."""
    rows = []
    for b in story.get("beats", []):
        c = b.get("contradiction")
        if not isinstance(c, dict):
            if c is not None:
                rows.append({"beat": b.get("beat_id"), "error":
                             "contradiction must be an object"})
            continue
        rows.append({
            "beat": str(b.get("beat_id")),
            "viewer_thinks": str(c.get("viewer_thinks") or "").strip(),
            "actually": str(c.get("actually") or "").strip(),
            "reveal_beat": str(c.get("reveal_beat") or "").strip(),
        })
    return rows


def run(plan: dict, story: dict) -> dict:
    """Check each declared contradiction is visually honored. Stamps the
    hook/reveal shots' `v8["contradiction"]` annotations."""
    rows = []
    for c in collect(story):
        if c.get("error"):
            rows.append(c)
            continue
        hook_shots = _beat_shots(plan, c["beat"])
        reveal_shots = (_beat_shots(plan, c["reveal_beat"]) if c["reveal_beat"]
                        else [])
        if not reveal_shots:  # fall back to the first planv8-phase-reveal shot
            reveal_shots = [s for s in plan.get("shots", [])
                            if (s.get("v8") or {}).get("phase") == "reveal"]
        row = {"beat": c["beat"], "viewer_thinks": c["viewer_thinks"],
               "actually": c["actually"], "reveal_beat": c["reveal_beat"]}
        if not hook_shots or not reveal_shots:
            row["verdict"] = "unresolved"
            row["note"] = ("no reveal beat/shot resolved"
                           if not reveal_shots else "no hook shots")
            rows.append(row)
            continue
        hook, reveal = hook_shots[0], reveal_shots[0]
        row["hook_shot"] = str(hook.get("shot_id"))
        row["reveal_shot"] = str(reveal.get("shot_id"))

        thinks_k, actual_k = _toks(c["viewer_thinks"]), _toks(c["actually"])
        shown = len(thinks_k & _toks(_shot_text(hook)))
        revealed_txt = len(actual_k & _toks(_shot_text(reveal)))
        ev_kinds = {str((e or {}).get("kind") or "").lower()
                    for e in (reveal.get("events") or [])}
        visual_reveal = bool(ev_kinds & _REVEAL_EVENTS)
        row["shown_overlap"] = shown
        row["revealed_overlap"] = revealed_txt
        row["visual_reveal_event"] = sorted(ev_kinds & _REVEAL_EVENTS)
        # SHOWN: the misconception is visible on the hook shot (>=1 content
        # token; the misconception shares the scene by construction of the
        # beat). REVEALED: >=2 actual-state tokens on the reveal shot AND a
        # living explanatory event (text alone is narration, not a reveal).
        shown_ok = shown >= 1
        revealed_ok = revealed_txt >= 2 and visual_reveal
        row["verdict"] = ("honored" if (shown_ok and revealed_ok)
                          else "declared_only" if shown_ok else
                          "missing_show")
        hook.setdefault("v8", {})["contradiction"] = {
            "role": "viewer_thinks", "text": c["viewer_thinks"],
            "reveal_shot": row["reveal_shot"]}
        reveal.setdefault("v8", {})["contradiction"] = {
            "role": "actually", "text": c["actually"],
            "hook_shot": row["hook_shot"]}
        rows.append(row)

    declared = [r for r in rows if not r.get("error")]
    honored = sum(1 for r in declared if r.get("verdict") == "honored")
    verdict = ("none_declared" if not rows else
               "pass" if honored == len(declared) else "check")
    return {"declared": len(rows), "honored": honored, "rows": rows,
            "verdict": verdict}
