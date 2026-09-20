"""V13 M7 — Jev inert shadow stub (closed-experiment seam).

PROVENANCE — Jev is a CLOSED experiment. Owner decision 2026-09-19:
the expanded validation run scored 60/100 with 12 unsafe
false-positives against a >=95% agreement bar. Jev shipped zero credit
into production and all engine decisions remain 100% deterministic.
``~/jev_experiment/`` is a closed historical archive: this module must
not, and does not, read, import, call, or reference any of it.

RULE — This stub is an inert seam only. It exists so a future
(never automatic) re-evaluation has a defined decision shape to plug
into. Default state is DISABLED (``flags.jev13()`` False; env
``V13_JEV`` unset/0). Even when opted in, ``evaluate`` ONLY formats a
deterministic summary dict of already-computed local metrics — no
model calls, no network, no subprocess, no file writes. Any future
live (model-calling) Jev requires explicit owner re-approval.

SELF-TEST — At import time this module greps its own source for
forbidden network-capable modules (requests / urllib / httpx / socket
and kin) and raises ImportError if any import line is found.
"""

import re

from engine import flags as _flags

__all__ = ["JevShadowStub"]


# Forbidden modules for the import-time source audit. Matched as import
# statements only (anchored), so prose mentions in docstrings are safe.
_FORBIDDEN_MODULES = (
    "requests",
    "urllib",
    "urllib3",
    "httpx",
    "http",
    "socket",
    "socketserver",
    "asyncio",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc",
    "subprocess",
    "multiprocessing",
)

_IMPORT_LINE_RE = re.compile(
    r"^\s*(?:import|from)\s+(%s)\b" % "|".join(_FORBIDDEN_MODULES),
    re.MULTILINE,
)


def _self_test_no_network_imports() -> None:
    """Grep this module's own source; raise on any forbidden import."""
    with open(__file__, "r", encoding="utf-8") as fh:
        source = fh.read()
    hits = [ln for ln in source.splitlines() if _IMPORT_LINE_RE.match(ln)]
    if hits:
        raise ImportError(
            "jev_stub must never import network/subprocess modules; found: %r"
            % (hits,)
        )


class JevShadowStub:
    """Inert shadow seam for the closed Jev experiment.

    ``evaluate(plan, metrics)`` returns ``None`` unless ``flags.jev13()``
    is on (env ``V13_JEV=1``). When on, it returns a deterministic
    summary dict built ONLY from values already present in ``plan`` /
    ``metrics`` (visual_sophistication composite, representation_mix,
    gate verdicts). Two calls with identical inputs return identical
    dicts: no timestamps, no randomness, no I/O of any kind.
    """

    name = "jev-shadow-stub"
    live = False  # a live (model-calling) judge would flip this; requires owner re-approval

    def evaluate(self, plan, metrics):
        if not _flags.jev13():
            return None
        return self._summarize(plan, metrics)

    # -- deterministic local-only formatting (no I/O below this line) ----

    def _summarize(self, plan, metrics):
        plan = plan if isinstance(plan, dict) else {}
        metrics = metrics if isinstance(metrics, dict) else {}

        summary = {
            "judge": self.name,
            "live": self.live,
            "mode": "inert-shadow-deterministic",
            "visual_sophistication": _lookup("visual_sophistication", metrics, plan),
            "representation_mix": _lookup("representation_mix", metrics, plan),
            "gate_verdicts": _gate_verdicts(_lookup("gates", metrics, plan)),
            "note": (
                "deterministic summary of precomputed local metrics; "
                "no model/network/subprocess/file activity"
            ),
        }
        # Sorted keys keep the dict (and its serialized form) stable across calls.
        return dict(sorted(summary.items()))


def _lookup(key, *mappings):
    """First present value for *key* across mappings; None otherwise."""
    for m in mappings:
        if isinstance(m, dict) and key in m:
            return m[key]
    return None


def _gate_verdicts(gates):
    """Normalize a gates structure into a sorted {name: verdict} dict.

    Accepts {name: verdict} mappings or sequences of dicts carrying
    'name' and 'verdict'/'passed'/'ok'. Anything else passes through.
    """
    if isinstance(gates, dict):
        return {str(k): gates[k] for k in sorted(gates, key=str)}
    if isinstance(gates, (list, tuple)):
        out = {}
        for g in gates:
            if isinstance(g, dict) and "name" in g:
                verdict = g.get("verdict", g.get("passed", g.get("ok")))
                out[str(g["name"])] = verdict
        return dict(sorted(out.items()))
    return gates


# Import-time assertion: the module refuses to exist if its own source
# contains any network/subprocess import. Runs on every import.
_self_test_no_network_imports()
