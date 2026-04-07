"""
Daily application planner.

Selects the top N jobs for today's application batch from the DB,
applying diversity rules (max per company) and sponsorship priority.
"""

from datetime import datetime, date
from collections import Counter


def generate_daily_plan(
    jobs: list[dict],
    target_count: int = 25,
    max_per_company: int = 3,
    min_score: float = 30.0,
) -> list[dict]:
    """
    Pick the best jobs for today's batch.

    Args:
        jobs: Unapplied, un-skipped jobs sorted by match_score DESC.
        target_count: How many applications to plan.
        max_per_company: Diversity cap per company.
        min_score: Minimum match score to consider.

    Returns:
        List of selected job dicts with 'plan_rank' added.
    """
    eligible = [j for j in jobs if j.get("match_score", 0) >= min_score]

    sponsor_likely = [j for j in eligible if j.get("sponsorship_status") == "sponsor_likely"]
    rest = [j for j in eligible if j.get("sponsorship_status") != "sponsor_likely"]

    plan: list[dict] = []
    company_counts: Counter = Counter()

    for pool in [sponsor_likely, rest]:
        for job in pool:
            if len(plan) >= target_count:
                break
            company = (job.get("company") or "").strip().lower()
            if company_counts[company] >= max_per_company:
                continue
            plan.append(job)
            company_counts[company] += 1

    plan.sort(key=lambda j: j.get("match_score", 0), reverse=True)

    for i, job in enumerate(plan):
        job["plan_rank"] = i + 1
        job["planned_date"] = date.today().isoformat()

    return plan


def get_plan_summary(plan: list[dict]) -> dict:
    """Return summary statistics for the daily plan."""
    if not plan:
        return {"count": 0}

    scores = [j.get("match_score", 0) for j in plan]
    companies = set(j.get("company", "") for j in plan)
    sources = Counter(j.get("source", "") for j in plan)
    sponsor_count = sum(1 for j in plan if j.get("sponsorship_status") == "sponsor_likely")

    return {
        "count": len(plan),
        "avg_score": sum(scores) / len(scores),
        "min_score": min(scores),
        "max_score": max(scores),
        "unique_companies": len(companies),
        "sources": dict(sources),
        "sponsor_likely": sponsor_count,
        "date": date.today().isoformat(),
    }
