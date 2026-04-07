import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).parent.parent.parent / "output" / "jobs.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            remote_type TEXT,
            description TEXT,
            salary_min INTEGER,
            salary_max INTEGER,
            salary_currency TEXT DEFAULT 'USD',
            url TEXT NOT NULL,
            source TEXT NOT NULL,
            external_id TEXT,
            date_posted TEXT,
            date_found TEXT NOT NULL,
            sponsorship_status TEXT DEFAULT 'unknown',
            match_score REAL DEFAULT 0,
            quality_score REAL,
            company_research TEXT,
            is_applied INTEGER DEFAULT 0,
            is_skipped INTEGER DEFAULT 0,
            date_applied TEXT,
            application_status TEXT DEFAULT 'new',
            status_source TEXT DEFAULT 'manual',
            last_status_update TEXT,
            resume_path TEXT,
            cover_letter_path TEXT,
            notes TEXT,
            raw_data TEXT
        );

        CREATE TABLE IF NOT EXISTS email_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail_message_id TEXT UNIQUE,
            subject TEXT,
            sender TEXT,
            received_date TEXT,
            classified_status TEXT,
            matched_job_id TEXT,
            confidence REAL,
            raw_snippet TEXT,
            processed_date TEXT NOT NULL,
            FOREIGN KEY (matched_job_id) REFERENCES jobs(id)
        );

        CREATE TABLE IF NOT EXISTS scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            query TEXT,
            jobs_found INTEGER DEFAULT 0,
            jobs_new INTEGER DEFAULT 0,
            scan_date TEXT NOT NULL,
            duration_seconds REAL
        );

        CREATE TABLE IF NOT EXISTS status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            source TEXT DEFAULT 'manual',
            details TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
        CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(application_status);
        CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(match_score DESC);
        CREATE INDEX IF NOT EXISTS idx_jobs_applied ON jobs(is_applied);
        CREATE INDEX IF NOT EXISTS idx_jobs_date_found ON jobs(date_found);
        CREATE INDEX IF NOT EXISTS idx_status_history_job ON status_history(job_id);

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT,
            channel_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            fire_at TEXT NOT NULL,
            fired INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reminders_fire_at ON reminders(fire_at, fired);

        CREATE TABLE IF NOT EXISTS schedule_events (
            day_key TEXT NOT NULL,
            event TEXT NOT NULL,
            PRIMARY KEY (day_key, event)
        );

        CREATE TABLE IF NOT EXISTS daily_schedule_overrides (
            day_key TEXT PRIMARY KEY,
            raw_text TEXT,
            windows_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    conn.commit()
    _migrate(conn)
    conn.close()


def _migrate(conn: sqlite3.Connection):
    """Add columns introduced in later phases without breaking existing DBs."""
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
    }
    migrations = [
        ("llm_score", "REAL"),
        ("llm_reasoning", "TEXT"),
        ("planned_date", "TEXT"),
        ("seniority_level", "TEXT"),
        ("required_years", "INTEGER"),
        ("seniority_penalty", "REAL DEFAULT 0"),
        ("reviewed_date", "TEXT"),
        # Competition / freshness data
        ("applicant_count", "INTEGER"),          # raw number scraped from LinkedIn etc.
        ("applicant_label", "TEXT"),             # e.g. "Be among the first 25 applicants"
        ("competition_level", "TEXT"),           # first_25 | low | medium | high | unknown
        ("is_expired", "INTEGER DEFAULT 0"),     # 1 = confirmed closed, skip on apply
        ("expired_reason", "TEXT"),              # e.g. "No longer accepting applications"
        ("last_checked", "TEXT"),                # ISO datetime of last freshness check
    ]
    for col_name, col_type in migrations:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}")
    conn.commit()


def mark_job_expired(job_id: str, reason: str) -> None:
    """Mark a job as expired/closed so it is skipped in future apply runs."""
    conn = get_connection()
    conn.execute(
        """UPDATE jobs SET is_expired=1, expired_reason=?, last_checked=?,
           application_status='expired'
           WHERE id=?""",
        (reason, datetime.now().isoformat(), job_id),
    )
    conn.commit()
    conn.close()


