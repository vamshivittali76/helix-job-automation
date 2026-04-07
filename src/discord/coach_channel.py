"""
Natural-language coach channel: paste job URLs for fit/viability/tips, or ask for
cover letters, LinkedIn outreach, resume help, and general career questions.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# channel_id -> last analyzed job dict (for follow-ups like "cover letter")
_LAST_JOB_BY_CHANNEL: dict[int, dict[str, Any]] = {}

_URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+", re.IGNORECASE)


def extract_urls(text: str) -> list[str]:
    """Find HTTP(S) URLs in a message; trim common trailing punctuation."""
    out: list[str] = []
    for m in _URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(").,;\"'")
        if u.startswith("http"):
            out.append(u)
    return out


def split_discord_chunks(text: str, limit: int = 1900) -> list[str]:
    """Split long text for Discord message limits (2000; use margin)."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            chunks.append(rest.strip())
            break
        cut = rest.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    return [c for c in chunks if c]


def _profile_summary(profile: dict) -> str:
    personal = profile.get("personal", {})
    skills = profile.get("skills", {})
    lines = [
        f"Name: {personal.get('first_name', '')} {personal.get('last_name', '')}".strip(),
        f"Location: {personal.get('location', '')}",
        f"Experience: {profile.get('years_of_experience', '')} years, {profile.get('experience_level', '')}",
        f"Target roles: {', '.join(profile.get('target_roles', []))}",
    ]
    for category, items in skills.items():
        if isinstance(items, list) and items:
            lines.append(f"{category}: {', '.join(items[:25])}")
    return "\n".join(lines)


def _infer_sponsorship_hint(description: str) -> str:
    d = (description or "").lower()
    if any(x in d for x in ("h1b", "h-1b", "visa sponsorship", "sponsor visa", "will sponsor")):
        return "sponsor_likely"
    if "no sponsorship" in d or "unable to sponsor" in d or "does not sponsor" in d:
        return "sponsor_unlikely"
    return "unknown"


def _guess_company(soup: Any, url: str) -> str:
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content"):
        return str(og["content"]).strip()[:120]
    netloc = urlparse(url).netloc.lower().replace("www.", "")
    if netloc:
        return netloc.split(".")[0].replace("-", " ").title()
    return "Unknown"


