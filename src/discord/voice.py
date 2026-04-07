"""
Helix voice — short, direct, encouraging coach. No guilt trips; clear next steps.
"""

from __future__ import annotations


TAGLINE = "Clear next steps. No guilt trips."

MORNING_TITLE_REST = "Rest day"
MORNING_TITLE_ACTIVE = "Good morning — your brief"

EVENING_TITLE = "Evening wrap-up"

APPROVE_APPLY_CARD = "Approved. Here is your apply card — open the link, apply in the browser, then tap **I Applied** when you are done."

APPLIED_CONFIRM = (
    "Logged as applied. Nice work. I will remind you to follow up in seven days "
    "unless you update the status first."
)

REMINDER_SCHEDULED = "On it — I will ping you here in two hours."

SKIP_JOB = "Skipped. On to the next one when you are ready."

REJECT_JOB = "Rejected and removed from your queue."

SCAN_OK = "Auto-scan finished — new matches are in the pipeline."

SCAN_FAIL_PREFIX = "Auto-scan hit a snag:"

FOLLOW_UP_INTRO = "A few applications are waiting on a follow-up. Here is the short list."

FOOTER_REVIEW = "Run /review when you are ready — one job at a time is fine."

FOOTER_GOAL_HIT = "You hit your goal today. That counts."

FOOTER_GOAL_SHORT = "Short of the goal today — tomorrow is a clean slate."

FOOTER_DEFAULT = "Helix is here when you need the next step."


def morning_footer(pending: int, follow_ups: int) -> str:
    parts = []
    if pending > 0:
        parts.append("/review to queue the next role")
    if follow_ups > 0:
        parts.append("/follow_up for stale threads")
    return " · ".join(parts) if parts else FOOTER_DEFAULT


def evening_footer(applied_today: int, daily_goal: int) -> str:
    if applied_today >= daily_goal:
        return FOOTER_GOAL_HIT
    return FOOTER_GOAL_SHORT
