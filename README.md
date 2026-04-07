# Helix — AI-Powered Job Search Coach

> **Beta** — Feedback welcome. See [docs/BETA_LAUNCH.md](docs/BETA_LAUNCH.md) for release checks.

Helix is a **Discord-native** job search coach: it discovers jobs, scores them against your profile, queues them for review, tracks applications, and helps you stay accountable. You apply on employer sites manually; Helix handles discovery, reminders, and optional Gmail read-only status updates.

**New here? Follow [SETUP.md](SETUP.md) end-to-end** — that is the single step-by-step guide (clone → venv → Discord bot → secrets → profile → run).

---

## What Helix Does

### Job discovery
- Scrapes multiple sources (configurable in `config/search_config.yaml`): e.g. Adzuna, Jooble, Greenhouse, Lever, Google Jobs, LinkedIn, The Muse, and more
- Deduplicates, scores with keyword + optional LLM matching, sponsorship hints, seniority
- Surfaces competition / expiry signals where available

### Review & apply (Discord)
- **`/review`** — next job in queue; **Approve** → **Apply Card** (direct link, match context, buttons)
- **I Applied** — logs to SQLite, sets follow-up reminder, refreshes the **Applied** sheet in the Excel tracker
- **Remind Me (2h)** — short reminder to apply
- **Resume Tips** — profile fitness + tips for that role
- **`/set_status`** — manual status updates (including applications you tracked outside Helix)

### Helix Coach (`#helix-coach`)
- Optional channel (auto-detected when named `#helix-coach`): paste job URLs for viability/fit/tips, or ask for cover-letter drafts, LinkedIn outreach, resume help, and general Q&A (requires Ollama or OpenAI)

### Accountability & schedule
- **`/today`**, **`/goal`**, **`/follow_up`**, **`/note`**, **`/schedule`**, **`/strategy`**, **`/myday`** — goals, follow-ups, and schedule-aware behavior driven by **`config/profile.yaml`** (your timezone and apply windows)

### Tracking & analytics
- **`/tracker`** — download **`output/tracker.xlsx`**: **Applications** (full queue), **Applied** (submitted applications), **Stats**
- **`/stats`**, **`/chart`**, **`/board`**, **`/profile_check`**

### Email (optional)
- **`/email_check`** — Gmail read-only monitoring when `config/credentials.json` is configured

---

## Discord commands (overview)

| Area | Commands |
|------|----------|
| Review | `/review`, `/review_batch`, `/review_count` |
| Discovery | `/scan`, `/jobs`, `/job`, `/fitness`, `/ask` |
| Apply / status | `/set_status`, `/status`, `/board`, `/tracker`, `/note` |
| Goals & schedule | `/today`, `/goal`, `/follow_up`, `/schedule`, `/strategy`, `/myday`, `/myday_clear` |
| Analytics | `/stats`, `/chart`, `/profile_check` |
| LinkedIn | `/linkedin_post`, `/linkedin_message`, `/linkedin_profile` |
| Email | `/email_check` |
| Help | `/help`, `/pin_commands` |

Full descriptions: use **`/help`** in Discord or browse [src/discord/bot.py](src/discord/bot.py) command tree.

---

## Quick start (short)

Full detail is only in **[SETUP.md](SETUP.md)**.

```bash
git clone https://github.com/vamshivittali76/helix-job-automation.git
cd helix-job-automation
python -m venv venv && venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp config/secrets.template.yaml config/secrets.yaml
cp config/profile.template.yaml config/profile.yaml
# Edit secrets.yaml (Discord token + LLM). Edit profile.yaml (you).
python -m src.discord.bot
```

---

## Requirements

- Python 3.11+
- Discord bot token ([SETUP.md](SETUP.md#step-3--create-your-discord-bot))
- **Ollama** (default, free) or **OpenAI** API key (optional)
- Optional: job API keys (Adzuna, Jooble, SerpAPI), Gmail OAuth for email monitoring

---

## Privacy

- `config/profile.yaml` and `config/secrets.yaml` are **gitignored**
- `output/` (database, tracker, generated files) is **gitignored**
- Only **templates** (e.g. `*.template.yaml`) belong in git

---

## Contributing / beta

Run tests and smoke scripts as described in **[docs/BETA_LAUNCH.md](docs/BETA_LAUNCH.md)** before tagging a release.

---

## Architecture (high level)

```
src/
  discord/       Bot, slash commands, ApplyCardView, charts, coach_channel (NL coach)
  scrapers/      Job sources
  matching/      Scoring, profile fitness, dedup
  tracker/       SQLite, Excel export (Applications + Applied + Stats)
  apply/         URL resolver, job page checks
  documents/     Resume / cover letter helpers
  email/         Gmail monitor (read-only)
  utils/         Schedule, LLM provider (Ollama / OpenAI)
config/
  profile.template.yaml   → copy to profile.yaml
  secrets.template.yaml   → copy to secrets.yaml
  search_config.yaml      Search queries and scraper toggles
```

Deeper product context for contributors and AI sessions: **[PROJECT_CONTEXT.xml](PROJECT_CONTEXT.xml)**.

---

## License

MIT
