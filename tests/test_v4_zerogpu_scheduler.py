"""test_v4_zerogpu_scheduler.py — Offline tests for the §8 quota-aware
ZeroGPU scheduler: error classification, quota state machine, retry-on-
different-Space, per-attempt §7 fields. All HTTP mocked.
"""

import pytest

from engine.broker.failures import (
    FailureClass,
    SpaceAttempt,
    classify_failure,
    parse_quota_remaining,
)
from engine.broker.providers.base import BrokerResult, ProviderError
from engine.broker.zerogpu_scheduler import (
    GenRequest,
    QuotaLedger,
    SpaceCandidate,
    ZeroGPUScheduler,
)


# ── Error taxonomy (§7) ──────────────────────────────────────────────────


def test_classification_quota_exhausted():
    assert classify_failure(
        "You have exceeded your GPU quota (60s requested vs. 44s left). "
        "Try again in 1:23:45") is FailureClass.QUOTA_EXHAUSTED
    assert classify_failure("ZeroGPU quota exceeded for today") is \
        FailureClass.QUOTA_EXHAUSTED


def test_classification_queue_timeout():
    assert classify_failure(
        "hf_zerogpu: poll timeout after 300s (queue may still be running)"
    ) is FailureClass.QUEUE_TIMEOUT
    assert classify_failure("The queue is full, try later") is \
        FailureClass.QUEUE_TIMEOUT


def test_classification_space_error():
    # The dino_v1 signature: raw SSE error event with a null payload.
    assert classify_failure("hf_zerogpu: space error: null") is \
        FailureClass.SPACE_ERROR
    assert classify_failure("hf_zerogpu: space error: CUDA out of memory") is \
        FailureClass.SPACE_ERROR


def test_classification_invalid_params_and_auth():
    assert classify_failure("HTTP 422: validation error on parameter 'mode'") \
        is FailureClass.INVALID_PARAMS
    assert classify_failure("hf_zerogpu: auth failed (HTTP 401)") is \
        FailureClass.AUTH_ERROR


def test_classification_empty_is_unknown():
    assert classify_failure("") is FailureClass.UNKNOWN


def test_quota_message_parsing():
    info = parse_quota_remaining(
        "You have exceeded your GPU quota (60s requested vs. 44s left). "
        "Try again in 1:23:45")
    assert info["gpu_sec_left"] == 44.0
    assert info["retry_in_sec"] == 1 * 3600 + 23 * 60 + 45


# ── QuotaLedger state machine ────────────────────────────────────────────


def test_ledger_quota_error_trips_block():
    ledger = QuotaLedger()
    assert not ledger.blocked
    ledger.mark_quota_exhausted("exceeded your GPU quota (60s vs. 12s left)")
    assert ledger.blocked
    assert ledger.gpu_sec_left == 12.0


def test_ledger_null_errors_mark_suspected_after_threshold():
    ledger = QuotaLedger(null_error_stop_after=2)
    ledger.mark_null_error("Space/A")
    assert not ledger.suspected_exhausted
    ledger.mark_null_error("Space/B")  # distinct space
    assert ledger.suspected_exhausted
    assert ledger.blocked
    # Same space twice does NOT trip (need distinct spaces).
    ledger2 = QuotaLedger(null_error_stop_after=2)
    ledger2.mark_null_error("Space/A")
    ledger2.mark_null_error("Space/A")
    assert not ledger2.suspected_exhausted


def test_ledger_success_accounting():
    ledger = QuotaLedger()
    ledger.mark_success(4.0)
    ledger.mark_success(6.0)
    assert ledger.successes == 2
    assert ledger.video_sec_generated == 10.0


# ── Scheduler (mocked clients) ───────────────────────────────────────────


class _FakeInfo:
    def __init__(self, n=1):
        self.endpoints = [object()] * n


class _FakeClient:
    """Records calls; behaviour injected per test via class attrs."""
    space_id = "Space/A"
    behavior: str = "ok"          # ok | quota | null | queue | invalid | boom
    upload_raises: bool = False

    def __init__(self, space_id, endpoint_name=None, token=None, **kw):
        self.space_id = space_id
        self.endpoint_name = endpoint_name

    def discover(self, verbose=False):
        if _FakeClient.behavior == "boom":
            raise ProviderError("hf_zerogpu: HTTP 503 on discover")
        return _FakeInfo()

    @staticmethod
    def file_data(server_path):
        return {"path": server_path, "meta": {"_type": "gradio.FileData"}}

    def upload_files(self, paths):
        if _FakeClient.upload_raises:
            raise ProviderError("hf_zerogpu: upload connection error")
        return ["/tmp/uploaded.png"]

    def generate(self, data, endpoint_name=None, timeout=None):
        b = _FakeClient.behavior
        if b == "quota":
            raise ProviderError(
                "You have exceeded your GPU quota (5s requested vs. 0s left)")
        if b == "null":
            raise ProviderError("hf_zerogpu: space error: null")
        if b == "queue":
            raise ProviderError("hf_zerogpu: poll timeout after 300s "
                                "(queue may still be running)")
        if b == "invalid":
            raise ProviderError("HTTP 422: validation error")
        if b == "boom":
            raise ProviderError("hf_zerogpu: connection error (reset)")
        return {"output": {"video": {"url": "https://example/x.mp4"}}}

    def download_result(self, payload):
        return [b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048]


