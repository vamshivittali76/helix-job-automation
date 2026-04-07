"""
LLM-powered company research.

For each job in the daily plan, generates a concise company brief to help
personalize cover letters and prepare for interviews.
"""

import json
import time
from typing import Any, Optional


def research_company(
    client: Any,
    company: str,
    job_title: str,
    job_description: str = "",
    model: str = "gpt-4o-mini",
) -> dict:
    """
    Research a company using LLM knowledge.

    Returns dict with: summary, size, industry, culture, h1b_history, talking_points
    """
    empty = {
        "summary": "", "size": "unknown", "industry": "unknown",
        "culture": "", "h1b_history": "unknown", "talking_points": [],
    }

    desc_snippet = job_description[:1500] if job_description else "N/A"

    prompt = (
        f"Research this company for a job application.\n\n"
        f"Company: {company}\n"
        f"Role: {job_title}\n"
        f"Job Description snippet: {desc_snippet}\n\n"
        "Provide a concise research brief. Respond ONLY with valid JSON:\n"
        "{\n"
        '  "summary": "<2-3 sentence company overview>",\n'
        '  "size": "<startup / mid-size / enterprise / unknown>",\n'
        '  "industry": "<primary industry>",\n'
        '  "culture": "<1-2 sentences on work culture, values>",\n'
        '  "h1b_history": "<known H1B sponsor / likely sponsor / unknown / unlikely>",\n'
        '  "talking_points": ["<specific point to mention in cover letter>", ...]\n'
        "}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a career research assistant. Provide factual, concise company "
                        "information useful for job applications. Return only valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=400,
        )

        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]

        return json.loads(text)
    except Exception as e:
        return {**empty, "summary": f"Research failed: {e}"}


def research_companies_batch(
    client: Any,
    jobs: list[dict],
    model: str = "gpt-4o-mini",
    on_progress=None,
) -> list[dict]:
    """Research companies for a batch of jobs. Skips already-researched jobs."""
    for i, job in enumerate(jobs):
        if job.get("company_research") and job["company_research"] != "":
            if on_progress:
                on_progress(i, len(jobs), job, None)
            continue

        result = research_company(
            client=client,
            company=job.get("company", ""),
            job_title=job.get("title", ""),
            job_description=job.get("description", ""),
            model=model,
        )
        job["company_research"] = json.dumps(result)

        if on_progress:
            on_progress(i, len(jobs), job, result)

        if i < len(jobs) - 1:
            time.sleep(0.5)

    return jobs
