"""
ATS email classification.

Classifies emails from job application systems into statuses:
  - rejection, interview_invite, assessment, offer, follow_up, generic

Uses keyword patterns first (fast), then LLM for ambiguous cases.
Matches emails to jobs in the DB using fuzzy company name matching.
"""

import re
from typing import Optional
from thefuzz import fuzz

REJECTION_SIGNALS = [
    "unfortunately", "not moving forward", "other candidates",
    "decided not to", "not selected", "will not be proceeding",
    "position has been filled", "gone with another candidate",
    "after careful consideration", "regret to inform",
    "not a match", "unable to offer", "not be moving forward",
    "pursuing other applicants", "application was not selected",
]

INTERVIEW_SIGNALS = [
    "schedule an interview", "interview invitation",
    "like to schedule", "meet with", "phone screen",
    "technical interview", "next steps in the process",
    "available for a call", "interview slot", "book a time",
    "calendly", "scheduler", "onsite interview", "virtual interview",
]

ASSESSMENT_SIGNALS = [
    "assessment", "coding challenge", "take-home",
    "hackerrank", "codility", "codesignal", "leetcode",
    "technical test", "skills test", "online test",
]

OFFER_SIGNALS = [
    "offer letter", "pleased to offer", "extending an offer",
    "compensation package", "start date", "welcome aboard",
    "offer of employment", "we'd like to offer",
]

FOLLOW_UP_SIGNALS = [
    "checking in", "following up", "any updates",
    "status of my application", "next steps",
]


def classify_email(subject: str, body: str) -> dict:
    """
    Classify an email into an application status.

    Returns dict with: status, confidence, matched_signals
    """
    text = f"{subject} {body}".lower()

    all_matches = {}
    for signals, status in [
        (OFFER_SIGNALS, "offer"),
        (INTERVIEW_SIGNALS, "interviewing"),
        (ASSESSMENT_SIGNALS, "assessment"),
        (REJECTION_SIGNALS, "rejected"),
        (FOLLOW_UP_SIGNALS, "follow_up"),
    ]:
        matched = [s for s in signals if s in text]
        if matched:
            confidence = min(1.0, len(matched) * 0.3 + 0.4)
            all_matches[status] = {
                "status": status,
                "confidence": round(confidence, 2),
                "matched_signals": matched,
            }

    if all_matches:
        priority = ["offer", "rejected", "interviewing", "assessment", "follow_up"]
        for p in priority:
            if p in all_matches:
                return all_matches[p]

    return {"status": "generic", "confidence": 0.1, "matched_signals": []}


def classify_email_with_llm(
    client,
    subject: str,
    body: str,
    model: str = "gpt-4o-mini",
) -> dict:
    """Use LLM for ambiguous emails that keyword matching can't resolve."""
    import json

    prompt = (
        "Classify this email from a job application process.\n\n"
        f"Subject: {subject}\n"
        f"Body: {body[:1500]}\n\n"
        "Classify as exactly one of: rejection, interviewing, assessment, offer, follow_up, generic\n\n"
        'Respond with JSON: {"status": "<classification>", "confidence": <0.0-1.0>, "reasoning": "<brief>"}'
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You classify job application emails. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=150,
        )
        text = (response.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        result = json.loads(text)
        result.setdefault("matched_signals", [])
        return result
    except Exception:
        return classify_email(subject, body)


def match_email_to_job(
    sender: str,
    subject: str,
    body: str,
    jobs: list[dict],
    threshold: int = 65,
) -> Optional[dict]:
    """Match an email to a job in the DB using company name fuzzy matching."""
    text = f"{sender} {subject} {body}".lower()

    best_match = None
    best_score = 0

    for job in jobs:
        company = (job.get("company") or "").lower()
        if not company or len(company) < 2:
            continue

        if company in text:
            score = 100
        else:
            score = fuzz.partial_ratio(company, text)

        if score > best_score and score >= threshold:
            best_score = score
            best_match = job

    if best_match:
        return {"job": best_match, "confidence": best_score / 100.0}
    return None
