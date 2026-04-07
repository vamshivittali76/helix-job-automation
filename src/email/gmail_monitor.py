"""
Gmail inbox monitor (READ-ONLY).

Polls the inbox for application-related emails, classifies them,
matches them to jobs in the DB, and updates application statuses.

SAFETY: This module NEVER sends, deletes, modifies, or moves emails.
It only reads subject lines and bodies for classification.
"""

import base64
from datetime import datetime
from typing import Optional

from src.email.email_parser import classify_email, match_email_to_job

EMAIL_STATUS_MAP = {
    "rejected": "rejected_by_company",
    "interviewing": "interview",
    "assessment": "interview",
    "offer": "offer",
}


def poll_inbox(
    service,
    jobs: list[dict],
    max_results: int = 50,
    after_date: str = None,
    llm_client=None,
    auto_update_db: bool = True,
    on_status_change=None,
) -> list[dict]:
    """
    Poll Gmail inbox for application-related emails.

    Args:
        service: Gmail API service object from gmail_auth.
        jobs: List of applied jobs to match against.
        max_results: Max emails to fetch per poll.
        after_date: Only check emails after this date (YYYY/MM/DD).
        llm_client: Optional unified LLM client (Ollama or OpenAI) for ambiguous classification.
        auto_update_db: If True, auto-update job statuses and log to email_log.
        on_status_change: Optional callback(job_id, old_status, new_status, email_info)
                          for triggering Discord notifications, Excel sync, etc.

    Returns:
        List of classified email results.
    """
    query = _build_search_query(after_date)

    try:
        messages = []
        page_token = None
        while len(messages) < max_results:
            kwargs = {"userId": "me", "q": query, "maxResults": min(50, max_results - len(messages))}
            if page_token:
                kwargs["pageToken"] = page_token
            results = service.users().messages().list(**kwargs).execute()
            messages.extend(results.get("messages", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break
    except Exception as e:
        return [{"error": f"Gmail API error: {e}"}]

    if not messages:
        return []

    classified = []
    for msg_stub in messages:
        msg_data = _fetch_message(service, msg_stub["id"])
        if not msg_data:
            continue

        classification = classify_email(msg_data["subject"], msg_data["body"])

        if classification["status"] == "generic" and classification["confidence"] < 0.3:
            if llm_client:
                from src.email.email_parser import classify_email_with_llm
                classification = classify_email_with_llm(
                    llm_client, msg_data["subject"], msg_data["body"]
                )

        if classification["status"] == "generic":
            continue

        job_match = match_email_to_job(
            sender=msg_data["sender"],
            subject=msg_data["subject"],
            body=msg_data["body"],
            jobs=jobs,
        )

        result = {
            "gmail_message_id": msg_stub["id"],
            "subject": msg_data["subject"],
            "sender": msg_data["sender"],
            "received_date": msg_data["date"],
            "classified_status": classification["status"],
            "confidence": classification["confidence"],
            "matched_signals": classification.get("matched_signals", []),
            "matched_job_id": job_match["job"]["id"] if job_match else None,
            "matched_job_title": job_match["job"]["title"] if job_match else None,
            "matched_company": job_match["job"]["company"] if job_match else None,
            "match_confidence": job_match["confidence"] if job_match else 0,
            "snippet": msg_data["body"][:200],
        }
        classified.append(result)

        if auto_update_db and job_match and classification["confidence"] >= 0.5:
            _auto_update_status(result, job_match["job"], on_status_change)

    return classified


def _auto_update_status(email_result: dict, matched_job: dict, on_status_change=None):
    """Auto-update the job's application status based on the email classification."""
    from src.tracker.db import update_application_status, get_connection

    conn = get_connection()
    already_logged = conn.execute(
        "SELECT 1 FROM email_log WHERE gmail_message_id = ?",
        (email_result["gmail_message_id"],),
    ).fetchone()

    if not already_logged:
        conn.execute(
            """INSERT OR IGNORE INTO email_log
               (gmail_message_id, subject, sender, received_date,
                classified_status, matched_job_id, confidence, raw_snippet, processed_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                email_result["gmail_message_id"],
                email_result["subject"],
                email_result["sender"],
                email_result["received_date"],
                email_result["classified_status"],
                email_result["matched_job_id"],
                email_result["confidence"],
                email_result["snippet"],
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
    conn.close()

    if already_logged:
        return

    new_status = EMAIL_STATUS_MAP.get(email_result["classified_status"])
    if not new_status:
        return

    old_status = matched_job.get("application_status", "applied")
    if old_status == new_status:
        return

    STATUS_PRIORITY = {
        "new": 0, "pending_review": 1, "approved": 2, "preparing": 3,
        "applied": 4, "interview": 5, "offer": 6, "accepted": 7,
    }
    if STATUS_PRIORITY.get(new_status, 0) < STATUS_PRIORITY.get(old_status, 0):
        if new_status != "rejected_by_company":
            return

    update_application_status(
        email_result["matched_job_id"],
        new_status,
        source="email",
        details=f"Email: {email_result['subject'][:100]}",
    )

    if on_status_change:
        on_status_change(
            email_result["matched_job_id"],
            old_status,
            new_status,
            email_result,
        )


def _build_search_query(after_date: str = None) -> str:
    """Build Gmail search query for application-related emails."""
    base_terms = [
        "application",
        "interview",
        "position",
        "candidacy",
        "opportunity",
        "role",
    ]
    query = f"({' OR '.join(base_terms)})"
    query += " -category:promotions -category:social"

    if after_date:
        query += f" after:{after_date}"

    return query


def _fetch_message(service, message_id: str) -> Optional[dict]:
    """Fetch a single email message and extract subject, sender, body, date."""
    try:
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}

        subject = headers.get("subject", "")
        sender = headers.get("from", "")
        date = headers.get("date", "")

        body = _extract_body(msg.get("payload", {}))

        return {
            "subject": subject,
            "sender": sender,
            "date": date,
            "body": body,
        }
    except Exception:
        return None


def _extract_body(payload: dict) -> str:
    """Extract text body from email payload, preferring plain text, falling back to HTML."""
    if payload.get("body", {}).get("data"):
        mime = payload.get("mimeType", "")
        raw = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        if mime == "text/html":
            return _strip_html(raw)
        return raw

    parts = payload.get("parts", [])

    for part in parts:
        mime = part.get("mimeType", "")
        if mime == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

    for part in parts:
        mime = part.get("mimeType", "")
        if mime == "text/html" and part.get("body", {}).get("data"):
            raw = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            return _strip_html(raw)

    for part in parts:
        if part.get("parts"):
            result = _extract_body(part)
            if result:
                return result

    return ""


def _strip_html(html: str) -> str:
    """Strip HTML tags to get readable text."""
    import re
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
