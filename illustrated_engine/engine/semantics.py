"""V8 semantic matching without an LLM (DeepSeek key is 401).

Deterministic semantic resolution for the curiosity ladder (brief §9) and
the payoff metric (brief §13): "Do NOT use lexical overlap as the primary
payoff metric. Measure semantic resolution."

Resolution link order (strongest first):
1. declared_concept — the two shots declare shared concept ids
   (story.json concepts are the author's own semantic layer)
2. declared_fact    — the beats cite a shared fact id
3. concept_alias    — alias-cluster token overlap (heat~warmth~thermal ...)
4. none

A shared *declared* concept is the honest signal: the author linked the
hook and payoff to the same concept id, which IS semantic resolution by
construction. Alias clusters only bridge wording differences.
"""

from __future__ import annotations

from engine.editorial7 import _stem, tokens

# canonical concept -> surface forms (both raw and stemmed forms are mapped)
_CLUSTERS = {
    "heat": ["heat", "warmth", "warm", "hot", "thermal", "glow", "glowing",
             "burn", "burning"],
    "energy": ["charge", "charging", "charger", "power", "energy",
               "electric", "electricity", "watt", "battery", "current"],
    "device": ["phone", "device", "handset", "screen"],
    "water": ["water", "flood", "flooding", "inrush", "sea", "ocean",
              "sink", "sinking", "buoyancy"],
    "ice": ["ice", "iceberg", "glacier", "frozen"],
    "ship": ["ship", "vessel", "liner", "titanic", "hull", "compartment",
             "boat"],
    "desert": ["desert", "sahara", "sahel", "sand", "dune", "arid"],
    "vegetation": ["green", "greening", "vegetation", "plant", "plants",
                   "leaf", "foliage", "verdant", "tree", "trees", "shrub"],
    "rain": ["rain", "rainfall", "precipitation", "monsoon", "wetting"],
    "climate": ["climate", "carbon", "warming", "atmosphere", "temperature",
                "co2"],
    "limit": ["limit", "protection", "slow", "slows", "throttle", "cap"],
    "loss": ["loss", "lose", "lost", "death", "perish", "disaster"],
}
_CANON: dict = {}
for _c, _forms in _CLUSTERS.items():
    for _f in _forms:
        _CANON.setdefault(_f, _c)
        _CANON.setdefault(_stem(_f), _c)


def concept_ids(concepts) -> list:
    """Shot concepts may be dicts {id, verb} or strings — extract ids."""
    out = []
    for c in concepts or []:
        if isinstance(c, dict):
            cid = c.get("id")
            if cid:
                out.append(str(cid))
        elif isinstance(c, str):
            out.append(c)
    return out


def canon_tokens(text: str) -> set:
    """Alias-canonicalized content tokens (long stems kept as-is)."""
    return {_CANON.get(t, t) for t in tokens(str(text or "")) if len(t) > 2}


def semantic_link(q_text: str, a_text: str, q_concepts, a_concepts,
                  q_facts=None, a_facts=None) -> dict:
    """Resolution link between an opened question and a candidate answer."""
    sc = sorted(set(concept_ids(q_concepts)) & set(concept_ids(a_concepts)))
    if sc:
        return {"link": "declared_concept", "shared": sc}
    sf = sorted(set(q_facts or []) & set(a_facts or []))
    if sf:
        return {"link": "declared_fact", "shared": sf}
    inter = sorted(canon_tokens(q_text) & canon_tokens(a_text))
    if inter:
        return {"link": "concept_alias", "shared": inter[:6]}
    return {"link": "none", "shared": []}