def _make_scheduler(n_candidates=2, **kw) -> ZeroGPUScheduler:
    candidates = [
        SpaceCandidate(space_id=f"Space/{chr(65 + i)}", model=f"m{i}",
                       template="ltx_distilled",
                       t2v_endpoint="text_to_video",
                       i2v_endpoint="image_to_video",
                       priority=10 + i)
        for i in range(n_candidates)
    ]
    return ZeroGPUScheduler(token="test-token", candidates=candidates, **kw)


@pytest.fixture(autouse=True)
def _patch_factory(monkeypatch):
    import engine.broker.zerogpu_scheduler as z
    _FakeClient.behavior = "ok"
    _FakeClient.upload_raises = False
    monkeypatch.setattr(z, "HFZeroGPUClient", _FakeClient)
    yield
    _FakeClient.behavior = "ok"
    _FakeClient.upload_raises = False


def test_successful_t2v_records_attempt_and_result():
    sched = _make_scheduler()
    result = sched.generate_t2v("a volcano erupting", duration=4.0)
    assert result.provider == "hf_zerogpu::Space/A"
    assert result.kind == "video"
    recs = result.metadata["attempts"]
    assert recs[0]["attempted_provider"] == "hf_zerogpu::Space/A"
    assert recs[0]["space_id"] == "Space/A"
    assert recs[0]["success"] is True
    assert recs[0]["output_kind"] == "t2v"
    assert sched.ledger.successes == 1
    assert sched.ledger.video_sec_generated == 4.0
    assert sched._state["Space/A"].known_good


def test_failure_on_first_space_retries_on_different_space():
    _FakeClient.behavior = "queue"
    orig_init = _FakeClient.__init__

    def init(self, space_id, **kw):
        orig_init(self, space_id)
        if space_id == "Space/A":
            _FakeClient.behavior = "queue"
        else:
            _FakeClient.behavior = "ok"

    _FakeClient.__init__ = init
    try:
        sched = _make_scheduler()
        result = sched.generate_t2v("test")
        assert result.provider == "hf_zerogpu::Space/B"
        recs = result.metadata["attempts"]
        assert recs[0]["success"] is False
        assert recs[0]["classification"] == "QUEUE_TIMEOUT"
        assert "next Space" in recs[0]["fallback_reason"]
        assert recs[1]["space_id"] == "Space/B"
        assert recs[1]["success"] is True
    finally:
        _FakeClient.__init__ = orig_init
        _FakeClient.behavior = "ok"


def test_quota_error_stops_all_further_attempts():
    _FakeClient.behavior = "quota"
    sched = _make_scheduler(n_candidates=3)
    with pytest.raises(ProviderError) as exc:
        sched.generate_t2v("test")
    # Only ONE attempt burned: quota is account-level, other Spaces refused.
    assert len(sched.attempts) == 1
    assert sched.attempts[0].classification == "QUOTA_EXHAUSTED"
    assert "account-level" in sched.attempts[0].fallback_reason
    assert sched.ledger.blocked
    # Subsequent requests refused outright without any attempt.
    before = len(sched.attempts)
    with pytest.raises(ProviderError, match="session quota blocked"):
        sched.generate_t2v("test again")
    assert len(sched.attempts) == before


def test_null_errors_across_spaces_mark_suspected_quota():
    _FakeClient.behavior = "null"
    sched = _make_scheduler(n_candidates=2)
    with pytest.raises(ProviderError, match="all candidate Spaces failed"):
        sched.generate_t2v("test")
    assert len(sched.attempts) == 2  # tried both Spaces
    assert sched.ledger.suspected_exhausted
    assert sched.ledger.blocked


def test_known_good_space_preferred_on_next_call():
    sched = _make_scheduler(n_candidates=2)
    sched._state["Space/B"].known_good = True
    result = sched.generate_t2v("second call")
    assert result.provider == "hf_zerogpu::Space/B"


def test_down_spaces_skipped():
    _FakeClient.behavior = "boom"
    sched = _make_scheduler(n_candidates=2)
    sched.probe()  # both fail discovery → down
    with pytest.raises(ProviderError, match="no candidate Space supports"):
        sched.generate_t2v("test")


def test_i2v_uploads_image_and_caches():
    import tempfile, os
    sched = _make_scheduler()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        path = fh.name
    try:
        result = sched.generate_i2v(path, "bring this to life", duration=4.0)
        assert result.kind == "image_to_video"
        assert result.path.exists()
        recs = result.metadata["attempts"]
        assert recs[-1]["success"] is True
    finally:
        os.unlink(path)


def test_attempt_record_has_directive_7_fields():
    _FakeClient.behavior = "invalid"
    sched = _make_scheduler(n_candidates=1)
    with pytest.raises(ProviderError):
        sched.generate_t2v("test")
    rec = sched.attempts[0].to_record()
    for field in ("attempted_provider", "space_id", "failure_reason",
                  "fallback_reason"):
        assert field in rec
        assert rec[field]
