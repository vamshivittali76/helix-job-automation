import requests
import time
from typing import Optional
from .base import BaseScraper, JobListing


class JoobleScraper(BaseScraper):
    """Jooble job search API client. Free API key."""

    name = "jooble"
    BASE_URL = "https://jooble.org/api"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(
        self,
        query: str,
        location: str = "United States",
        results_per_request: int = 50,
        max_pages: int = 3,
        **kwargs,
    ) -> list[JobListing]:
        all_jobs = []

        for page in range(1, max_pages + 1):
            payload = {
                "keywords": query,
                "location": location,
                "page": str(page),
                "searchMode": 1,
            }

            url = f"{self.BASE_URL}/{self.api_key}"

            try:
                resp = requests.post(url, json=payload, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as e:
                print(f"  [jooble] Error on page {page}: {e}")
                break

            jobs_data = data.get("jobs", [])
            if not jobs_data:
                break

            for item in jobs_data:
                job = self._parse_result(item)
                if job:
                    all_jobs.append(job)

            total_count = data.get("totalCount", 0)
            if len(all_jobs) >= total_count or not jobs_data:
                break

            time.sleep(1.5)

        return all_jobs

    def _parse_result(self, item: dict) -> Optional[JobListing]:
        title = (item.get("title") or "").strip()
        company = (item.get("company") or "Unknown").strip()
        url = item.get("link", "")
        if not title or not url:
            return None

        description = self._clean_html(item.get("snippet", ""))
        location = item.get("location", "")
        salary = item.get("salary", "")

        salary_min, salary_max = self._parse_salary(salary)

        return JobListing(
            title=title,
            company=company if company else "Unknown",
            url=url,
            source="jooble",
            location=location if location else None,
            remote_type=self._detect_remote_type(title, location, description),
            description=description,
            salary_min=salary_min,
            salary_max=salary_max,
            external_id=item.get("id"),
            date_posted=item.get("updated"),
            sponsorship_status=self._detect_sponsorship(description),
            raw_data=item,
        )

    def _parse_salary(self, salary_str: str) -> tuple[Optional[int], Optional[int]]:
        if not salary_str:
            return None, None
        import re
        numbers = re.findall(r"[\d,]+", salary_str.replace(",", ""))
        numbers = [int(n) for n in numbers if n.isdigit() and int(n) > 1000]
        if len(numbers) >= 2:
            return min(numbers), max(numbers)
        if len(numbers) == 1:
            return numbers[0], None
        return None, None
