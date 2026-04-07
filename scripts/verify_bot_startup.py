#!/usr/bin/env python3
"""
Local check: same schedule preview Helix prints after connecting (before Discord sync).
Run after code changes:  python scripts/verify_bot_startup.py

Full bot (sync + Discord):  venv\\Scripts\\python -m src.discord.bot
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    import yaml

    prof = ROOT / "config" / "profile.yaml"
    if not prof.exists():
        print("Missing config/profile.yaml")
        return 1
    with open(prof, "r", encoding="utf-8") as f:
        profile = yaml.safe_load(f)
    from src.utils.schedule import coerce_schedule, describe_next_events

    sched = coerce_schedule(profile)
    print("Schedule (profile timezone) — expect similar lines in bot console after 'Helix is ready.':")
    print(describe_next_events(sched))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
