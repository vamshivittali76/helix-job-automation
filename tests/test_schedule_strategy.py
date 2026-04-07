"""Unit tests for schedule-aware application strategy helpers."""

import src.utils.schedule as sched
from src.utils import schedule_parse as sp


def _sample_schedule():
    return {
        "timezone": "UTC",
        "apply_windows": {
            "monday": ["08:00-10:00", "18:00-19:00"],
            "tuesday": ["09:00-12:00"],
            "wednesday": [],
            "thursday": ["10:00-11:00"],
            "friday": ["08:00-09:00"],
            "saturday": [],
            "sunday": [],
        },
        "apps_per_hour_assumption": 2,
    }


def test_total_apply_minutes_two_windows():
    s = _sample_schedule()
    # Patch "today" by using a fixed weekday: inject monday windows -> 2h + 1h = 180 min
    from unittest.mock import patch
    from datetime import datetime, timezone

    with patch.object(sched, "_user_now") as m:
        m.return_value = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)
        assert sched.total_apply_minutes_today(s) == 180


def test_total_apply_minutes_rest_day():
    s = _sample_schedule()
    from unittest.mock import patch
    from datetime import datetime, timezone

    with patch.object(sched, "_user_now") as m:
        m.return_value = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)  # Wednesday empty
        assert sched.total_apply_minutes_today(s) == 0


def test_effective_daily_goal_from_profile():
    profile = {"daily_application_target": 7}
    schedule = {}
    assert sched.effective_daily_goal(profile, schedule) == 7


def test_effective_daily_goal_from_weekly_only():
    profile = {}
    schedule = {
        "weekly_application_target": 14,
        "apply_windows": {
            "monday": ["09:00-10:00"],
            "tuesday": ["09:00-10:00"],
            "wednesday": ["09:00-10:00"],
            "thursday": ["09:00-10:00"],
            "friday": ["09:00-10:00"],
            "saturday": [],
            "sunday": [],
        },
    }
    # 14 / 5 active days -> ceil 2.8 -> 3 in integer math: (14+5-1)//5 = 3
    assert sched.effective_daily_goal(profile, schedule) == 3


def test_split_goal_proportional():
    w = [120.0, 60.0]
    out = sched._split_goal_across_weights(w, 5)
    assert sum(out) == 5
    assert out[0] >= out[1]


def test_suggested_plan_splits_across_windows():
    profile = {"daily_application_target": 4}
    schedule = {
        "timezone": "UTC",
        "apps_per_hour_assumption": 2,
        "apply_windows": {
            "monday": ["08:00-10:00", "18:00-19:00"],
            "tuesday": ["09:00-12:00"],
            "wednesday": [],
            "thursday": ["10:00-11:00"],
            "friday": ["08:00-09:00"],
            "saturday": [],
            "sunday": [],
        },
    }
    from unittest.mock import patch
    from datetime import datetime, timezone

    with patch.object(sched, "_user_now") as m:
        m.return_value = datetime(2026, 4, 6, 9, 0, tzinfo=timezone.utc)
        plan = sched.suggested_app_plan_today(
            profile, schedule, applied_today_count=0, applied_this_week_count=1
        )
    assert plan["daily_goal"] == 4
    assert plan["realistic_cap"] >= 4
    assert len(plan["windows"]) == 2
    assert sum(w["suggested_apps"] for w in plan["windows"]) == 4


def test_get_effective_apply_windows_uses_override():
    s = _sample_schedule()
    from unittest.mock import patch
    from datetime import datetime, timezone

    with patch.object(sched, "_user_now") as m:
        m.return_value = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)
    with patch("src.tracker.db.get_daily_schedule_override") as go:
        go.return_value = {"windows": ["10:00-11:00"], "raw_text": "office"}
        wins, ov, raw = sched.get_effective_apply_windows(s, "2026-04-06")
        assert ov is True
        assert wins == ["10:00-11:00"]
        assert raw == "office"


def test_extract_windows_regex_finds_ranges():
    text = "07:00-10:00 and 16:00-23:00"
    assert sp._extract_windows_regex(text) == ["07:00-10:00", "16:00-23:00"]


def test_get_effective_apply_windows_falls_back_to_profile():
    s = _sample_schedule()
    from unittest.mock import patch

    with patch("src.tracker.db.get_daily_schedule_override") as go:
        go.return_value = None
        wins, ov, raw = sched.get_effective_apply_windows(s, "2026-04-06")
        assert ov is False
        assert raw is None
        assert "08:00-10:00" in wins


def test_format_strategy_discord_block_includes_minutes():
    plan = {
        "total_minutes": 60,
        "daily_goal": 3,
        "realistic_cap": 2,
        "windows": [{"label": "08:00–09:00", "minutes": 60, "suggested_apps": 2}],
        "weekly_target": 10,
        "weekly_progress": 3,
        "strategy_notes": "Test note",
        "message": "Cap note",
    }
    text = sched.format_strategy_discord_block(plan)
    assert "60 min" in text or "Time budget" in text
    assert "Test note" in text
