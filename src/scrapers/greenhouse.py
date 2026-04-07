"""
Greenhouse career page scraper.

Greenhouse powers career pages for many tech companies. Their board API
is public and returns JSON: boards-api.greenhouse.io/v1/boards/{token}/jobs
"""

import requests
import time
from typing import Optional
from .base import BaseScraper, JobListing

DEFAULT_BOARDS = [
    "airbnb", "cloudflare", "coinbase", "datadog", "discord",
    "doordash", "elastic", "figma", "gitlab", "hashicorp",
    "hubspot", "instacart", "lyft", "notion", "okta",
    "pagerduty", "palantir", "plaid", "ramp", "reddit",
    "robinhood", "samsara", "snyk", "square", "stripe",
    "twilio", "unity3d", "waymo", "zscaler",
]


class GreenhouseScraper(BaseScraper):
    """Scrape jobs from Greenhouse-powered career pages via their public API."""

    name = "greenhouse"
    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    def __init__(self, boards: list[str] | None = None):
        self.boards = boards or DEFAULT_BOARDS

    def search(
        self,
        query: str,
        location: str = "United States",
        max_per_board: int = 20,
        **kwargs,
    ) -> list[JobListing]:
        all_jobs: list[JobListing] = []
        query_lower = query.lower()

        for board in self.boards:
            try:
                jobs = self._fetch_board(board, query_lower, max_per_board)
                all_jobs.extend(jobs)
            except Exception as e:
                print(f"  [greenhouse] {board}: {e}")
            time.sleep(1)

        return all_jobs

    def _fetch_board(
        self, board_token: str, query_lower: str, max_results: int
    ) -> list[JobListing]:
        url = f"{self.BASE_URL}/{board_token}/jobs"
        resp = requests.get(url, params={"content": "true"}, timeout=30)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()

        jobs: list[JobListing] = []
        for item in resp.json().get("jobs", []):
            job = self._parse_job(item, board_token, query_lower)
            if job:
                jobs.append(job)
                if len(jobs) >= max_results:
                    break
        return jobs

    def _parse_job(
        self, item: dict, board_token: str, query_lower: str
    ) -> Optional[JobListing]:
        title = (item.get("title") or "").strip()
        if not title:
            return None
        if not self._is_relevant(title.lower(), query_lower):
            return None

        loc = item.get("location") or {}
        location_name = (loc.get("name") or "") if isinstance(loc, dict) else ""
        description = self._clean_html(item.get("content", ""))
        url = item.get("absolute_url", "")
        if not url:
            return None
        raw_depts = item.get("departments") or []
        departments = [d.get("name", "") for d in raw_depts if isinstance(d, dict)]

        return JobListing(
            title=title,
            company=board_token.replace("-", " ").title(),
            url=url,
            source="greenhouse",
            location=location_name if location_name else None,
            remote_type=self._detect_remote_type(title, location_name, description),
            description=description[:2000] if description else None,
            external_id=str(item.get("id", "")),
            date_posted=item.get("updated_at"),
            sponsorship_status=self._detect_sponsorship(description),
            raw_data={"board": board_token, "departments": departments},
        )

    def _is_relevant(self, title_lower: str, query_lower: str) -> bool:
        core_terms = [t for t in query_lower.split() if len(t) > 2]
        if not core_terms:
            return True
        return any(term in title_lower for term in core_terms)
