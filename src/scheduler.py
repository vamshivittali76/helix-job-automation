"""
Task scheduler for automated periodic runs.

Schedules:
  - Job scanning at configurable intervals
  - Email monitoring at configurable intervals
  - Daily plan generation at a fixed time
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from rich.console import Console
from datetime import datetime

console = Console(force_terminal=True, highlight=False)


def create_scheduler(
    scan_interval_hours: int = 6,
    email_interval_minutes: int = 30,
    plan_time: str = "08:00",
    config: dict = None,
) -> BlockingScheduler:
    """
    Create and configure the scheduler with all jobs.

    Args:
        scan_interval_hours: Hours between job scans.
        email_interval_minutes: Minutes between email checks.
        plan_time: Time to generate daily plan (HH:MM).
        config: Full config dict with secrets, profile, search_config.
    """
    scheduler = BlockingScheduler()

    scheduler.add_job(
        func=_run_scan,
        trigger=IntervalTrigger(hours=scan_interval_hours),
        id="job_scan",
        name="Scan job boards",
        kwargs={"config": config},
        next_run_time=datetime.now(),
    )

    if config and config.get("gmail_enabled"):
        scheduler.add_job(
            func=_run_email_monitor,
            trigger=IntervalTrigger(minutes=email_interval_minutes),
            id="email_monitor",
            name="Check Gmail for updates",
            kwargs={"config": config},
        )

    plan_hour, plan_minute = plan_time.split(":")
    scheduler.add_job(
        func=_run_daily_plan,
        trigger=CronTrigger(hour=int(plan_hour), minute=int(plan_minute)),
        id="daily_plan",
        name="Generate daily application plan",
        kwargs={"config": config},
    )

    return scheduler


def _run_scan(config: dict = None):
    """Execute a job scan."""
    console.print(f"\n[cyan][{datetime.now().strftime('%H:%M:%S')}] Running scheduled scan...[/cyan]")

    try:
        from src.tracker.db import init_db, insert_jobs_batch, log_scan, get_all_jobs
        from src.matching.scorer import compute_match_score
        from src.matching.sponsorship import enrich_sponsorship
        from src.matching.dedup import deduplicate_jobs
        from src.tracker.excel_tracker import export_jobs_to_excel
        import time

        init_db()

        if not config:
            console.print("[yellow]No config provided for scan[/yellow]")
            return

        secrets = config.get("secrets", {})
        profile = config.get("profile", {})
        search_cfg = config.get("search_config", {})

        from src.cli import _build_scrapers, _get_scraper_kwargs
        scrapers = _build_scrapers(secrets, search_cfg)

        all_collected = []
        for scraper in scrapers:
            for query_cfg in search_cfg.get("search_queries", []):
                query = query_cfg.get("title", "")
                keywords = query_cfg.get("keywords", "")
                full_query = f"{query} {keywords}".strip()

                try:
                    jobs = scraper.search(
                        query=full_query,
                        location=search_cfg.get("locations", ["United States"])[0],
                        **_get_scraper_kwargs(search_cfg, scraper.name),
                    )
                    if jobs:
                        all_collected.extend([j.to_dict() for j in jobs])
                except Exception as e:
                    console.print(f"  [red]{scraper.name} error: {e}[/red]")

        if all_collected:
            all_collected = deduplicate_jobs(all_collected)
            enrich_sponsorship(all_collected)

            for job in all_collected:
                job["match_score"] = compute_match_score(
                    job["title"], job.get("description", ""),
                    job.get("location"), job.get("sponsorship_status", "unknown"),
                    profile,
                )

            total, new = insert_jobs_batch(all_collected)
            console.print(f"  Scan complete: {total} jobs, {new} new")

            export_jobs_to_excel(get_all_jobs(limit=1000))

    except Exception as e:
        console.print(f"[red]Scan error: {e}[/red]")


def _run_email_monitor(config: dict = None):
    """Execute email monitoring."""
    console.print(f"\n[cyan][{datetime.now().strftime('%H:%M:%S')}] Checking Gmail...[/cyan]")

    try:
        from src.email.gmail_auth import get_gmail_service
        from src.email.gmail_monitor import poll_inbox
        from src.tracker.db import get_jobs_by_status, update_application_status

        if not config:
            return

        secrets = config.get("secrets", {})
        creds_path = secrets.get("gmail_credentials_path", "config/credentials.json")

        service = get_gmail_service(creds_path)
        applied_jobs = get_jobs_by_status("applied")

        results = poll_inbox(service, applied_jobs, max_results=30)

        updates = 0
        for result in results:
            if result.get("error"):
                continue
            if result.get("matched_job_id") and result.get("classified_status"):
                update_application_status(
                    result["matched_job_id"],
                    result["classified_status"],
                    source="email",
                )
                updates += 1

        if updates:
            console.print(f"  [green]Updated {updates} application statuses from email[/green]")
        else:
            console.print(f"  No new status updates found")

    except Exception as e:
        console.print(f"[red]Email monitor error: {e}[/red]")


def _run_daily_plan(config: dict = None):
    """Generate the daily application plan."""
    console.print(f"\n[cyan][{datetime.now().strftime('%H:%M:%S')}] Generating daily plan...[/cyan]")

    try:
        from src.tracker.db import get_unapplied_jobs
        from src.quality.daily_planner import generate_daily_plan, get_plan_summary

        if not config:
            return

        profile = config.get("profile", {})
        target = profile.get("daily_application_target", 25)

        jobs = get_unapplied_jobs(min_score=30, limit=200)
        plan = generate_daily_plan(jobs, target_count=target)
        summary = get_plan_summary(plan)

        console.print(
            f"  Daily plan: {summary['count']} jobs | "
            f"Avg score: {summary.get('avg_score', 0):.0f} | "
            f"Sponsors: {summary.get('sponsor_likely', 0)}"
        )

    except Exception as e:
        console.print(f"[red]Daily plan error: {e}[/red]")
