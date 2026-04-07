"""
Profile fitness analysis.

Computes a detailed 0-100 fitness score showing how well the user's
profile matches a specific job, broken down by category. Also generates
actionable resume improvement suggestions.
"""

import re
from typing import Optional


def compute_profile_fitness(job: dict, profile: dict) -> dict:
    """
    Compute a detailed fitness breakdown for a job against the user profile.

    Returns dict with:
      - fitness_score: 0-100 overall
      - breakdown: {category: {score, max, details}}
      - missing_skills: skills the job wants that the user lacks
      - matching_skills: skills that match
      - resume_tips: list of actionable suggestions
    """
    title = job.get("title", "")
    desc = (job.get("description") or "").lower()
    text = f"{title} {desc}".lower()

    user_skills = _flatten_skills(profile.get("skills", {}))
    user_skills_lower = {s.lower() for s in user_skills}
    # Also harvest skills from work_experience tech stacks
    for exp in profile.get("work_experience", []):
        for tech in exp.get("technologies", []):
            user_skills_lower.add(tech.lower())
    job_skills = _extract_job_skills(text, user_skills=user_skills_lower)

    matching = user_skills_lower & job_skills
    missing = job_skills - user_skills_lower

    role_score = _fitness_role(title, profile.get("target_roles", []))
    skills_score, skills_detail = _fitness_skills(matching, missing, job_skills)
    exp_score, exp_detail = _fitness_experience(job, profile)
    sponsor_score = _fitness_sponsorship(job.get("sponsorship_status", "unknown"))
    location_score = _fitness_location(job.get("location"), profile.get("preferences", {}))

    weights = {"role": 25, "skills": 35, "experience": 20, "sponsorship": 10, "location": 10}
    raw = (
        role_score * weights["role"]
        + skills_score * weights["skills"]
        + exp_score * weights["experience"]
        + sponsor_score * weights["sponsorship"]
        + location_score * weights["location"]
    ) / 100

    fitness_score = round(min(100, max(0, raw)), 0)

    breakdown = {
        "Role Alignment": {"score": round(role_score), "max": 100,
                           "detail": _role_detail(title, profile.get("target_roles", []))},
        "Skills Match": {"score": round(skills_score), "max": 100, "detail": skills_detail},
        "Experience Level": {"score": round(exp_score), "max": 100, "detail": exp_detail},
        "Sponsorship": {"score": round(sponsor_score), "max": 100,
                        "detail": job.get("sponsorship_status", "unknown")},
        "Location": {"score": round(location_score), "max": 100,
                     "detail": job.get("location") or "Not specified"},
    }

    resume_tips = _generate_resume_tips(job, profile, matching, missing, exp_score)

    return {
        "fitness_score": int(fitness_score),
        "breakdown": breakdown,
        "matching_skills": sorted(matching),
        "missing_skills": sorted(missing),
        "resume_tips": resume_tips,
    }


def _flatten_skills(skills: dict) -> set[str]:
    """Flatten all skill categories into a single set."""
    result = set()
    for cat_skills in skills.values():
        if isinstance(cat_skills, list):
            result.update(cat_skills)
    return result


_COMMON_TECH_SKILLS = {
    "python", "java", "javascript", "typescript", "c#", "c++", "go", "rust", "ruby",
    "sql", "nosql", "mongodb", "postgresql", "mysql", "redis", "elasticsearch",
    "react", "angular", "vue", "node.js", "express", "django", "flask", "fastapi",
    "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "jenkins", "ci/cd",
    "git", "github", "gitlab", "bitbucket",
    "selenium", "playwright", "cypress", "jest", "mocha", "pytest", "junit",
    "rest", "graphql", "grpc", "microservices", "api",
    "agile", "scrum", "jira", "confluence",
    "machine learning", "deep learning", "nlp", "computer vision", "ai",
    "linux", "bash", "powershell",
    "kafka", "rabbitmq", "spark", "hadoop",
    "figma", "sketch",
    "playwright", "testim", "postman", "browserstack",
    "sealights", "datadog", "splunk", "grafana",
    "openai", "langchain", "huggingface",
}


def _extract_job_skills(text: str, user_skills: set = None) -> set[str]:
    """
    Extract likely skill/technology mentions from job text.
    Unions the hardcoded common set with the user's actual skills so personal
    technologies (Sealights, Testim, BrowserStack, etc.) are always checked.
    """
    found = set()
    check_set = _COMMON_TECH_SKILLS | ({s.lower() for s in (user_skills or set())})
    for skill in check_set:
        pattern = r"\b" + re.escape(skill) + r"\b"
        if re.search(pattern, text):
            found.add(skill)
    return found


def _fitness_role(title: str, target_roles: list[str]) -> float:
    title_lower = title.lower()
    for role in target_roles:
        if role.lower() in title_lower:
            return 100.0
    keywords = {"sdet", "test", "qa", "quality", "automation", "software", "engineer"}
    matched = sum(1 for kw in keywords if kw in title_lower)
    return min(100, matched * 25)


def _role_detail(title: str, target_roles: list[str]) -> str:
    title_lower = title.lower()
    for role in target_roles:
        if role.lower() in title_lower:
            return f"Direct match: {role}"
    return "Partial keyword match"


def _fitness_skills(matching: set, missing: set, job_skills: set) -> tuple[float, str]:
    if not job_skills:
        return 60.0, "No specific skills detected in job posting"
    ratio = len(matching) / len(job_skills) if job_skills else 0
    score = min(100, ratio * 120)
    detail = f"{len(matching)}/{len(job_skills)} skills matched"
    return score, detail


