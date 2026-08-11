#!/usr/bin/env python3
"""v24 failsafe regression test — replays the exact Venus v2 blocker.

The Venus v2 run hard-blocked on claim_contradictions for the narration
"NASA's DAVINCI plus and VERITAS missions launch late 2020s and early 2030s":
the extractor split it into two window claims ("launch late 2020s" /
"launch early 2030s"), each contradicted by the LLM, and the gate died.

v24 must: (1) parse "2020s" as a DECADE, not seconds, (2) recognise the
distributed span is fully supported by the research pack (span_supported),
(3) verify both claims instead of contradicting them.
"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.qa.claim_verifier import ClaimVerifier

# The exact research-pack fact that supported the narration.
RESEARCH = {"facts": [
    {"claim": "nasa has approved two new missions, davinci+ and veritas, "
              "targeting venus in the late 2020s and early 2030s",
     "value": "late 2020s and early 2030s"},
    {"claim": "davinci+ will descend through venus's atmosphere",
     "value": "atmospheric probe"},
    {"claim": "veritas will map the surface", "value": "orbiter"},
    {"claim": "liquid oceans existed for billions of years on Venus",
     "value": "billions of years"},
]}

SCENES = [
    {"title": "Venus", "narration":
     "Models suggest Venus once held liquid oceans, perhaps for billions of "
     "years. NASA's DAVINCI plus and VERITAS missions launch late 2020s and "
     "early 2030s, seeking answers. What secrets does this sister planet hide?"},
]

# A hostile LLM stub: extraction reproduces the OLD failure mode (two split
# window claims, each contradicting the other), and verification insists the
# claims are contradicted.  If the v24 span reconciliation works, the
# deterministic layer verifies both BEFORE the LLM gets a say.
class HostileLLM:
    def generate_json(self, prompt):
        if "EXTRACT" in prompt.upper() or "Extract" in prompt:
            return {
                "claims": [
                    {"text": "NASA's DAVINCI plus and VERITAS missions launch late 2020s",
                     "kind": "quantitative", "value": "2020s", "unit": "decade",
                     "entity": "DAVINCI+/VERITAS"},
                    {"text": "NASA's DAVINCI plus and VERITAS missions launch early 2030s",
                     "kind": "quantitative", "value": "2030s", "unit": "decade",
                     "entity": "DAVINCI+/VERITAS"},
                    {"text": "liquid oceans existed for billions of years on Venus",
                     "kind": "quantitative", "value": "billions", "unit": "years",
                     "entity": "Venus"},
                ],
                "entities": ["DAVINCI+", "VERITAS", "Venus"],
            }
        if "disambiguat" in prompt.lower():
            return {"risks": []}
        # verify prompt → hostile: always contradict
        return {"status": "contradicted", "reason": "hostile stub",
                "source": "stub"}

def main():
    v = ClaimVerifier(llm=HostileLLM(), research_pack=RESEARCH)
    gate = v.run(SCENES, out_dir="")
    print("passed:", gate["passed"])
    print("blocking:", gate["blocking_failures"])
    for c in gate["claims"]:
        flag = "  <-- MUST NOT HAPPEN" if c["status"] == "contradicted" else ""
        print(f"  [{c['status']}] value={c.get('value')} unit={c.get('unit')} "
              f"text={c.get('text','')[:70]!r}{flag}")
    # decade parsing check: "2020s" must be a decade, never seconds
    decs = [c for c in gate["claims"]
            if c.get("value") in ("2020s", "2030s") and c.get("unit") == "decade"]
    secs = [c for c in gate["claims"] if c.get("unit") == "s"]
    print(f"decade claims parsed: {len(decs)} (expect 4: deterministic + LLM split), "
          f"bogus seconds claims: {len(secs)} (expect 0)")
    ok = (gate["passed"] and not gate["blocking_failures"]
          and len(decs) == 4 and not secs
          and not any(c["status"] == "contradicted" for c in gate["claims"]))
    print("\nRESULT:", "PASS ✅ v24 failsafe defeats the Venus v2 false-positive"
          if ok else "FAIL ❌")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
