"""
schedule.py
-----------
Reads the user's apply_windows from profile.yaml and answers:
  - Is now inside an apply window?
  - What is the first window start time today?
  - What is the last window end time today?

Used by the Discord bot to decide when to send reminders and digests.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_DEFAULT_WINDOWS = {
    "monday": ["09:00-12:00", "18:00-20:00"],
    "tuesday": ["09:00-12:00", "18:00-20:00"],
    "wednesday": ["09:00-12:00", "18:00-20:00"],
    "thursday": ["09:00-12:00", "18:00-20:00"],
    "friday": ["09:00-12:00"],
    "saturday": [],
    "sunday": [],
}


def coerce_schedule(profile: dict) -> dict:
    """
    Return a schedule dict safe for the bot. Fills timezone and apply_windows if missing
    so digests and scans still run for new installs.
    """
    raw = profile.get("schedule")
    if not isinstance(raw, dict):
        raw = {}
    out = dict(raw)
    if not out.get("timezone"):
        out["timezone"] = "UTC"
    if not out.get("apply_windows") or not isinstance(out["apply_windows"], dict):
        out["apply_windows"] = dict(_DEFAULT_WINDOWS)
    return out


def _parse_window(window_str: str) -> tuple[time, time]:
    """Parse '08:00-11:00' into (time(8,0), time(11,0))."""
    start_s, end_s = window_str.strip().split("-")
    sh, sm = map(int, start_s.split(":"))
    eh, em = map(int, end_s.split(":"))
    return time(sh, sm), time(eh, em)


def total_apply_minutes_from_strings(windows: list[str]) -> int:
    """Total minutes across window strings (same day, no overnight wrap except end < start)."""
    total = 0
    for w in windows or []:
        try:
            start, end = _parse_window(w)
            sm = start.hour * 60 + start.minute
            em = end.hour * 60 + end.minute
            if em < sm:
                em += 24 * 60
            total += em - sm
        except Exception:
            continue
    return total


def get_effective_apply_windows(
    schedule: dict, day_key: str
) -> tuple[list[str], bool, str | None]:
    """
    Apply windows for a calendar day: /myday override if present, else profile weekday.

    Returns (windows, used_override, raw_override_text_or_none).
    """
    from src.tracker.db import get_daily_schedule_override

    o = get_daily_schedule_override(day_key)
    if o is not None:
        wins = o.get("windows")
        if not isinstance(wins, list):
            wins = []
        raw = o.get("raw_text")
        if isinstance(raw, str) and raw.strip():
            return wins, True, raw.strip()
        return wins, True, None
    d = date.fromisoformat(day_key)
    day_name = DAY_NAMES[d.weekday()]
    wins = (schedule.get("apply_windows") or {}).get(day_name, [])
    return wins, False, None


def _windows_for_effective_today(schedule: dict) -> tuple[list[str], bool, str | None]:
    return get_effective_apply_windows(schedule, user_local_day_key(schedule))


def _user_now(schedule: dict) -> datetime:
    """Current datetime in the user's timezone."""
    tz_name = schedule.get("timezone", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


def is_apply_window(schedule: dict) -> bool:
    """Return True if the current local time falls inside an apply window (profile or /myday override)."""
    windows, _, _ = _windows_for_effective_today(schedule)
    now = _user_now(schedule)
    now_t = now.time().replace(second=0, microsecond=0)
    for w in windows:
        try:
            start, end = _parse_window(w)
            if start <= now_t <= end:
                return True
        except Exception:
            continue
    return False


def today_first_window_start(schedule: dict) -> time | None:
    """Return the start time of the first apply window today, or None if rest day."""
    windows, _, _ = _windows_for_effective_today(schedule)
    for w in windows:
        try:
            start, _ = _parse_window(w)
            return start
        except Exception:
            continue
    return None


def today_last_window_end(schedule: dict) -> time | None:
    """Return the end time of the last apply window today, or None if rest day."""
    windows, _, _ = _windows_for_effective_today(schedule)
    last = None
    for w in windows:
        try:
            _, end = _parse_window(w)
            last = end
        except Exception:
            continue
    return last


def is_rest_day(schedule: dict) -> bool:
    """True when there are no effective apply windows today (profile or /myday)."""
    windows, _, _ = _windows_for_effective_today(schedule)
    return len(windows) == 0


def is_profile_rest_day_today(schedule: dict) -> bool:
    """Rest day from profile only (ignores /myday)."""
    now = _user_now(schedule)
    day_name = DAY_NAMES[now.weekday()]
    windows = (schedule.get("apply_windows") or {}).get(day_name, [])
    return len(windows) == 0


def window_status_message(schedule: dict) -> str:
    """Human-readable current window status for Discord."""
    windows, used_override, _ = _windows_for_effective_today(schedule)
    if not windows:
        if used_override:
            return "No apply windows today (per your /myday schedule)."
        return "Today is a rest day — no apply windows scheduled."
    if is_apply_window(schedule):
        end = today_last_window_end(schedule)
        return f"You're in an apply window. {'Ends at ' + end.strftime('%H:%M') if end else ''}"
    first = today_first_window_start(schedule)
    if first:
        return f"Outside apply window. Next window starts at {first.strftime('%H:%M')}."
    return "No apply windows today."


def user_timezone(schedule: dict):
    """User's tzinfo (ZoneInfo, or UTC fallback)."""
    tz_name = schedule.get("timezone", "UTC")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        try:
            return ZoneInfo("UTC")
        except Exception:
            return timezone.utc


def user_local_day_key(schedule: dict) -> str:
    """YYYY-MM-DD in the user's timezone (for stats and digest de-dupe)."""
    return _user_now(schedule).strftime("%Y-%m-%d")


def user_yesterday_key(schedule: dict) -> str:
    d = date.fromisoformat(user_local_day_key(schedule))
    return (d - timedelta(days=1)).isoformat()


def user_calendar_week_bounds(schedule: dict) -> tuple[str, str]:
    """Monday and Sunday dates (YYYY-MM-DD) for the current week in the user's timezone."""
    now = _user_now(schedule)
    d = now.date()
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def notification_tolerance_minutes(schedule: dict) -> int:
    """How many minutes after a target time we still fire (covers tick interval + boot delay)."""
    raw = schedule.get("notification_tolerance_minutes")
    if raw is not None:
        try:
            return max(3, min(60, int(raw)))
        except (TypeError, ValueError):
            pass
    return 12


def reminders_only_in_apply_windows(schedule: dict) -> bool:
    return bool(schedule.get("reminders_only_in_apply_windows", True))


def is_within_trigger_window(
    schedule: dict,
    target_local: datetime | None,
    tolerance_minutes: int | None = None,
) -> bool:
    """True if now (user TZ) is in [target, target + tolerance)."""
    if target_local is None:
        return False
    tol = tolerance_minutes if tolerance_minutes is not None else notification_tolerance_minutes(schedule)
    now = _user_now(schedule)
    if target_local.tzinfo != now.tzinfo:
        target_local = target_local.astimezone(now.tzinfo)
    delta_min = (now - target_local).total_seconds() / 60.0
    return 0.0 <= delta_min < float(tol)


def morning_digest_local_datetime(schedule: dict) -> datetime | None:
    """Fire morning digest at the start of the first apply window today (user TZ)."""
    if is_rest_day(schedule):
        return None
    start = today_first_window_start(schedule)
    if not start:
        return None
    now = _user_now(schedule)
    tz = user_timezone(schedule)
    return datetime.combine(now.date(), start, tzinfo=tz)


def evening_summary_local_datetime(schedule: dict) -> datetime | None:
    """Fire evening summary at the end of the last apply window today (user TZ)."""
    if is_rest_day(schedule):
        return None
    end_t = today_last_window_end(schedule)
    if not end_t:
        return None
    now = _user_now(schedule)
    tz = user_timezone(schedule)
    return datetime.combine(now.date(), end_t, tzinfo=tz)


def auto_scan_local_datetimes(schedule: dict) -> list[datetime]:
    """
    One pre-window scan per block: 15 minutes before each apply window start today.
    Skipped on rest days.
    """
    if is_rest_day(schedule):
        return []
    now = _user_now(schedule)
    windows, _, _ = _windows_for_effective_today(schedule)
    tz = user_timezone(schedule)
    out: list[datetime] = []
    for w in windows:
        try:
            start, _ = _parse_window(w)
            dt = datetime.combine(now.date(), start, tzinfo=tz) - timedelta(minutes=15)
            out.append(dt)
        except Exception:
            continue
    return out


def follow_up_check_local_datetime(schedule: dict) -> datetime | None:
    """Nudge for stale applications: 45 minutes after first window starts (same day)."""
    base = morning_digest_local_datetime(schedule)
    if base is None:
        return None
    return base + timedelta(minutes=45)


def describe_next_events(schedule: dict) -> str:
    """Multi-line summary for /schedule command."""
    dk = user_local_day_key(schedule)
    wins_eff, ov, raw_ov = get_effective_apply_windows(schedule, dk)
    lines = [
        f"**Timezone:** `{schedule.get('timezone', 'UTC')}`",
        f"**Today ({dk}):**",
    ]
    if ov:
        snippet = (raw_ov or "")[:200]
        if len(raw_ov or "") > 200:
            snippet = snippet[:197] + "..."
        lines.append("- **Today's schedule:** `/myday`" + (f" — _{snippet}_" if snippet else ""))
    if not wins_eff:
        lines.append("- No apply windows today (profile rest day, or `/myday` with no free time)")
    else:
        for w in wins_eff:
            lines.append(f"- Apply window: `{w}`")
        md = morning_digest_local_datetime(schedule)
        es = evening_summary_local_datetime(schedule)
        if md:
            lines.append(f"- Morning digest targets: `{md.strftime('%H:%M')}` local")
        if es:
            lines.append(f"- Evening summary targets: `{es.strftime('%H:%M')}` local")
        scans = auto_scan_local_datetimes(schedule)
        for i, s in enumerate(scans, 1):
            lines.append(f"- Auto-scan #{i}: ~`{s.strftime('%H:%M')}` local (15 min before a window)")
        fu = follow_up_check_local_datetime(schedule)
        if fu:
            lines.append(f"- Follow-up ping: ~`{fu.strftime('%H:%M')}` local")
    lines.append(f"- **Now:** `{_user_now(schedule).strftime('%Y-%m-%d %H:%M')}`")
    lines.append(f"- **In apply window:** {'yes' if is_apply_window(schedule) else 'no'}")
    lines.append(
        f"- **Reminders gated to windows:** {'yes' if reminders_only_in_apply_windows(schedule) else 'no'}"
    )
    return "\n".join(lines)


def count_active_apply_days(schedule: dict) -> int:
    """Weekdays in apply_windows with at least one window."""
    aw = schedule.get("apply_windows") or {}
    return sum(1 for d in DAY_NAMES if aw.get(d))


def total_apply_minutes_today(schedule: dict) -> int:
    """Total minutes across all apply windows today (user TZ). Rest day => 0."""
    windows, _, _ = _windows_for_effective_today(schedule)
    return total_apply_minutes_from_strings(windows)


def _minutes_per_application(schedule: dict) -> float:
    aph = schedule.get("apps_per_hour_assumption", 2)
    try:
        aph = float(aph)
    except (TypeError, ValueError):
        aph = 2.0
    aph = max(0.25, aph)
    return 60.0 / aph


def effective_daily_goal(profile: dict, schedule: dict) -> int:
    """
    Daily application target: uses daily_application_target when set; otherwise derives
    from weekly_application_target / active apply days.
    """
    daily = profile.get("daily_application_target")
    if daily is not None:
        try:
            return max(1, int(daily))
        except (TypeError, ValueError):
            pass
    weekly = schedule.get("weekly_application_target")
    if weekly is not None:
        try:
            w = max(1, int(weekly))
        except (TypeError, ValueError):
            w = 25
        active = count_active_apply_days(schedule)
        if active <= 0:
            return max(1, (w + 6) // 7)
        return max(1, (w + active - 1) // active)
    return 5


def _split_goal_across_weights(weights: list[float], total: int) -> list[int]:
    """Largest-remainder split of total across positive weights."""
    n = len(weights)
    if total <= 0 or n == 0:
        return [0] * n
    s = sum(weights)
    if s <= 0:
        return [0] * n
    exact = [total * weights[i] / s for i in range(n)]
    floors = [int(x) for x in exact]
    rem = total - sum(floors)
    order = sorted(range(n), key=lambda i: exact[i] - floors[i], reverse=True)
    for k in range(rem):
        floors[order[k % n]] += 1
    return floors


def suggested_app_plan_today(
    profile: dict,
    schedule: dict,
    *,
    applied_today_count: int = 0,
    applied_this_week_count: int | None = None,
) -> dict:
    """
    Build today's application strategy: time budget, per-window targets, weekly context.

    Returns keys: daily_goal, realistic_cap, total_minutes, windows (list of dicts),
    remaining_today, message (optional), weekly_target, weekly_progress, weekly_remaining,
    strategy_notes, catch_up_policy, shortfall (goal vs time budget).
    """
    sched = schedule if isinstance(schedule.get("apply_windows"), dict) else coerce_schedule(profile)

    notes = (sched.get("strategy_notes") or "").strip()
    policy = (sched.get("catch_up_policy") or "even_split").strip().lower()
    if policy not in ("even_split", "next_window"):
        policy = "even_split"

    daily_goal = effective_daily_goal(profile, sched)
    weekly_tgt = sched.get("weekly_application_target")
    try:
        weekly_tgt = int(weekly_tgt) if weekly_tgt is not None else None
    except (TypeError, ValueError):
        weekly_tgt = None

    day_key = user_local_day_key(sched)
    wins_eff, used_override, raw_override = get_effective_apply_windows(sched, day_key)
    total_min = total_apply_minutes_from_strings(wins_eff)
    mpa = _minutes_per_application(sched)
    realistic_cap = int(total_min / mpa) if mpa > 0 else 0

    windows_out: list[dict] = []
    if not wins_eff or total_min <= 0:
        msg = None
        if used_override:
            msg = "Today's `/myday` schedule has no apply windows — use `/myday` again if you want to adjust."
        else:
            msg = "Rest day — no apply windows. Weekly goals carry to other days."
        out = {
            "daily_goal": daily_goal,
            "realistic_cap": 0,
            "total_minutes": 0,
            "windows": [],
            "remaining_today": max(0, daily_goal - applied_today_count),
            "message": msg,
            "weekly_target": weekly_tgt,
            "weekly_progress": applied_this_week_count,
            "weekly_remaining": (
                max(0, weekly_tgt - applied_this_week_count) if weekly_tgt is not None and applied_this_week_count is not None else None
            ),
            "strategy_notes": notes,
            "catch_up_policy": policy,
            "shortfall": max(0, daily_goal - realistic_cap) if realistic_cap < daily_goal else 0,
            "schedule_source": "override" if used_override else "profile",
            "override_raw": raw_override,
        }
        return out

    raw_windows = wins_eff
    weights: list[float] = []
    labels: list[str] = []
    for w in raw_windows:
        try:
            start, end = _parse_window(w)
            sm = start.hour * 60 + start.minute
            em = end.hour * 60 + end.minute
            if em < sm:
                em += 24 * 60
            dur = float(em - sm)
            weights.append(dur)
            labels.append(f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}")
        except Exception:
            continue

    achievable = min(daily_goal, realistic_cap)
    counts = _split_goal_across_weights(weights, achievable) if weights else []

    for i, lbl in enumerate(labels):
        windows_out.append(
            {
                "label": lbl,
                "minutes": int(weights[i]) if i < len(weights) else 0,
                "suggested_apps": counts[i] if i < len(counts) else 0,
            }
        )

    remaining_today = max(0, daily_goal - applied_today_count)
    shortfall = max(0, daily_goal - realistic_cap)

    message_parts = []
    if used_override:
        message_parts.append(
            "Using **today's** `/myday` windows (overrides your default weekly profile for this date)."
        )
    if shortfall > 0:
        message_parts.append(
            f"Time budget today supports ~**{realistic_cap}** complete application(s); "
            f"your goal is **{daily_goal}**. Consider a shorter `/goal`, longer windows, "
            f"or a faster `apps_per_hour_assumption` if you batch hard."
        )
    if weekly_tgt is not None and applied_this_week_count is not None:
        wr = max(0, weekly_tgt - applied_this_week_count)
        if wr > 0 and policy == "even_split":
            # rough: remaining week days with windows
            remaining_days = _remaining_active_days_this_week(sched)
            if remaining_days > 0:
                per = (wr + remaining_days - 1) // remaining_days
                message_parts.append(
                    f"Weekly progress: **{applied_this_week_count}/{weekly_tgt}**. "
                    f"Rough pace: ~**{per}**/day on remaining apply days to hit the week."
                )
        elif wr > 0 and policy == "next_window":
            message_parts.append(
                f"Weekly progress: **{applied_this_week_count}/{weekly_tgt}**. "
                "Catch up in your next apply window when you can focus."
            )

    return {
        "daily_goal": daily_goal,
        "realistic_cap": realistic_cap,
        "total_minutes": total_min,
        "windows": windows_out,
        "remaining_today": remaining_today,
        "message": "\n".join(message_parts) if message_parts else None,
        "weekly_target": weekly_tgt,
        "weekly_progress": applied_this_week_count,
        "weekly_remaining": (
            max(0, weekly_tgt - applied_this_week_count) if weekly_tgt is not None and applied_this_week_count is not None else None
        ),
        "strategy_notes": notes,
        "catch_up_policy": policy,
        "shortfall": shortfall,
        "schedule_source": "override" if used_override else "profile",
        "override_raw": raw_override,
    }


def _remaining_active_days_this_week(schedule: dict) -> int:
    """From today (user TZ) through Sunday: days that have apply windows."""
    now = _user_now(schedule)
    today_idx = now.weekday()  # 0=Mon
    remaining = 0
    for offset in range(7 - today_idx):
        idx = today_idx + offset
        day_name = DAY_NAMES[idx]
        wins = (schedule.get("apply_windows") or {}).get(day_name, [])
        if wins:
            remaining += 1
    return max(1, remaining)


def format_strategy_blurb(plan: dict, max_lines: int = 4) -> str:
    """Short text for morning digest or /today (Discord-safe length)."""
    if not plan.get("windows") and plan.get("message"):
        return plan["message"][:500]
    lines = []
    for w in plan.get("windows") or []:
        lines.append(f"{w['label']}: aim for **{w['suggested_apps']}**")
    if plan.get("remaining_today") is not None and plan.get("daily_goal"):
        lines.append(f"Goal today: **{plan['daily_goal']}** applied (remaining ~**{plan['remaining_today']}**).")
    if plan.get("message"):
        lines.append(plan["message"])
    if plan.get("strategy_notes"):
        lines.append(f"Notes: {plan['strategy_notes'][:200]}")
    text = "\n".join(lines[:max_lines])
    if len(text) > 1800:
        return text[:1797] + "..."
    return text


def format_strategy_discord_block(plan: dict) -> str:
    """Longer block for /strategy command."""
    parts = []
    if plan.get("schedule_source") == "override":
        parts.append("**Schedule:** today's `/myday` override (not default profile windows).")
        parts.append("")
    parts.append(f"**Time budget today:** {plan.get('total_minutes', 0)} min in apply windows")
    parts.append(f"**Daily goal:** {plan.get('daily_goal', 0)} | **Realistic cap:** ~{plan.get('realistic_cap', 0)} applies (from your minutes / apps_per_hour)")
    if plan.get("weekly_target") is not None:
        wp = plan.get("weekly_progress")
        if wp is not None:
            parts.append(f"**This week:** {wp}/{plan['weekly_target']} applications logged")
        else:
            parts.append(f"**Weekly target:** {plan['weekly_target']}")
    parts.append("")
    for w in plan.get("windows") or []:
        parts.append(f"- `{w['label']}` — ~**{w['suggested_apps']}** application(s) ({w['minutes']} min)")
    if plan.get("strategy_notes"):
        parts.append("")
        parts.append(f"**Your notes:** {plan['strategy_notes']}")
    if plan.get("message"):
        parts.append("")
        parts.append(plan["message"])
    return "\n".join(parts)
