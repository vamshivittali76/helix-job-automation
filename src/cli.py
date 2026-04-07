import os
import time
import sys
from pathlib import Path
import yaml
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich import box

os.environ["PYTHONIOENCODING"] = "utf-8"
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

console = Console(force_terminal=True, highlight=False)


def load_config(filename: str) -> dict:
    path = ROOT / "config" / filename
    if not path.exists():
        console.print(f"[red]Config file not found: {path}[/red]")
        raise SystemExit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_secrets() -> dict:
    return load_config("secrets.yaml")


def load_profile() -> dict:
    return load_config("profile.yaml")


def load_search_config() -> dict:
    return load_config("search_config.yaml")


@click.group()
def cli():
    """Helix -- AI-powered job search agent."""
    pass


@cli.command()
@click.option("--source", type=str, default=None,
              help="Run specific scraper (adzuna, jooble, themuse, greenhouse, lever, google_jobs, linkedin)")
@click.option("--limit", type=int, default=None, help="Max jobs per query per source")
@click.option("--llm", is_flag=True, help="Enable LLM scoring (local Ollama or OpenAI — see secrets.template.yaml)")
@click.option("--llm-top", type=int, default=40, help="How many top keyword-scored jobs to LLM-score")
def scan(source, limit, llm, llm_top):
    """Scan job boards, deduplicate, score results, and update tracker."""
    from src.tracker.db import init_db, insert_jobs_batch, log_scan, get_all_jobs, update_job
    from src.matching.scorer import compute_match_score, compute_enhanced_score, apply_seniority_penalty, apply_competition_bonus
    from src.matching.sponsorship import enrich_sponsorship
    from src.matching.dedup import deduplicate_jobs
    from src.matching.seniority import enrich_seniority, user_level_from_profile, is_out_of_range
    from src.tracker.excel_tracker import export_jobs_to_excel
    from src.matching.profile_validator import validate_profile, profile_completeness_score

    init_db()

    secrets = load_secrets()
    profile = load_profile()
    search_cfg = load_search_config()

    # Warn if profile is incomplete — affects matching quality
    profile_warnings = validate_profile(profile)
    completeness = profile_completeness_score(profile)
    if profile_warnings:
        console.print(Panel(
            "\n".join(f"[yellow]• {w}[/yellow]" for w in profile_warnings[:5])
            + (f"\n[dim]...and {len(profile_warnings) - 5} more. Run: python -m src.cli profile-check[/dim]"
               if len(profile_warnings) > 5 else "")
            + f"\n\n[dim]Profile completeness: {completeness}/100. Run: python -m src.cli profile-check[/dim]",
            title=f"[bold yellow]Profile Warnings ({len(profile_warnings)})[/bold yellow]",
            border_style="yellow",
        ))

    scrapers = _build_scrapers(secrets, search_cfg, source_filter=source)

    if not scrapers:
        console.print("[red]No scrapers configured or enabled. Check config/secrets.yaml[/red]")
        return

    all_collected: list[dict] = []
    scan_logs: list[dict] = []

    console.print(Panel.fit(
        "[bold cyan]Job Scan Starting[/bold cyan]\n"
        f"Sources: {', '.join(s.name for s in scrapers)}\n"
        f"Queries: {len(search_cfg.get('search_queries', []))}\n"
        f"LLM scoring: {'[green]ON[/green]' if llm else '[dim]OFF[/dim]'}",
        border_style="cyan",
    ))

    for scraper in scrapers:
        for query_cfg in search_cfg.get("search_queries", []):
            query = query_cfg.get("title", "")
            keywords = query_cfg.get("keywords", "")
            full_query = f"{query} {keywords}".strip()

            console.print(f"\n[bold]{scraper.name}[/bold] -> [cyan]{query}[/cyan]")

            start_time = time.time()
            try:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    transient=True,
                    console=console,
                ) as progress:
                    progress.add_task(description=f"Searching {scraper.name}...", total=None)
                    jobs = scraper.search(
                        query=full_query,
                        location=search_cfg.get("locations", ["United States"])[0],
                        **_get_scraper_kwargs(search_cfg, scraper.name, limit),
                    )
            except Exception as e:
                console.print(f"  [red]Error: {e}[/red]")
                continue

            duration = time.time() - start_time

            if not jobs:
                console.print(f"  No results ({duration:.1f}s)")
                scan_logs.append({"source": scraper.name, "query": query, "found": 0, "duration": duration})
                continue

            job_dicts = [j.to_dict() for j in jobs]
            console.print(f"  Fetched [green]{len(job_dicts)}[/green] jobs ({duration:.1f}s)")
            all_collected.extend(job_dicts)
            scan_logs.append({
                "source": scraper.name, "query": query,
                "found": len(job_dicts), "duration": duration,
            })

    if not all_collected:
        console.print("\n[yellow]No jobs found across any source.[/yellow]")
        return

    pre_dedup = len(all_collected)
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True, console=console) as progress:
        progress.add_task(description=f"Deduplicating {pre_dedup} jobs...", total=None)
        all_collected = deduplicate_jobs(all_collected)
    post_dedup = len(all_collected)
    removed = pre_dedup - post_dedup
    if removed > 0:
        console.print(f"[dim]Dedup: {pre_dedup} -> {post_dedup} ({removed} duplicates removed)[/dim]")

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True, console=console) as progress:
        progress.add_task(description="Enriching sponsorship data...", total=None)
        enrich_sponsorship(all_collected)

    user_level, user_years = user_level_from_profile(profile)
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True, console=console) as progress:
        progress.add_task(description="Analyzing seniority levels...", total=None)
        enrich_seniority(all_collected, user_level=user_level, user_years=user_years)

    before_filter = len(all_collected)
    all_collected = [
        j for j in all_collected
        if not is_out_of_range(
            j.get("seniority_level", "mid"),
            j.get("required_years"),
            user_level=user_level,
            user_years=user_years,
        )
    ]
    dropped = before_filter - len(all_collected)
    if dropped:
        console.print(f"[dim]Filtered out {dropped} jobs above your experience level[/dim]")

    for job in all_collected:
        job["match_score"] = compute_match_score(
            job_title=job["title"],
            job_description=job.get("description", ""),
            job_location=job.get("location"),
            sponsorship_status=job.get("sponsorship_status", "unknown"),
            profile=profile,
        )
        if job.get("seniority_penalty", 0) < 0:
            job["match_score"] = apply_seniority_penalty(
                job["match_score"], job["seniority_penalty"]
            )
        # Boost/penalise based on competition level scraped from LinkedIn
        if job.get("competition_level") or (job.get("raw_data") or {}).get("competition_level"):
            level = job.get("competition_level") or (job.get("raw_data") or {}).get("competition_level", "unknown")
            job["match_score"] = apply_competition_bonus(job["match_score"], level)

    all_collected.sort(key=lambda j: j.get("match_score", 0), reverse=True)

    if llm:
        llm_client = _get_llm_client(secrets)
        if llm_client:
            top_jobs = all_collected[:llm_top]
            console.print(f"\n[bold cyan]LLM scoring top {len(top_jobs)} jobs...[/bold cyan]")
            from src.matching.llm_scorer import score_jobs_batch_llm

            with Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                console=console,
            ) as progress:
                task = progress.add_task("Scoring with LLM...", total=len(top_jobs))

                def _on_progress(i, total, job, result):
                    progress.update(task, completed=i + 1)

                score_jobs_batch_llm(
                    client=llm_client,
                    jobs=top_jobs,
                    profile=profile,
                    on_progress=_on_progress,
                )

            for job in top_jobs:
                if job.get("llm_score", 0) > 0:
                    job["match_score"] = compute_enhanced_score(
                        job["match_score"], job["llm_score"]
                    )

            all_collected.sort(key=lambda j: j.get("match_score", 0), reverse=True)
            llm_scored = sum(1 for j in top_jobs if j.get("llm_score", 0) > 0)
            console.print(f"[green]LLM scored {llm_scored}/{len(top_jobs)} jobs[/green]")
        else:
            console.print(
                "[yellow]LLM scoring requested but no LLM backend is available. "
                "Install Ollama (https://ollama.ai), run `ollama pull llama3.2`, "
                "or set openai_api_key in secrets.yaml.[/yellow]"
            )

    batch_total, batch_new = insert_jobs_batch(all_collected)

    from src.tracker.db import update_application_status, generate_job_id
    review_threshold = 40
    promoted = 0
    for job in all_collected:
        if not job.get("_is_new"):
            continue
        if job.get("match_score", 0) >= review_threshold:
            job_id = job.get("id") or generate_job_id(
                job.get("title", ""), job.get("company", ""), job.get("url", "")
            )
            try:
                update_application_status(job_id, "pending_review", source="auto_scan")
                promoted += 1
            except Exception:
                pass

    for entry in scan_logs:
        entry_new = sum(1 for j in all_collected if j.get("_is_new") and j.get("source") == entry["source"])
        log_scan(entry["source"], entry["query"], entry["found"], entry_new, entry["duration"])

    sponsor_count = sum(1 for j in all_collected if j["sponsorship_status"] == "sponsor_likely")
    high_score = sum(1 for j in all_collected if j["match_score"] >= 60)

    console.print(
        f"\n[bold]Results: {batch_total} jobs, {batch_new} new[/bold] | "
        f"Score>=60: [cyan]{high_score}[/cyan] | "
        f"Sponsor likely: [yellow]{sponsor_count}[/yellow] | "
        f"Pending review: [green]{promoted}[/green]"
    )

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True, console=console) as progress:
        progress.add_task(description="Exporting to Excel...", total=None)
        all_jobs = get_all_jobs(limit=1000)
        export_jobs_to_excel(all_jobs)

    console.print(f"[green]Tracker updated:[/green] output/tracker.xlsx")


