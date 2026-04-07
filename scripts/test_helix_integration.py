#!/usr/bin/env python3
"""
Local integration check: schedule (your timezone), keyword matching, Helix voice strings.
Does not start Discord or call OpenAI.

Run from repo root:
  python scripts/test_helix_integration.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    import yaml

    profile_path = ROOT / "config" / "profile.yaml"
    if not profile_path.exists():
        print("Missing config/profile.yaml — copy from profile.template.yaml first.")
        return 1

    with open(profile_path, "r", encoding="utf-8") as f:
        profile = yaml.safe_load(f)

    from src.utils.schedule import coerce_schedule, describe_next_events, user_local_day_key
    from src.matching.scorer import compute_match_score
    from src.discord import voice as helix_voice

    sched = coerce_schedule(profile)
    print("=== Schedule (coerced) ===")
    print(describe_next_events(sched))
    print(f"\nLocal today key: {user_local_day_key(sched)}")

    print("\n=== Sample keyword match score ===")
    sample = {
        "title": "Senior SDET — API test automation",
        "description": "Python, Playwright, CI/CD, REST APIs, AWS. 5+ years QA automation.",
        "location": "Remote — United States",
        "sponsorship": "unknown",
    }
    score = compute_match_score(
        sample["title"],
        sample["description"],
        sample["location"],
        sample["sponsorship"],
        profile,
    )
    print(f"Job: {sample['title']}")
    print(f"Keyword match score: {score}/100 (LLM layer not run here)")

    print("\n=== Helix voice samples ===")
    print(f"Approve / apply card: {helix_voice.APPROVE_APPLY_CARD[:80]}...")
    print(f"Applied confirm: {helix_voice.APPLIED_CONFIRM}")
    print(f"Morning footer (3 pending, 1 follow-up): {helix_voice.morning_footer(3, 1)}")
    print(f"Evening footer (goal met): {helix_voice.evening_footer(5, 5)}")
    print(f"Evening footer (under goal): {helix_voice.evening_footer(1, 5)}")

    try:
        from src.matching.profile_fitness import compute_profile_fitness

        job_row = {
            "title": sample["title"],
            "company": "Example Corp",
            "location": sample["location"],
            "description": sample["description"],
            "url": "https://example.com/job",
            "sponsorship_status": "unknown",
            "match_score": score,
        }
        fit = compute_profile_fitness(job_row, profile)
        print("\n=== Profile fitness (same sample job) ===")
        print(f"Fitness score: {fit.get('fitness_score', 0)}/100")
    except Exception as e:
        print(f"\n(Fitness check skipped: {e})")

    print("\nDone. Next: start the bot and run /schedule, /review, /today in Discord.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
