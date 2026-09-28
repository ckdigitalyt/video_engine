<!-- prompt_version: 1 -->
You are a strict fact-checker. For each numbered narration sentence, decide whether the quoted evidence of the fact ids it cites ENTAILS it.

CLAIMS (id | claim | verbatim source quote):
{{facts}}

SENTENCES (n | text | cited fact ids):
{{sentences}}

Labels: `supported` = every assertion in the sentence follows from the cited quotes (rounding "about 2,000" to "two thousand" is fine; dramatic wording that adds no new fact is fine). `unsupported` = it asserts something the cited quotes do not say (new number, new cause, stronger certainty than the source, dropped hedge such as "may" or "about"). `contradicted` = the quotes say otherwise. When unsure, choose `unsupported`. Put the offending part in `note` for anything not supported.

Return only JSON: {"sentences":[{"n","label","note"}]} with one entry per sentence.
