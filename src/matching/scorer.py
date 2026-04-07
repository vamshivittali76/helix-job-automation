import re
from typing import Optional


def compute_match_score(
    job_title: str,
    job_description: str,
    job_location: Optional[str],
    sponsorship_status: str,
    profile: dict,
) -> float:
    """
    Compute a composite match score (0-100) for a job against the user profile.
    Phase 1: keyword-based scoring. Phase 2 will add LLM semantic matching.
    """
    scores = {}

    scores["role"] = _score_role_match(job_title, profile.get("target_roles", []))
    scores["skills"] = _score_skills_match(
        job_title, job_description or "", profile.get("skills", {})
    )
    scores["sponsorship"] = _score_sponsorship(sponsorship_status)
    scores["recency"] = 8.0  # Placeholder until we parse dates properly
    scores["location"] = _score_location(job_location, profile.get("preferences", {}))

    weights = {
        "role": 0.30,
        "skills": 0.30,
        "sponsorship": 0.20,
        "recency": 0.10,
        "location": 0.10,
    }

    final_score = sum(scores[k] * weights[k] for k in weights)
    return round(min(100, max(0, final_score)), 1)


def _score_role_match(job_title: str, target_roles: list[str]) -> float:
    if not target_roles:
        return 50.0
    title_lower = job_title.lower()

    exact_match_terms = {
        "sdet": 100,
        "software development engineer in test": 100,
        "software engineer": 90,
        "qa automation engineer": 95,
        "qa engineer": 90,
        "quality assurance engineer": 90,
        "test automation engineer": 95,
        "software test engineer": 90,
        "automation engineer": 85,
        "quality engineer": 85,
    }
    for term, score in exact_match_terms.items():
        if term in title_lower:
            return float(score)

    partial_keywords = {
        "test": 60, "qa": 65, "quality": 60, "automation": 65,
        "software": 55, "engineer": 50, "developer": 50, "sdet": 100,
    }
    best = 0
    for kw, score in partial_keywords.items():
        if re.search(r"\b" + re.escape(kw) + r"\b", title_lower):
            best = max(best, score)

    return float(best)


def _score_skills_match(job_title: str, description: str, skills: dict) -> float:
    if not description and not job_title:
        return 30.0

    text = f"{job_title} {description}".lower()

    all_skills = []
    for category_skills in skills.values():
        if isinstance(category_skills, list):
            all_skills.extend(category_skills)

    if not all_skills:
        return 30.0

    matched = 0
    for skill in all_skills:
        skill_lower = skill.lower()
        if skill_lower in text or skill_lower.replace(" ", "") in text.replace(" ", ""):
            matched += 1
        elif len(skill_lower) > 3 and re.search(re.escape(skill_lower), text):
            matched += 1

    ratio = matched / len(all_skills) if all_skills else 0
    return min(100, ratio * 150)


def _score_sponsorship(status: str) -> float:
    return {
        "sponsor_likely": 100.0,
        "sponsor_unlikely": 20.0,
        "unknown": 55.0,
    }.get(status, 55.0)


def _score_location(location: Optional[str], preferences: dict) -> float:
    if not location:
        return 50.0
    loc_lower = location.lower()
    preferred_types = preferences.get("location_types", ["remote", "hybrid", "onsite"])

    if "remote" in loc_lower and "remote" in preferred_types:
        return 90.0
    if "hybrid" in loc_lower and "hybrid" in preferred_types:
        return 75.0
    return 60.0


def compute_enhanced_score(keyword_score: float, llm_score: float) -> float:
    """Blend keyword and LLM scores. LLM gets higher weight when available."""
    if llm_score > 0:
        return round(keyword_score * 0.35 + llm_score * 0.65, 1)
    return keyword_score


def apply_seniority_penalty(score: float, penalty: float) -> float:
    """Apply seniority mismatch penalty, clamping to [0, 100]."""
    return round(min(100, max(0, score + penalty)), 1)


def apply_competition_bonus(score: float, competition_level: str) -> float:
    """
    Adjust match score based on how many applicants have already applied.
    Fewer applicants = higher priority (act faster on early postings).
    """
    bonus = {
        "first_25": +8.0,   # early posting — jump on it
        "low":      +4.0,
        "medium":    0.0,
        "high":     -5.0,   # flooded with applicants — lower priority
        "unknown":   0.0,
    }.get(competition_level or "unknown", 0.0)
    return round(min(100, max(0, score + bonus)), 1)


def score_jobs_batch(jobs: list[dict], profile: dict) -> list[dict]:
    """Score a batch of jobs and update their match_score field."""
    for job in jobs:
        job["match_score"] = compute_match_score(
            job_title=job.get("title", ""),
            job_description=job.get("description", ""),
            job_location=job.get("location"),
            sponsorship_status=job.get("sponsorship_status", "unknown"),
            profile=profile,
        )
    return jobs
