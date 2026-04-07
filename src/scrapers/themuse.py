import requests
import time
from typing import Optional
from .base import BaseScraper, JobListing


class TheMuseScraper(BaseScraper):
    """The Muse job search API client. Free, no key required."""

    name = "themuse"
    BASE_URL = "https://www.themuse.com/api/public/jobs"

    CATEGORY_MAP = {
        "sdet": "Engineering",
        "software engineer": "Engineering",
        "qa": "Engineering",
        "test": "Engineering",
        "quality": "Engineering",
        "automation": "Engineering",
        "devops": "Engineering",
        "data": "Data Science",
    }

    LEVEL_MAP = {
        "entry": "Entry Level",
        "mid": "Mid Level",
        "senior": "Senior Level",
    }

    def search(
        self,
        query: str,
        location: str = "United States",
        experience_level: str = "mid",
        results_per_page: int = 20,
        max_pages: int = 5,
        **kwargs,
    ) -> list[JobListing]:
        all_jobs = []
        query_lower = query.lower()

        category = self._resolve_category(query)
        level = self.LEVEL_MAP.get(experience_level)

        for page in range(0, max_pages):
            params = {
                "page": page,
                "descending": "true",
            }
            if category:
                params["category"] = category
            if level:
                params["level"] = level

            try:
                resp = requests.get(self.BASE_URL, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as e:
                print(f"  [themuse] Error on page {page}: {e}")
                break

            results = data.get("results", [])
            if not results:
                break

            for item in results:
                job = self._parse_result(item, query)
                if job and self._is_relevant(job, query_lower):
                    all_jobs.append(job)

            page_count = data.get("page_count", 0)
            if page_count and page >= page_count - 1:
                break

            time.sleep(1)

        return all_jobs

    def _is_relevant(self, job: JobListing, query_lower: str) -> bool:
        """Strict relevance filter based on job title. Only keep tech/engineering roles."""
        title_lower = job.title.lower()

        must_have_one = [
            "engineer", "developer", "sdet", "qa ", "quality assurance",
            "software", "automation", "devops", "sre", "test ",
            "testing", "programming", "full stack", "fullstack",
            "backend", "frontend", "full-stack", "data engineer",
        ]
        reject_if_contains = [
            "intern", "director", "vp ", "vice president",
            "mechanical", "civil", "electrical engineer",
            "nurse", "physician", "pharmacist", "pharmacy",
            "clerk", "sales associate", "technician", "welder",
            "driver", "warehouse", "retail", "cashier",
            "cook", "chef", "prep ", "grocery", "bakery",
            "custodian", "janitor", "security guard",
            "sales rep", "account executive",
        ]

        for reject in reject_if_contains:
            if reject in title_lower:
                return False

        for keyword in must_have_one:
            if keyword in title_lower:
                return True

        return False

    def _resolve_category(self, query: str) -> Optional[str]:
        q = query.lower()
        for keyword, category in self.CATEGORY_MAP.items():
            if keyword in q:
                return category
        return "Engineering"

    def _parse_result(self, item: dict, query: str) -> Optional[JobListing]:
        title = (item.get("name") or "").strip()
        company_data = item.get("company") or {}
        company = (company_data.get("name") or "Unknown").strip()

        refs = item.get("refs", {})
        url = refs.get("landing_page", "")
        if not title or not url:
            return None

        locations = item.get("locations") or []
        location_str = ", ".join(
            (loc.get("name") or "") for loc in locations if isinstance(loc, dict)
        ) if locations else None

        categories = item.get("categories", [])
        levels = item.get("levels", [])

        description_parts = []
        if item.get("contents"):
            description_parts.append(self._clean_html(item["contents"]))

        description = " ".join(description_parts)

        return JobListing(
            title=title,
            company=company,
            url=url,
            source="themuse",
            location=location_str,
            remote_type=self._detect_remote_type(title, location_str or "", description),
            description=description[:2000] if description else None,
            external_id=str(item.get("id", "")),
            date_posted=item.get("publication_date"),
            sponsorship_status=self._detect_sponsorship(description),
            raw_data={
                "categories": [c.get("name") for c in categories],
                "levels": [l.get("name") for l in levels],
                "company_id": company_data.get("id"),
            },
        )
