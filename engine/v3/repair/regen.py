"""regen.py — Selective regeneration loop (directive §22).

Only failing shots are re-rendered; successful shots are never touched.
Versioned outputs: each attempt renders into shots/v{N}/{shot_id}.mp4 and
the best-scoring version is kept (best = highest QA score, ties → latest).
After `max_retries` failed same-renderer retries, the shot is re-routed to
the next renderer in its §24 fallback chain.

--force-fail SXX (dev) injects a synthetic first-attempt QA failure so the
loop can be exercised deterministically in tests.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from engine.v3.qa.shot_qa import qa_shot

logger = logging.getLogger(__name__)

RenderFn = Callable[..., dict]  # (shot, out_dir, attempt, **kw) -> record


def selective_regen(
    shots: list[dict],
    records: dict[str, dict],
    reports: dict[str, dict],
    *,
    render_fn: RenderFn,
    qa_dir: str | Path,
    shots_root: str | Path,
    max_retries: int = 1,
    force_fail: set[str] | None = None,
    use_vision: bool = True,
    qa_kw: dict | None = None,
) -> dict:
    """Regenerate failing shots; re-route chronic failures.

    Returns {"records", "reports", "versions", "rerouted": [shot_id...],
             "regenerated": [shot_id...], "history": [...]}.
    """
    force_fail = force_fail or set()
    merged_qa_kw: dict = {"use_vision": use_vision, **(qa_kw or {})}
    qa_kw = merged_qa_kw
    versions: dict[str, list[dict]] = {}   # shot_id -> [{version, record, report}]
    history: list[dict] = []

    for shot in shots:
        sid = shot["shot_id"]
        rec = records.get(sid) or {"ok": False, "attempts": [], "path": None}
        rep = reports.get(sid) or {"score": 0, "action": "regenerate"}
        if sid in force_fail and rep.get("action") != "regenerate":
            # --force-fail SXX (dev): inject a synthetic QA failure on the
            # first attempt so the regen path is exercised deterministically.
            rep = {"shot_id": sid, "score": 30, "action": "regenerate",
                   "issues": ["forced failure (--force-fail dev flag)"],
                   "technical_pass": False, "vision_available": False}
            if sid not in reports:
                reports = {**reports, sid: rep}
            else:
                reports[sid] = rep
        version = 1
        versions[sid] = [{"version": version, "record": rec, "report": rep}]

        attempt = 1
        while (not rec.get("ok") or rep.get("action") == "regenerate") \
                and attempt <= max_retries:
            forced = sid in force_fail and attempt == 1
            logger.info("regen %s: attempt %d (version v%d)%s", sid, attempt,
                        attempt + 1, " [forced-fail]" if forced else "")
            vdir = Path(shots_root) / f"v{attempt + 1}"
            rec = render_fn(shot, vdir, attempt=attempt)
            version = attempt + 1
            rep = qa_shot(shot, rec["path"] if rec.get("ok") else "-nonexistent",
                          qa_dir,
                          force_fail=False if not rec.get("ok") else True,
                          **qa_kw) if rec.get("ok") else {
                "shot_id": sid, "score": 0, "action": "regenerate",
                "issues": [f"render failed: {rec.get('attempts', [])[:2]}"],
                "technical_pass": False, "vision_available": False,
            }
            if forced and rec.get("ok"):
                rep = dict(rep)
                rep["action"] = "regenerate"
                rep["score"] = min(rep.get("score", 0), 30)
                rep["issues"] = list(rep.get("issues", [])) + [
                    "forced failure (--force-fail dev flag)"]
            versions[sid].append(
                {"version": version, "record": rec, "report": rep})
            history.append({"shot_id": sid, "attempt": attempt,
                            "renderer": rec.get("renderer_used"),
                            "score": rep.get("score"),
                            "action": rep.get("action")})
            attempt += 1

        # Chronic failure → re-route to the next renderer in the §24 chain.
        cur = rec.get("renderer_used") or shot.get("renderer")
        still_bad = not rec.get("ok") or rep.get("action") == "regenerate"
        if still_bad:
            reroute = _next_reroute(shot, cur)
            if reroute:
                logger.info("re-route %s: %s → %s after repeated failure",
                            sid, cur, reroute)
                vdir = Path(shots_root) / f"v{attempt + 1}_rerouted"
                rec2 = render_fn(shot, vdir, attempt=attempt,
                                 renderer_override=reroute)
                if rec2.get("ok"):
                    rep2 = qa_shot(shot, rec2["path"], qa_dir,
                                   **qa_kw)
                    versions[sid].append(
                        {"version": attempt + 1, "record": rec2,
                         "report": rep2, "rerouted_to": reroute})
                    history.append({"shot_id": sid, "attempt": attempt,
                                    "renderer": reroute, "rerouted": True,
                                    "score": rep2.get("score"),
                                    "action": rep2.get("action")})

    # Keep the best version per shot; rewrite records/reports accordingly.
    final_records: dict[str, dict] = {}
    final_reports: dict[str, dict] = {}
    regenerated: list[str] = []
    rerouted: list[str] = []
    for shot in shots:
        sid = shot["shot_id"]
        cands = versions.get(sid, [])
        best = max(cands, key=lambda c: (c["report"].get("score", 0),
                                         c["version"]))
        final_records[sid] = best["record"]
        final_reports[sid] = dict(best["report"])
        final_reports[sid]["version"] = best["version"]
        if len(cands) > 1:
            regenerated.append(sid)
        if any(c.get("rerouted_to") for c in cands) \
                and best.get("rerouted_to"):
            rerouted.append(sid)
            shot.setdefault("metadata", {})["rerouted_renderer"] = \
                best["record"].get("renderer_used")

    return {"records": final_records, "reports": final_reports,
            "versions": {k: len(v) for k, v in versions.items()},
            "rerouted": rerouted, "regenerated": regenerated,
            "history": history}


def _next_reroute(shot: dict, current: str | None) -> str | None:
    from engine.v3.render.runner import full_chain

    chain = full_chain(shot)
    for rid in chain:
        if rid != current:
            return rid
    return None


def save_regen_log(result: dict, out_path: str | Path) -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2, default=str),
                 encoding="utf-8")
    return p
