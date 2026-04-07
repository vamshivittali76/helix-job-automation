"""
Helix -- AI-powered job search agent.

Discord bot serving as the primary interface for the
Job Application Automation System.

Run: venv\\Scripts\\python -m src.discord.bot
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import tasks
import yaml

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.tracker.db import (
    init_db, get_job, get_detailed_stats, get_pending_review_jobs,
    get_jobs_by_filters, get_all_jobs, update_application_status,
    get_status_history, get_connection, try_claim_schedule_event,
)
from src.discord.views import ReviewView, BatchReviewSelect, PaginationView, MyDayModal
from src.discord.charts import (
    chart_weekly, chart_sources, chart_scores, chart_funnel,
    chart_seniority, get_daily_stats_from_db,
)


def load_config():
    with open(ROOT / "config" / "secrets.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_profile():
    with open(ROOT / "config" / "profile.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


SECRETS = load_config()


def _coach_channel_id() -> int | None:
    """
    Natural-language Helix coach channel.
    Prefer explicit ``helix_coach_channel_id`` in secrets (non-zero); else auto-detected #helix-coach.
    """
    raw = SECRETS.get("helix_coach_channel_id")
    if raw is not None and raw != "":
        try:
            n = int(raw)
        except (TypeError, ValueError):
            n = 0
        if n != 0:
            return n
    if COACH_CHANNEL_ID:
        return COACH_CHANNEL_ID
    return None
BOT_TOKEN = SECRETS.get("discord_bot_token", "")

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

NOTIFICATION_CHANNEL_ID: int = 0
COACH_CHANNEL_ID: int = 0  # set in on_ready when #helix-coach exists (unless overridden in secrets)

_scan_lock = asyncio.Lock()
_tasks_started = False


def _sponsor_badge(status: str) -> str:
    return {"sponsor_likely": "\U0001f7e2 Likely", "sponsor_unlikely": "\U0001f534 Unlikely"}.get(
        status, "\u26aa Unknown"
    )


def _seniority_badge(level: str) -> str:
    return {
        "entry": "\U0001f331 Entry", "mid": "\U0001f4bc Mid",
        "senior": "\u2b50 Senior", "lead": "\U0001f451 Lead",
        "executive": "\U0001f3e2 Executive",
    }.get(level or "mid", "\U0001f4bc Mid")


def _compute_fitness(job: dict) -> int:
    """Quick fitness score for embed display."""
    try:
        from src.matching.profile_fitness import compute_profile_fitness
        profile = load_profile()
        return compute_profile_fitness(job, profile)["fitness_score"]
    except Exception:
        return 0


def _fitness_emoji(score: int) -> str:
    if score >= 80:
        return "\U0001f7e2"
    if score >= 60:
        return "\U0001f7e1"
    if score >= 40:
        return "\U0001f7e0"
    return "\U0001f534"


def _job_embed(job: dict, index: int = None, total: int = None) -> discord.Embed:
    title = job.get("title", "Untitled")
    if index is not None and total is not None:
        title = f"[{index}/{total}] {title}"
    title = title[:256]

    fitness = _compute_fitness(job)

    embed = discord.Embed(
        title=title,
        url=job.get("url"),
        color=discord.Color.green() if fitness >= 70 else discord.Color.gold() if fitness >= 50 else discord.Color.red(),
    )
    embed.add_field(name="Company", value=job.get("company", "Unknown"), inline=True)
    embed.add_field(name="Location", value=job.get("location") or "N/A", inline=True)
    embed.add_field(
        name="Profile Fit",
        value=f"{_fitness_emoji(fitness)} **{fitness}**/100",
        inline=True,
    )
    embed.add_field(
        name="Match Score",
        value=f"**{job.get('match_score', 0):.0f}**/100",
        inline=True,
    )
    embed.add_field(name="Sponsorship", value=_sponsor_badge(job.get("sponsorship_status", "")), inline=True)
    embed.add_field(name="Seniority", value=_seniority_badge(job.get("seniority_level")), inline=True)

    # Competition / freshness intel
    if job.get("is_expired"):
        embed.add_field(
            name="⚠️ Status",
            value=f"🚫 Closed — {job.get('expired_reason', 'No longer accepting')[:50]}",
            inline=False,
        )
    elif job.get("applicant_label"):
        comp_emoji = {"first_25": "🟢", "low": "🟢", "medium": "🟡", "high": "🔴"}.get(
            job.get("competition_level", "unknown"), "⚪"
        )
        embed.add_field(
            name="👥 Applicants",
            value=f"{comp_emoji} {job['applicant_label']}",
            inline=True,
        )

    penalty = job.get("seniority_penalty", 0)
    if penalty < 0:
        embed.add_field(name="Penalty", value=f"{penalty:.0f} pts", inline=True)

    req_years = job.get("required_years")
    if req_years:
        embed.add_field(name="Req. Years", value=f"{req_years}+", inline=True)

    desc = (job.get("description") or "")
    if desc:
        truncated = len(desc) > 300
        desc = desc[:300]
        embed.add_field(name="Description", value=desc + ("..." if truncated else ""), inline=False)

    embed.set_footer(text=f"Source: {job.get('source', '?')} | Found: {job.get('date_found', '?')[:10]}")
    return embed


# ── Slash Commands ──────────────────────────────────────────

@tree.command(name="review", description="Review the next pending job")
async def cmd_review(interaction: discord.Interaction):
    jobs = get_pending_review_jobs(limit=1)
    if not jobs:
        await interaction.response.send_message("No jobs pending review!", ephemeral=True)
        return
    total = len(get_pending_review_jobs(limit=500))
    job = jobs[0]
    embed = _job_embed(job, index=1, total=total)
    view = ReviewView(job["id"])
    await interaction.response.send_message(embed=embed, view=view)


@tree.command(name="review_batch", description="Review multiple jobs at once")
@app_commands.describe(count="Number of jobs to show (max 25)")
async def cmd_review_batch(interaction: discord.Interaction, count: int = 10):
    jobs = get_pending_review_jobs(limit=min(count, 25))
    if not jobs:
        await interaction.response.send_message("No jobs pending review!", ephemeral=True)
        return
    view = BatchReviewSelect(jobs)
    await interaction.response.send_message(
        f"**{len(jobs)} jobs pending** -- select which to approve/reject:", view=view
    )


@tree.command(name="review_count", description="How many jobs are pending review")
async def cmd_review_count(interaction: discord.Interaction):
    count = len(get_pending_review_jobs(limit=1000))
    await interaction.response.send_message(f"\U0001f4cb **{count}** jobs pending review.")


@tree.command(name="stats", description="Show job search statistics")
async def cmd_stats(interaction: discord.Interaction):
    stats = get_detailed_stats()
    embed = discord.Embed(title="\U0001f4ca Job Search Stats", color=discord.Color.gold())
    embed.add_field(name="Total Jobs", value=str(stats["total"]), inline=True)
    embed.add_field(name="Pending Review", value=str(stats.get("pending_review", 0)), inline=True)
    embed.add_field(name="Approved", value=str(stats.get("approved", 0)), inline=True)
    embed.add_field(name="Applied", value=str(stats.get("applied", 0)), inline=True)
    embed.add_field(name="Interviews", value=str(stats.get("interview", 0)), inline=True)
    embed.add_field(name="Offers", value=str(stats.get("offer", 0)), inline=True)
    embed.add_field(name="Rejected (by company)", value=str(stats.get("rejected_by_company", 0)), inline=True)
    embed.add_field(name="Sponsor Likely", value=str(stats.get("sponsor_likely", 0)), inline=True)
    embed.add_field(name="Avg Score", value=f"{stats['avg_score']:.1f}", inline=True)
    embed.add_field(name="Found Today", value=str(stats.get("found_today", 0)), inline=True)
    embed.add_field(name="Applied Today", value=str(stats.get("applied_today", 0)), inline=True)

    source_items = list(stats.get("by_source", {}).items())
    source_text = "\n".join(f"**{k}**: {v}" for k, v in source_items[:15])
    if source_text:
        embed.add_field(name="By Source", value=source_text[:1024], inline=False)

    await interaction.response.send_message(embed=embed)


@tree.command(name="board", description="Application status board")
async def cmd_board(interaction: discord.Interaction):
    stats = get_detailed_stats()
    board = (
        f"```\n"
        f"Pending Review : {stats.get('pending_review', 0):>4}  |  Approved  : {stats.get('approved', 0):>4}\n"
        f"Applied        : {stats.get('applied', 0):>4}  |  Interview : {stats.get('interview', 0):>4}\n"
        f"Offer          : {stats.get('offer', 0):>4}  |  Accepted  : {stats.get('accepted', 0):>4}\n"
        f"Rejected (co.) : {stats.get('rejected_by_company', 0):>4}  |  No Resp.  : {stats.get('no_response', 0):>4}\n"
        f"Rejected (you) : {stats.get('rejected_by_user', 0):>4}  |  Skipped   : {stats.get('skipped', 0):>4}\n"
        f"```"
    )
    embed = discord.Embed(
        title="\U0001f5c2 Application Board",
        description=board,
        color=discord.Color.teal(),
    )
    embed.set_footer(text=f"Total: {stats['total']} jobs")
    await interaction.response.send_message(embed=embed)


@tree.command(name="jobs", description="List jobs with filters")
@app_commands.describe(
    status="Filter by status (new, pending_review, approved, applied, interview, offer)",
    min_score="Minimum match score",
    sponsor="Show only sponsor-likely jobs",
    seniority="Filter by seniority (entry, mid, senior, lead)",
    source="Filter by source (jooble, adzuna, google_jobs, etc.)",
    search="Search by title or company name",
)
async def cmd_jobs(
    interaction: discord.Interaction,
    status: str = None,
    min_score: float = 0.0,
    sponsor: bool = False,
    seniority: str = None,
    source: str = None,
    search: str = None,
):
    jobs = get_jobs_by_filters(
        status=status, min_score=min_score, sponsor_only=sponsor,
        seniority=seniority, source=source, search=search, limit=50,
    )
    if not jobs:
        await interaction.response.send_message("No jobs match those filters.", ephemeral=True)
        return

    pages = []
    per_page = 10
    for i in range(0, len(jobs), per_page):
        chunk = jobs[i:i + per_page]
        desc_lines = []
        for j, job in enumerate(chunk, start=i + 1):
            score = job.get("match_score", 0)
            sponsor_icon = "\U0001f7e2" if job.get("sponsorship_status") == "sponsor_likely" else "\u26aa"
            desc_lines.append(
                f"`{j:>2}.` {sponsor_icon} **{job['company'][:18]}** - {job['title'][:35]} "
                f"| Score: {score:.0f}"
            )
        embed = discord.Embed(
            title=f"\U0001f4cb Jobs ({i + 1}-{i + len(chunk)} of {len(jobs)})",
            description="\n".join(desc_lines),
            color=discord.Color.blue(),
        )
        pages.append(embed)

    if len(pages) == 1:
        await interaction.response.send_message(embed=pages[0])
    else:
        view = PaginationView(pages)
        await interaction.response.send_message(embed=pages[0], view=view)


@tree.command(name="job", description="Show full detail for a specific job")
@app_commands.describe(job_id="The job ID (from the jobs list)")
async def cmd_job_detail(interaction: discord.Interaction, job_id: str):
    job = get_job(job_id)
    if not job:
        await interaction.response.send_message("Job not found.", ephemeral=True)
        return

    embed = _job_embed(job)
    history = get_status_history(job_id)
    if history:
        timeline = "\n".join(
            f"`{h['changed_at'][:16]}` {h.get('old_status', '?')} \u2192 **{h['new_status']}** ({h.get('source', '?')})"
            for h in history[:5]
        )
        embed.add_field(name="Status History", value=timeline, inline=False)

    await interaction.response.send_message(embed=embed)


@tree.command(name="profile_check", description="Check your profile completeness and get improvement tips")
async def cmd_profile_check(interaction: discord.Interaction):
    from src.matching.profile_validator import format_validation_report
    try:
        profile = load_profile()
        report = format_validation_report(profile)
        if len(report) > 2000:
            report = report[:1997] + "..."
        await interaction.response.send_message(report, ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"\u274c Error: {e}", ephemeral=True)


@tree.command(name="fitness", description="Detailed profile fitness analysis for a job")
@app_commands.describe(job_id="The job ID to analyze")
async def cmd_fitness(interaction: discord.Interaction, job_id: str):
    from src.matching.profile_fitness import compute_profile_fitness, format_fitness_discord
    job = get_job(job_id)
    if not job:
        await interaction.response.send_message("Job not found.", ephemeral=True)
        return
    profile = load_profile()
    result = compute_profile_fitness(job, profile)
    header = f"**{job.get('title', 'Untitled')}** at **{job.get('company', 'Unknown')}**\n\n"
    body = format_fitness_discord(result)
    msg = header + body
    if len(msg) > 2000:
        msg = msg[:1997] + "..."
    await interaction.response.send_message(msg, ephemeral=True)


@tree.command(name="set_status", description="Manually change a job's status")
@app_commands.describe(job_id="Job ID", status="New status")
@app_commands.choices(status=[
    app_commands.Choice(name="Approved", value="approved"),
    app_commands.Choice(name="Applied", value="applied"),
    app_commands.Choice(name="Interview", value="interview"),
    app_commands.Choice(name="Offer", value="offer"),
    app_commands.Choice(name="Rejected by company", value="rejected_by_company"),
    app_commands.Choice(name="Rejected by me", value="rejected_by_user"),
    app_commands.Choice(name="No response", value="no_response"),
    app_commands.Choice(name="Skipped", value="skipped"),
])
async def cmd_set_status(interaction: discord.Interaction, job_id: str, status: app_commands.Choice[str]):
    job = get_job(job_id)
    if not job:
        await interaction.response.send_message("Job not found.", ephemeral=True)
        return
    update_application_status(job_id, status.value, source="discord")
    await interaction.response.send_message(
        f"\u2705 **{job['company']} - {job['title']}** status \u2192 **{status.name}**"
    )


@tree.command(name="status", description="Check application status for a company")
@app_commands.describe(company="Company name to search")
async def cmd_status(interaction: discord.Interaction, company: str):
    from src.tracker.db import search_jobs_by_company
    jobs = search_jobs_by_company(company)
    if not jobs:
        await interaction.response.send_message(f"No jobs found for '{company}'.", ephemeral=True)
        return

    lines = []
    for j in jobs[:10]:
        lines.append(
            f"**{j['title'][:40]}** | Status: `{j['application_status']}` | Score: {j.get('match_score', 0):.0f}"
        )
    embed = discord.Embed(
        title=f"\U0001f50d {company} ({len(jobs)} jobs)",
        description="\n".join(lines),
        color=discord.Color.purple(),
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="scan", description="Trigger a job scan")
@app_commands.describe(source="Specific scraper to use (leave empty for all)")
async def cmd_scan(interaction: discord.Interaction, source: str = None):
    if _scan_lock.locked():
        await interaction.response.send_message(
            "\u23f3 A scan is already in progress. Please wait.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        "\U0001f50d **Scan started** \u2014 this can take a few minutes. "
        "I'll post results here when done."
    )
    channel = interaction.channel

    async def _do_scan():
        async with _scan_lock:
            try:
                result = await asyncio.to_thread(_run_scan, source)
                await channel.send(result)
            except Exception as e:
                await channel.send(f"\u274c Scan error: {e}")

    asyncio.create_task(_do_scan())


def _run_scan(source_filter: str = None) -> str:
    """Run the scan pipeline synchronously (called from thread)."""
    from src.matching.scorer import compute_match_score, apply_seniority_penalty
    from src.matching.sponsorship import enrich_sponsorship
    from src.matching.dedup import deduplicate_jobs
    from src.matching.seniority import enrich_seniority, user_level_from_profile, is_out_of_range

    secrets = load_config()
    profile = load_profile()
    search_cfg = yaml.safe_load(open(ROOT / "config" / "search_config.yaml", encoding="utf-8"))

    init_db()

    sys.path.insert(0, str(ROOT))
    from src.cli import _build_scrapers, _get_scraper_kwargs

    scrapers = _build_scrapers(secrets, search_cfg, source_filter=source_filter)
    if not scrapers:
        return "\u274c No scrapers configured or enabled."

    import signal, threading

    all_collected = []
    for scraper in scrapers:
        for query_cfg in search_cfg.get("search_queries", []):
            query = f"{query_cfg.get('title', '')} {query_cfg.get('keywords', '')}".strip()
            try:
                result_holder = []
                exc_holder = []

                def _scrape():
                    try:
                        jobs = scraper.search(
                            query=query,
                            location=search_cfg.get("locations", ["United States"])[0],
                            **_get_scraper_kwargs(search_cfg, scraper.name, None),
                        )
                        result_holder.extend(jobs)
                    except Exception as e:
                        exc_holder.append(e)

                t = threading.Thread(target=_scrape, daemon=True)
                t.start()
                t.join(timeout=60)
                if t.is_alive():
                    continue
                if exc_holder:
                    continue
                all_collected.extend([j.to_dict() for j in result_holder])
            except Exception:
                continue

    if not all_collected:
        return "\u26a0 No jobs found across any source."

    all_collected = deduplicate_jobs(all_collected)
    enrich_sponsorship(all_collected)

    user_level, user_years = user_level_from_profile(profile)
    enrich_seniority(all_collected, user_level=user_level, user_years=user_years)

    all_collected = [
        j for j in all_collected
        if not is_out_of_range(
            j.get("seniority_level", "mid"),
            j.get("required_years"),
            user_level=user_level,
            user_years=user_years,
        )
    ]

    for job in all_collected:
        job["match_score"] = compute_match_score(
            job["title"], job.get("description", ""),
            job.get("location"), job.get("sponsorship_status", "unknown"),
            profile,
        )
        if job.get("seniority_penalty", 0) < 0:
            job["match_score"] = apply_seniority_penalty(
                job["match_score"], job["seniority_penalty"]
            )

    from src.tracker.db import insert_jobs_batch, update_application_status, generate_job_id
    total, new = insert_jobs_batch(all_collected)

    promoted = 0
    for job in all_collected:
        if not job.get("_is_new"):
            continue
        if job.get("match_score", 0) >= 40:
            jid = job.get("id") or generate_job_id(
                job.get("title", ""), job.get("company", ""), job.get("url", "")
            )
            try:
                update_application_status(jid, "pending_review", source="auto_scan")
                promoted += 1
            except Exception:
                pass

    from src.tracker.excel_tracker import export_jobs_to_excel
    export_jobs_to_excel(get_all_jobs(limit=1000))

    sponsors = sum(1 for j in all_collected if j.get("sponsorship_status") == "sponsor_likely")
    entry_mid = sum(1 for j in all_collected if j.get("seniority_level") in ("entry", "mid"))
    return (
        f"\u2705 **Scan complete!**\n"
        f"Found **{total}** jobs (**{new}** new)\n"
        f"Entry/Mid level: **{entry_mid}** | Sponsor likely: **{sponsors}**\n"
        f"Pending review: **{promoted}**"
    )


@tree.command(name="email_check", description="Check Gmail for application status updates")
async def cmd_email_check(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        result = await asyncio.to_thread(_run_email_check)
        await interaction.followup.send(result)
    except Exception as e:
        await interaction.followup.send(f"\u274c Email check error: {e}")


def _run_email_check() -> str:
    try:
        from src.email.gmail_auth import get_gmail_service
        from src.email.gmail_monitor import poll_inbox
        from src.tracker.db import get_jobs_by_filters

        creds_path = SECRETS.get("gmail_credentials_path", "config/credentials.json")
        service = get_gmail_service(creds_path)
        applied_jobs = get_jobs_by_filters(status="applied", limit=200)
        results = poll_inbox(service, applied_jobs, auto_update_db=True)

        if not results:
            return "\U0001f4ec No new application emails found."

        updates = [r for r in results if r.get("matched_job_id")]
        return (
            f"\U0001f4ec Processed **{len(results)}** emails, "
            f"**{len(updates)}** matched to jobs."
        )
    except Exception as e:
        return f"\u26a0 Gmail not configured or error: {e}"


async def _run_tracker_export(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        from src.tracker.excel_tracker import export_jobs_to_excel, TRACKER_PATH

        export_jobs_to_excel(get_all_jobs(limit=10000))
        if not TRACKER_PATH.exists():
            await interaction.followup.send("Export failed — tracker file was not created.", ephemeral=True)
            return
        size = TRACKER_PATH.stat().st_size
        if size > 24 * 1024 * 1024:
            await interaction.followup.send(
                f"Tracker is too large to attach ({size // (1024 * 1024)} MB). "
                f"Open on disk: `{TRACKER_PATH}`",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            content=(
                "**tracker.xlsx** — **Applications** (all jobs in your queue), **Applied** "
                "(submitted applications only, synced when you mark applied), **Stats**."
            ),
            file=discord.File(TRACKER_PATH, filename="tracker.xlsx"),
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"\u274c Error: {e}", ephemeral=True)


@tree.command(name="tracker", description="Download Excel job tracker (refreshed from your database)")
async def cmd_tracker(interaction: discord.Interaction):
    await _run_tracker_export(interaction)


@tree.command(name="track", description="Alias for /tracker — download Excel job tracker")
async def cmd_track(interaction: discord.Interaction):
    await _run_tracker_export(interaction)


# ── Chart Commands ──────────────────────────────────────────

@tree.command(name="chart", description="Generate a visual chart")
@app_commands.describe(chart_type="Type of chart to generate")
@app_commands.choices(chart_type=[
    app_commands.Choice(name="Weekly activity", value="weekly"),
    app_commands.Choice(name="Sources breakdown", value="sources"),
    app_commands.Choice(name="Score distribution", value="scores"),
    app_commands.Choice(name="Application funnel", value="funnel"),
    app_commands.Choice(name="Seniority levels", value="seniority"),
])
async def cmd_chart(interaction: discord.Interaction, chart_type: app_commands.Choice[str]):
    await interaction.response.defer()
    try:
        stats = get_detailed_stats()

        if chart_type.value == "weekly":
            daily = get_daily_stats_from_db()
            buf = chart_weekly(daily)
        elif chart_type.value == "sources":
            buf = chart_sources(stats.get("by_source", {}))
        elif chart_type.value == "scores":
            conn = get_connection()
            rows = conn.execute("SELECT match_score FROM jobs WHERE match_score > 0").fetchall()
            conn.close()
            buf = chart_scores([r[0] for r in rows])
        elif chart_type.value == "funnel":
            buf = chart_funnel(stats)
        elif chart_type.value == "seniority":
            buf = chart_seniority(stats)
        else:
            await interaction.followup.send("Unknown chart type.")
            return

        file = discord.File(buf, filename=f"{chart_type.value}_chart.png")
        await interaction.followup.send(file=file)
    except Exception as e:
        await interaction.followup.send(f"\u274c Chart error: {e}")


# ── LinkedIn Content Commands ───────────────────────────────

@tree.command(name="linkedin_post", description="Generate a LinkedIn post draft")
@app_commands.describe(topic="Topic or project to write about")
async def cmd_linkedin_post(interaction: discord.Interaction, topic: str):
    await interaction.response.defer()
    try:
        from src.linkedin.content_generator import generate_post
        post = await asyncio.to_thread(generate_post, topic, load_profile())
        post = (post or "No content generated.")
        msg = f"**LinkedIn Post Draft:**\n```\n{post}\n```"
        if len(msg) > 2000:
            msg = msg[:1997] + "```"
        await interaction.followup.send(msg)
    except Exception as e:
        await interaction.followup.send(f"\u274c Error: {e}")


@tree.command(name="linkedin_message", description="Generate a recruiter outreach message")
@app_commands.describe(company="Target company or role")
async def cmd_linkedin_message(interaction: discord.Interaction, company: str):
    await interaction.response.defer()
    try:
        from src.linkedin.content_generator import generate_recruiter_message
        msg = await asyncio.to_thread(generate_recruiter_message, company, load_profile())
        msg = (msg or "No content generated.")
        text = f"**Recruiter Message Draft:**\n```\n{msg}\n```"
        if len(text) > 2000:
            text = text[:1997] + "```"
        await interaction.followup.send(text)
    except Exception as e:
        await interaction.followup.send(f"\u274c Error: {e}")


@tree.command(name="linkedin_profile", description="Get LinkedIn profile optimization suggestions")
async def cmd_linkedin_profile(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        from src.linkedin.content_generator import optimize_profile
        suggestions = await asyncio.to_thread(optimize_profile, load_profile())
        if len(suggestions) > 2000:
            suggestions = suggestions[:1997] + "..."
        await interaction.followup.send(f"**Profile Optimization:**\n{suggestions}")
    except Exception as e:
        await interaction.followup.send(f"\u274c Error: {e}")


# ── Natural Language Query ──────────────────────────────────

@tree.command(name="ask", description="Ask a natural language question about your job search")
@app_commands.describe(question="Your question (e.g., 'show me remote QA jobs with sponsorship')")
async def cmd_ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    try:
        result = await asyncio.to_thread(_nl_query, question)
        if len(result) > 2000:
            result = result[:1997] + "..."
        await interaction.followup.send(result)
    except Exception as e:
        await interaction.followup.send(f"\u274c Error: {e}")


def _nl_query(question: str) -> str:
    """Use LLM to interpret a natural language question about job data."""
    from src.utils.llm_provider import create_llm_client

    secrets = load_config()
    client = create_llm_client(secrets)
    if not client:
        return (
            "\u26a0 No LLM available. Install **Ollama** (free) from https://ollama.ai, run `ollama pull llama3.2`, "
            "or set `openai_api_key` in secrets.yaml. See `secrets.template.yaml`."
        )
    stats = get_detailed_stats()

    prompt = (
        "You are a job search assistant. The user has a SQLite database with job listings.\n"
        "Available columns: id, title, company, location, remote_type, description, "
        "match_score, sponsorship_status, seniority_level, required_years, "
        "application_status, source, date_found, date_applied.\n"
        f"Current stats: {stats}\n\n"
        f"User question: {question}\n\n"
        "Generate a SQL query to answer this (table name is 'jobs'). "
        "Return ONLY the SQL query, no explanation."
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Return only a SELECT SQL query. No markdown, no explanation."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=200,
    )

    sql = response.choices[0].message.content.strip()
    if sql.startswith("```"):
        sql = sql.split("\n", 1)[1] if "\n" in sql else sql[3:]
        sql = sql.rsplit("```", 1)[0].strip()

    if not sql.upper().startswith("SELECT"):
        return f"\u26a0 LLM returned non-SELECT query. Aborting for safety.\nGenerated: `{sql}`"

    conn = get_connection()
    try:
        rows = conn.execute(sql).fetchall()
    except Exception as e:
        conn.close()
        return f"\u26a0 SQL error: {e}\nQuery: `{sql}`"
    conn.close()

    if not rows:
        return f"No results found.\nQuery: `{sql}`"

    lines = []
    cols = rows[0].keys() if hasattr(rows[0], "keys") else range(len(rows[0]))
    for row in rows[:20]:
        d = dict(row) if hasattr(row, "keys") else {str(i): v for i, v in enumerate(row)}
        if "title" in d and "company" in d:
            line = f"**{d.get('company', '')}** - {d.get('title', '')}"
            if "match_score" in d:
                line += f" | Score: {d['match_score']:.0f}"
            if "application_status" in d:
                line += f" | `{d['application_status']}`"
            lines.append(line)
        else:
            lines.append(" | ".join(f"{k}: {v}" for k, v in list(d.items())[:5]))

    header = f"**Results ({len(rows)} rows):**\n" if len(rows) <= 20 else f"**Results (showing 20/{len(rows)}):**\n"
    return header + "\n".join(lines)


# ── Accountability Commands ──────────────────────────────────

@tree.command(name="today", description="Today's application progress vs your daily goal")
async def cmd_today(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        from src.tracker.db import get_connection, count_applied_between_days
        from src.utils.schedule import (
            coerce_schedule,
            window_status_message,
            user_local_day_key,
            user_calendar_week_bounds,
            effective_daily_goal,
            suggested_app_plan_today,
            format_strategy_blurb,
        )
        from src.discord import voice as helix_voice

        profile = load_profile()
        schedule = coerce_schedule(profile)
        daily_goal = effective_daily_goal(profile, schedule)
        day_key = user_local_day_key(schedule)

        conn = get_connection()
        logged_today = conn.execute(
            """SELECT COUNT(DISTINCT job_id) FROM status_history
               WHERE new_status='applied'
               AND substr(changed_at, 1, 10) = ?""",
            (day_key,),
        ).fetchone()[0]
        from_jobs = conn.execute(
            """SELECT COUNT(*) FROM jobs
               WHERE application_status='applied'
               AND date_applied IS NOT NULL
               AND substr(date_applied, 1, 10) = ?""",
            (day_key,),
        ).fetchone()[0]
        conn.close()

        count = max(logged_today, from_jobs)
        w0, w1 = user_calendar_week_bounds(schedule)
        week_applied = count_applied_between_days(w0, w1)
        plan = suggested_app_plan_today(
            profile,
            schedule,
            applied_today_count=count,
            applied_this_week_count=week_applied,
        )
        plan_blurb = format_strategy_blurb(plan)

        pct = min(int((count / max(daily_goal, 1)) * 100), 100)
        bar_filled = int(pct / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)

        status_line = window_status_message(schedule)

        color = discord.Color.green() if count >= daily_goal else discord.Color.gold()
        embed = discord.Embed(title="Today's progress", color=color)
        embed.add_field(name="Applied", value=f"**{count}** / {daily_goal}", inline=True)
        embed.add_field(name="Progress", value=f"`{bar}` {pct}%", inline=True)
        embed.add_field(name="Schedule", value=status_line, inline=False)
        embed.add_field(
            name="Today's plan",
            value=plan_blurb[:1024] if plan_blurb else "(no windows today)",
            inline=False,
        )
        if count >= daily_goal:
            embed.set_footer(text=helix_voice.FOOTER_GOAL_HIT)
        else:
            remaining = daily_goal - count
            embed.set_footer(text=f"{remaining} left to hit your goal — {helix_voice.FOOTER_REVIEW}")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}")


@tree.command(
    name="myday",
    description="Tell Helix your real schedule for today (overrides profile windows for today only)",
)
@app_commands.describe(
    description="Describe availability and blocks (gym, office). Leave empty to open a form.",
)
async def cmd_myday(interaction: discord.Interaction, description: str = None):
    text = (description or "").strip()
    if text:
        from src.discord.myday import complete_myday

        await complete_myday(interaction, text)
        return
    await interaction.response.send_modal(MyDayModal())


@tree.command(
    name="myday_clear",
    description="Remove today's /myday override and use your profile apply windows again",
)
async def cmd_myday_clear(interaction: discord.Interaction):
    from src.tracker.db import clear_daily_schedule_override
    from src.utils.schedule import coerce_schedule, user_local_day_key

    profile = load_profile()
    sched = coerce_schedule(profile)
    clear_daily_schedule_override(user_local_day_key(sched))
    await interaction.response.send_message(
        "\u2705 Cleared today's schedule override. Your default weekly profile windows apply again.",
        ephemeral=True,
    )


@tree.command(
    name="schedule",
    description="Your apply windows and when digests / scans run (uses profile timezone)",
)
async def cmd_schedule(interaction: discord.Interaction):
    from src.utils.schedule import coerce_schedule, describe_next_events

    profile = load_profile()
    sched = coerce_schedule(profile)
    embed = discord.Embed(
        title="Your Helix schedule",
        description=describe_next_events(sched),
        color=0x7289DA,
    )
    embed.set_footer(
        text="Digests align with first/last apply window today. "
        "Widen notification_tolerance_minutes in profile if a digest ever misses after a restart."
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(
    name="strategy",
    description="Application strategy for today: time budget, per-window targets, weekly progress",
)
async def cmd_strategy(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        from src.tracker.db import get_connection, count_applied_between_days
        from src.utils.schedule import (
            coerce_schedule,
            user_local_day_key,
            user_calendar_week_bounds,
            suggested_app_plan_today,
            format_strategy_discord_block,
        )

        profile = load_profile()
        sched = coerce_schedule(profile)
        day_key = user_local_day_key(sched)
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
            title="Helix application strategy",
            description=body[:4096],
            color=0x7289DA,
        )
        embed.set_footer(text="Tune schedule and goals in config/profile.yaml")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


@tree.command(name="follow_up", description="Jobs applied 5–14 days ago with no update — time to follow up")
async def cmd_follow_up(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        from src.tracker.db import get_connection
        conn = get_connection()
        rows = conn.execute(
            """SELECT j.id, j.title, j.company, j.url, sh.changed_at
               FROM jobs j
               JOIN status_history sh ON sh.job_id = j.id
               WHERE sh.new_status = 'applied'
               AND j.application_status = 'applied'
               AND date(sh.changed_at) <= date('now', '-5 days')
               AND date(sh.changed_at) >= date('now', '-14 days')
               ORDER BY sh.changed_at ASC
               LIMIT 10"""
        ).fetchall()
        conn.close()

        if not rows:
            await interaction.followup.send(
                "✅ No follow-ups needed — all recent applications are within 5 days or already have updates."
            )
            return

        embed = discord.Embed(
            title="Follow-up Radar",
            description="These applications are 5-14 days old with no status update.",
            color=discord.Color.orange(),
        )
        for r in rows:
            applied_on = r["changed_at"][:10] if r["changed_at"] else "?"
            embed.add_field(
                name=f"{r['company']} — {r['title']}",
                value=f"Applied: {applied_on} · [Job link]({r['url']}) · ID: `{r['id'][:12]}`",
                inline=False,
            )
        embed.set_footer(text="Use /set_status <job_id> <status> to update after following up.")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}")


@tree.command(name="goal", description="View or update your daily application target")
@app_commands.describe(number="Set a new daily goal (leave empty to just see current goal)")
async def cmd_goal(interaction: discord.Interaction, number: int = None):
    profile = load_profile()
    current = profile.get("daily_application_target", 5)
    if number is None:
        await interaction.response.send_message(
            f"🎯 Your daily application goal is **{current}**.\n"
            "Use `/goal <number>` to change it.",
            ephemeral=True,
        )
        return

    if number < 1 or number > 50:
        await interaction.response.send_message(
            "Please choose a goal between 1 and 50.", ephemeral=True
        )
        return

    try:
        root = ROOT
        profile_path = root / "config" / "profile.yaml"
        with open(profile_path, "r", encoding="utf-8") as f:
            raw = f.read()
        import re
        raw = re.sub(
            r"^daily_application_target:\s*\d+",
            f"daily_application_target: {number}",
            raw,
            flags=re.MULTILINE,
        )
        with open(profile_path, "w", encoding="utf-8") as f:
            f.write(raw)
        await interaction.response.send_message(
            f"✅ Daily goal updated to **{number}** applications/day. Let's go!",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.response.send_message(f"Error saving goal: {e}", ephemeral=True)


@tree.command(name="note", description="Add a note to a job application")
@app_commands.describe(
    job_id="The job ID (first 12+ chars)",
    text="Your note — e.g. 'Recruiter called, follow up Friday'",
)
async def cmd_note(interaction: discord.Interaction, job_id: str, text: str):
    try:
        from src.tracker.db import get_job, get_connection
        # Fuzzy ID match
        conn = get_connection()
        matches = conn.execute(
            "SELECT id FROM jobs WHERE id LIKE ? LIMIT 1", (f"{job_id}%",)
        ).fetchall()
        conn.close()
        if not matches:
            await interaction.response.send_message(f"❌ No job found with ID starting `{job_id}`.", ephemeral=True)
            return
        full_id = matches[0]["id"]
        job = get_job(full_id)

        conn2 = get_connection()
        conn2.execute(
            """INSERT INTO status_history (job_id, old_status, new_status, note, changed_at)
               VALUES (?, ?, ?, ?, ?)""",
            (full_id, job.get("application_status", ""), "note", text, datetime.now().isoformat()),
        )
        conn2.commit()
        conn2.close()
        await interaction.response.send_message(
            f"📝 Note saved for **{job.get('title')} @ {job.get('company')}**:\n> {text}",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)


# ── Scheduled Tasks (profile timezone + apply_windows) ──────

async def _send_morning_digest(channel: discord.abc.Messageable, profile: dict, sched: dict, day_key: str) -> None:
    from src.tracker.db import count_applied_between_days, get_daily_schedule_override
    from src.utils.schedule import (
        window_status_message,
        is_rest_day,
        user_yesterday_key,
        user_calendar_week_bounds,
        effective_daily_goal,
        suggested_app_plan_today,
        format_strategy_blurb,
    )
    from src.discord import voice as helix_voice

    stats = get_detailed_stats()
    pending = stats.get("pending_review", 0)
    daily_goal = effective_daily_goal(profile, sched)
    yesterday_key = user_yesterday_key(sched)
    try:
        conn = get_connection()
        applied_yesterday = conn.execute(
            """SELECT COUNT(DISTINCT job_id) FROM status_history
               WHERE new_status='applied' AND substr(changed_at, 1, 10) = ?""",
            (yesterday_key,),
        ).fetchone()[0]
        follow_ups_due = conn.execute(
            """SELECT COUNT(*) FROM jobs
               WHERE application_status='applied'
               AND date(date_found) <= date('now', '-7 days')
               AND date(date_found) >= date('now', '-14 days')"""
        ).fetchone()[0]
        applied_today = conn.execute(
            """SELECT COUNT(DISTINCT job_id) FROM status_history
               WHERE new_status='applied' AND substr(changed_at, 1, 10) = ?""",
            (day_key,),
        ).fetchone()[0]
        conn.close()
    except Exception:
        applied_yesterday = 0
        follow_ups_due = 0
        applied_today = 0

    w0, w1 = user_calendar_week_bounds(sched)
    week_applied = count_applied_between_days(w0, w1)
    plan = suggested_app_plan_today(
        profile,
        sched,
        applied_today_count=applied_today,
        applied_this_week_count=week_applied,
    )
    strategy_blurb = format_strategy_blurb(plan, max_lines=5)

    top_jobs = get_pending_review_jobs(limit=5)
    is_rest = is_rest_day(sched)
    title = (
        f"\u2600\ufe0f {helix_voice.MORNING_TITLE_REST}"
        if is_rest
        else f"\u2600\ufe0f {helix_voice.MORNING_TITLE_ACTIVE}"
    )
    embed = discord.Embed(title=title, color=discord.Color.gold(), timestamp=datetime.now())
    embed.add_field(name="Daily goal", value=f"**{daily_goal}** applications today", inline=True)
    embed.add_field(name="Yesterday", value=f"Applied **{applied_yesterday}**", inline=True)
    embed.add_field(name="Pending review", value=str(pending), inline=True)
    embed.add_field(name="Total applied", value=str(stats.get("applied", 0)), inline=True)
    embed.add_field(name="Interviews", value=str(stats.get("interview", 0)), inline=True)
    embed.add_field(name="Offers", value=str(stats.get("offer", 0)), inline=True)

    if is_rest:
        embed.add_field(name="Schedule", value="Rest day — digests and scans are paused today.", inline=False)
    else:
        embed.add_field(name="Schedule", value=window_status_message(sched), inline=False)

    if get_daily_schedule_override(day_key) is None:
        embed.add_field(
            name="What does your schedule look like today?",
            value="Use `/myday` with your real availability (office, gym, meetings). Helix will align today's targets.",
            inline=False,
        )

    if strategy_blurb:
        embed.add_field(
            name="Today's strategy",
            value=strategy_blurb[:1024],
            inline=False,
        )

    if follow_ups_due > 0:
        embed.add_field(
            name="Follow-ups",
            value=f"**{follow_ups_due}** application(s) look stale. `/follow_up` for the list.",
            inline=False,
        )

    if top_jobs and not is_rest:
        lines = "\n".join(
            f"`{j['id'][:10]}` **{j['company']}** — {j['title']} · {j.get('match_score', 0):.0f}"
            for j in top_jobs[:3]
        )
        embed.add_field(name="Top jobs to review", value=lines, inline=False)

    embed.set_footer(text=helix_voice.morning_footer(pending, follow_ups_due))
    await channel.send(embed=embed)


async def _send_evening_summary(
    channel: discord.abc.Messageable, profile: dict, sched: dict, day_key: str
) -> None:
    from src.utils.schedule import effective_daily_goal
    from src.discord import voice as helix_voice

    stats = get_detailed_stats()
    daily_goal = effective_daily_goal(profile, sched)
    try:
        conn = get_connection()
        applied_today = conn.execute(
            """SELECT COUNT(DISTINCT job_id) FROM status_history
               WHERE new_status='applied' AND substr(changed_at, 1, 10) = ?""",
            (day_key,),
        ).fetchone()[0]
        follow_ups_due = conn.execute(
            """SELECT COUNT(*) FROM jobs
               WHERE application_status='applied'
               AND date(date_found) <= date('now', '-5 days')
               AND date(date_found) >= date('now', '-14 days')"""
        ).fetchone()[0]
        conn.close()
    except Exception:
        applied_today = 0
        follow_ups_due = 0

    pct = min(int((applied_today / max(daily_goal, 1)) * 100), 100)
    bar_filled = int(pct / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    embed = discord.Embed(
        title=f"\U0001f319 {helix_voice.EVENING_TITLE}",
        description="Quick read on how today went:",
        color=discord.Color.blurple(),
        timestamp=datetime.now(),
    )
    embed.add_field(name="Applied today", value=f"**{applied_today}** / {daily_goal}", inline=True)
    embed.add_field(name="Goal progress", value=f"`{bar}` {pct}%", inline=True)
    embed.add_field(name="Pending review", value=str(stats.get("pending_review", 0)), inline=True)
    embed.add_field(name="Interviews", value=str(stats.get("interview", 0)), inline=True)
    embed.add_field(name="Offers", value=str(stats.get("offer", 0)), inline=True)
    if follow_ups_due > 0:
        embed.add_field(
            name="Follow-ups",
            value=f"{follow_ups_due} application(s) may need a nudge. `/follow_up`.",
            inline=False,
        )
    embed.set_footer(text=helix_voice.evening_footer(applied_today, daily_goal))
    await channel.send(embed=embed)


async def _send_follow_up_ping(channel: discord.abc.Messageable) -> None:
    from src.discord import voice as helix_voice

    try:
        conn = get_connection()
        rows = conn.execute(
            """SELECT j.id, j.title, j.company, sh.changed_at
               FROM jobs j
               JOIN status_history sh ON sh.job_id = j.id
               WHERE sh.new_status = 'applied'
               AND j.application_status = 'applied'
               AND date(sh.changed_at) <= date('now', '-7 days')
               AND date(sh.changed_at) >= date('now', '-14 days')
               ORDER BY sh.changed_at ASC
               LIMIT 5"""
        ).fetchall()
        conn.close()
        if rows:
            lines = "\n".join(
                f"- {r['company']} — {r['title']} (applied {r['changed_at'][:10]})" for r in rows
            )
            await channel.send(
                f"**{helix_voice.FOLLOW_UP_INTRO}**\n{lines}\n\n`/follow_up` for the full list."
            )
    except Exception:
        pass


@tasks.loop(minutes=3)
async def schedule_tick():
    """
    Run digest, scan, and follow-up hooks at times derived from profile.schedule
    (user timezone + apply_windows). De-duplicated per calendar day via schedule_events.
    """
    from src.utils.schedule import (
        coerce_schedule,
        user_local_day_key,
        morning_digest_local_datetime,
        evening_summary_local_datetime,
        auto_scan_local_datetimes,
        follow_up_check_local_datetime,
        is_within_trigger_window,
        notification_tolerance_minutes,
    )

    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if not channel:
        return

    profile = load_profile()
    sched = coerce_schedule(profile)
    day_key = user_local_day_key(sched)
    tol = notification_tolerance_minutes(sched)

    if is_within_trigger_window(
        sched, morning_digest_local_datetime(sched), tol
    ) and try_claim_schedule_event(day_key, "morning_digest"):
        await _send_morning_digest(channel, profile, sched, day_key)

    if is_within_trigger_window(
        sched, evening_summary_local_datetime(sched), tol
    ) and try_claim_schedule_event(day_key, "evening_summary"):
        await _send_evening_summary(channel, profile, sched, day_key)

    for i, scan_t in enumerate(auto_scan_local_datetimes(sched)):
        if is_within_trigger_window(sched, scan_t, tol) and try_claim_schedule_event(
            day_key, f"auto_scan_{i}"
        ):
            if _scan_lock.locked():
                continue
            async with _scan_lock:
                try:
                    from src.discord import voice as helix_voice

                    result = await asyncio.to_thread(_run_scan, None)
                    if "0 new" not in result:
                        await channel.send(f"\U0001f504 **{helix_voice.SCAN_OK}**\n{result}")
                except Exception as e:
                    from src.discord import voice as helix_voice

                    await channel.send(f"{helix_voice.SCAN_FAIL_PREFIX} `{e}`")

    if is_within_trigger_window(
        sched, follow_up_check_local_datetime(sched), tol
    ) and try_claim_schedule_event(day_key, "follow_up_check"):
        await _send_follow_up_ping(channel)


@schedule_tick.before_loop
async def _before_schedule_tick():
    await bot.wait_until_ready()


def _is_two_hour_apply_reminder(message: str) -> bool:
    """Apply-card 'Remind me in 2h' pings must fire even when reminders_only_in_apply_windows is on."""
    return "\u23f0 **Reminder:** Time to apply" in (message or "")


@tasks.loop(minutes=5)
async def check_reminders():
    """Deliver due reminders; apply-window gate skips generic pings but not 2h apply reminders."""
    try:
        from src.tracker.db import get_due_reminders, mark_reminder_fired
        from src.utils.schedule import coerce_schedule, is_apply_window, reminders_only_in_apply_windows

        profile = load_profile()
        sched = coerce_schedule(profile)
        gate = reminders_only_in_apply_windows(sched) and not is_apply_window(sched)

        due = get_due_reminders()
        for reminder in due:
            if gate and not _is_two_hour_apply_reminder(reminder.get("message", "")):
                continue
            try:
                cid = int(reminder["channel_id"])
                ch = bot.get_channel(cid)
                if ch is None:
                    ch = await bot.fetch_channel(cid)
                if ch:
                    await ch.send(reminder["message"])
                    mark_reminder_fired(reminder["id"])
            except Exception:
                pass
    except Exception:
        pass


# ── Help & Reference ────────────────────────────────────────

COMMAND_CATEGORIES = {
    "Job Review": {
        "/review": "Review the next pending job — approve to get apply card with direct link",
        "/review_batch [count]": "Review multiple jobs at once",
        "/review_count": "How many jobs are pending review",
    },
    "Job Discovery": {
        "/scan [source]": "Trigger a job scan (all sources or specific)",
        "/jobs [status] [min_score] [source]": "List jobs with filters",
        "/job <job_id>": "Show full detail for a specific job",
        "/fitness <job_id>": "Detailed profile fitness + resume tips for a job",
        "/ask <question>": "Natural-language query about your job search",
    },
    "Accountability": {
        "/today": "Today's application progress vs your daily goal",
        "/myday [description]": "Set today's real schedule in chat (overrides profile for today); omit text for a form",
        "/myday_clear": "Remove today's /myday override",
        "/schedule": "Your apply windows and when digests/scans run (profile timezone)",
        "/strategy": "Time budget and per-window application targets (schedule + goals)",
        "/follow_up": "Jobs applied 5-14 days ago with no status update",
        "/goal [number]": "View or update your daily application target",
        "/note <job_id> <text>": "Add a note to a job application",
    },
    "Applications": {
        "/board": "Application status board overview",
        "/status <company>": "Check application status for a company",
        "/set_status <job_id> <status>": "Manually change a job's status",
        "/tracker": "Download Excel tracker: Applications (queue), Applied (submissions), Stats",
        "/track": "Same as /tracker",
    },
    "Analytics": {
        "/stats": "Show job search statistics",
        "/chart <type>": "Generate a visual chart (weekly, sources, scores, funnel, seniority)",
        "/profile_check": "Check profile completeness and get improvement tips",
    },
    "Email": {
        "/email_check": "Check Gmail for application status updates (needs config/credentials.json + token)",
    },
    "LinkedIn": {
        "/linkedin_post <topic>": "Generate a LinkedIn post draft",
        "/linkedin_message <company>": "Generate a recruiter outreach message",
        "/linkedin_profile": "Get LinkedIn profile optimization suggestions",
    },
    "Helix Coach (channel)": {
        "#helix-coach": (
            "Paste job URLs for viability, keyword match, profile fitness, resume tips; "
            "or ask for cover letters, LinkedIn recruiter messages, resume help, and general Q&A. "
            "Auto-detected when a channel named `helix-coach` exists; optional `helix_coach_channel_id` in secrets overrides."
        ),
    },
}


def _build_help_embeds(detailed: str = None) -> list[discord.Embed]:
    """Build one or more embeds listing all commands by category."""
    if detailed and detailed in COMMAND_CATEGORIES:
        cat = detailed
        cmds = COMMAND_CATEGORIES[cat]
        embed = discord.Embed(title=f"Helix \u2014 {cat}", color=0x7289DA)
        for cmd, desc in cmds.items():
            embed.add_field(name=cmd, value=desc, inline=False)
        embed.set_footer(text="Use /help to see all categories")
        return [embed]

    embed = discord.Embed(
        title="Helix Command Reference",
        description="All available slash commands, grouped by category.",
        color=0x7289DA,
    )
    for cat, cmds in COMMAND_CATEGORIES.items():
        lines = "\n".join(f"`{c}` \u2014 {d}" for c, d in cmds.items())
        embed.add_field(name=cat, value=lines, inline=False)
    embed.set_footer(text="Use /help [category] for parameter details")
    return [embed]


@tree.command(name="help", description="Show all Helix commands")
@app_commands.describe(category="Filter to a specific category")
@app_commands.choices(category=[
    app_commands.Choice(name=cat, value=cat) for cat in COMMAND_CATEGORIES
])
async def cmd_help(interaction: discord.Interaction, category: str = None):
    embeds = _build_help_embeds(detailed=category)
    await interaction.response.send_message(embeds=embeds, ephemeral=True)


@tree.command(name="pin_commands", description="Post command reference (pin it for quick access)")
async def cmd_pin_commands(interaction: discord.Interaction):
    embeds = _build_help_embeds()
    await interaction.response.send_message(embeds=embeds)


# ── Bot Events ──────────────────────────────────────────────

def _sync_guild_object() -> discord.Object | None:
    """If ``discord_guild_id`` is set in secrets, sync commands to that guild only (updates in seconds)."""
    raw = SECRETS.get("discord_guild_id")
    if raw is None or raw == "":
        return None
    try:
        gid = int(raw)
    except (TypeError, ValueError):
        return None
    if gid == 0:
        return None
    return discord.Object(id=gid)


@bot.event
async def on_ready():
    global NOTIFICATION_CHANNEL_ID, COACH_CHANNEL_ID, _tasks_started
    try:
        print(f"Helix connected as {bot.user} – syncing commands...")
        guild_obj = _sync_guild_object()
        if guild_obj:
            synced = await tree.sync(guild=guild_obj)
            print(f"Helix online | Synced {len(synced)} slash command(s) to guild {guild_obj.id} (instant)")
        else:
            await tree.sync()
            print("Helix online | Synced slash commands globally (Discord may take up to ~1h to show new commands)")
    except Exception as exc:
        print(f"Command sync failed: {exc}")

    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.name in ("helix-jobs", "job-feed", "daily-digest", "general") and not NOTIFICATION_CHANNEL_ID:
                NOTIFICATION_CHANNEL_ID = channel.id
                print(f"Notification channel: #{channel.name} ({channel.id})")
            if channel.name == "helix-coach" and not COACH_CHANNEL_ID:
                COACH_CHANNEL_ID = channel.id
                print(f"Helix Coach channel: #{channel.name} ({channel.id})")

    if not _tasks_started:
        _tasks_started = True
        try:
            schedule_tick.start()
            update_presence.start()
            check_reminders.start()
        except Exception as exc:
            print(f"Scheduled task start error: {exc}")

    try:
        stats = get_detailed_stats()
        activity = f"Tracking {stats['total']} jobs"
        await bot.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name=activity)
        )
    except Exception as exc:
        print(f"Presence update error: {exc}")

    # Profile completeness check on startup
    try:
        from src.matching.profile_validator import validate_profile, profile_completeness_score
        profile = load_profile()
        warnings = validate_profile(profile)
        score = profile_completeness_score(profile)
        if warnings:
            print(f"Profile completeness: {score}/100 — {len(warnings)} warning(s)")
            for w in warnings[:3]:
                print(f"  • {w}")
        else:
            print(f"Profile completeness: {score}/100 — all sections complete")
    except Exception as exc:
        print(f"Profile validation error: {exc}")

    try:
        from src.utils.schedule import coerce_schedule, describe_next_events

        sched = coerce_schedule(load_profile())
        print("Schedule (profile timezone):")
        for line in describe_next_events(sched).split("\n"):
            print(f"  {line}")
    except Exception as exc:
        print(f"Schedule preview error: {exc}")

    print("Helix is ready.")

    coach_id = _coach_channel_id()
    if coach_id:
        print(f"Helix Coach channel enabled (id={coach_id}) — natural-language job URL + career Q&A.")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    cid = _coach_channel_id()
    if not cid or message.channel.id != cid:
        return
    from src.discord.coach_channel import process_coach_message

    async with message.channel.typing():
        try:
            chunks = await asyncio.to_thread(
                process_coach_message,
                message.content,
                message.channel.id,
                load_profile(),
                load_config(),
            )
        except Exception as exc:
            chunks = [f"\u274c {exc}"]
    for chunk in chunks:
        if chunk:
            await message.channel.send(chunk)


@tasks.loop(minutes=5)
async def update_presence():
    stats = get_detailed_stats()
    pending = stats.get("pending_review", 0)
    activity = f"{stats['total']} jobs | {pending} pending"
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name=activity)
    )


# ── Main ────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        print("ERROR: discord_bot_token not set in config/secrets.yaml")
        print("1. Go to https://discord.com/developers/applications")
        print("2. Create application 'Helix' > Bot > Copy token")
        print("3. Add to secrets.yaml: discord_bot_token: \"your-token\"")
        sys.exit(1)

    init_db()
    print("Starting Helix...")
    bot.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
