"""
Visa sponsorship detection.

Three-tier approach:
  Tier 1: Known H1B sponsor list (USCIS data + MyVisaJobs top sponsors)
  Tier 2: Job description keyword scanning
  Tier 3: Unknown (no data either way)
"""

KNOWN_H1B_SPONSORS = {
    "google", "amazon", "microsoft", "meta", "apple", "netflix",
    "salesforce", "oracle", "ibm", "intel", "cisco", "adobe",
    "uber", "lyft", "airbnb", "stripe", "square", "paypal",
    "nvidia", "qualcomm", "broadcom", "amd",
    "jpmorgan", "goldman sachs", "morgan stanley", "bank of america",
    "capital one", "wells fargo", "citibank", "barclays",
    "deloitte", "accenture", "pwc", "kpmg", "ernst & young", "ey",
    "mckinsey", "boston consulting group", "bain",
    "walmart", "target", "costco",
    "tesla", "spacex", "boeing", "lockheed martin",
    "tcs", "infosys", "wipro", "cognizant", "hcl", "tech mahindra",
    "capgemini", "thoughtworks",
    "spotify", "twitter", "snap", "pinterest", "linkedin",
    "vmware", "dell", "hp", "lenovo",
    "snowflake", "databricks", "palantir", "splunk",
    "doordash", "instacart", "robinhood", "coinbase",
    "zoom", "slack", "atlassian", "twilio",
    "epic systems", "cerner", "unitedhealth",
    "johnson & johnson", "pfizer", "merck",
    "visa", "mastercard", "american express",
    "samsung", "sony", "siemens",
    "mathworks", "bloomberg", "two sigma", "citadel", "jane street",
}


def check_sponsorship(company: str, description: str = "") -> str:
    """
    Returns: 'sponsor_likely', 'sponsor_unlikely', or 'unknown'
    """
    if _is_known_sponsor(company):
        if description and _has_negative_signals(description):
            return "sponsor_unlikely"
        return "sponsor_likely"

    if description:
        if _has_positive_signals(description):
            return "sponsor_likely"
        if _has_negative_signals(description):
            return "sponsor_unlikely"

    return "unknown"


def _is_known_sponsor(company: str) -> bool:
    import re
    company_lower = company.lower().strip()
    if not company_lower or len(company_lower) < 2:
        return False
    for sponsor in KNOWN_H1B_SPONSORS:
        pattern = r"\b" + re.escape(sponsor) + r"\b"
        if re.search(pattern, company_lower):
            return True
    return False


def _has_positive_signals(text: str) -> bool:
    text = text.lower()
    positive = [
        "visa sponsorship available",
        "will sponsor",
        "sponsorship available",
        "h1b sponsor",
        "open to sponsoring",
        "we sponsor",
        "sponsorship is available",
        "provide sponsorship",
        "offer sponsorship",
    ]
    return any(s in text for s in positive)


def _has_negative_signals(text: str) -> bool:
    text = text.lower()
    negative = [
        "no visa sponsorship",
        "not sponsor",
        "cannot sponsor",
        "won't sponsor",
        "will not sponsor",
        "without sponsorship",
        "no sponsorship",
        "must be authorized to work in the u",
        "must be a u.s. citizen",
        "us citizens only",
        "permanent resident only",
        "no h1b",
        "unable to sponsor",
        "not able to sponsor",
        "does not sponsor",
        "do not sponsor",
        "legally authorized to work in the united states",
    ]
    return any(s in text for s in negative)


def enrich_sponsorship(jobs: list[dict]) -> list[dict]:
    """Update sponsorship_status for a batch of jobs using all tiers."""
    for job in jobs:
        job["sponsorship_status"] = check_sponsorship(
            job.get("company", ""),
            job.get("description", ""),
        )
    return jobs
