#!/usr/bin/env python3
"""
True local E2E: pytest + smoke + one real job-board scan (your API keys) + optional bot start.

Does not print secret values. Requires:
  - config/profile.yaml, config/secrets.yaml
  - At least one enabled scraper with valid keys (default run: Adzuna only)
  - Ollama or OpenAI for --llm scan step

Usage:
  python scripts/e2e_true.py                      # full pipeline
  python scripts/e2e_true.py --limit 50 --llm-top 15   # more results per query (more likely to insert new rows)
  python scripts/e2e_true.py --also-jooble      # after primary source, run Jooble too (if keys present)
  python scripts/e2e_true.py --skip-tests       # only smoke + scan(s) — faster iteration
  python scripts/e2e_true.py --start-bot        # also start Discord bot in background (Windows)

Afterward, complete the Discord checklist printed at the end.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _secret_ok(val: str | None) -> bool:
    if not val or not isinstance(val, str):
        return False
    v = val.strip()
    if len(v) < 8:
        return False
    if "your-" in v.lower():
        return False
    return True


def validate_config() -> tuple[list[str], str, bool]:
    """Return (problems, primary_scan_source, jooble_ok)."""
    import yaml

    problems: list[str] = []
    scan_source = "adzuna"
    sec_path = ROOT / "config" / "secrets.yaml"
    if not sec_path.exists():
        problems.append("Missing config/secrets.yaml")
        return problems, scan_source, False

    with open(sec_path, "r", encoding="utf-8") as f:
        secrets = yaml.safe_load(f) or {}

    if not _secret_ok(secrets.get("discord_bot_token")):
        problems.append("discord_bot_token missing or placeholder")

    adz = secrets.get("adzuna") or {}
    adz_ok = _secret_ok(adz.get("app_id")) and _secret_ok(adz.get("app_key"))
    jooble_key = (secrets.get("jooble") or {}).get("api_key", "")
    jooble_ok = _secret_ok(jooble_key)

    if not adz_ok and not jooble_ok:
        problems.append("Need Adzuna (app_id + app_key) or Jooble (api_key) for live scan")
    elif not adz_ok and jooble_ok:
        scan_source = "jooble"

    return problems, scan_source, jooble_ok


def _run_scan(
    py: str,
    source: str,
    limit: str,
    llm_top: str,
    use_llm: bool,
) -> int:
    cmd = [
        py,
        "-m",
        "src.cli",
        "scan",
        "--source",
        source,
        "--limit",
        limit,
        "--llm-top",
        llm_top,
    ]
    if use_llm:
        cmd.append("--llm")
    print(f"\n--- scan --source {source} --limit {limit} --llm-top {llm_top} ---\n")
    t0 = time.perf_counter()
    r = subprocess.run(cmd, cwd=str(ROOT))
    print(f"\nFinished in {time.perf_counter() - t0:.0f}s (exit {r.returncode})")
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="True E2E pipeline (keys on disk, not printed).")
    ap.add_argument("--skip-tests", action="store_true", help="Skip pytest + smoke_release")
    ap.add_argument("--skip-scan", action="store_true", help="Skip real job-board scan")
    ap.add_argument("--no-llm", action="store_true", help="Scan without LLM scoring (faster)")
    ap.add_argument("--start-bot", action="store_true", help="Start `python -m src.discord.bot` in background (Windows)")
    ap.add_argument(
        "--limit",
        type=str,
        default="50",
        help="Per-query page size for CLI scan (higher = more results, more likely new inserts). Default 50.",
    )
    ap.add_argument(
        "--llm-top",
        type=str,
        default="15",
        help="How many top keyword jobs get LLM scoring. Default 15.",
    )
    ap.add_argument(
        "--also-jooble",
        action="store_true",
        help="After the primary scan, run a second scan with --source jooble (if Jooble key is configured).",
    )
    args = ap.parse_args()
    py = sys.executable

    print("=== E2E: config validation ===\n")
    probs, scan_source, jooble_ok = validate_config()
    if probs:
        for p in probs:
            print(f"  [FAIL] {p}")
        print("\nFix secrets.yaml, then re-run.")
        return 1
    print(
        f"  [OK] secrets.yaml has Discord token + scraper keys (values not shown); "
        f"scan will use --source {scan_source}\n"
    )

    if not args.skip_tests:
        print("=== E2E: pytest ===\n")
        r = subprocess.run([py, "-m", "pytest", "tests", "-q", "--tb=short"], cwd=str(ROOT))
        if r.returncode != 0:
            print("\n[FAIL] pytest — fix tests before E2E.")
            return r.returncode

        print("\n=== E2E: smoke_release --with-llm ===\n")
        r = subprocess.run([py, str(ROOT / "scripts" / "smoke_release.py"), "--with-llm"], cwd=str(ROOT))
        if r.returncode != 0:
            print("\n[FAIL] smoke_release")
            return r.returncode

    if not args.skip_scan:
        print(
            f"\n=== E2E: real scan (primary={scan_source}, limit={args.limit}, llm-top={args.llm_top}) ===\n"
        )
        rc = _run_scan(py, scan_source, args.limit, args.llm_top, not args.no_llm)
        if rc != 0:
            print("[WARN] Primary scan failed — check network/API limits.")

        if args.also_jooble and jooble_ok and scan_source != "jooble":
            print("\n=== E2E: second scan (jooble) ===")
            rc2 = _run_scan(py, "jooble", args.limit, args.llm_top, not args.no_llm)
            if rc2 != 0:
                print("[WARN] Jooble scan failed.")
        elif args.also_jooble and not jooble_ok:
            print("\n[SKIP] --also-jooble requested but Jooble api_key not configured.")

        try:
            from src.tracker.db import get_detailed_stats

            stats = get_detailed_stats()
            print(
                f"\nDB snapshot: total_jobs={stats.get('total', '?')} "
                f"pending_review={stats.get('pending_review', '?')} "
                f"applied={stats.get('applied', '?')}"
            )
        except Exception as e:
            print(f"(Could not read stats: {e})")

    print("\n=== E2E: Discord (you are the human) ===\n")
    print("With the bot running, run these in order:\n")
    print("  1. /help")
    print("  2. /schedule")
    print("  3. /today")
    print("  4. /myday  (or describe availability)")
    print("  5. /review_count  then  /review  if count > 0")
    print("  6. /stats")
    print("")

    if args.start_bot:
        print("=== Starting Discord bot in background ===\n")
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            subprocess.Popen(
                [py, "-m", "src.discord.bot"],
                cwd=str(ROOT),
                creationflags=creationflags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            print("Bot process started detached. Check Discord for Helix online.")
        else:
            subprocess.Popen(
                [py, "-m", "src.discord.bot"],
                cwd=str(ROOT),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("Bot process started in background.")
    else:
        print("Start the bot manually:\n")
        print(f"  {py} -m src.discord.bot\n")

    print("E2E automation complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
