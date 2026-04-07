# Helix — Setup Guide (step-by-step)

**Use this file for complete setup from zero to a running bot.**  
CLI-only workflows, command reference, and automation details are in **[GUIDE.md](GUIDE.md)**.  
Pre-release checks: **[docs/BETA_LAUNCH.md](docs/BETA_LAUNCH.md)**.

Helix is a Discord-native job search coach: it scans sources, scores jobs, queues them for your review, tracks applications, and can remind you on a schedule you define in `config/profile.yaml`.

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) |
| pip | bundled | `python -m pip install --upgrade pip` |
| Discord account | any | Free |
| Ollama (recommended) | latest | Free local LLM — [ollama.ai](https://ollama.ai) |
| OpenAI account | optional | Only if you prefer cloud LLM or fallback |

---

## Step 1 — Get the code

```bash
git clone https://github.com/YOUR_ORG/helix-job-automation.git
cd helix-job-automation
```

---

## Step 2 — Virtual environment and dependencies

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

---

## Step 3 — Create your Discord bot

1. Open [discord.com/developers/applications](https://discord.com/developers/applications)
2. **New Application** → name it (e.g. `Helix`)
3. **Bot** → **Add Bot** → confirm
4. Under **Privileged Gateway Intents**, enable:
   - **Message Content Intent** (required for Helix Coach text channel)
   - **Server Members Intent** (if you use member-related features)
5. **Reset Token** → copy the token (you will paste it into `secrets.yaml` in Step 5)
6. **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: **Send Messages**, **Embed Links**, **Attach Files**, **Read Message History**, **Add Reactions**
7. Open the generated URL and invite the bot to your server

### Channels Helix recognizes by name

Create text channels as needed (names matter for auto-detection):

| Channel name | Purpose |
|--------------|---------|
| `#helix-jobs`, `#job-feed`, `#daily-digest`, or `#general` | Notifications, digests, scan results (first match wins) |
| `#helix-coach` | Optional **Helix Coach**: paste job URLs, ask for cover letters, LinkedIn outreach, resume help (auto-detected; no ID required) |

---

## Step 4 — Ollama (free local LLM, default)

1. Install [Ollama](https://ollama.ai) and start it
2. Pull a model once:

```bash
ollama pull llama3.2
```

Defaults in `secrets.yaml`: `llm_provider: auto`, `ollama_base_url: http://127.0.0.1:11434`, `ollama_model: llama3.2`.  
**Optional:** set `llm_provider: openai` and add `openai_api_key` if you want cloud-only or fallback when Ollama is down.

---

## Step 5 — Secrets (`config/secrets.yaml`)

```bash
cp config/secrets.template.yaml config/secrets.yaml
```

Edit `config/secrets.yaml`. Minimum to run the bot:

```yaml
discord_bot_token: "PASTE_TOKEN_FROM_STEP_3"

llm_provider: auto
ollama_base_url: "http://127.0.0.1:11434"
ollama_model: "llama3.2"
openai_api_key: ""
```

**Optional (recommended for job scans):** Adzuna `app_id` / `app_key`, Jooble `api_key`, SerpAPI `serpapi_key` — see comments in `secrets.template.yaml`.

**Optional — Gmail (read-only status monitoring):** Download OAuth **Desktop** client JSON from Google Cloud → save as `config/credentials.json`, then run `python -m src.cli monitor --setup` when ready.

**Optional — Helix Coach channel override:** If you do **not** use the name `#helix-coach`, set `helix_coach_channel_id` to your channel’s numeric ID (Discord: Settings → Advanced → Developer Mode → right‑click channel → Copy ID). Use `0` or omit to auto-detect `#helix-coach`.

`config/secrets.yaml` is **gitignored** — never commit it.

---

## Step 6 — Profile (`config/profile.yaml`)

```bash
cp config/profile.template.yaml config/profile.yaml
```

Fill in at least:

- **`personal`** — name, email, phone, LinkedIn (used for documents and coaching)
- **`target_roles`**, **`skills`**, **`work_experience`**, **`preferences`**
- **`daily_application_target`**
- **`schedule`** — `timezone`, `apply_windows`, digest/scan preferences (Helix uses **your** timezone, not the server clock)

`config/profile.yaml` is **gitignored**.

---

## Step 7 — Search configuration (optional)

Edit **`config/search_config.yaml`** — search queries, locations, filters, and which scrapers are enabled (Adzuna, Jooble, Greenhouse, Lever, Google Jobs, LinkedIn, etc.).  
Tune this after your first `/scan` to match your market.

---

## Step 8 — Run the Discord bot

```bash
# Windows
venv\Scripts\python -m src.discord.bot

# macOS / Linux
python -m src.discord.bot
```

Expected log lines include: connected user, synced slash commands, notification channel, **`Helix Coach channel: #helix-coach`** if that channel exists, and **Helix is ready.**

---

## Step 9 — First actions in Discord

| Command | What it does |
|---------|----------------|
| `/scan` | Pull new jobs from enabled sources into your queue |
| `/review` | Review the next job; **Approve** → apply card (link + **I Applied** / **Remind Me (2h)** / **Resume Tips**) |
| `/today` | Progress vs daily goal |
| `/tracker` | Download **`output/tracker.xlsx`** — sheets **Applications** (full queue), **Applied** (submitted apps), **Stats** |
| `/help` | All slash commands |

In **`#helix-coach`** (if you created it): paste a job URL for fit/viability/tips, or ask for cover-letter drafts, LinkedIn recruiter messages, and general career help (needs Ollama or OpenAI).

---

## Keeping Helix running

- **Windows:** Task Scheduler, or keep a terminal open with the bot process
- **macOS/Linux:** `nohup`, `tmux`, or `systemd`
- **Cloud:** Small VPS with Python + Ollama (or OpenAI only)

---

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| `discord_bot_token not set` | `config/secrets.yaml` exists and contains a real token |
| Slash commands missing | Wait a few minutes; restart bot; ensure bot was invited with `applications.commands` |
| `ModuleNotFoundError` | Activate `venv` and `pip install -r requirements.txt` |
| Bot posts in wrong channel | Create `#helix-jobs`, `#job-feed`, `#daily-digest`, or use `#general` (see Step 3 table) |
| LLM errors in Discord | Start Ollama and `ollama list`, or set `openai_api_key` |
| Helix Coach not responding | Channel must be named **`helix-coach`** or set `helix_coach_channel_id`; bot needs **Message Content Intent** |

---

## Feedback

Open a GitHub issue or share feedback from the beta. This guide is the **single place** for full install steps; **[GUIDE.md](GUIDE.md)** covers CLI power-user flows.

**Publishing the repo:** before you `git push` a public fork, run the **repository hygiene** checklist in **[docs/BETA_LAUNCH.md §3a](docs/BETA_LAUNCH.md#3a-repository-hygiene-before-push)** so secrets and personal data never land in git history.
