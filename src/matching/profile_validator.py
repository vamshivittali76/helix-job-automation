"""
Profile completeness validator.

Checks config/profile.yaml for missing or thin sections that reduce
the quality of LLM scoring, resume tailoring, and fitness analysis.
Returns a list of warning strings; empty list means profile is complete.
"""

from typing import Optional


def validate_profile(profile: dict) -> list[str]:
    """
    Validate profile completeness. Returns list of warning strings.
    Empty list = fully complete profile.
    """
    warnings = []

    # ── Personal info ───────────────────────────────────────
    personal = profile.get("personal", {})
    for field in ("first_name", "last_name", "email", "phone", "linkedin"):
        if not personal.get(field):
            warnings.append(f"personal.{field} is missing — required for form auto-fill")

    # ── Work experience ─────────────────────────────────────
    work_exp = profile.get("work_experience", [])
    if not work_exp:
        warnings.append(
            "work_experience is empty — LLM scoring will be generic; "
            "add at least one role with accomplishments"
        )
    else:
        for i, exp in enumerate(work_exp):
            label = f"work_experience[{i}] ({exp.get('company', 'unknown')})"
            if not exp.get("accomplishments"):
                warnings.append(
                    f"{label}: no accomplishments listed — "
                    "quantified bullets dramatically improve resume tailoring quality"
                )
            elif len(exp.get("accomplishments", [])) < 2:
                warnings.append(
                    f"{label}: only {len(exp['accomplishments'])} accomplishment(s) — "
                    "aim for 2-4 quantified bullets per role"
                )
            if not exp.get("technologies"):
                warnings.append(f"{label}: no technologies listed — used for skill matching")

    # ── Key achievements ────────────────────────────────────
    achievements = profile.get("key_achievements", [])
    if not achievements:
        warnings.append(
            "key_achievements is empty — resume Professional Summary will be generic; "
            "add 3-5 quantified impact statements"
        )
    elif len(achievements) < 3:
        warnings.append(
            f"key_achievements has only {len(achievements)} item(s) — "
            "add at least 3 for best resume tailoring"
        )

    # ── Skills ──────────────────────────────────────────────
    skills = profile.get("skills", {})
    all_skills = []
    for items in skills.values():
        if isinstance(items, list):
            all_skills.extend(items)
    if len(all_skills) < 10:
        warnings.append(
            f"Only {len(all_skills)} skills listed — add more to improve keyword matching score"
        )

    # ── Projects ────────────────────────────────────────────
    if not profile.get("projects"):
        warnings.append(
            "projects section is empty — adding side projects strengthens AI/automation roles"
        )

    # ── Education ───────────────────────────────────────────
    if not profile.get("education"):
        warnings.append("education section is empty — required for most ATS forms")

    # ── Target roles ────────────────────────────────────────
    target_roles = profile.get("target_roles", [])
    if not target_roles:
        warnings.append("target_roles is empty — role matching will score 0")
    elif len(target_roles) < 3:
        warnings.append(
            f"Only {len(target_roles)} target role(s) — add aliases to catch more jobs "
            "(e.g. 'Test Automation Engineer', 'Software Quality Engineer')"
        )

    # ── Visa ────────────────────────────────────────────────
    visa = profile.get("visa", {})
    if "requires_sponsorship" not in visa:
        warnings.append(
            "visa.requires_sponsorship not set — sponsorship scoring will default to 'unknown'"
        )

    return warnings


def profile_completeness_score(profile: dict) -> int:
    """
    Return a 0-100 completeness score based on how many sections are filled.
    """
    checks = [
        bool(profile.get("personal", {}).get("first_name")),
        bool(profile.get("personal", {}).get("email")),
        bool(profile.get("personal", {}).get("linkedin")),
        bool(profile.get("work_experience")),
        any(
            exp.get("accomplishments")
            for exp in profile.get("work_experience", [])
        ),
        bool(profile.get("key_achievements")),
        len(profile.get("key_achievements", [])) >= 3,
        bool(profile.get("projects")),
        bool(profile.get("skills")),
        sum(
            len(v) for v in profile.get("skills", {}).values()
            if isinstance(v, list)
        ) >= 15,
        bool(profile.get("education")),
        bool(profile.get("target_roles")),
        len(profile.get("target_roles", [])) >= 4,
        "requires_sponsorship" in profile.get("visa", {}),
    ]
    filled = sum(1 for c in checks if c)
    return round(filled / len(checks) * 100)


def format_validation_report(profile: dict) -> str:
    """Format a human-readable validation report for CLI and Discord output."""
    warnings = validate_profile(profile)
    score = profile_completeness_score(profile)

    if score >= 90:
        grade = "Excellent"
        icon = "[green]PASS[/green]"
    elif score >= 70:
        grade = "Good"
        icon = "[yellow]GOOD[/yellow]"
    elif score >= 50:
        grade = "Needs work"
        icon = "[yellow]WARN[/yellow]"
    else:
        grade = "Incomplete"
        icon = "[red]FAIL[/red]"

    lines = [
        f"{icon} [bold]Profile Completeness: {score}/100[/bold] ({grade})",
    ]

    if warnings:
        lines.append(f"\n[yellow]{len(warnings)} issue(s) found:[/yellow]\n")
        for i, w in enumerate(warnings, 1):
            lines.append(f"{i}. {w}")
    else:
        lines.append("\n[green]All sections complete -- ready for best-quality applications![/green]")

    return "\n".join(lines)
