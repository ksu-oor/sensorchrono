"""FiducialCounter acceptance policy (refractory gating + regularity)."""
from __future__ import annotations

from sensorchrono.orchestration.fiducial_live import FiducialCounter


def test_refractory_rejects_close_taps():
    c = FiducialCounter(refractory_s=0.8, min_count=3)
    assert c.offer(0.0) is True
    assert c.offer(0.1) is False  # key-repeat / double tap, too soon
    assert c.offer(1.0) is True
    assert c.offer(2.0) is True
    assert c.count == 3 and c.calibrated


def test_not_calibrated_below_threshold():
    c = FiducialCounter(min_count=5)
    for t in (0.0, 1.0, 2.0):
        c.offer(t)
    assert not c.calibrated


def test_regularity_cv_low_for_metronomic_taps():
    c = FiducialCounter(refractory_s=0.1)
    for t in (0.0, 1.0, 2.0, 3.0):
        c.offer(t)
    cv = c.regularity_cv()
    assert cv is not None and cv < 0.01


def test_regularity_cv_none_with_too_few():
    c = FiducialCounter()
    c.offer(0.0)
    assert c.regularity_cv() is None


def test_reset_clears_counts():
    c = FiducialCounter()
    c.offer(0.0)
    c.reset()
    assert c.count == 0 and not c.calibrated
