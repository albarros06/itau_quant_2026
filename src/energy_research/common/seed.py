"""Single determinism entry point (Constitution Principle VIII, FR-028).

Every randomness source used anywhere in the pipeline is seeded here, once, at the
start of a research cycle. Modules that need randomness call :func:`get_rng` instead
of constructing their own generators, so there is exactly one seam to audit.
"""

from __future__ import annotations

import random

import numpy as np

_rng: np.random.Generator | None = None
_seed: int | None = None


def set_seed(seed: int) -> None:
    """Seed every randomness source used by the pipeline."""
    global _rng, _seed
    _seed = int(seed)
    random.seed(_seed)
    np.random.seed(_seed % 2**32)  # legacy global, in case a dependency uses it
    _rng = np.random.default_rng(_seed)


def get_rng() -> np.random.Generator:
    """Return the cycle's shared generator; requires :func:`set_seed` first."""
    if _rng is None:
        raise RuntimeError(
            "randomness requested before set_seed() was called — a research run must "
            "seed all randomness up front (Constitution Principle VIII)"
        )
    return _rng


def current_seed() -> int | None:
    return _seed
