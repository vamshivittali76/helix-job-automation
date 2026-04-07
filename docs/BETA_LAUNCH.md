# Beta launch — test plan and ship checklist

Use this before tagging a release, posting on LinkedIn, or inviting beta testers.

**New users installing from scratch:** follow **[SETUP.md](../SETUP.md)** first (single canonical setup guide).

## What “end to end” means here

| Layer | Automated | Manual (Discord) |
|--------|-----------|-------------------|
| Config + DB + imports | `pytest`, `smoke_release.py` | — |
| Ollama / LLM | `smoke_release.py --with-llm` | `/ask`, `/myday` |
| Job pipeline | — | `/scan`, `/review`, `/today` |
| Docs | — | Follow [SETUP.md](../SETUP.md) on a clean machine |

Fully automated E2E (including Discord and job APIs) is not in CI — beta testers validate real flows.

---

## 1. Automated (run before every push / release)

From repo root, with venv activated:

```bash
python -m pytest tests -v
python scripts/test_helix_integration.py
python scripts/smoke_release.py
python scripts/smoke_release.py --with-llm
```

Expect: all tests pass; smoke exits 0; `--with-llm` prints a short reply when Ollama or OpenAI is configured.

**True E2E with your keys (live job boards, does not print secrets):**

```bash
python scripts/e2e_true.py
python scripts/e2e_true.py --skip-tests --limit 50 --llm-top 15 --also-jooble
```

Use higher `--limit` and `--also-jooble` when you want more hits and a better chance of **new** rows in a large existing DB.

CI (GitHub Actions) runs `pytest` on push/PR to `main` / `master`.

---

## 2. Manual beta script (~15 minutes)

**Fresh machine or second Windows account (recommended once):**

1. Clone repo, `pip install -r requirements.txt`, copy `secrets.template.yaml` → `secrets.yaml`, `profile.template.yaml` → `profile.yaml`.
2. Install [Ollama](https://ollama.ai), run `ollama pull llama3.2`, keep Ollama running.
3. Set `discord_bot_token` and LLM block in `secrets.yaml` (see SETUP.md).
4. Start bot: `python -m src.discord.bot`.
5. In Discord, verify:

| Step | Command / action | Expected |
|------|------------------|----------|
| 1 | `/help` | Command list |
| 2 | `/schedule` | Timezone + today’s windows |
| 3 | `/myday` free text *or* explicit `07:00-10:00` | Plan or regex windows |
| 4 | `/myday_clear` | Clears override |
| 5 | `/today` | Progress + strategy blurb |
| 6 | `/ask` with a simple question | SQL or LLM error only if no LLM |
| 7 | `/review` or `/review_count` | No crash (empty queue OK) |

**Optional:** run a small scan (`/scan` or CLI) if API keys are enabled — confirm no tracebacks.

---

## 3. GitHub

### 3a. Repository hygiene before push

Use this before every push; it is **required** for a public or open-source repo.

Run from the repo root. **Goal:** no secrets, no real `profile.yaml` / `secrets.yaml`, and no personal employer names or identifiers in **tracked** files.

| Step | Command or action | What you want |
|------|-------------------|---------------|
| 1 | `git status` | Nothing under **Changes to be committed** that should be private (`config/profile.yaml`, `config/secrets.yaml`, `config/credentials.json`, `config/gmail_token.json`, anything under `output/`). |
| 2 | `git ls-files config/` | Only safe, intentional paths — typically `profile.template.yaml`, `secrets.template.yaml`, `search_config.yaml`. **Not** `profile.yaml` or `secrets.yaml`. |
| 3 | `git check-ignore -v config/profile.yaml` | Prints the `.gitignore` rule that ignores `profile.yaml` (confirms it will not be committed by default). |
| 4 | `git diff` and, if staging, `git diff --cached` | No API keys, Discord tokens, or pasted personal URLs. |
| 5 | String checks on tracked text (adjust names to your situation) | No matches for employer names or your name in templates/docs: |

```bash
# Tracked files only — expect empty output (no matches)
git grep -i "tek" -- "*.yaml" "*.yml" "*.md" "*.xml" 2>nul
git grep -i "vamshi" 2>nul
```

On **PowerShell**, use `$null` instead of `2>nul`, or run the `git grep` lines without redirection; empty output means no hits.

| 6 | Open **`config/profile.template.yaml`** and **`PROJECT_CONTEXT.xml`** | Placeholders only (e.g. Jane Doe, `YOUR_ORG`); no real employers, emails, or home addresses. |
| 7 | **`README.md` / `SETUP.md`** clone URL | Replace `YOUR_ORG` with your real org or username **once** the public repo exists — or keep placeholder until then. |
| 8 | Optional — history | If you **ever** committed secrets or `profile.yaml`, rotate those keys/tokens and consider [git filter-repo](https://github.com/newren/git-filter-repo) or a fresh public repo; a normal `git push` does not remove old commits from history. |

### 3b. Release checklist

- [ ] `secrets.yaml` is **never** committed (`.gitignore`).
- [ ] Section **3a** steps satisfied for the branch you are pushing.
- [ ] `pytest` green locally and on CI.
- [ ] Tag: `git tag v0.x.y && git push origin v0.x.y`
- [ ] Release notes: Ollama-first LLM, `/myday`, link to SETUP.md.

---

## 4. LinkedIn (short post template)

Use your own voice; keep it factual:

> **Beta:** I’m opening a few slots for [Helix] — a Discord-based job search coach: scans boards, scores matches, tracks applications, and nudges you on daily goals. Runs locally with **Ollama** (no paid LLM required) or optional OpenAI. If you’re job searching and want to try it, comment or DM — I’ll send the repo + setup guide. Windows/macOS, Python 3.11+.

---

## 5. Beta feedback to collect

- Setup time (target: &lt; 30 min with SETUP.md).
- Ollama vs any cloud issues.
- One “must fix” and one “nice to have” from each tester.

---

## 6. Support

- Point testers to **SETUP.md** and [docs/BETA_LAUNCH.md](BETA_LAUNCH.md) (this file).
- Use a single channel (Discord thread, GitHub Discussions, or email) for feedback.
