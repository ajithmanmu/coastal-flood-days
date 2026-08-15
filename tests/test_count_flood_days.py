"""Rule checks for the counting logic. No network. Run: .venv/bin/python tests/test_count_flood_days.py"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flood_days import count_flood_days  # noqa: E402


def series(pairs):
    index = pd.to_datetime([t for t, _ in pairs])
    return pd.DataFrame({"v": [v for _, v in pairs]}, index=index)


def test_two_exceedances_in_one_day_count_once():
    """Rule 1: the unit is the day, not the crossing."""
    heights = series([
        ("2024-01-01 02:00", 1.6),  # morning high tide over the line
        ("2024-01-01 08:00", 0.2),
        ("2024-01-01 14:00", 1.7),  # afternoon high tide over it again
    ])
    assert count_flood_days(heights, threshold=1.5, year=2024).flood_days == 1


def test_day_below_threshold_is_not_counted():
    heights = series([("2024-01-01 02:00", 1.4), ("2024-01-01 14:00", 1.49)])
    assert count_flood_days(heights, threshold=1.5, year=2024).flood_days == 0


def test_exactly_at_threshold_counts():
    """>= not >. Stated so the boundary is a decision, not an accident."""
    heights = series([("2024-01-01 02:00", 1.5)])
    assert count_flood_days(heights, threshold=1.5, year=2024).flood_days == 1


def test_missing_days_are_not_counted_as_dry():
    """Rule 5: a gauge that went down is not a run of calm weather."""
    heights = series([("2024-01-01 02:00", 1.6), ("2024-06-01 02:00", 1.6)])
    result = count_flood_days(heights, threshold=1.5, year=2024)
    assert result.flood_days == 2
    assert result.days_observed == 2  # not 366, and not 152
    assert not result.usable  # two hours of data must never be reportable


def test_gaps_within_a_day_still_yield_a_daily_max():
    heights = series([("2024-01-01 02:00", 1.6), ("2024-01-01 03:00", None)])
    assert count_flood_days(heights, threshold=1.5, year=2024).flood_days == 1


def test_completeness_is_a_fraction_of_the_calendar_year():
    heights = series([(f"2024-01-{d:02d} 02:00", 0.0) for d in range(1, 32)])
    result = count_flood_days(heights, threshold=1.5, year=2024)
    assert round(result.completeness, 5) == round(31 / (366 * 24), 5)
    assert not result.usable


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall passed")