@cli.command()
@click.option("--min-score", type=float, default=0, help="Minimum match score to show")
@click.option("--limit", type=int, default=30, help="Max jobs to display")
@click.option("--sponsor-only", is_flag=True, help="Show only sponsor-likely jobs")
def review(min_score, limit, sponsor_only):
    """Review discovered jobs in a ranked table."""
    from src.tracker.db import get_unapplied_jobs

    jobs = get_unapplied_jobs(min_score=min_score, limit=limit)
    if sponsor_only:
        jobs = [j for j in jobs if j["sponsorship_status"] == "sponsor_likely"]

    if not jobs:
        console.print("[yellow]No jobs found matching criteria.[/yellow]")
        return

    has_llm = any(job.get("llm_score") for job in jobs)

    table = Table(
        title="Top Jobs (Unapplied)",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        title_style="bold cyan",
        width=120 if has_llm else 110,
        pad_edge=False,
    )
    table.add_column("#", style="dim", width=3, no_wrap=True)
    table.add_column("Score", justify="right", width=5, no_wrap=True)
    if has_llm:
        table.add_column("LLM", justify="right", width=4, no_wrap=True)
    table.add_column("Sponsor", width=9, no_wrap=True)
    table.add_column("Company", width=16)
    table.add_column("Role", width=35)
    table.add_column("Location", width=20)
    table.add_column("Src", width=6)

    for i, job in enumerate(jobs, 1):
        score = job.get("match_score", 0)
        score_color = "green" if score >= 70 else "yellow" if score >= 50 else "red"
        sp = job.get("sponsorship_status", "unknown")
        sp_display = {
            "sponsor_likely": "[green]Likely[/green]",
            "sponsor_unlikely": "[red]Unlikely[/red]",
            "unknown": "[yellow]Unknown[/yellow]",
        }.get(sp, sp)

        row = [
            str(i),
            f"[{score_color}]{score:.0f}[/{score_color}]",
        ]
        if has_llm:
            llm_s = job.get("llm_score") or 0
            llm_color = "green" if llm_s >= 70 else "yellow" if llm_s >= 50 else "dim"
            row.append(f"[{llm_color}]{llm_s:.0f}[/{llm_color}]" if llm_s else "[dim]-[/dim]")
        row.extend([
            sp_display,
            _safe(job.get("company", ""), 16),
            _safe(job.get("title", ""), 35),
            _safe(job.get("location") or "", 20),
            job.get("source", "")[:6],
        ])
        table.add_row(*row)

    console.print(table)
    console.print(f"\n[dim]Showing {len(jobs)} jobs. Use --min-score to filter.[/dim]")


