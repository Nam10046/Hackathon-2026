"""Fill forecast. Owner: AI person.

Predicts hours until the compactor is full, using a straight line (linear regression)
through the load % since the last emptying. Later: add day-of-week patterns, ML model.
"""
from datetime import datetime


def hours_to_full(points: list[tuple[datetime, float]], current_load_pct: float):
    """
    points: [(timestamp, load_pct)] oldest first, only since the last emptying
    returns hours (float) or None if unknown / not filling
    """
    if current_load_pct >= 100:
        return 0.0
    if len(points) < 3:
        return None

    t0 = points[0][0]
    xs = [(t - t0).total_seconds() / 3600 for t, _ in points]  # hours
    ys = [p for _, p in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var  # % per hour

    if slope <= 0.01:
        return None  # not filling
    return round((100 - current_load_pct) / slope, 1)
