import re
from collections import Counter


COMMON_TECH_KEYWORDS = [
    "python", "java", "javascript", "typescript", "c#", "c++", "go", "rust", "ruby",
    "sql", "nosql", "mongodb", "postgresql", "mysql", "redis", "dynamodb",
    "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "jenkins",
    "selenium", "cypress", "playwright", "pytest", "junit", "testng", "jest",
    "rest api", "graphql", "microservices", "ci/cd", "git", "github", "gitlab",
    "agile", "scrum", "jira", "confluence",
    "react", "angular", "vue", "node.js", "django", "flask", "spring",
    "linux", "bash", "powershell",
    "machine learning", "data engineering", "etl",
    "performance testing", "load testing", "jmeter", "gatling",
    "api testing", "postman", "swagger",
    "test automation", "bdd", "tdd", "cucumber",
]


def extract_keywords_from_description(description: str) -> list[str]:
    """Extract tech keywords from a job description."""
    if not description:
        return []
    text = description.lower()
    found = []
    for kw in COMMON_TECH_KEYWORDS:
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, text):
            found.append(kw)
    return found


def compute_keyword_overlap(job_keywords: list[str], profile_skills: list[str]) -> float:
    """Returns overlap ratio between 0 and 1."""
    if not job_keywords:
        return 0.0
    job_set = set(k.lower() for k in job_keywords)
    profile_set = set(s.lower() for s in profile_skills)
    overlap = job_set & profile_set
    return len(overlap) / len(job_set) if job_set else 0.0


def get_missing_keywords(job_keywords: list[str], profile_skills: list[str]) -> list[str]:
    """Return keywords the job requires that the profile is missing."""
    job_set = set(k.lower() for k in job_keywords)
    profile_set = set(s.lower() for s in profile_skills)
    return sorted(job_set - profile_set)


def flatten_profile_skills(skills_dict: dict) -> list[str]:
    """Flatten the nested skills dict from profile.yaml into a single list."""
    flat = []
    for category, items in skills_dict.items():
        if isinstance(items, list):
            flat.extend(items)
    return flat
