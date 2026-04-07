"""
Cross-source job deduplication.

Uses multiple signals to detect duplicate listings:
  1. Exact URL match (after normalization)
  2. Fuzzy title + company match (thefuzz)
  3. Description similarity for borderline cases
"""

from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from thefuzz import fuzz

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "referer", "tracking", "gh_jid", "lever_origin",
    "click_id", "fbclid", "gclid", "si", "trk",
}


def normalize_url(url: str) -> str:
    """Strip tracking parameters and normalize URL for dedup comparison."""
    if not url:
        return ""
    parsed = urlparse(url.strip().rstrip("/").lower())
    params = parse_qs(parsed.query)
    cleaned = {k: v for k, v in params.items() if k.lower() not in TRACKING_PARAMS}
    clean_query = urlencode(cleaned, doseq=True) if cleaned else ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", clean_query, ""))


def is_duplicate(
    job_a: dict,
    job_b: dict,
    title_threshold: int = 85,
    company_threshold: int = 80,
) -> bool:
    """Check if two jobs are likely duplicates using URL, title, company, and description."""
    url_a = normalize_url(job_a.get("url", ""))
    url_b = normalize_url(job_b.get("url", ""))
    if url_a and url_b and url_a == url_b:
        return True

    title_a = (job_a.get("title") or "").strip().lower()
    title_b = (job_b.get("title") or "").strip().lower()
    company_a = (job_a.get("company") or "").strip().lower()
    company_b = (job_b.get("company") or "").strip().lower()

    if not title_a or not title_b or not company_a or not company_b:
        return False

    company_score = fuzz.ratio(company_a, company_b)
    if company_score < company_threshold:
        return False

    title_score = fuzz.token_sort_ratio(title_a, title_b)
    if title_score >= title_threshold:
        return True

    desc_a = (job_a.get("description") or "")[:500]
    desc_b = (job_b.get("description") or "")[:500]
    if company_score >= 90 and desc_a and desc_b:
        desc_score = fuzz.ratio(desc_a.lower(), desc_b.lower())
        if desc_score >= 80:
            return True

    return False


def _pick_best(job_a: dict, job_b: dict) -> dict:
    """Return the job with more useful data (longer description, salary, sponsorship info)."""
    score_a = len(job_a.get("description") or "")
    score_b = len(job_b.get("description") or "")

    if job_a.get("sponsorship_status") != "unknown":
        score_a += 500
    if job_b.get("sponsorship_status") != "unknown":
        score_b += 500

    if job_a.get("salary_min"):
        score_a += 300
    if job_b.get("salary_min"):
        score_b += 300

    return job_a if score_a >= score_b else job_b


def deduplicate_jobs(jobs: list[dict]) -> list[dict]:
    """Remove duplicate jobs from a list, keeping the best version of each."""
    if not jobs:
        return []

    unique: list[dict] = []
    seen_urls: dict[str, int] = {}

    for job in jobs:
        norm_url = normalize_url(job.get("url", ""))

        if norm_url and norm_url in seen_urls:
            idx = seen_urls[norm_url]
            unique[idx] = _pick_best(unique[idx], job)
            continue

        is_dup = False
        for i, existing in enumerate(unique):
            if is_duplicate(job, existing):
                unique[i] = _pick_best(existing, job)
                is_dup = True
                break

        if not is_dup:
            if norm_url:
                seen_urls[norm_url] = len(unique)
            unique.append(job)

    return unique


def deduplicate_against_db(new_jobs: list[dict], existing_jobs: list[dict]) -> list[dict]:
    """Filter out jobs that already exist in the DB (exact URL or fuzzy match)."""
    if not existing_jobs:
        return new_jobs

    existing_urls = {normalize_url(j.get("url", "")) for j in existing_jobs}
    existing_urls.discard("")

    novel = []
    for job in new_jobs:
        norm_url = normalize_url(job.get("url", ""))
        if norm_url and norm_url in existing_urls:
            continue

        is_dup = any(is_duplicate(job, ex) for ex in existing_jobs)
        if not is_dup:
            novel.append(job)

    return novel
