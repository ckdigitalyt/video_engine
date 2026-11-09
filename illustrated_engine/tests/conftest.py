"""Suite-wide isolation (2026-11-09): engine.v16_topics reads a production
auto-weight override (data/cluster_weight_state.json) that the feedback loop
rewrites. Tests that assert exact scores/shares against the hand-set
CLUSTER_PRIORS / CLUSTER_TARGET_SHARE must not depend on whatever that file
holds today, so every test starts with the override disabled. Tests of the
override layer itself point V16_CLUSTER_WEIGHT_STATE at a temp file.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_production_cluster_weight_state(monkeypatch):
    monkeypatch.setenv("V16_CLUSTER_WEIGHT_STATE", "off")