@cli.command()
def stats():
    """Show application statistics."""
    from src.tracker.db import get_stats

    s = get_stats()

    table = Table(title="Application Stats", box=box.ROUNDED, title_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Total Jobs Discovered", str(s["total_jobs"]))
    table.add_row("Applications Submitted", f"[green]{s['applied']}[/green]")
    table.add_row("New / Unreviewed", f"[cyan]{s['new']}[/cyan]")
    table.add_row("Interviewing", f"[green]{s['interviewing']}[/green]")
    table.add_row("Rejected", f"[red]{s['rejected']}[/red]")
    table.add_row("Ghosted (21+ days)", f"[dim]{s['ghosted']}[/dim]")
    table.add_row("Offers", f"[bold green]{s['offers']}[/bold green]")
    table.add_row("Sponsor Likely", f"[yellow]{s['sponsor_likely']}[/yellow]")
    table.add_row("Avg Match Score", f"{s['avg_score']:.1f}")

    console.print(table)


@cli.command()
@click.option("--count", type=int, default=25, help="Number of jobs to plan for today")
@click.option("--min-score", type=float, default=30, help="Minimum match score to consider")
def plan(count, min_score):
    """Generate today's application plan (top N jobs)."""
    from src.tracker.db import init_db, get_unapplied_jobs, update_job
    from src.quality.daily_planner import generate_daily_plan, get_plan_summary

    init_db()

    jobs = get_unapplied_jobs(min_score=min_score, limit=200)
    if not jobs:
        console.print("[yellow]No unapplied jobs found. Run 'scan' first.[/yellow]")
        return

    daily_plan = generate_daily_plan(jobs, target_count=count, min_score=min_score)
    summary = get_plan_summary(daily_plan)

    for job in daily_plan:
        update_job(job["id"], planned_date=job.get("planned_date", ""))

    table = Table(
        title=f"Daily Plan - {summary['date']} ({summary['count']} jobs)",
        box=box.SIMPLE_HEAVY,
        title_style="bold cyan",
        width=115,
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", justify="right", width=5)
    table.add_column("Sponsor", width=9)
    table.add_column("Company", width=18)
    table.add_column("Role", width=35)
    table.add_column("Location", width=18)
    table.add_column("Src", width=6)

    for job in daily_plan:
        score = job.get("match_score", 0)
        sc = "green" if score >= 70 else "yellow" if score >= 50 else "red"
        sp = job.get("sponsorship_status", "unknown")
        sp_d = {"sponsor_likely": "[green]Likely[/green]", "sponsor_unlikely": "[red]Unlikely[/red]"}.get(sp, "[yellow]Unknown[/yellow]")
        table.add_row(
            str(job.get("plan_rank", "")), f"[{sc}]{score:.0f}[/{sc}]", sp_d,
            _safe(job.get("company", ""), 18), _safe(job.get("title", ""), 35),
            _safe(job.get("location") or "", 18), job.get("source", "")[:6],
        )

    console.print(table)
    console.print(
        f"\n[dim]Avg score: {summary.get('avg_score', 0):.0f} | "
        f"Sponsors: {summary.get('sponsor_likely', 0)} | "
        f"Companies: {summary.get('unique_companies', 0)}[/dim]"
    )
    console.print("[green]Run 'prepare' to generate tailored documents for these jobs.[/green]")


@cli.command()
@click.option("--count", type=int, default=25, help="Number of jobs to prepare")
@click.option("--min-score", type=float, default=30, help="Minimum match score")
@click.option("--skip-research", is_flag=True, help="Skip company research step")
def prepare(count, min_score, skip_research):
    """Research companies, generate tailored resumes/cover letters, and run quality gate."""
    from src.tracker.db import init_db, get_unapplied_jobs, update_job
    from src.quality.daily_planner import generate_daily_plan
    from src.quality.company_research import research_companies_batch
    from src.documents.resume_tailor import generate_resume_for_job
    from src.documents.cover_letter import generate_cover_letter_for_job
    from src.quality.quality_gate import run_quality_gate, extract_text_from_docx, MAX_RETRIES

    init_db()
    secrets = load_secrets()
    profile = load_profile()

    llm_client = _get_llm_client(secrets)
    if not llm_client:
        console.print(
            "[red]No LLM backend for document generation. Install Ollama from https://ollama.ai, "
            "run `ollama pull llama3.2`, or set openai_api_key in secrets.yaml.[/red]"
        )
        return

    base_resume = ROOT / "templates" / "base_resume.docx"
    if not base_resume.exists():
        console.print(f"[red]Base resume not found: {base_resume}[/red]")
        console.print("[yellow]Place your resume at templates/base_resume.docx[/yellow]")
        return

    jobs = get_unapplied_jobs(min_score=min_score, limit=200)
    daily_plan = generate_daily_plan(jobs, target_count=count, min_score=min_score)

    if not daily_plan:
        console.print("[yellow]No jobs to prepare. Run 'scan' first.[/yellow]")
        return

    console.print(Panel.fit(
        f"[bold cyan]Preparing {len(daily_plan)} Applications[/bold cyan]\n"
        f"Steps: Company Research -> Resume Tailoring -> Cover Letter -> Quality Gate",
        border_style="cyan",
    ))

    if not skip_research:
        console.print(f"\n[bold]Step 1: Company Research[/bold]")
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(),
                      TextColumn("{task.completed}/{task.total}"), console=console) as progress:
            task = progress.add_task("Researching...", total=len(daily_plan))

            def _rp(i, total, job, result):
                progress.update(task, completed=i + 1)

            research_companies_batch(llm_client, daily_plan, on_progress=_rp)

        for job in daily_plan:
            if job.get("company_research"):
                update_job(job["id"], company_research=job["company_research"])

    prepared = 0
    failed = 0

    console.print(f"\n[bold]Step 2: Generating Documents[/bold]")
    for i, job in enumerate(daily_plan):
        company = _safe(job.get("company", ""), 20)
        title = _safe(job.get("title", ""), 30)
        console.print(f"\n  [{i+1}/{len(daily_plan)}] {title} at {company}")

        resume_path = None
        cover_letter_path = None
        quality_passed = False

        for attempt in range(1, MAX_RETRIES + 2):
            with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                          transient=True, console=console) as progress:
                progress.add_task("Generating resume...", total=None)
                resume_path = generate_resume_for_job(
                    llm_client, job, profile, base_resume_path=base_resume
                )

            if not resume_path:
                console.print(f"    [red]Resume generation failed[/red]")
                break

            with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                          transient=True, console=console) as progress:
                progress.add_task("Generating cover letter...", total=None)
                cover_letter_path = generate_cover_letter_for_job(llm_client, job, profile)

            if not cover_letter_path:
                console.print(f"    [red]Cover letter generation failed[/red]")
                break

            with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                          transient=True, console=console) as progress:
                progress.add_task("Running quality gate...", total=None)
                resume_text = extract_text_from_docx(resume_path)
                cl_text = extract_text_from_docx(cover_letter_path)
                gate_result = run_quality_gate(
                    llm_client, resume_text, cl_text,
                    job.get("title", ""), job.get("description", ""),
                )

            r_score = gate_result.get("resume_score", 0)
            cl_score = gate_result.get("cover_letter_score", 0)

            if gate_result.get("passed"):
                console.print(
                    f"    [green]Quality PASSED[/green] "
                    f"(Resume: {r_score:.1f}/10, Cover Letter: {cl_score:.1f}/10)"
                )
                quality_passed = True
                break
            else:
                console.print(
                    f"    [yellow]Quality gate attempt {attempt}: "
                    f"Resume {r_score:.1f}/10, CL {cl_score:.1f}/10 - regenerating...[/yellow]"
                )

        if quality_passed and resume_path and cover_letter_path:
            update_job(
                job["id"],
                resume_path=str(resume_path),
                cover_letter_path=str(cover_letter_path),
                quality_score=gate_result.get("resume_score", 0),
            )
            job["resume_path"] = str(resume_path)
            job["cover_letter_path"] = str(cover_letter_path)
            prepared += 1
        else:
            failed += 1

    console.print(
        f"\n[bold]Preparation complete:[/bold] "
        f"[green]{prepared} ready[/green] | [red]{failed} failed[/red]"
    )
    if prepared > 0:
        console.print("[green]Run 'apply' to start submitting applications.[/green]")



