"""Combining reviews across Trusts (requirement 10.6)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Score:
    vetoed: bool
    trust: float | None       # average of the Trust values given
    rating: float | None
    reviewers: int            # Trusts that list the app

    @property
    def unreviewed(self) -> bool:
        return self.reviewers == 0


def _weighted(pairs: list[tuple[float, float]]) -> float | None:
    total = sum(w for _, w in pairs)
    return round(sum(v * w for v, w in pairs) / total, 1) if total else None


def combine(reviews: list[tuple]) -> Score:
    """reviews: (trust, rating) or (trust, rating, weight) from each enabled Trust that lists the
    app. The weight is the Trust's Score, 1–5 (requirement 10.6.2); a 0 still vetoes (10.6.1)."""
    rows = [(r[0], r[1], r[2] if len(r) > 2 and r[2] else 1) for r in reviews]
    trusts = [(t, w) for t, _, w in rows if t is not None]
    ratings = [(r, w) for _, r, w in rows if r is not None]
    vetoed = any(t == 0 for t, _ in trusts)
    return Score(vetoed=vetoed, trust=None if vetoed else _weighted(trusts), rating=_weighted(ratings),
                 reviewers=len(reviews))


def sort_key(name: str, score: Score, by: str = "trust"):
    """Catalog order (requirement 12.2): Trust (highest first), then name; unreviewed last."""
    if by == "name":
        return (name.lower(),)
    v = score.trust if by == "trust" else score.rating
    return (v is None, -(v or 0), name.lower())
