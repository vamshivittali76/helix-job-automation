"""
url_resolver.py
---------------
Resolves aggregator/redirect URLs (Jooble, Dice, BeeBee, JobLeads, etc.)
to their final ATS destination (Greenhouse, Lever, Workday, Ashby, etc.).

Why: aggregator links like jooble.org/jdp/... hit Cloudflare.
     The *real* URL (boards.greenhouse.io/...) does not.

Strategy:
  1. Follow HTTP redirects with cloudscraper (handles Cloudflare JS challenges)
  2. If blocked, use Playwright headless to resolve the final URL
  3. Cache resolved URLs in the DB so we never resolve the same link twice
"""

from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import urlparse

# ── Aggregator domains we always try to resolve through ──────────────────────
AGGREGATOR_DOMAINS = {
    "jooble.org",
    "dice.com",
    "bebee.com",
    "jobleads.com",
    "jobvite.com",
    "indeed.com",
    "ziprecruiter.com",
    "careerbuilder.com",
    "simplyhired.com",
    "glassdoor.com",
    "monster.com",
    "talent.com",
    "adzuna.com",
    "neuvoo.com",
    "jobsora.com",
    "jobisjob.com",
    "trovit.com",
    "themuse.com",
}

# ── Known-good ATS domains — these are the destinations we want ──────────────
ATS_DOMAINS = {
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "workday.com",
    "ashbyhq.com",
    "bamboohr.com",
    "smartrecruiters.com",
    "jobvite.com",
    "icims.com",
    "taleo.net",
    "successfactors.com",
    "linkedin.com",
    "careers.",     # e.g. careers.airbnb.com, careers.stripe.com
}


def needs_resolution(url: str) -> bool:
    """Return True if this URL goes through an aggregator that needs resolving."""
    if not url:
        return False
    domain = urlparse(url).netloc.lower().lstrip("www.")
    return any(agg in domain for agg in AGGREGATOR_DOMAINS)


def is_ats_url(url: str) -> bool:
    """Return True if this URL is already a direct ATS link."""
    if not url:
        return False
    url_lower = url.lower()
    return any(ats in url_lower for ats in ATS_DOMAINS)


def resolve_url(url: str, timeout: int = 15) -> str:
    """
    Follow redirects to find the final destination URL.
    Returns the resolved URL, or the original if resolution fails.
    """
    if not url or not url.startswith("http"):
        return url

    # Already an ATS URL — no need to resolve
    if is_ats_url(url) and not needs_resolution(url):
        return url

    # Use cloudscraper (handles Cloudflare JS challenges)
    resolved = _resolve_with_cloudscraper(url, timeout)
    if resolved and resolved != url:
        return resolved

    return url


def _resolve_with_cloudscraper(url: str, timeout: int = 15) -> str | None:
    """Use cloudscraper to follow redirects through Cloudflare-protected pages."""
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        resp = scraper.get(url, timeout=timeout, allow_redirects=True)
        final_url = resp.url

        # Sometimes the page embeds the real URL in a meta-refresh or JS redirect
        if final_url == url or _same_domain(url, final_url):
            embedded = _extract_redirect_from_html(resp.text)
            if embedded:
                return embedded

        return final_url
    except Exception:
        return None


def _resolve_with_playwright(url: str) -> str | None:
    """Playwright fallback removed — cloudscraper handles all resolution now."""
    return None


def _extract_redirect_from_html(html: str) -> str | None:
    """Look for meta-refresh or window.location redirects in page HTML."""
    # meta refresh
    m = re.search(r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+url=(["\'])([^"\']+)\1', html, re.IGNORECASE)
    if m:
        return m.group(2)
    # window.location = "..."
    m = re.search(r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']', html)
    if m:
        return m.group(1)
    # <a href="..." id="apply-link" or class*="apply">
    m = re.search(r'<a[^>]+(?:id|class)=["\'][^"\']*apply[^"\']*["\'][^>]+href=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m and m.group(1).startswith("http"):
        return m.group(1)
    return None


def _same_domain(url1: str, url2: str) -> bool:
    return urlparse(url1).netloc == urlparse(url2).netloc


def resolve_and_cache(job_id: str, url: str) -> str:
    """
    Resolve a URL and write the result back to the DB.
    Returns the resolved URL (or original if resolution failed).
    """
    if not needs_resolution(url):
        return url

    resolved = resolve_url(url)

    if resolved and resolved != url:
        try:
            from src.tracker.db import get_connection
            conn = get_connection()
            conn.execute(
                "UPDATE jobs SET url=?, last_checked=datetime('now') WHERE id=? AND url=?",
                (resolved, job_id, url),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    return resolved or url
