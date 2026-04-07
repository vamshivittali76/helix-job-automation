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

- [ ] `secrets.yaml` is **never** committed (`.gitignore`).
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
