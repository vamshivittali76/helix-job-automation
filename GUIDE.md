# Helix — CLI & automation guide

> **First-time setup (Discord bot, secrets, profile, channels): use [SETUP.md](SETUP.md)** — that is the canonical step-by-step guide.  
> This document focuses on **CLI** workflows (`python -m src.cli …`), batch jobs, and power-user automation. The primary product surface is **Discord** (`python -m src.discord.bot`).

---

## Quick Start (CLI)

```bash
# 1. Activate virtual environment
venv\Scripts\activate

# 2. Discover jobs from all 7 sources
python -m src.cli scan

# 3. Same but with LLM semantic scoring (uses OpenAI)
python -m src.cli scan --llm

# 4. Review top-ranked jobs
python -m src.cli review --min-score 50

# 5. Generate today's application plan (top 25)
python -m src.cli plan

# 6. Research companies + generate tailored resumes/cover letters
python -m src.cli prepare

# 7. Check Gmail for status updates (optional)
python -m src.cli monitor

# 8. View statistics
python -m src.cli stats

# 9. Run periodic tasks on autopilot (optional)
python -m src.cli schedule
```

---

## Setup Checklist

- [x] Python 3.11+ installed
- [x] Virtual environment created (`venv/`)
- [x] Dependencies installed (`pip install -r requirements.txt`)
- [x] Playwright Chromium installed (`playwright install chromium`)
- [x] API keys configured (`config/secrets.yaml`)
- [ ] Profile filled in (`config/profile.yaml`) -- **YOU NEED TO DO THIS**
- [ ] Base resume placed at `templates/base_resume.docx` -- **YOU NEED TO DO THIS**
- [ ] (Optional) Gmail credentials for email monitoring (`config/credentials.json`)

---

## CLI Commands Reference

### `scan` -- Discover Jobs

Scrapes all enabled sources, deduplicates, scores, and saves to DB + Excel.

```bash
python -m src.cli scan                          # All sources, keyword scoring only
python -m src.cli scan --llm                    # + LLM scoring on top 40 candidates
python -m src.cli scan --llm --llm-top 60       # LLM score top 60 instead
python -m src.cli scan --source greenhouse      # Only scan Greenhouse boards
python -m src.cli scan --source linkedin        # Only scan LinkedIn
python -m src.cli scan --limit 10               # Max 10 jobs per query per source
```

**Sources:** adzuna, jooble, themuse, greenhouse, lever, google_jobs, linkedin

### `review` -- View Ranked Jobs

```bash
python -m src.cli review                        # Show top 30 unapplied jobs
python -m src.cli review --min-score 60         # Only show score >= 60
python -m src.cli review --sponsor-only         # Only sponsor-likely jobs
python -m src.cli review --limit 50             # Show more results
```

### `stats` -- Application Statistics

```bash
python -m src.cli stats                         # Total, applied, interviewing, rejected, etc.
```

### `plan` -- Generate Daily Plan

Selects the best jobs for today. Prioritizes sponsor-likely, enforces max 3 per company.

```bash
python -m src.cli plan                          # Top 25 (default)
python -m src.cli plan --count 15               # Top 15
python -m src.cli plan --min-score 50           # Only jobs scoring >= 50
```

### `prepare` -- Generate Tailored Documents

For each planned job: researches company, generates resume + cover letter, runs quality gate.

```bash
python -m src.cli prepare                       # Prepare top 25
python -m src.cli prepare --count 10            # Prepare top 10
python -m src.cli prepare --skip-research       # Skip company research (faster)
```

**Requires:** `templates/base_resume.docx` and OpenAI API key.

**Quality Gate:** Each resume + cover letter is scored by LLM. Must score >= 7/10 on ATS compliance, keyword match, relevance, and readability. Failed docs are regenerated up to 2 times.

**Output:** `output/resumes/` and `output/cover_letters/` with filenames like `FirstName_LastName_Resume_CompanyName.docx`

### Application submission (Discord-first)

The shipped workflow is **manual apply** in the browser: use Discord **`/review`** → **Approve** → open the link on the **Apply Card**, then **I Applied** to log to SQLite and the Excel **Applied** sheet. There is **no** `python -m src.cli apply` in the current coach build.

### `monitor` -- Check Gmail for Updates

Reads your inbox (read-only) and classifies emails as: rejection, interview, assessment, offer.