@cli.command()
@click.option("--after", type=str, default=None, help="Check emails after date (YYYY/MM/DD)")
def monitor(after):
    """Check Gmail for application status updates (read-only)."""
    from src.tracker.db import init_db, get_jobs_by_status, update_application_status
    from src.email.gmail_auth import get_gmail_service
    from src.email.gmail_monitor import poll_inbox
    from src.tracker.db import get_connection

    init_db()
    secrets = load_secrets()
    creds_path = secrets.get("gmail_credentials_path", "config/credentials.json")

    console.print("[cyan]Connecting to Gmail (read-only)...[/cyan]")

    try:
        service = get_gmail_service(creds_path)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        return
    except Exception as e:
        console.print(f"[red]Gmail auth failed: {e}[/red]")
        return

    applied_jobs = get_jobs_by_status("applied")
    if not applied_jobs:
        console.print("[yellow]No applied jobs to monitor.[/yellow]")
        return

    llm_client = _get_llm_client(secrets)

    console.print(f"Checking inbox against {len(applied_jobs)} applied jobs...")
    results = poll_inbox(service, applied_jobs, max_results=50, after_date=after, llm_client=llm_client)

    if not results:
        console.print("[dim]No application-related emails found.[/dim]")
        return

    table = Table(title="Email Status Updates", box=box.ROUNDED, title_style="bold cyan")
    table.add_column("Status", width=12)
    table.add_column("Company", width=18)
    table.add_column("Role", width=25)
    table.add_column("Subject", width=35)
    table.add_column("Conf", width=5)

    updates = 0
    for r in results:
        if r.get("error"):
            continue

        status = r.get("classified_status", "")
        status_colors = {
            "interviewing": "green", "offer": "bold green",
            "rejected": "red", "assessment": "cyan",
        }
        sc = status_colors.get(status, "yellow")

        table.add_row(
            f"[{sc}]{status}[/{sc}]",
            _safe(r.get("matched_company") or "Unknown", 18),
            _safe(r.get("matched_job_title") or "Unknown", 25),
            _safe(r.get("subject", ""), 35),
            f"{r.get('confidence', 0):.0%}",
        )

        if r.get("matched_job_id") and r.get("classified_status"):
            update_application_status(r["matched_job_id"], r["classified_status"], source="email")
            updates += 1

    console.print(table)
    console.print(f"\n[green]Updated {updates} application statuses.[/green]")


