from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class JobListing:
    title: str
    company: str
    url: str
    source: str
    location: Optional[str] = None
    remote_type: Optional[str] = None
    description: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: str = "USD"
    external_id: Optional[str] = None
    date_posted: Optional[str] = None
    sponsorship_status: str = "unknown"
    raw_data: Optional[dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class BaseScraper(ABC):
    """Abstract base for all job scrapers / API clients."""

    name: str = "base"

    @abstractmethod
    def search(self, query: str, location: str = "United States", **kwargs) -> list[JobListing]:
        """Search for jobs matching query. Returns list of JobListing."""
        ...

    def _clean_html(self, html: str) -> str:
        """Strip HTML tags from description text."""
        if not html:
            return ""
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)

    def _detect_remote_type(self, title: str, location: str, description: str) -> str:
        text = f"{title} {location} {description}".lower()
        if "remote" in text:
            return "remote"
        if "hybrid" in text:
            return "hybrid"
        return "onsite"

    def _detect_sponsorship(self, description: str) -> str:
        if not description:
            return "unknown"
        text = description.lower()

        negative_signals = [
            "no visa sponsorship",
            "not sponsor",
            "cannot sponsor",
            "won't sponsor",
            "will not sponsor",
            "without sponsorship",
            "no sponsorship",
            "must be authorized to work",
            "must be a u.s. citizen",
            "us citizen",
            "permanent resident only",
            "no h1b",
            "unable to sponsor",
            "not able to sponsor",
        ]
        positive_signals = [
            "visa sponsorship available",
            "will sponsor",
            "sponsorship available",
            "h1b sponsor",
            "open to sponsoring",
            "sponsorship is available",
            "we sponsor",
        ]

        for signal in negative_signals:
            if signal in text:
                return "sponsor_unlikely"
        for signal in positive_signals:
            if signal in text:
                return "sponsor_likely"
        return "unknown"
