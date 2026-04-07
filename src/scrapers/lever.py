"""
Lever career page scraper.

Lever powers career pages for many startups and mid-size companies.
Public API: https://api.lever.co/v0/postings/{company}?mode=json
"""

import requests
import time
from typing import Optional
from .base import BaseScraper, JobListing

DEFAULT_COMPANIES = [
    "netflix", "rivian", "anduril", "databricks", "anthropic",
    "openai", "scaleai", "brex", "flexport", "gusto",
    "loom", "miro", "netlify", "nerdwallet", "onemedical",
    "postman", "relativity", "remitly", "rippling", "truework",
    "upstart", "vanta", "watershed", "webflow", "yelp",
]


class LeverScraper(BaseScraper):
    """Scrape jobs from Lever-powered career pages via their public API."""

    name = "lever"
    BASE_URL = "https://api.lever.co/v0/postings"

    def __init__(self, companies: list[str] | None = None):
        self.companies = companies or DEFAULT_COMPANIES

    def search(
        self,
        query: str,
        location: str = "United States",
        max_per_company: int = 20,
        **kwargs,
    ) -> list[JobListing]:
        all_jobs: list[JobListing] = []
        query_lower = query.lower()

        for company in self.companies:
            try:
                jobs = self._fetch_company(company, query_lower, max_per_company)
                all_jobs.extend(jobs)
            except Exception as e:
                print(f"  [lever] {company}: {e}")
            time.sleep(1)

        return all_jobs

    def _fetch_company(
        self, company: str, query_lower: str, max_results: int
    ) -> list[JobListing]:
        url = f"{self.BASE_URL}/{company}"
        resp = requests.get(url, params={"mode": "json"}, timeout=30)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()

        postings = resp.json()
        if not isinstance(postings, list):
            return []

        jobs: list[JobListing] = []
        for item in postings:
            job = self._parse_posting(item, company, query_lower)
            if job:
                jobs.append(job)
                if len(jobs) >= max_results:
                    break
        return jobs

    def _parse_posting(
        self, item: dict, company_slug: str, query_lower: str
    ) -> Optional[JobListing]:
        title = (item.get("text") or "").strip()
        if not title:
            return None
        if not self._is_relevant(title.lower(), query_lower):
            return None

        categories = item.get("categories") or {}
        location_str = (categories.get("location") or "") if isinstance(categories, dict) else ""
        department = categories.get("department", "")
        team = categories.get("team", "")

        description_parts = []
        if item.get("descriptionPlain"):
            description_parts.append(item["descriptionPlain"])
        for section in item.get("lists", []):
            if section.get("content"):
                description_parts.append(self._clean_html(section["content"]))
        description = " ".join(description_parts)

        url = (item.get("hostedUrl") or "").strip()
        if not url:
            return None

        return JobListing(
            title=title,
            company=company_slug.replace("-", " ").title(),
            url=url,
            source="lever",
            location=location_str if location_str else None,
            remote_type=self._detect_remote_type(title, location_str, description),
            description=description[:2000] if description else None,
            external_id=item.get("id", ""),
            date_posted=None,
            sponsorship_status=self._detect_sponsorship(description),
            raw_data={
                "company_slug": company_slug,
                "department": department,
                "team": team,
            },
        )

    def _is_relevant(self, title_lower: str, query_lower: str) -> bool:
        core_terms = [t for t in query_lower.split() if len(t) > 2]
        if not core_terms:
            return True
        return any(term in title_lower for term in core_terms)
