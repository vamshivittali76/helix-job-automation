import requests
import time
from typing import Optional
from .base import BaseScraper, JobListing


class AdzunaScraper(BaseScraper):
    """Adzuna job search API client. Free tier, no scraping needed."""

    name = "adzuna"
    BASE_URL = "https://api.adzuna.com/v1/api/jobs"

    def __init__(self, app_id: str, app_key: str, country: str = "us"):
        self.app_id = app_id
        self.app_key = app_key
        self.country = country

    def search(
        self,
        query: str,
        location: str = "United States",
        results_per_page: int = 50,
        max_pages: int = 3,
        full_time_only: bool = True,
        salary_min: Optional[int] = None,
        **kwargs,
    ) -> list[JobListing]:
        all_jobs = []

        for page in range(1, max_pages + 1):
            params = {
                "app_id": self.app_id,
                "app_key": self.app_key,
                "results_per_page": results_per_page,
                "what": query,
                "where": location,
                "sort_by": "date",
            }
            if full_time_only:
                params["full_time"] = 1
            if salary_min:
                params["salary_min"] = salary_min

            url = f"{self.BASE_URL}/{self.country}/search/{page}"

            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as e:
                print(f"  [adzuna] Error on page {page}: {e}")
                break

            results = data.get("results", [])
            if not results:
                break

            for item in results:
                job = self._parse_result(item)
                if job:
                    all_jobs.append(job)

            time.sleep(1)

        return all_jobs

    def _parse_result(self, item: dict) -> Optional[JobListing]:
        title = (item.get("title") or "").strip()
        company_obj = item.get("company") or {}
        company = ((company_obj.get("display_name") if isinstance(company_obj, dict) else None) or "Unknown").strip()
        url = item.get("redirect_url", "")
        if not title or not url:
            return None

        location_parts = []
        loc = item.get("location") or {}
        if loc.get("display_name"):
            location_parts.append(loc["display_name"])

        description = item.get("description", "")
        salary_min = item.get("salary_min")
        salary_max = item.get("salary_max")

        try:
            salary_min = int(float(salary_min)) if salary_min else None
        except (ValueError, TypeError):
            salary_min = None
        try:
            salary_max = int(float(salary_max)) if salary_max else None
        except (ValueError, TypeError):
            salary_max = None

        location_str = ", ".join(location_parts) if location_parts else None

        return JobListing(
            title=title,
            company=company,
            url=url,
            source="adzuna",
            location=location_str,
            remote_type=self._detect_remote_type(title, location_str or "", description),
            description=self._clean_html(description),
            salary_min=salary_min,
            salary_max=salary_max,
            external_id=str(item.get("id", "")),
            date_posted=item.get("created"),
            sponsorship_status=self._detect_sponsorship(description),
            raw_data=item,
        )
