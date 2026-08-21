"""Phase A tests: wave-interference + pressure physics verifiers (§46)."""

import pytest

from engine.validation.physics_verify import (
    verify_pressure_volume_burst,
    verify_wave_interference,
)


def test_destructive_at_180():
    v = verify_wave_interference(1.0, 1.0, 180.0)
    assert v.ok
    assert v.failures() == []


def test_constructive_at_0():
    v = verify_wave_interference(1.0, 1.0, 0.0)
    assert v.ok


def test_any_phase_valid():
    for ph in (0.0, 90.0, 180.0, 270.0, 360.0):
        assert verify_wave_interference(1.0, 1.0, ph).ok


def test_negative_frequency_fails():
    v = verify_wave_interference(-1.0, 1.0, 180.0)
    assert not v.ok
    assert any(not f["passed"] for f in v.failures())


def test_phase_out_of_range_fails():
    v = verify_wave_interference(1.0, 1.0, 400.0)
    assert not v.ok


def test_burst_nominal():
    v = verify_pressure_volume_burst(9.0, 180.0)
    assert v.ok


def test_burst_bad_pressure_fails():
    v = verify_pressure_volume_burst(-3.0, 180.0)
    assert not v.ok


def test_burst_temp_band():
    # 9 atm near 180 °C is the burst point; far off-band should fail
    v = verify_pressure_volume_burst(9.0, 20.0)
    assert not v.ok
