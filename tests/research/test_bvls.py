"""The bounded least-squares solver used by the identifiability study, checked against exhaustive enumeration."""
import itertools

import numpy as np
import pytest

from research.bea.identifiability import bvls


def brute(A, y, lo, hi):
    """Exact minimum by enumerating which variables sit at which bound (convex problem: the optimum is one of them)."""
    n = A.shape[1]
    best = np.inf
    for pattern in itertools.product((0, 1, 2), repeat=n):          # 0 free, 1 at lo, 2 at hi
        if any((p == 1 and not np.isfinite(lo[i])) or (p == 2 and not np.isfinite(hi[i])) for i, p in enumerate(pattern)):
            continue
        x = np.zeros(n)
        free = np.array([p == 0 for p in pattern])
        for i, p in enumerate(pattern):
            x[i] = lo[i] if p == 1 else hi[i] if p == 2 else 0.0
        if free.any():
            x[free] = np.linalg.lstsq(A[:, free], y - A[:, ~free] @ x[~free], rcond=None)[0]
        if np.all(x >= lo - 1e-9) and np.all(x <= hi + 1e-9):
            best = min(best, float(np.sum((A @ x - y) ** 2)))
    return best


@pytest.mark.parametrize("seed", range(60))
def test_matches_enumeration(seed):
    rng = np.random.default_rng(seed)
    m, n = rng.integers(4, 12), rng.integers(1, 6)
    A = rng.normal(size=(m, n))
    if seed % 3 == 0 and n >= 2:                 # exactly collinear columns, as grade, Crr and extra force in R2
        A[:, 1] = 2.5 * A[:, 0]
    y = rng.normal(size=m) * 3
    lo = -rng.uniform(0, 1, n)
    hi = rng.uniform(0, 1, n)
    if seed % 4 == 1:
        lo[0], hi[0] = 0.0, np.inf               # one-sided, as the extra-force hypothesis
    if seed % 5 == 2:
        lo[-1] = hi[-1] = 0.0                    # fixed at zero, as a fault size under H0
    x, J = bvls(A, y, lo, hi)
    assert np.all(x >= lo - 1e-9) and np.all(x <= hi + 1e-9)
    assert J == pytest.approx(brute(A, y, lo, hi), rel=1e-7, abs=1e-9)


def test_unbounded_equals_least_squares():
    rng = np.random.default_rng(1)
    A, y = rng.normal(size=(30, 4)), rng.normal(size=30)
    x, J = bvls(A, y, np.full(4, -np.inf), np.full(4, np.inf))
    assert np.allclose(x, np.linalg.lstsq(A, y, rcond=None)[0])


@pytest.mark.parametrize("seed", range(20))
def test_badly_scaled_collinear_columns(seed):
    """As in the force balances: grade and rolling resistance are 1000 times the extra-force column and collinear with it."""
    rng = np.random.default_rng(100 + seed)
    m = 40
    one = np.ones(m)
    A = np.column_stack([one, 981.0 * one, 981.0 * one, rng.normal(size=m) * 50, rng.normal(size=m) * 5000])
    y = A[:, 1] * rng.uniform(0.005, 0.05) + rng.normal(size=m) * rng.choice([0.0, 0.1])
    lo = np.array([0.0, -0.001, -0.0003, -1.0, -0.003])
    hi = np.array([np.inf, 0.001, 0.0003, 1.0, 0.003])
    x, J = bvls(A, y, lo, hi)
    assert J <= brute(A, y, lo, hi) + 1e-9 * (1 + y @ y)
