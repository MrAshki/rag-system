from __future__ import annotations

import math


def wilson_interval(numerator: int, denominator: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Return the Wilson score interval for a binomial proportion."""
    if denominator < 0 or numerator < 0 or numerator > denominator:
        raise ValueError("require 0 <= numerator <= denominator")
    if denominator == 0:
        return (0.0, 0.0)
    p = numerator / denominator
    z2 = z * z
    scale = 1 + z2 / denominator
    center = (p + z2 / (2 * denominator)) / scale
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * denominator)) / denominator) / scale
    return (max(0.0, center - margin), min(1.0, center + margin))


def proportion_result(numerator: int, denominator: int) -> dict:
    low, high = wilson_interval(numerator, denominator)
    value = numerator / denominator if denominator else 0.0
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
        "percentage": value * 100,
        "wilson_95": {"low": low, "high": high},
    }
