# Phase 2 — Deferred Test Failures

These 18 tests were failing at Phase 2 kickoff (`pytest tests/ --tb=line`).
Deferred for now — fix only when actively modifying the code they cover.

## 1. tests/test_asset_router.py
- `TestOrchestratorIntegration::test_history_routes_correctly`
  - Assertion: expected `["wikimedia", "pexels", "pixabay"]` but got `["wikimedia", "pixabay", "pexels"]`
  - Priority ordering mismatch; likely a config or History category routing change.

## 2. tests/test_config.py
- `TestRequiredKeys::test_section_and_keys[providers-keys6]`
  - Missing/invalid config key in the `providers` section.

## 3. tests/test_data_isolation.py
- `TestNarrationIsolation::test_search_plan_rejects_high_overlap_with_narration`
  - Semantic validator not rejecting high-overlap search terms as expected.

## 4. tests/test_subtitles.py
- `TestConfig::test_default_config_keys_exist`
  - Missing config keys for subtitle engine defaults.

## 5. tests/test_visual_director.py
All `TestConceptPlanner` tests (6 tests):
- `test_default_config`
- `test_llm_generation`
- `test_llm_error_fallback`
- `test_parse_queries`
- `test_parse_queries_with_fences`
- `test_extract_keywords`

All `TestQualityGates` tests (3 tests):
- `test_reuse_gate_fails`
- `test_duplicate_gate_by_id`
- `test_check_all_details_structure`

All `TestCriticFailClosed` tests (3 tests):
- `test_api_error_sets_approved_false`
- `test_auth_error_sets_approved_false`
- `test_config_error_sets_approved_false`

Likely cause (all 12): ConceptPlanner/QualityGate/Critic tests require DeepSeek/Gemini API keys or env vars not available in the test environment.

## 6. tests/test_visual_intent.py
- `TestQueryExpander::test_max_20_queries`
- `TestStoryboardValidator::test_missing_filepath_detected`

Likely cause: AssetPipeline/storyboard-validator environment dependencies.

---

**Total: 18 failed / 647 collected (629 passed)**
Generated: 2026-07-11
