#!/usr/bin/env python3
"""
Pre-ship smoke checks (no Discord, no job-board APIs).

Usage:
  python scripts/smoke_release.py              # fast: config, DB, imports, Ollama ping
  python scripts/smoke_release.py --with-llm  # also one tiny Ollama/OpenAI chat (slower)

Exit code 0 = all checks passed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _ok(name: str) -> None:
    print(f"  [OK] {name}")


def _fail(name: str, detail: str) -> None:
    print(f"  [FAIL] {name}: {detail}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Run one minimal chat completion (requires local Ollama or configured cloud key).",
    )
    args = parser.parse_args()
    failed = 0

    print("=== Config files ===")
    for rel in ("config/profile.yaml", "config/secrets.yaml"):
        p = ROOT / rel
        if p.exists():
            _ok(rel)
        else:
            _fail(rel, "missing — copy from *.template.yaml")
            failed += 1

    print("\n=== Database ===")
    try:
        from src.tracker.db import init_db, get_connection

        init_db()
        conn = get_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        _ok("init_db + sqlite query")
    except Exception as e:
        _fail("database", str(e))
        failed += 1

    print("\n=== Core imports ===")
    try:
        from src.utils.llm_provider import create_llm_client, load_secrets, ollama_reachable, llm_backend_label
        from src.utils.schedule import coerce_schedule, user_local_day_key
        from src.matching.scorer import compute_match_score

        profile_path = ROOT / "config" / "profile.yaml"
        if profile_path.exists():
            import yaml

            with open(profile_path, "r", encoding="utf-8") as f:
                profile = yaml.safe_load(f)
            sched = coerce_schedule(profile)
            _ = user_local_day_key(sched)
        _ok("llm_provider, schedule, scorer")
    except Exception as e:
        _fail("imports", str(e))
        failed += 1

    print("\n=== LLM backend ===")
    try:
        from src.utils.llm_provider import create_llm_client, load_secrets, ollama_reachable, llm_backend_label

        secrets = load_secrets()
        base = (secrets.get("ollama_base_url") or "http://127.0.0.1:11434").rstrip("/")
        if ollama_reachable(base):
            _ok(f"Ollama reachable at {base}")
        else:
            print(f"  [WARN] Ollama not reachable at {base} (optional if using OpenAI only)")

        client = create_llm_client(secrets)
        if client:
            _ok(f"LLM client: {llm_backend_label(secrets)}")
        else:
            print("  [WARN] No LLM client — install Ollama or set openai_api_key (see SETUP.md)")

        if args.with_llm:
            if not client:
                _fail("LLM chat", "no client; cannot run --with-llm")
                failed += 1
            else:
                r = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Reply with one word only."},
                        {"role": "user", "content": "Say OK."},
                    ],
                    temperature=0,
                    max_tokens=8,
                )
                text = (r.choices[0].message.content or "").strip()
                if text:
                    _ok(f"LLM reply sample: {text[:40]!r}")
                else:
                    _fail("LLM chat", "empty response")
                    failed += 1
    except Exception as e:
        _fail("LLM backend", str(e))
        failed += 1

    print("\n=== Schedule parse (regex) ===")
    try:
        from src.utils.schedule_parse import _extract_windows_regex, parse_freeform_day_schedule

        rw = _extract_windows_regex("Free 09:00-11:00 and 14:00-16:00")
        if len(rw) >= 2:
            _ok(f"regex extraction: {rw}")
        else:
            _fail("regex extraction", str(rw))
            failed += 1

        try:
            out = parse_freeform_day_schedule(
                "Free 09:00-11:00 and 14:00-16:00",
                "UTC",
                "2026-04-07",
            )
            pw = out.get("windows") or []
            _ok(f"/myday parse path returned {len(pw)} window(s)")
        except Exception as e:
            print(f"  [WARN] full parse_freeform_day_schedule: {e}")
    except Exception as e:
        _fail("schedule_parse", str(e))
        failed += 1

    print("\n=== Discord module import (no token) ===")
    try:
        import discord  # noqa: F401

        _ok("discord.py import")
    except Exception as e:
        _fail("discord", str(e))
        failed += 1

    print()
    if failed:
        print(f"Smoke finished with {failed} failure(s).")
        return 1
    print("Smoke finished — all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
