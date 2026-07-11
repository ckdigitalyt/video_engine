---
pytest tests/test_visual_intent.py -v

20 tests passed / 0 failed (all tests passed)

Coverage:
- VisualIntent: construction, defaults, serialization, extras validation
- QueryExpander: search_terms, concepts, empty fallback, shots, dedup, limit, qualifiers
- DiversityTracker: first pass, exact reuse, similar queries, different assets, history tracking, trimming, reset, violations, Jaccard, fingerprint
- StoryboardValidator: empty, missing assets, missing filepaths, duration calculation
- QualityGatesDiversity: reject reuse, allow different assets
