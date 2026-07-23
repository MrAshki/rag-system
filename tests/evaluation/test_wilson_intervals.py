import pytest

from evaluation.metrics.proportions import proportion_result, wilson_interval


def test_wilson_known_half_case():
    low, high = wilson_interval(5, 10)
    assert low == pytest.approx(0.2366, abs=0.0002)
    assert high == pytest.approx(0.7634, abs=0.0002)


def test_wilson_zero_denominator_and_validation():
    assert wilson_interval(0, 0) == (0.0, 0.0)
    assert proportion_result(0, 0)["percentage"] == 0
    with pytest.raises(ValueError):
        wilson_interval(2, 1)
