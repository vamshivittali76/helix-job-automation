"""
LinkedIn job scraper using Playwright.

Scrapes LinkedIn's public job search (no login required for basic listings).
Respects rate limits with randomized delays (3-10s between actions).
Hard-capped at 50 jobs per session per project rules.
"""

import random
import time
from typing import Optional
from .base import BaseScraper, JobListing

MAX_JOBS_PER_SESSION = 50


class LinkedInScraper(BaseScraper):
    """Scrape LinkedIn public job search results using Playwright browser automation."""

    name = "linkedin"

    def __init__(self, headless: bool = True):
        self.headless = headless

    def search(
        self,
        query: str,
        location: str = "United States",
        max_results: int = 50,
        **kwargs,
    ) -> list[JobListing]:
        max_results = min(max_results, MAX_JOBS_PER_SESSION)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("  [linkedin] playwright not installed. Run: pip install playwright && playwright install chromium")
            return []

        all_jobs: list[JobListing] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                viewport={"width": 1366, "height": 768},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()

            try:
                all_jobs = self._scrape_jobs(page, query, location, max_results)
            except Exception as e:
                print(f"  [linkedin] Scraping error: {e}")
            finally:
                browser.close()

        return all_jobs

    def _scrape_jobs(self, page, query: str, location: str, max_results: int) -> list[JobListing]:
        from urllib.parse import quote_plus

        url = (
            f"https://www.linkedin.com/jobs/search/"
            f"?keywords={quote_plus(query)}"
            f"&location={quote_plus(location)}"
            f"&f_TPR=r604800"
            f"&f_JT=F"
            f"&position=1&pageNum=0"
        )

        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(3, 5))

        jobs: list[JobListing] = []
        seen_urls: set[str] = set()
        scroll_count = 0
        max_scrolls = max_results // 8 + 3

        while len(jobs) < max_results and scroll_count < max_scrolls:
            cards = page.query_selector_all(
                "div.base-card, li.jobs-search-results__list-item, div.job-search-card"
            )

            for card in cards:
                if len(jobs) >= max_results:
                    break
                job = self._parse_card(card)
                if job and job.url not in seen_urls:
                    seen_urls.add(job.url)
                    jobs.append(job)

            show_more = page.query_selector(
                "button.infinite-scroller__show-more-button, "
                "button[aria-label='See more jobs']"
            )
            if show_more:
                try:
                    show_more.click()
                    time.sleep(random.uniform(3, 6))
                except Exception:
                    pass

            page.evaluate("window.scrollBy(0, 800)")
            time.sleep(random.uniform(2, 4))
            scroll_count += 1

            if page.query_selector("div.authwall-join-form, form.login-form"):
                print("  [linkedin] Auth wall detected, stopping")
                break

        return jobs

    def _parse_card(self, card) -> Optional[JobListing]:
        try:
            title_el = card.query_selector(
                "h3.base-search-card__title, a.base-card__full-link, h3"
            )
            title = title_el.inner_text().strip() if title_el else ""

            company_el = card.query_selector(
                "h4.base-search-card__subtitle, a.hidden-nested-link"
            )
            company = company_el.inner_text().strip() if company_el else ""

            link_el = card.query_selector(
                "a.base-card__full-link, a[href*='/jobs/view/']"
            )
            url = link_el.get_attribute("href") if link_el else ""
            if url and not url.startswith("http"):
                url = "https://www.linkedin.com" + url

            location_el = card.query_selector("span.job-search-card__location")
            location = location_el.inner_text().strip() if location_el else ""

            date_el = card.query_selector("time")
            date_posted = date_el.get_attribute("datetime") if date_el else None

            if not title or not url:
                return None

            clean_url = url.split("?")[0]

            # ── Applicant count & closed status ───────────────────────────
            raw_data: dict = {}
            applicant_count = None
            applicant_label = ""
            competition_level = "unknown"
            is_expired = False

            # LinkedIn card shows applicant count in several selectors
            count_el = card.query_selector(
                ".job-search-card__applicant-count, "
                ".num-applicants__caption, "
                "span[class*='applicants'], "
                "span[class*='applicant-count']"
            )
            if count_el:
                raw_text = count_el.inner_text().strip()
                applicant_label = raw_text
                raw_data["applicant_label"] = raw_text

                # Check if job is closed right on the card
                if any(p in raw_text.lower() for p in ("no longer", "closed")):
                    is_expired = True
                else:
                    import re
                    is_first = "first" in raw_text.lower()
                    m = re.search(r"[\d,]+", raw_text)
                    if m:
                        try:
                            applicant_count = int(m.group(0).replace(",", ""))
                            raw_data["applicant_count"] = applicant_count
                            if is_first or applicant_count <= 25:
                                competition_level = "first_25"
                            elif applicant_count <= 75:
                                competition_level = "low"
                            elif applicant_count <= 200:
                                competition_level = "medium"
                            else:
                                competition_level = "high"
                        except ValueError:
                            pass

            raw_data.update({
                "competition_level": competition_level,
                "is_expired": int(is_expired),
            })

            return JobListing(
                title=title,
                company=company if company else "Unknown",
                url=clean_url,
                source="linkedin",
                location=location if location else None,
                remote_type=self._detect_remote_type(title, location, ""),
                description=None,
                external_id=clean_url.split("/view/")[-1].split("/")[0] if "/view/" in clean_url else None,
                date_posted=date_posted,
                sponsorship_status="unknown",
                raw_data=raw_data,
            )
        except Exception:
            return None
