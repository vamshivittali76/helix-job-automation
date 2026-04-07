"""
Experience-level / seniority detection for job listings.

Parses job titles and descriptions to determine the seniority level
and required years of experience, then compares against the user's profile.
"""

import re
from typing import Optional

LEVEL_ENTRY = "entry"
LEVEL_MID = "mid"
LEVEL_SENIOR = "senior"
LEVEL_LEAD = "lead"
LEVEL_EXECUTIVE = "executive"

SENIORITY_ORDER = {
    LEVEL_ENTRY: 0,
    LEVEL_MID: 1,
    LEVEL_SENIOR: 2,
    LEVEL_LEAD: 3,
    LEVEL_EXECUTIVE: 4,
}

_TITLE_PATTERNS: list[tuple[str, str]] = [
    # Executive / Director level
    (r"\b(?:director|vp|vice\s*president|head\s+of|cto|cio)\b", LEVEL_EXECUTIVE),
    (r"\b(?:engineering\s+manager|test\s+manager|qa\s+manager)\b", LEVEL_EXECUTIVE),
    # Lead / Principal / Staff
    (r"\b(?:principal|staff|distinguished)\b", LEVEL_LEAD),
    (r"\b(?:lead|team\s+lead|tech\s+lead)\b", LEVEL_LEAD),
    (r"\blevel\s*(?:iv|4|v|5)\b", LEVEL_LEAD),
    (r"\b(?:senior\s+lead|sr\.?\s+lead)\b", LEVEL_LEAD),
    # Senior
    (r"\b(?:senior|sr\.?)\b", LEVEL_SENIOR),
    (r"\blevel\s*(?:iii|3)\b", LEVEL_SENIOR),
    # Entry / Junior
    (r"\b(?:junior|jr\.?|entry[\s-]*level|associate|intern|trainee)\b", LEVEL_ENTRY),
    (r"\b(?:new\s+grad|recent\s+grad(?:uate)?|graduate)\b", LEVEL_ENTRY),
    (r"\blevel\s*(?:i|1)\b", LEVEL_ENTRY),
    # Mid is the fallback when nothing matches
    (r"\blevel\s*(?:ii|2)\b", LEVEL_MID),
]

_YEARS_PATTERNS = [
    re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)", re.I),
    re.compile(r"(?:minimum|min|at\s+least)\s+(\d{1,2})\s+(?:years?|yrs?)", re.I),
    re.compile(r"(\d{1,2})\s*[-–]\s*\d{1,2}\s+(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)", re.I),
    re.compile(r"(?:requires?|requiring)\s+(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I),
]


def detect_seniority_from_title(title: str) -> str:
    """Detect seniority level from job title. Returns one of the LEVEL_* constants."""
    t = title.lower().strip()
    for pattern, level in _TITLE_PATTERNS:
        if re.search(pattern, t):
            return level
    return LEVEL_MID


def extract_required_years(description: str) -> Optional[int]:
    """Extract the minimum years of experience from a job description."""
    if not description:
        return None
    years_found: list[int] = []
    for pat in _YEARS_PATTERNS:
        for match in pat.finditer(description):
            try:
                y = int(match.group(1))
                if 0 < y <= 30:
                    years_found.append(y)
            except (ValueError, IndexError):
                continue
    return min(years_found) if years_found else None


def compute_seniority_penalty(
    job_seniority: str,
    required_years: Optional[int],
    user_level: str = LEVEL_MID,
    user_years: int = 3,
) -> float:
    """
    Compute a score penalty (negative number) for seniority mismatch.
    Returns 0 if the job is at or below the user's level.
    A positive bonus is applied for entry-level roles when user is mid.
    """
    job_rank = SENIORITY_ORDER.get(job_seniority, 1)
    user_rank = SENIORITY_ORDER.get(user_level, 1)

    level_gap = job_rank - user_rank
    penalty = 0.0

    if level_gap <= -1 and job_seniority == LEVEL_ENTRY:
        penalty = 5.0
    elif level_gap == 1:
        penalty = -35.0
    elif level_gap == 2:
        penalty = -60.0
    elif level_gap >= 3:
        penalty = -80.0

    if required_years and required_years > user_years + 1:
        years_gap = required_years - user_years
        penalty -= min(years_gap * 8.0, 40.0)

    return penalty


def is_out_of_range(job_seniority: str, required_years: Optional[int],
                    user_level: str = LEVEL_MID, user_years: int = 3) -> bool:
    """Hard filter: True if the job is beyond the user's level."""
    job_rank = SENIORITY_ORDER.get(job_seniority, 1)
    user_rank = SENIORITY_ORDER.get(user_level, 1)
    if job_rank - user_rank >= 1:
        return True
    if required_years and required_years > user_years + 2:
        return True
    return False


def enrich_seniority(
    jobs: list[dict],
    user_level: str = LEVEL_MID,
    user_years: int = 3,
) -> list[dict]:
    """
    Enrich a list of job dicts with seniority_level, required_years,
    and seniority_penalty fields.
    """
    for job in jobs:
        title = job.get("title", "")
        desc = job.get("description", "")

        job["seniority_level"] = detect_seniority_from_title(title)
        job["required_years"] = extract_required_years(desc)
        job["seniority_penalty"] = compute_seniority_penalty(
            job["seniority_level"],
            job["required_years"],
            user_level=user_level,
            user_years=user_years,
        )
    return jobs


def user_level_from_profile(profile: dict) -> tuple[str, int]:
    """Extract user's seniority level and years from profile config."""
    years = profile.get("years_of_experience", 3)
    level_str = profile.get("experience_level", "mid").lower()
    level_map = {
        "entry": LEVEL_ENTRY, "junior": LEVEL_ENTRY,
        "mid": LEVEL_MID, "middle": LEVEL_MID,
        "senior": LEVEL_SENIOR, "sr": LEVEL_SENIOR,
        "lead": LEVEL_LEAD, "principal": LEVEL_LEAD, "staff": LEVEL_LEAD,
    }
    return level_map.get(level_str, LEVEL_MID), years
