"""
Quality gate for generated documents.

Scores tailored resumes and cover letters on ATS compliance, keyword match,
relevance, and readability. Documents must score >= 7/10 to pass.
Failed documents trigger up to 2 regeneration attempts.
"""

import json
from typing import Any, Optional

PASS_THRESHOLD = 7.0
MAX_RETRIES = 2


def score_document(
    client: Any,
    document_text: str,
    job_title: str,
    job_description: str,
    doc_type: str = "resume",
    model: str = "gpt-4o-mini",
) -> dict:
    """
    Score a document on quality dimensions.

    Returns dict with:
      - overall_score: float (1-10)
      - ats_compliance: float (1-10)
      - keyword_match: float (1-10)
      - relevance: float (1-10)
      - readability: float (1-10)
      - passed: bool
      - feedback: str
      - improvements: list[str]
    """
    prompt = (
        f"Score this {doc_type} for a '{job_title}' application.\n\n"
        f"DOCUMENT:\n{document_text[:3000]}\n\n"
        f"JOB DESCRIPTION:\n{job_description[:2000]}\n\n"
        "Score each dimension from 1-10:\n"
        "1. ATS compliance (simple formatting, standard headings, no tables/graphics)\n"
        "2. Keyword match (mirrors exact phrases from job description)\n"
        "3. Relevance (content directly addresses the role requirements)\n"
        "4. Readability (clear, professional, concise)\n\n"
        f"A {doc_type} MUST score >= 7.0 overall to pass.\n\n"
        "Respond with valid JSON:\n"
        "{\n"
        '  "ats_compliance": <1-10>,\n'
        '  "keyword_match": <1-10>,\n'
        '  "relevance": <1-10>,\n'
        '  "readability": <1-10>,\n'
        '  "overall_score": <1-10 weighted average>,\n'
        '  "feedback": "<1-2 sentence overall assessment>",\n'
        '  "improvements": ["<specific improvement>", ...]\n'
        "}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict ATS compliance auditor and resume reviewer. "
                        "Score honestly. Be specific about improvements. Return only valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=400,
        )

        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]

        result = json.loads(text)
        overall = float(result.get("overall_score", 0))
        result["passed"] = overall >= PASS_THRESHOLD
        result["overall_score"] = overall
        return result
    except Exception as e:
        return {
            "overall_score": 0, "ats_compliance": 0, "keyword_match": 0,
            "relevance": 0, "readability": 0, "passed": False,
            "feedback": f"Scoring failed: {e}", "improvements": [],
        }


def run_quality_gate(
    client: Any,
    resume_text: str,
    cover_letter_text: str,
    job_title: str,
    job_description: str,
    model: str = "gpt-4o-mini",
) -> dict:
    """
    Run quality gate on both resume and cover letter.

    Returns dict with resume_score, cover_letter_score, and overall passed status.
    """
    resume_result = score_document(
        client, resume_text, job_title, job_description,
        doc_type="resume", model=model,
    )
    cl_result = score_document(
        client, cover_letter_text, job_title, job_description,
        doc_type="cover letter", model=model,
    )

    return {
        "resume": resume_result,
        "cover_letter": cl_result,
        "passed": resume_result.get("passed", False) and cl_result.get("passed", False),
        "resume_score": resume_result.get("overall_score", 0),
        "cover_letter_score": cl_result.get("overall_score", 0),
    }


def extract_text_from_docx(docx_path) -> str:
    """Extract plain text from a docx file for scoring."""
    from docx import Document
    doc = Document(str(docx_path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