```bash
python -m src.cli monitor                       # Check recent emails
python -m src.cli monitor --after 2026/03/01    # Only emails after March 1
```

**Requires:** Gmail OAuth credentials (`config/credentials.json`). First run opens browser for consent.

### `schedule` -- Automated Scheduler

Runs scan, email check, and daily plan on a timer. Press Ctrl+C to stop.

```bash
python -m src.cli schedule                              # Default: scan/6h, email/30m, plan at 8AM
python -m src.cli schedule --scan-hours 4               # Scan every 4 hours
python -m src.cli schedule --email-minutes 15           # Check email every 15 min
python -m src.cli schedule --plan-time 07:00            # Daily plan at 7 AM
```

---

## Data Pipeline Flow

```
scan  -->  7 Job Board Sources
             |
           Deduplicate (URL + fuzzy title/company)
             |
           Enrich sponsorship (known H1B sponsors + keywords)
             |
           Keyword scoring (role + skills + sponsorship + location)
             |
           [Optional] LLM semantic scoring (gpt-4o-mini)
             |
           Save to SQLite + Excel tracker

plan  -->  Pull top unapplied jobs from DB
             |
           Apply diversity rules (max 3/company)
             |
           Prioritize sponsor-likely jobs
             |
           Select top 25 for today

prepare --> Company research via LLM
              |
            Tailor resume (reword, reorder, match keywords)
              |
            Generate cover letter (personalized, ATS-friendly)
              |
            Quality gate (LLM scores >= 7/10, retry up to 2x)
              |
            Save .docx + .pdf to output/

(Discord)  -->  User opens apply URL manually, taps I Applied / set_status
              |
            Update tracker

monitor --> Poll Gmail (read-only)
              |
            Classify emails (rejection/interview/offer/assessment)
              |
            Fuzzy-match to applied jobs
              |
            Auto-update application status in DB
```

---

## Job Sources

| Source | Type | Key Required | Default Limit |
|--------|------|-------------|---------------|
| Adzuna | REST API | Yes (free) | 50/page, 3 pages |
| Jooble | REST API | Yes (free) | 50/request |
| The Muse | REST API | No | 20/page, 5 pages |
| Greenhouse | REST API | No | 15/board, 29 boards |
| Lever | REST API | No | 15/company, 25 companies |
| Google Jobs | SerpAPI | Yes (free 100/mo) | 3 pages |
| LinkedIn | Playwright | No | 50/session |

---

## Scoring System

**Keyword Score (0-100):**
- Role match: 30% weight
- Skills match: 30% weight
- Sponsorship: 20% weight
- Recency: 10% weight
- Location: 10% weight

**LLM Score (0-100, optional):**
- Role alignment, skills match, experience fit, growth opportunity
- Scored by gpt-4o-mini

**Enhanced Score (when LLM is used):**
- 35% keyword + 65% LLM

---

## Config Files

### `config/profile.yaml`
Your personal info, skills, education, visa status, preferences. **Must be filled in before running `prepare`.**

### `config/search_config.yaml`
Search queries, locations, scraper enable/disable, result limits. Edit to customize which roles and boards to search.

### `config/secrets.yaml`
All API keys. **Never share or commit this file.**

---

## ATS Compliance Rules (Enforced Automatically)

- Single-column layout, Calibri font 11pt, standard section headings
- No tables, images, columns, text boxes, headers/footers
- Keywords mirrored exactly from job description
- Professional Summary tailored per job (never generic "Objective")
- Filename format: `FirstName_LastName_Resume_CompanyName.docx`
- Never fabricate experience -- only rephrase and reorder existing content

---

## Troubleshooting

**"No scrapers configured"** -- Check that API keys in `secrets.yaml` don't contain placeholder values like `your-`.

**"Base resume not found"** -- Place your resume at `templates/base_resume.docx` (Word format).

**LinkedIn auth wall** -- LinkedIn may block after too many requests. The scraper stops gracefully. Try again later or set `headless: false` in `search_config.yaml` to see the browser.

**Gmail auth fails** -- You need `config/credentials.json` from Google Cloud Console (Gmail API > OAuth 2.0 Client ID > Desktop app). First run opens a browser for consent.

**Quality gate keeps failing** -- The LLM may need a better base resume to work with. Ensure your `base_resume.docx` has detailed bullet points with quantified achievements.

**docx2pdf fails** -- Requires Microsoft Word installed on Windows. If not available, .docx files are still generated (skip PDF).