def _fitness_experience(job: dict, profile: dict) -> tuple[float, str]:
    user_years = profile.get("years_of_experience", 3)
    req_years = job.get("required_years")
    seniority = job.get("seniority_level", "mid")

    if not req_years:
        if seniority in ("entry", "mid"):
            return 85.0, f"Level: {seniority} (good fit for {user_years} yrs)"
        return 50.0, f"Level: {seniority} (may need more experience)"

    if user_years >= req_years:
        return 100.0, f"You have {user_years} yrs, job needs {req_years}+"
    gap = req_years - user_years
    if gap <= 1:
        return 75.0, f"Close: {user_years} yrs vs {req_years}+ required"
    if gap <= 2:
        return 45.0, f"Gap: {user_years} yrs vs {req_years}+ required"
    return 20.0, f"Big gap: {user_years} yrs vs {req_years}+ required"


def _fitness_sponsorship(status: str) -> float:
    return {"sponsor_likely": 100.0, "sponsor_unlikely": 15.0, "unknown": 50.0}.get(status, 50.0)


def _fitness_location(location: Optional[str], preferences: dict) -> float:
    if not location:
        return 50.0
    loc_lower = location.lower()
    preferred = preferences.get("location_types", ["remote", "hybrid", "onsite"])
    if "remote" in loc_lower and "remote" in preferred:
        return 100.0
    if "hybrid" in loc_lower and "hybrid" in preferred:
        return 80.0
    return 60.0


def _generate_resume_tips(job: dict, profile: dict, matching: set,
                          missing: set, exp_score: float) -> list[str]:
    """Generate actionable resume improvement suggestions for this specific job."""
    tips = []
    title = job.get("title", "")
    desc = (job.get("description") or "").lower()

    if missing:
        top_missing = sorted(missing)[:5]
        tips.append(
            f"Add these skills to your resume (mentioned in this job): "
            f"**{', '.join(top_missing)}**"
        )

    if matching:
        tips.append(
            f"Highlight these matching skills prominently: "
            f"**{', '.join(sorted(matching)[:5])}**"
        )

    # Surface relevant achievements from work experience
    achievements = profile.get("key_achievements", [])
    title_lower = title.lower()
    if achievements and any(kw in title_lower for kw in ["automation", "sdet", "qa", "test"]):
        top_achievement = achievements[0]
        tips.append(f"Lead your Professional Summary with: \"{top_achievement}\"")

    if "automation" in title_lower and "automation" not in desc[:200]:
        tips.append("Quantify your automation impact (e.g., 'automated X tests reducing regression time by Y%')")

    if any(kw in desc for kw in ["ci/cd", "pipeline", "continuous"]):
        tips.append("Emphasize your CI/CD pipeline experience with specific tools (Azure DevOps, Jenkins, etc.)")

    if any(kw in desc for kw in ["api test", "rest", "postman", "api"]):
        tips.append("Add a bullet about API testing experience -- mention tools, protocols, and scale")

    if any(kw in desc for kw in ["cloud", "aws", "azure", "gcp"]):
        tips.append("Highlight cloud platform experience -- certifications are a strong signal here")

    if any(kw in desc for kw in ["ai", "machine learning", "llm", "generative"]):
        proj_names = [p.get("name", "") for p in profile.get("projects", [])]
        ai_proj = next((p for p in proj_names if "ai" in p.lower() or "agent" in p.lower()), None)
        if ai_proj:
            tips.append(f"Feature your '{ai_proj}' project prominently — AI/LLM experience is highly sought after")
        else:
            tips.append("Feature your AI agent and custom AI solution work prominently -- this is highly sought after")

    if any(kw in desc for kw in ["agile", "scrum", "sprint"]):
        tips.append("Mention Agile/Scrum ceremony participation and cross-team collaboration examples")

    if exp_score < 60:
        tips.append(
            "This role may want more experience than you have -- "
            "compensate by highlighting project impact and breadth of skills"
        )

    if not tips:
        tips.append("Your profile is a strong match -- tailor your summary to mirror this job's keywords")

    return tips


def format_fitness_discord(result: dict) -> str:
    """Format the fitness result for a Discord message."""
    score = result["fitness_score"]

    if score >= 80:
        grade = "Excellent"
        bar_emoji = "\U0001f7e2"
    elif score >= 60:
        grade = "Good"
        bar_emoji = "\U0001f7e1"
    elif score >= 40:
        grade = "Fair"
        bar_emoji = "\U0001f7e0"
    else:
        grade = "Weak"
        bar_emoji = "\U0001f534"

    lines = [f"**Profile Fitness: {score}/100** ({grade}) {bar_emoji}\n"]

    for cat, data in result["breakdown"].items():
        filled = data["score"] // 10
        empty = 10 - filled
        bar = "\u2588" * filled + "\u2591" * empty
        lines.append(f"`{bar}` **{cat}**: {data['score']}/100 -- {data['detail']}")

    if result["matching_skills"]:
        lines.append(f"\n**Your matching skills**: {', '.join(result['matching_skills'][:8])}")
    if result["missing_skills"]:
        lines.append(f"**Skills to add**: {', '.join(result['missing_skills'][:6])}")

    if result["resume_tips"]:
        lines.append("\n**Resume Tips for this job:**")
        for i, tip in enumerate(result["resume_tips"][:5], 1):
            lines.append(f"{i}. {tip}")

    return "\n".join(lines)
