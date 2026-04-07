"""
Apply flow: DB transitions (review → approved → applied), reminders, apply-card embed.
No Discord runtime — safe for CI.
"""

import pytest

import src.tracker.db as db


def test_job_insert_and_apply_lifecycle(tmp_db):
    job = {
        "id": "test_apply_flow_01",
        "title": "Senior SDET",
        "company": "Acme Labs",
        "url": "https://example.com/jobs/1",
        "source": "test",
        "location": "Remote — US",
        "match_score": 82.0,
        "description": "Python, Playwright, APIs.",
    }
    assert db.insert_job(job) is True
    assert db.insert_job(job) is False  # duplicate

    db.update_application_status(job["id"], "pending_review", source="test")
    assert db.get_job(job["id"])["application_status"] == "pending_review"

    db.update_application_status(job["id"], "approved", source="discord")
    assert db.get_job(job["id"])["application_status"] == "approved"

    db.update_application_status(job["id"], "applied", source="discord")
    row = db.get_job(job["id"])
    assert row["application_status"] == "applied"
    assert row["is_applied"] == 1
    assert row.get("date_applied")


def test_reminder_due_immediately(tmp_db):
    db.add_reminder(999001, "Test reminder body", delay_seconds=0, job_id="jid")
    due = db.get_due_reminders()
    assert len(due) == 1
    assert due[0]["message"] == "Test reminder body"
    db.mark_reminder_fired(due[0]["id"])
    assert db.get_due_reminders() == []


def test_schedule_event_claim_once_per_day(tmp_db):
    assert db.try_claim_schedule_event("2026-04-07", "morning_digest") is True
    assert db.try_claim_schedule_event("2026-04-07", "morning_digest") is False
    assert db.try_claim_schedule_event("2026-04-08", "morning_digest") is True


def test_apply_card_embed_builds():
    from src.discord.views import _build_apply_card_embed

    embed = _build_apply_card_embed(
        {
            "title": "QA Automation Engineer",
            "company": "Example Co",
            "url": "https://boards.greenhouse.io/example/jobs/123",
            "location": "Remote",
            "match_score": 76.0,
            "competition_level": "medium",
            "applicant_label": "Over 100 applicants",
            "sponsorship_status": "sponsor_likely",
            "salary_min": 120000,
            "salary_max": 150000,
        }
    )
    assert embed.title.startswith("Apply")
    assert embed.url.startswith("https://")
    assert embed.fields  # match score, etc.


def test_voice_strings_import():
    from src.discord import voice as v

    assert "apply card" in v.APPROVE_APPLY_CARD.lower()
    assert v.TAGLINE
