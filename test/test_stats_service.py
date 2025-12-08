import datetime
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.stats_service import build_daily_series, conversion_table, _score_quality


def _dt(days_ago: int) -> str:
    return (datetime.datetime.now() - datetime.timedelta(days=days_ago)).isoformat()


def test_score_quality_penalizes_high_share():
    scores = [8] * 80 + [5] * 20
    result = _score_quality(scores)
    assert result.count == 100
    assert result.high_share > 0.7
    assert result.quality_score < 8  # should be penalized for skew


def test_daily_series_counts_new_and_seek():
    candidates = [
        {"updated_at": _dt(0), "stage": "SEEK"},
        {"updated_at": _dt(1), "stage": "CHAT"},
        {"updated_at": _dt(1), "stage": "SEEK"},
    ]
    series = build_daily_series(candidates, days=2)
    assert series[-1]["new"] == 1  # today
    assert series[-1]["seek"] == 1
    assert series[-2]["new"] == 2
    assert series[-2]["seek"] == 1


def test_conversion_table_orders_stages():
    candidates = [
        {"stage": "GREET"},
        {"stage": "CHAT"},
        {"stage": "SEEK"},
        {"stage": "CONTACT"},
        {"stage": "PASS"},
    ]
    table = conversion_table(candidates)
    stages = [row["stage"] for row in table]
    assert stages[:4] == ["GREET", "CHAT", "SEEK", "CONTACT"]
    pass_row = next(row for row in table if row["stage"] == "PASS")
    assert pass_row["count"] == 1