def add_reminder(
    channel_id: int,
    message: str,
    delay_seconds: int,
    job_id: str = "",
) -> None:
    """Schedule a reminder to fire after delay_seconds from now."""
    from datetime import timedelta
    fire_at = (datetime.now() + timedelta(seconds=delay_seconds)).isoformat()
    conn = get_connection()
    conn.execute(
        """INSERT INTO reminders (job_id, channel_id, message, fire_at, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (job_id or None, channel_id, message, fire_at, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_due_reminders() -> list[dict]:
    """Return all unfired reminders whose fire_at time has passed."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM reminders
           WHERE fired = 0 AND fire_at <= ?
           ORDER BY fire_at ASC""",
        (datetime.now().isoformat(),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_reminder_fired(reminder_id: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE reminders SET fired=1 WHERE id=?", (reminder_id,))
    conn.commit()
    conn.close()


def try_claim_schedule_event(day_key: str, event: str) -> bool:
    """
    Atomically record that a schedule event ran for this calendar day (user TZ).
    Returns True if this is the first claim (caller should run the event).
    """
    conn = get_connection()
    cur = conn.execute(
        "INSERT OR IGNORE INTO schedule_events (day_key, event) VALUES (?, ?)",
        (day_key, event),
    )
    conn.commit()
    claimed = cur.rowcount > 0
    conn.close()
    return claimed


def update_job_competition(
    job_id: str,
    applicant_count: int | None,
    applicant_label: str,
    competition_level: str,
) -> None:
    """Store competition data scraped from LinkedIn or other sources."""
    conn = get_connection()
    conn.execute(
        """UPDATE jobs SET applicant_count=?, applicant_label=?,
           competition_level=?, last_checked=?
           WHERE id=?""",
        (applicant_count, applicant_label, competition_level,
         datetime.now().isoformat(), job_id),
    )
    conn.commit()
    conn.close()


def generate_job_id(title: str, company: str, url: str) -> str:
    import hashlib
    raw = f"{title.lower().strip()}|{company.lower().strip()}|{url.strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def insert_job(job: dict) -> bool:
    """Insert a job. Returns True if new, False if duplicate."""
    conn = get_connection()
    job_id = job.get("id") or generate_job_id(
        job["title"], job["company"], job["url"]
    )
    try:
        # Pull competition data out of raw_data if the scraper stored it there
        raw = job.get("raw_data") or {}
        applicant_count = job.get("applicant_count") or raw.get("applicant_count")
        applicant_label = job.get("applicant_label") or raw.get("applicant_label", "")
        competition_level = job.get("competition_level") or raw.get("competition_level", "unknown")
        is_expired = int(job.get("is_expired") or raw.get("is_expired", 0))

        conn.execute(
            """INSERT INTO jobs (id, title, company, location, remote_type,
               description, salary_min, salary_max, salary_currency, url,
               source, external_id, date_posted, date_found,
               sponsorship_status, match_score, llm_score, llm_reasoning,
               seniority_level, required_years, seniority_penalty,
               applicant_count, applicant_label, competition_level, is_expired,
               raw_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                job["title"],
                job["company"],
                job.get("location"),
                job.get("remote_type"),
                job.get("description"),
                job.get("salary_min"),
                job.get("salary_max"),
                job.get("salary_currency", "USD"),
                job["url"],
                job["source"],
                job.get("external_id"),
                job.get("date_posted"),
                datetime.now().isoformat(),
                job.get("sponsorship_status", "unknown"),
                job.get("match_score", 0),
                job.get("llm_score"),
                job.get("llm_reasoning"),
                job.get("seniority_level"),
                job.get("required_years"),
                job.get("seniority_penalty", 0),
                applicant_count,
                applicant_label,
                competition_level,
                is_expired,
                json.dumps(raw) if raw else None,
            ),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def insert_jobs_batch(jobs: list[dict]) -> tuple[int, int]:
    """Insert multiple jobs. Returns (total, new_count). Marks new jobs with _is_new=True."""
    new_count = 0
    for job in jobs:
        is_new = insert_job(job)
        job["_is_new"] = is_new
        if is_new:
            new_count += 1
    return len(jobs), new_count


def update_job(job_id: str, **fields):
    conn = get_connection()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


def update_application_status(
    job_id: str, status: str, source: str = "manual", details: str = None
):
    """Update a job's application status and log the change to status_history."""
    conn = get_connection()
    row = conn.execute(
        "SELECT application_status FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    old_status = row["application_status"] if row else None
    conn.close()

    now = datetime.now().isoformat()
    update_fields = dict(
        application_status=status,
        status_source=source,
        last_status_update=now,
    )
    if status == "applied":
        update_fields["is_applied"] = 1
        update_fields["date_applied"] = now
    if status in ("approved", "rejected_by_user", "skipped"):
        update_fields["reviewed_date"] = now

    update_job(job_id, **update_fields)
    log_status_change(job_id, old_status, status, source, details)

    if status == "applied":
        try:
            from src.tracker.excel_tracker import sync_applied_sheet

            sync_applied_sheet()
        except Exception:
            pass


def log_status_change(
    job_id: str, old_status: str, new_status: str,
    source: str = "manual", details: str = None,
):
    conn = get_connection()
    conn.execute(
        """INSERT INTO status_history (job_id, old_status, new_status, changed_at, source, details)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (job_id, old_status, new_status, datetime.now().isoformat(), source, details),
    )
    conn.commit()
    conn.close()


def get_status_history(job_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM status_history WHERE job_id = ? ORDER BY changed_at DESC",
        (job_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_daily_schedule_override(day_key: str, raw_text: str, windows: list[str]) -> None:
    """Store LLM-parsed apply windows for a calendar day (user local YYYY-MM-DD)."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO daily_schedule_overrides (day_key, raw_text, windows_json, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(day_key) DO UPDATE SET
             raw_text=excluded.raw_text,
             windows_json=excluded.windows_json,
             updated_at=excluded.updated_at""",
        (day_key, raw_text, json.dumps(windows), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_daily_schedule_override(day_key: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM daily_schedule_overrides WHERE day_key = ?", (day_key,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["windows"] = json.loads(d["windows_json"] or "[]")
    except json.JSONDecodeError:
        d["windows"] = []
    return d


def clear_daily_schedule_override(day_key: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM daily_schedule_overrides WHERE day_key = ?", (day_key,))
    conn.commit()
    conn.close()


def count_applied_between_days(day_start: str, day_end: str) -> int:
    """Count distinct jobs marked applied in status_history within inclusive YYYY-MM-DD range."""
    conn = get_connection()
    row = conn.execute(
        """SELECT COUNT(DISTINCT job_id) FROM status_history
           WHERE new_status = 'applied'
           AND substr(changed_at, 1, 10) >= ?
           AND substr(changed_at, 1, 10) <= ?""",
        (day_start, day_end),
    ).fetchone()
    conn.close()
    return int(row[0]) if row else 0


def get_jobs_by_filters(
    status: str = None,
    min_score: float = 0,
    sponsor_only: bool = False,
    seniority: str = None,
    source: str = None,
    search: str = None,
    limit: int = 50,
    offset: int = 0,
    exclude_expired: bool = False,
) -> list[dict]:
    """Flexible job query with multiple filters."""
    conn = get_connection()
    clauses = []
    params = []

    if status:
        clauses.append("application_status = ?")
        params.append(status)
    if min_score > 0:
        clauses.append("match_score >= ?")
        params.append(min_score)
    if sponsor_only:
        clauses.append("sponsorship_status = 'sponsor_likely'")
    if seniority:
        clauses.append("seniority_level = ?")
        params.append(seniority)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if search:
        clauses.append("(LOWER(title) LIKE ? OR LOWER(company) LIKE ?)")
        params.extend([f"%{search.lower()}%", f"%{search.lower()}%"])
    if exclude_expired:
        clauses.append("(is_expired IS NULL OR is_expired = 0)")

    where = " AND ".join(clauses) if clauses else "1=1"
    params.extend([limit, offset])

    rows = conn.execute(
        f"""SELECT * FROM jobs WHERE {where}
            ORDER BY match_score DESC LIMIT ? OFFSET ?""",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_review_jobs(limit: int = 50) -> list[dict]:
    """Return pending review jobs, excluding expired/closed ones."""
    return get_jobs_by_filters(status="pending_review", limit=limit, exclude_expired=True)


def get_jobs_by_filters_exclude_expired(limit: int = 50) -> list[dict]:
    """Convenience: approved jobs excluding expired."""
    return get_jobs_by_filters(status="approved", limit=limit, exclude_expired=True)


def get_detailed_stats() -> dict:
    """Extended stats for Discord bot and dashboard."""
    conn = get_connection()
    stats = {}
    stats["total"] = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    for status in [
        "new", "pending_review", "approved", "preparing", "applied",
        "interview", "offer", "accepted", "rejected_by_user",
        "rejected_by_company", "no_response", "skipped",
    ]:
        stats[status] = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE application_status = ?", (status,)
        ).fetchone()[0]

    stats["sponsor_likely"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE sponsorship_status = 'sponsor_likely'"
    ).fetchone()[0]
    stats["avg_score"] = (
        conn.execute(
            "SELECT AVG(match_score) FROM jobs WHERE match_score > 0"
        ).fetchone()[0] or 0
    )

    for level in ["entry", "mid", "senior", "lead", "executive"]:
        stats[f"seniority_{level}"] = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE seniority_level = ?", (level,)
        ).fetchone()[0]

    by_source = conn.execute(
        "SELECT source, COUNT(*) as cnt FROM jobs GROUP BY source ORDER BY cnt DESC"
    ).fetchall()
    stats["by_source"] = {r["source"]: r["cnt"] for r in by_source}

    today = datetime.now().strftime("%Y-%m-%d")
    stats["found_today"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE date_found LIKE ?", (f"{today}%",)
    ).fetchone()[0]
    stats["applied_today"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE date_applied LIKE ?", (f"{today}%",)
    ).fetchone()[0]

    # Expired / competition stats
    stats["expired"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE is_expired = 1"
    ).fetchone()[0]
    for level in ["first_25", "low", "medium", "high"]:
        stats[f"competition_{level}"] = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE competition_level = ?", (level,)
        ).fetchone()[0]

    conn.close()
    return stats


def get_job(job_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_unapplied_jobs(min_score: float = 0, limit: int = 50) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM jobs
           WHERE is_applied = 0 AND is_skipped = 0 AND match_score >= ?
           ORDER BY match_score DESC
           LIMIT ?""",
        (min_score, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_jobs_by_status(status: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE application_status = ? ORDER BY date_found DESC",
        (status,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_jobs(limit: int = 500) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY date_found DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_applied_jobs(limit: int = 10000) -> list[dict]:
    """
    Jobs the user has submitted an application for (Helix apply flow, /set_status applied,
    or any path that sets is_applied / application_status=applied).
    Ordered by application date (newest first).
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM jobs
           WHERE is_applied = 1 OR application_status = 'applied'
           ORDER BY COALESCE(date_applied, last_status_update, date_found) DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stale_applications(days: int = 21) -> list[dict]:
    """Find applications with no status update for N days (ghosted)."""
    conn = get_connection()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT * FROM jobs
           WHERE application_status = 'applied'
           AND (last_status_update IS NULL OR last_status_update < ?)
           AND date_applied IS NOT NULL AND date_applied < ?""",
        (cutoff, cutoff),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    conn = get_connection()
    stats = {}
    stats["total_jobs"] = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    stats["applied"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE is_applied = 1"
    ).fetchone()[0]
    stats["new"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE application_status = 'new'"
    ).fetchone()[0]
    stats["interview"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE application_status = 'interview'"
    ).fetchone()[0]
    stats["rejected"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE application_status IN ('rejected_by_company', 'rejected_by_user')"
    ).fetchone()[0]
    stats["no_response"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE application_status = 'no_response'"
    ).fetchone()[0]
    stats["offers"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE application_status = 'offer'"
    ).fetchone()[0]
    stats["sponsor_likely"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE sponsorship_status = 'sponsor_likely'"
    ).fetchone()[0]
    stats["avg_score"] = (
        conn.execute(
            "SELECT AVG(match_score) FROM jobs WHERE match_score > 0"
        ).fetchone()[0]
        or 0
    )
    conn.close()
    return stats


def log_scan(source: str, query: str, jobs_found: int, jobs_new: int, duration: float):
    conn = get_connection()
    conn.execute(
        """INSERT INTO scan_log (source, query, jobs_found, jobs_new, scan_date, duration_seconds)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (source, query, jobs_found, jobs_new, datetime.now().isoformat(), duration),
    )
    conn.commit()
    conn.close()


def job_exists(title: str, company: str, url: str) -> bool:
    job_id = generate_job_id(title, company, url)
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return row is not None


def search_jobs_by_company(company_name: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE LOWER(company) LIKE ? ORDER BY date_found DESC",
        (f"%{company_name.lower()}%",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


init_db()
