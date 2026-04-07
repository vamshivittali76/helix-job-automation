"""
Google Jobs scraper via SerpAPI.

Uses SerpAPI's google_jobs engine to get structured job listings
from Google's job aggregation. Requires a SerpAPI key (free tier: 100/mo).
"""

import requests
import time
from typing import Optional
from .base import BaseScraper, JobListing


class GoogleJobsScraper(BaseScraper):
    """Fetch jobs from Google Jobs via SerpAPI."""

    name = "google_jobs"
    BASE_URL = "https://serpapi.com/search.json"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(
        self,
        query: str,
        location: str = "United States",
        max_pages: int = 3,
        **kwargs,
    ) -> list[JobListing]:
        all_jobs: list[JobListing] = []
        next_page_token: Optional[str] = None

        for page in range(max_pages):
            params = {
                "engine": "google_jobs",
                "q": query,
                "location": location,
                "api_key": self.api_key,
                "chips": "date_posted:week",
            }
            if next_page_token:
                params["next_page_token"] = next_page_token

            try:
                resp = requests.get(self.BASE_URL, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as e:
                print(f"  [google_jobs] Error on page {page}: {e}")
                break

            results = data.get("jobs_results", [])
            if not results:
                break

            for item in results:
                job = self._parse_result(item)
                if job:
                    all_jobs.append(job)

            serpapi_pagination = data.get("serpapi_pagination", {})
            next_page_token = serpapi_pagination.get("next_page_token")
            if not next_page_token:
                break

            time.sleep(2)

        return all_jobs

    def _parse_result(self, item: dict) -> Optional[JobListing]:
        title = (item.get("title") or "").strip()
        company = (item.get("company_name") or "Unknown").strip()
        location = (item.get("location") or "")
        if not title:
            return None

        description = item.get("description", "")

        url = self._extract_apply_url(item)
        if not url:
            return None

        extensions = item.get("detected_extensions", {})
        schedule = extensions.get("schedule_type", "")

        return JobListing(
            title=title,
            company=company,
            url=url,
            source="google_jobs",
            location=location if location else None,
            remote_type=self._detect_remote_type(title, location, description),
            description=description[:2000] if description else None,
            external_id=item.get("job_id"),
            date_posted=extensions.get("posted_at"),
            sponsorship_status=self._detect_sponsorship(description),
            raw_data={"schedule": schedule, "via": item.get("via", "")},
        )

    def _extract_apply_url(self, item: dict) -> str:
        for opt in item.get("apply_options", []):
            link = opt.get("link", "")
            if link:
                return link
        for rel in item.get("related_links", []):
            link = rel.get("link", "")
            if link:
                return link
        return item.get("share_link", "")
