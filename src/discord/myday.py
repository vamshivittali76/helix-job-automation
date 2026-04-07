"""Shared handler for `/myday`: parse natural language, save override, show today's plan."""

from __future__ import annotations

import yaml
from pathlib import Path

import discord

ROOT = Path(__file__).parent.parent.parent


def load_profile() -> dict:
    with open(ROOT / "config" / "profile.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def complete_myday(interaction: discord.Interaction, raw_text: str) -> None:
    """Parse schedule text, persist for today, reply with strategy embed (ephemeral)."""
    raw_text = (raw_text or "").strip()
    if not raw_text:
        await interaction.response.send_message(
            "Describe your schedule — when you're free to apply and what's blocking you (gym, office, etc.).",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        from src.utils.schedule_parse import parse_freeform_day_schedule
        from src.utils.schedule import (
            coerce_schedule,
            user_local_day_key,
            user_calendar_week_bounds,
            suggested_app_plan_today,
            format_strategy_discord_block,
        )
        from src.tracker.db import save_daily_schedule_override, get_connection, count_applied_between_days

        profile = load_profile()
        sched = coerce_schedule(profile)
        day_key = user_local_day_key(sched)
        tz = sched.get("timezone", "UTC")
        parsed = parse_freeform_day_schedule(raw_text, tz, day_key)
        save_daily_schedule_override(day_key, raw_text, parsed["windows"])

        conn = get_connection()
        applied_today = conn.execute(
            """SELECT COUNT(DISTINCT job_id) FROM status_history
               WHERE new_status='applied' AND substr(changed_at, 1, 10) = ?""",
            (day_key,),
        ).fetchone()[0]
        conn.close()
        w0, w1 = user_calendar_week_bounds(sched)
        week_applied = count_applied_between_days(w0, w1)
        plan = suggested_app_plan_today(
            profile,
            sched,
            applied_today_count=applied_today,
            applied_this_week_count=week_applied,
        )
        body = format_strategy_discord_block(plan)
        embed = discord.Embed(
            title="Today's plan",
            description=body[:4096],
            color=0x7289DA,
        )
        if parsed.get("summary"):
            embed.add_field(name="Parsed summary", value=parsed["summary"][:1024], inline=False)
        wins = parsed.get("windows") or []
        if wins:
            embed.add_field(
                name="Apply windows (today)",
                value=", ".join(f"`{w}`" for w in wins)[:1024],
                inline=False,
            )
        else:
            embed.add_field(
                name="Apply windows (today)",
                value="None — if that's wrong, run `/myday` again with your free blocks.",
                inline=False,
            )
        embed.set_footer(text="Tomorrow your profile windows apply again unless you use /myday.")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except ValueError as e:
        await interaction.followup.send(f"\u26a0 {e}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"\u274c Error: {e}", ephemeral=True)
