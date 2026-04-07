"""
LLM-powered semantic job matching.

Uses a local LLM (Ollama) or OpenAI to evaluate how well a job matches the user's profile.
Configure backends in config/secrets.yaml (see secrets.template.yaml).
Results are cached in SQLite to avoid re-scoring.
"""

import json
import time
from typing import Any, Optional

from src.utils.llm_provider import create_llm_client, load_secrets


def create_client(api_key: str = "") -> Optional[Any]:
    """
    Return an LLM client when Ollama or OpenAI is configured.

    ``api_key`` (optional) overrides ``openai_api_key`` in secrets for backward compatibility.
    """
    secrets = load_secrets()
    if api_key and "your-" not in api_key and not api_key.startswith("sk-your"):
        secrets = {**secrets, "openai_api_key": api_key}
    return create_llm_client(secrets)


def score_job_with_llm(
    client: Any,
    job_title: str,
    job_company: str,
    job_description: str,
    profile: dict,
    model: str = "gpt-4o-mini",
) -> dict:
    """
    Score a single job using LLM semantic analysis.

    Returns dict with:
      - llm_score: float 0-100
      - reasoning: str
      - key_matches: list[str]
      - concerns: list[str]
    """
    empty = {"llm_score": 0, "reasoning": "", "key_matches": [], "concerns": []}

    if not job_description:
        empty["reasoning"] = "No description available"
        empty["concerns"] = ["No job description to analyze"]
        return empty

    profile_summary = _build_profile_summary(profile)
    desc = job_description[:3000]

    prompt = (
        "Evaluate how well this job matches the candidate's profile. "
        "Be practical and realistic.\n\n"
        f"JOB:\nTitle: {job_title}\nCompany: {job_company}\n"
        f"Description: {desc}\n\n"
        f"CANDIDATE PROFILE:\n{profile_summary}\n\n"
        "Score the match from 0-100 considering:\n"
        "1. Role alignment (does the job title/responsibilities match target roles?)\n"
        "2. Skills match (does the candidate have the required technical skills?)\n"
        "3. Experience level fit (is the seniority appropriate?)\n"
        "4. Growth opportunity (would this advance the candidate's career?)\n\n"
        "Respond ONLY with valid JSON:\n"
        '{"score": <int 0-100>, "reasoning": "<1-2 sentences>", '
        '"key_matches": ["<skill/qualification that matches>", ...], '
        '"concerns": ["<gap or mismatch>", ...]}'
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a technical recruiter evaluating job-candidate fit. "
                        "Be concise and accurate. Return only valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=300,
        )

        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]

        result = json.loads(text)
        return {
            "llm_score": float(result.get("score", 0)),
            "reasoning": result.get("reasoning", ""),
            "key_matches": result.get("key_matches", []),
            "concerns": result.get("concerns", []),
        }
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        return {**empty, "reasoning": f"Parse error: {e}"}
    except Exception as e:
        return {**empty, "reasoning": f"API error: {e}"}


def score_jobs_batch_llm(
    client: Any,
    jobs: list[dict],
    profile: dict,
    model: str = "gpt-4o-mini",
    max_jobs: int = 50,
    on_progress=None,
) -> list[dict]:
    """
    Score a batch of jobs with LLM. Updates each job dict in place.

    Args:
        on_progress: Optional callback(index, total, job, result) for progress reporting.
    """
    target = jobs[:max_jobs]
    for i, job in enumerate(target):
        if job.get("llm_score") and job["llm_score"] > 0:
            continue

        result = score_job_with_llm(
            client=client,
            job_title=job.get("title", ""),
            job_company=job.get("company", ""),
            job_description=job.get("description", ""),
            profile=profile,
            model=model,
        )
        job["llm_score"] = result["llm_score"]
        job["llm_reasoning"] = result["reasoning"]

        if on_progress:
            on_progress(i, len(target), job, result)

        if i < len(target) - 1:
            time.sleep(0.5)

    return jobs


def _build_profile_summary(profile: dict) -> str:
    """
    Condense the profile YAML into a rich text summary for the LLM prompt.
    Includes work experience with accomplishments and key achievements so the
    LLM can reason about actual experience, not just a skill list.
    """
    lines = []

    target_roles = profile.get("target_roles", [])
    if target_roles:
        lines.append(f"Target roles: {', '.join(target_roles[:5])}")

    level = profile.get("experience_level", "mid")
    years = profile.get("years_of_experience", "")
    if years:
        lines.append(f"Experience: {level} level ({years} years)")
    else:
        lines.append(f"Experience: {level} level")

    visa = profile.get("visa", {})
    if visa.get("requires_sponsorship"):
        lines.append(f"Visa: {visa.get('status', 'Requires sponsorship')} - needs H1B sponsorship")

    # Work experience with accomplishments — gives LLM real context
    for exp in profile.get("work_experience", [])[:3]:
        company = exp.get("company", "")
        title = exp.get("title", "")
        start = exp.get("start", "")
        end = exp.get("end", "present")
        techs = ", ".join(exp.get("technologies", [])[:8])
        lines.append(f"\nRole: {title} at {company} ({start} – {end})")
        if techs:
            lines.append(f"  Tech stack: {techs}")
        for acc in exp.get("accomplishments", [])[:3]:
            lines.append(f"  • {acc}")

    # Key achievements (top quantified wins)
    achievements = profile.get("key_achievements", [])
    if achievements:
        lines.append("\nKey achievements:")
        for ach in achievements[:4]:
            lines.append(f"  • {ach}")

    # Projects
    for proj in profile.get("projects", [])[:2]:
        proj_techs = ", ".join(proj.get("technologies", [])[:5])
        lines.append(f"\nProject: {proj.get('name', '')} — {proj.get('summary', '')}")
        if proj_techs:
            lines.append(f"  Tech: {proj_techs}")

    # Skills summary (flat list for keyword matching)
    skills = profile.get("skills", {})
    all_skills = []
    for items in skills.values():
        if isinstance(items, list):
            all_skills.extend(items)
    if all_skills:
        lines.append(f"\nAll skills: {', '.join(all_skills[:40])}")

    for edu in profile.get("education", [])[:2]:
        if isinstance(edu, dict):
            lines.append(
                f"Education: {edu.get('degree', '')} in {edu.get('field', '')} "
                f"from {edu.get('university', '')}"
            )

    return "\n".join(lines)
