"""
job_checker.py
--------------
Pre-apply validation: checks if a job URL is still accepting applications
and extracts applicant count / competition level from LinkedIn.

Uses cloudscraper for Cloudflare-resistant HTTP checks.
Playwright dependency removed — all checks are pure HTTP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

try:
    import cloudscraper as _cloudscraper
    _HAS_CLOUDSCRAPER = True
except ImportError:
    import requests as _cloudscraper  # type: ignore[no-redef]
    _HAS_CLOUDSCRAPER = False

# ── Closed-job signal phrases ─────────────────────────────────────────────────
CLOSED_PHRASES = [
    "no longer accepting applications",
    "this job is no longer available",
    "position has been filled",
    "this position is no longer available",
    "job has expired",
    "this listing has expired",
    "job is closed",
    "this job has been closed",
    "application period has ended",
    "not accepting applications",
    "job no longer available",
    "this role has been filled",
    "this vacancy has been filled",
]

# ── LinkedIn applicant-count patterns ─────────────────────────────────────────
# "8 people clicked apply"  |  "Over 200 applicants"  |  "Be among the first 25"
_LI_APPLICANT_PATTERNS = [
    r"be among the first\s+(\d+)\s+applicants?",          # "Be among the first 25 applicants"
    r"(\d[\d,]*)\s+people\s+clicked\s+apply",             # "8 people clicked apply"
    r"over\s+([\d,]+)\s+applicants?",                     # "Over 200 applicants"
    r"([\d,]+)\s+applicants?",                            # "143 applicants"
    r"([\d,]+)\+?\s+people\s+applied",                   # "50+ people applied"
]


@dataclass
class JobStatus:
    active: bool = True
    closed_reason: str = ""
    applicant_count: int | None = None
    applicant_label: str = ""   # raw text from the page
    competition: str = "unknown"  # "first_25" | "low" | "medium" | "high" | "unknown"
    check_method: str = "requests"  # "requests" | "playwright" | "skipped"
    error: str = ""

    @property
    def competition_emoji(self) -> str:
        return {
            "first_25": "\U0001f7e2",
            "low":      "\U0001f7e2",
            "medium":   "\U0001f7e1",
            "high":     "\U0001f534",
            "unknown":  "\u26aa",
        }.get(self.competition, "\u26aa")

    def discord_summary(self) -> str:
        if not self.active:
            return f"\U0001f6ab **Job closed** \u2014 {self.closed_reason}"
        parts = []
        if self.applicant_label:
            parts.append(f"{self.competition_emoji} **{self.applicant_label}**")
        if self.competition == "first_25":
            parts.append("*(early \u2014 apply fast!)*")
        elif self.competition == "high":
            parts.append("*(very competitive)*")
        return " | ".join(parts) if parts else "\u2705 Still accepting applications"


def check_job(url: str, timeout: int = 15, job_id: str = "") -> JobStatus:
    """
    Check whether a job URL is still active and extract applicant count.

    Automatically resolves aggregator redirect URLs (Jooble, Dice, BeeBee…)
    to their final ATS destination before checking, bypassing Cloudflare.
    """
    if not url or not url.startswith("http"):
        return JobStatus(active=False, closed_reason="Invalid URL", check_method="skipped")

    # Step 1: resolve aggregator/redirect URLs to the real ATS page
    from src.apply.url_resolver import needs_resolution, resolve_and_cache
    if needs_resolution(url):
        resolved = resolve_and_cache(job_id, url) if job_id else _quick_resolve(url)
        if resolved and resolved != url:
            url = resolved  # check the real page, not the aggregator

    # Lightweight cloudscraper check (handles Cloudflare automatically)
    return _check_with_requests(url, timeout)


def _quick_resolve(url: str) -> str:
    """Resolve without DB write — used when we have no job_id."""
    from src.apply.url_resolver import resolve_url
    return resolve_url(url)


def _check_with_requests(url: str, timeout: int = 15) -> JobStatus:
    """
    HTTP check using cloudscraper (handles Cloudflare JS challenges automatically).
    Falls back to plain requests if cloudscraper is not installed.
    """
    status = JobStatus(check_method="cloudscraper" if _HAS_CLOUDSCRAPER else "requests")
    try:
        if _HAS_CLOUDSCRAPER:
            import cloudscraper
            session = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
        else:
            import requests
            session = requests.Session()
            session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            })

        resp = session.get(url, timeout=timeout, allow_redirects=True)

        if resp.status_code in (404, 410):
            status.active = False
            status.closed_reason = f"HTTP {resp.status_code} — job page not found"
            return status

        text = resp.text.lower()

        for phrase in CLOSED_PHRASES:
            if phrase in text:
                status.active = False
                status.closed_reason = phrase.title()
                return status

        _extract_applicant_info(text, status)
        return status

    except Exception as e:
        err = str(e).lower()
        if "timeout" in err:
            status.error = "Request timed out"
        elif "connection" in err:
            status.error = "Connection error"
        else:
            status.error = str(e)
    return status



def _extract_applicant_info(text: str, status: JobStatus) -> None:
    """Parse applicant count from page text using regex patterns."""
    for pattern in _LI_APPLICANT_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw_num = m.group(1).replace(",", "")
            try:
                count = int(raw_num)
            except ValueError:
                continue
            status.applicant_count = count
            status.applicant_label = m.group(0).strip()
            _set_competition(count, status, is_first_25="first" in m.group(0).lower())
            return


def _parse_applicant_count(raw: str, status: JobStatus) -> None:
    """Parse applicant count from a known applicant-count element text."""
    raw_lower = raw.lower()
    is_first_25 = "first" in raw_lower
    m = re.search(r"[\d,]+", raw)
    if m:
        try:
            count = int(m.group(0).replace(",", ""))
            status.applicant_count = count
            _set_competition(count, status, is_first_25=is_first_25)
        except ValueError:
            pass


def _set_competition(count: int, status: JobStatus, is_first_25: bool = False) -> None:
    if is_first_25 or count <= 25:
        status.competition = "first_25"
    elif count <= 75:
        status.competition = "low"
    elif count <= 200:
        status.competition = "medium"
    else:
        status.competition = "high"


def applicant_score_bonus(status: JobStatus) -> float:
    """
    Returns a match score bonus/penalty based on competition level.
    Called during job scoring so fewer applicants = higher priority.
    """
    return {
        "first_25": +8.0,   # Early posting, act fast
        "low":      +4.0,
        "medium":    0.0,
        "high":     -5.0,   # Very competitive, lower priority
        "unknown":   0.0,
    }.get(status.competition, 0.0)