def fetch_job_snapshot(url: str) -> tuple[dict[str, Any] | None, str | None]:
    """
    Fetch HTML and build a minimal job dict: title, company, description, url.
    Returns (job, error_message).
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None, "beautifulsoup4 is required (pip install beautifulsoup4)."

    try:
        from src.apply.url_resolver import resolve_url

        resolved = (resolve_url(url.strip()) or url.strip()).strip()
        url = resolved
    except Exception as e:
        return None, f"Could not resolve URL: {e}"

    try:
        try:
            import cloudscraper

            session = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
        except ImportError:
            import requests

            session = requests.Session()
            session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
            })

        resp = session.get(url, timeout=25, allow_redirects=True)
        html = resp.text or ""
    except Exception as e:
        return None, f"Failed to fetch page: {e}"

    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title_el = soup.find("title")
        title = (title_el.get_text(strip=True) if title_el else "") or "Job posting"
        title = re.sub(r"\s+", " ", title)[:300]
        company = _guess_company(soup, url)
        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text[:18000]
        loc = ""
        og_loc = soup.find("meta", attrs={"name": "jobLocation"})
        if og_loc and og_loc.get("content"):
            loc = str(og_loc["content"])[:200]
        job: dict[str, Any] = {
            "title": title,
            "company": company,
            "description": text,
            "url": url,
            "location": loc,
            "sponsorship_status": _infer_sponsorship_hint(text),
        }
        return job, None
    except Exception as e:
        return None, f"Could not parse page: {e}"


def _viability_line(match_score: float, fitness: int, status: Any) -> str:
    if not getattr(status, "active", True):
        return "**Viability:** Low — the page suggests this listing may be closed or unavailable."
    parts = []
    if fitness >= 75 and match_score >= 55:
        parts.append("profile and keywords align well")
    elif fitness >= 55:
        parts.append("reasonable fit")
    else:
        parts.append("mixed fit — tailoring and gaps to address")

    comp = getattr(status, "competition", "unknown")
    if comp == "first_25":
        parts.append("early applicant window")
    elif comp == "high":
        parts.append("high competition")

    return "**Viability:** " + "; ".join(parts).capitalize() + "."


def _wants_cover_letter(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ("cover letter", "coverletter", "cover note"))


def _wants_linkedin_msg(text: str) -> bool:
    t = (text or "").lower()
    return any(
        k in t
        for k in (
            "linkedin",
            "recruiter",
            "outreach",
            "cold message",
            "message to ",
            "dm ",
            "inmail",
        )
    )


def _wants_resume_help(text: str) -> bool:
    t = (text or "").lower()
    if re.search(r"\b(resume|cv)\b", t):
        return True
    return any(
        k in t
        for k in (
            "tailor ",
            "rewrite ",
            "bullet ",
        )
    )


def _format_cover_letter_text(content: dict[str, Any]) -> str:
    if content.get("error"):
        return f"Cover letter: could not generate ({content['error']})"
    parts = [
        content.get("greeting", ""),
        content.get("opening", ""),
        content.get("body", ""),
        content.get("closing", ""),
        content.get("sign_off", ""),
    ]
    body = "\n\n".join(p for p in parts if p)
    return "**Cover letter (draft)**\n\n" + body


def _general_coach(question: str, profile: dict, secrets: dict) -> str:
    from src.utils.llm_provider import create_llm_client

    client = create_llm_client(secrets)
    if not client:
        return (
            "No LLM available. Install **Ollama** from https://ollama.ai (`ollama pull llama3.2`) "
            "or set `openai_api_key` in config/secrets.yaml."
        )
    summary = _profile_summary(profile)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Helix, a concise career coach. "
                    "Use the candidate profile when relevant. "
                    "Give actionable, specific advice. No filler. "
                    "Use markdown sparingly (bold for headings if needed)."
                ),
            },
            {"role": "user", "content": f"Candidate profile:\n{summary}\n\nQuestion:\n{question}"},
        ],
        temperature=0.55,
        max_tokens=1800,
    )
    return (response.choices[0].message.content or "").strip() or "(empty response)"


def process_coach_message(
    content: str,
    channel_id: int,
    profile: dict,
    secrets: dict,
) -> list[str]:
    """
    Main entry: return one or more Discord message chunks.
    """
    text = (content or "").strip()
    if not text:
        return []

    urls = extract_urls(text)

    # --- Job URL path ---
    if urls:
        url = urls[0]
        job, err = fetch_job_snapshot(url)
        if err or not job:
            return split_discord_chunks(f"\u274c {err or 'Unknown error fetching job.'}")

        from src.apply.job_checker import check_job
        from src.matching.profile_fitness import compute_profile_fitness, format_fitness_discord
        from src.matching.scorer import compute_match_score

        status = check_job(job.get("url", url))
        match_score = float(
            compute_match_score(
                job.get("title", ""),
                job.get("description") or "",
                job.get("location") or None,
                job.get("sponsorship_status", "unknown"),
                profile,
            )
        )
        job["match_score"] = match_score
        fitness = compute_profile_fitness(job, profile)
        fit_text = format_fitness_discord(fitness)
        viab = _viability_line(match_score, fitness["fitness_score"], status)

        header = (
            f"**{job.get('title', 'Job')}** — *{job.get('company', 'Company')}*\n"
            f"{job.get('url', url)}\n"
        )
        block1 = (
            header
            + f"{status.discord_summary()}\n"
            + f"**Keyword match score:** {match_score:.0f}/100\n"
            + viab
            + "\n\n"
            + fit_text
        )

        _LAST_JOB_BY_CHANNEL[channel_id] = {**job, "match_score": match_score}

        out: list[str] = []
        out.extend(split_discord_chunks(block1))

        from src.utils.llm_provider import create_llm_client

        client = create_llm_client(secrets)

        if _wants_cover_letter(text) and client:
            from src.documents.cover_letter import generate_cover_letter_content

            raw = generate_cover_letter_content(
                client=client,
                job_title=job.get("title", ""),
                job_company=job.get("company", ""),
                job_description=job.get("description", ""),
                profile=profile,
                company_research="",
                model="gpt-4o-mini",
            )
            out.extend(split_discord_chunks(_format_cover_letter_text(raw)))

        if _wants_linkedin_msg(text) and client:
            from src.linkedin.content_generator import generate_recruiter_message

            target = f"{job.get('company', '')} — {job.get('title', '')}".strip(" —")
            msg = generate_recruiter_message(target or job.get("company", "this role"), profile)
            out.extend(split_discord_chunks("**LinkedIn / recruiter message (draft)**\n\n" + msg))

        if len(urls) > 1:
            extra = "\n\n_(I analyzed the first URL only; paste others in separate messages if needed.)_"
            if out:
                out[-1] = out[-1] + extra
            else:
                out.append(extra.strip())

        return out if out else ["(no output)"]

    # --- No URL: follow-ups and general chat ---
    last = _LAST_JOB_BY_CHANNEL.get(channel_id)

    if _wants_cover_letter(text):
        if not last:
            return [
                "No job in context yet. **Paste a job posting URL** in this channel first, "
                "then ask for a cover letter again."
            ]
        from src.utils.llm_provider import create_llm_client

        client = create_llm_client(secrets)
        if not client:
            return split_discord_chunks(
                "No LLM for cover letter. Configure Ollama or OpenAI in secrets.yaml."
            )
        from src.documents.cover_letter import generate_cover_letter_content

        raw = generate_cover_letter_content(
            client=client,
            job_title=last.get("title", ""),
            job_company=last.get("company", ""),
            job_description=last.get("description", ""),
            profile=profile,
            company_research="",
            model="gpt-4o-mini",
        )
        return split_discord_chunks(_format_cover_letter_text(raw))

    if _wants_linkedin_msg(text):
        from src.utils.llm_provider import create_llm_client

        client = create_llm_client(secrets)
        if not client:
            return split_discord_chunks(
                "No LLM for LinkedIn message. Configure Ollama or OpenAI in secrets.yaml."
            )
        from src.linkedin.content_generator import generate_recruiter_message

        target = "this role"
        if last:
            target = f"{last.get('company', '')} — {last.get('title', '')}".strip(" —")
        msg = generate_recruiter_message(target, profile)
        return split_discord_chunks("**LinkedIn / recruiter message (draft)**\n\n" + msg)

    if _wants_resume_help(text):
        return split_discord_chunks(_general_coach(f"Resume help: {text}", profile, secrets))

    return split_discord_chunks(_general_coach(text, profile, secrets))
