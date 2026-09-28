<!-- prompt_version: 3 -->
You are a strict fact-checker. For each numbered narration sentence, decide whether the quoted evidence of the fact ids it cites ENTAILS it (claim plus evidence of the cited ids only).

FACTS (id | vetted claim | evidence). The evidence is the verbatim source quote; when it is only terse measured values (curated facts), the vetted claim is itself the accepted statement and the evidence gives its numbers. Where a claim and its quote differ, the quote governs.
{{facts}}

SENTENCES (n | text | cited fact ids):
{{sentences}}

Labels: `supported` = every assertion in the sentence follows from the cited quotes (rounding "about 2,000" to "two thousand" is fine; dramatic wording that adds no new fact is fine). `unsupported` = it asserts something the cited quotes do not say (new number, new cause, stronger certainty than the source, dropped hedge such as "may" or "about"). `contradicted` = the quotes say otherwise. Label `unsupported` only when you can name the specific added assertion (a new number, cause, name, certainty or dropped hedge) in `note`. Dramatic phrasing, scene-setting and rhythm that assert nothing new are `supported`; if your note would say "mild" or "acceptable", the label is `supported`. If a sentence is cut off, judge the part that is there.

Write `note` FIRST (one line: the added assertion, or "nothing added"), then decide `label` from it. Return only JSON: {"sentences":[{"n","note","label"}]} with one entry per sentence.
