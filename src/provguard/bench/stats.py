"""Metrics with Wilson 95% confidence intervals."""

from __future__ import annotations

import math
from collections.abc import Iterable

from pydantic import BaseModel


class Proportion(BaseModel):
    k: int
    n: int
    value: float | None
    ci_low: float | None
    ci_high: float | None

    @classmethod
    def of(cls, successes: Iterable[bool], z: float = 1.959964) -> Proportion:
        outcomes = list(successes)
        n, k = len(outcomes), sum(outcomes)
        if n == 0:
            return cls(k=0, n=0, value=None, ci_low=None, ci_high=None)
        low, high = wilson(k, n, z)
        return cls(k=k, n=n, value=k / n, ci_low=low, ci_high=high)

    def fmt(self) -> str:
        if self.value is None:
            return "[PENDING]"
        assert self.ci_low is not None and self.ci_high is not None
        return f"{100 * self.value:.1f}% [{100 * self.ci_low:.1f}, {100 * self.ci_high:.1f}] (n={self.n})"


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion k/n."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= k <= n:
        raise ValueError("k must be within [0, n]")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


class Metrics(BaseModel):
    benign_utility: Proportion
    utility_under_attack: Proportion
    targeted_asr: Proportion
    injection_tasks_solvable: Proportion