@cli.command()
@click.option("--scan-hours", type=int, default=6, help="Hours between job scans")
@click.option("--email-minutes", type=int, default=30, help="Minutes between email checks")
@click.option("--plan-time", type=str, default="08:00", help="Daily plan time (HH:MM)")
def schedule(scan_hours, email_minutes, plan_time):
    """Start the automated scheduler (scans, email checks, daily plan)."""
    from src.scheduler import create_scheduler
    from pathlib import Path

    secrets = load_secrets()
    profile = load_profile()
    search_cfg = load_search_config()

    gmail_creds = Path(secrets.get("gmail_credentials_path", "config/credentials.json"))

    config = {
        "secrets": secrets,
        "profile": profile,
        "search_config": search_cfg,
        "gmail_enabled": gmail_creds.exists(),
    }

    console.print(Panel.fit(
        f"[bold cyan]Scheduler Starting[/bold cyan]\n"
        f"Job scan: every {scan_hours}h\n"
        f"Email check: every {email_minutes}m"
        + (" [green](active)[/green]" if config["gmail_enabled"] else " [dim](Gmail not configured)[/dim]")
        + f"\nDaily plan: {plan_time}",
        border_style="cyan",
    ))
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    scheduler = create_scheduler(
        scan_interval_hours=scan_hours,
        email_interval_minutes=email_minutes,
        plan_time=plan_time,
        config=config,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        console.print("\n[yellow]Scheduler stopped.[/yellow]")


def _safe(text: str, max_len: int = 50) -> str:
    """Sanitize text for Windows console output."""
    if not text:
        return ""
    cleaned = text.encode("ascii", errors="replace").decode("ascii")
    return cleaned[:max_len]


def _get_llm_client(secrets: dict):
    """Create LLM client (Ollama local or OpenAI) when configured."""
    from src.utils.llm_provider import create_llm_client

    return create_llm_client(secrets)


def _build_scrapers(secrets: dict, search_cfg: dict, source_filter=None) -> list:
    scrapers = []
    scraper_cfg = search_cfg.get("scrapers", {})

    if (source_filter in (None, "adzuna")) and scraper_cfg.get("adzuna", {}).get("enabled", False):
        adzuna_creds = secrets.get("adzuna", {})
        app_id = adzuna_creds.get("app_id", "")
        app_key = adzuna_creds.get("app_key", "")
        if app_id and app_key and "your-" not in app_id:
            from src.scrapers.adzuna import AdzunaScraper
            scrapers.append(AdzunaScraper(
                app_id=app_id,
                app_key=app_key,
                country=scraper_cfg.get("adzuna", {}).get("country", "us"),
            ))

    if (source_filter in (None, "jooble")) and scraper_cfg.get("jooble", {}).get("enabled", False):
        jooble_key = secrets.get("jooble", {}).get("api_key", "")
        if jooble_key and "your-" not in jooble_key:
            from src.scrapers.jooble import JoobleScraper
            scrapers.append(JoobleScraper(api_key=jooble_key))

    if (source_filter in (None, "themuse")) and scraper_cfg.get("themuse", {}).get("enabled", False):
        from src.scrapers.themuse import TheMuseScraper
        scrapers.append(TheMuseScraper())

    if (source_filter in (None, "greenhouse")) and scraper_cfg.get("greenhouse", {}).get("enabled", False):
        from src.scrapers.greenhouse import GreenhouseScraper
        boards = scraper_cfg.get("greenhouse", {}).get("boards")
        scrapers.append(GreenhouseScraper(boards=boards))

    if (source_filter in (None, "lever")) and scraper_cfg.get("lever", {}).get("enabled", False):
        from src.scrapers.lever import LeverScraper
        companies = scraper_cfg.get("lever", {}).get("companies")
        scrapers.append(LeverScraper(companies=companies))

    if (source_filter in (None, "google_jobs")) and scraper_cfg.get("google_jobs", {}).get("enabled", False):
        serpapi_key = secrets.get("serpapi_key", "")
        if serpapi_key and serpapi_key not in ("", "your-serpapi-key"):
            from src.scrapers.google_jobs import GoogleJobsScraper
            scrapers.append(GoogleJobsScraper(api_key=serpapi_key))

    if (source_filter in (None, "linkedin")) and scraper_cfg.get("linkedin", {}).get("enabled", False):
        from src.scrapers.linkedin import LinkedInScraper
        headless = scraper_cfg.get("linkedin", {}).get("headless", True)
        scrapers.append(LinkedInScraper(headless=headless))

    return scrapers


def _get_scraper_kwargs(search_cfg: dict, scraper_name: str, limit_override=None) -> dict:
    kwargs = {}
    cfg = search_cfg.get("scrapers", {}).get(scraper_name, {})

    if scraper_name == "adzuna":
        kwargs["results_per_page"] = limit_override or cfg.get("results_per_page", 50)
        kwargs["max_pages"] = cfg.get("max_pages", 3)
    elif scraper_name == "jooble":
        kwargs["results_per_request"] = limit_override or cfg.get("results_per_request", 50)
    elif scraper_name == "themuse":
        kwargs["results_per_page"] = limit_override or cfg.get("results_per_page", 20)
        kwargs["max_pages"] = cfg.get("max_pages", 5)
    elif scraper_name == "greenhouse":
        kwargs["max_per_board"] = limit_override or cfg.get("max_per_board", 15)
    elif scraper_name == "lever":
        kwargs["max_per_company"] = limit_override or cfg.get("max_per_company", 15)
    elif scraper_name == "google_jobs":
        kwargs["max_pages"] = cfg.get("max_pages", 3)
    elif scraper_name == "linkedin":
        kwargs["max_results"] = limit_override or cfg.get("max_results", 50)

    filters = search_cfg.get("filters", {})
    if filters.get("min_salary"):
        kwargs["salary_min"] = filters["min_salary"]

    return kwargs


@cli.command(name="profile-check")
def profile_check():
    """Check profile completeness and show improvement suggestions."""
    from src.matching.profile_validator import format_validation_report, profile_completeness_score
    profile = load_profile()
    report = format_validation_report(profile)
    score = profile_completeness_score(profile)

    color = "green" if score >= 90 else "yellow" if score >= 70 else "red"
    console.print(Panel(
        report,
        title=f"[bold {color}]Profile Completeness: {score}/100[/bold {color}]",
        border_style=color,
    ))


if __name__ == "__main__":
    cli()
