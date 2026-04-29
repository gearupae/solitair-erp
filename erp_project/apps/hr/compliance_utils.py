"""Shared helpers for HR compliance expiry badges (green / amber / red)."""
from __future__ import annotations

from datetime import date
from typing import Iterable

UNKNOWN = 'unknown'


def expiry_band(expiry_date: date | None) -> str:
    """
    Green: > 60 days remaining.
    Amber: 30–60 days remaining (inclusive).
    Red: < 30 days remaining or already expired.
    """
    if expiry_date is None:
        return UNKNOWN
    days = (expiry_date - date.today()).days
    if days < 0:
        return 'red'
    if days < 30:
        return 'red'
    if days <= 60:
        return 'amber'
    return 'green'


def severity_rank(band: str) -> int:
    return {'unknown': 0, 'green': 1, 'amber': 2, 'red': 3}.get(band, 0)


def worst_band(bands: Iterable[str]) -> str:
    ranked = list(bands)
    if not ranked:
        return UNKNOWN
    mx = max((severity_rank(b) for b in ranked), default=0)
    for name in (UNKNOWN, 'green', 'amber', 'red'):
        if severity_rank(name) == mx:
            return name
    return UNKNOWN
