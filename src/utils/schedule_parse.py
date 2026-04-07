"""
Parse natural-language daily availability into apply window strings (HH:MM-HH:MM).

Uses the same LLM backend as the rest of Helix (local Ollama by default — see llm_provider).
Falls back to regex extraction of explicit HH:MM-HH:MM ranges when no LLM is available.
"""

from __future__ import annotations

import json
import re


def _normalize_window(s: str) -> str | None:
    """Validate and normalize 'H:MM-H:MM' or 'HH:MM-HH:MM' to 'HH:MM-HH:MM'."""
    s = s.strip().replace("–", "-").replace("—", "-")
    m = re.match(
        r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$",
        s,
    )
    if not m:
        return None
    sh, sm, eh, em = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    if not (0 <= sh <= 23 and 0 <= eh <= 23 and 0 <= sm <= 59 and 0 <= em <= 59):
        return None
    return f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"


def _extract_windows_regex(text: str) -> list[str]:
    """Best-effort extraction of HH:MM-HH:MM windows when the API is unavailable."""
    if not text:
        return []
    pattern = re.compile(
        r"\b(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})\b",
        re.IGNORECASE,
    )
    found: list[str] = []
    for m in pattern.finditer(text):
        cand = f"{m.group(1)}:{m.group(2)}-{m.group(3)}:{m.group(4)}"
        n = _normalize_window(cand)
        if n:
            found.append(n)
    seen = set()
    out: list[str] = []
    for w in found:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _validate_windows(raw: list) -> list[str]:
    out: list[str] = []
    for item in raw or []:
        if not isinstance(item, str):
            continue
        n = _normalize_window(item)
        if n:
            out.append(n)
    seen = set()
    uniq = []
    for w in out:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq


def parse_freeform_day_schedule(
    text: str,
    timezone_name: str,
    calendar_day: str,
) -> dict:
    """
    Turn free-form text into apply windows for one calendar day.

    Returns:
        {"windows": ["07:00-10:00", ...], "summary": "short explanation"}

    Raises:
        ValueError: empty input, or cannot parse even with regex fallback
    """
    from src.utils.llm_provider import create_llm_client, load_secrets

    text = (text or "").strip()
    if not text:
        raise ValueError("Describe when you can apply today (availability and any blocks like gym).")

    secrets = load_secrets()
    client = create_llm_client(secrets)

    system = (
        "You extract job-application time windows from the user's message. "
        "The user describes their day in natural language (office, gym, meetings, etc.).\n"
        "Rules:\n"
        "- Output ONLY valid JSON: {\"windows\": [\"HH:MM-HH:MM\", ...], \"summary\": \"one short sentence\"}\n"
        "- Times are 24-hour in the user's local timezone (given separately). Use two digits for hours when needed.\n"
        "- Each window is when they CAN actively search and submit applications (focused time).\n"
        "- Subtract blocked time: gym, commute, meetings, sleep, meals unless they say they apply during those.\n"
        "- If they give multiple ranges (e.g. 7am-10am and 4pm-11pm with gym 7-8pm in the evening), "
        "split the evening block around the gym.\n"
        "- If they truly have no time to apply, use \"windows\": [].\n"
        "- Do not invent windows they did not imply.\n"
    )
    user_msg = (
        f"Calendar date (local): {calendar_day}\n"
        f"Timezone: {timezone_name}\n\n"
        f"User message:\n{text}"
    )

    if client:
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            raw = (response.choices[0].message.content or "").strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"Could not parse model response: {e}") from e

            windows = _validate_windows(data.get("windows"))
            summary = data.get("summary")
            if not isinstance(summary, str):
                summary = ""
            summary = summary.strip()[:500]

            return {"windows": windows, "summary": summary}
        except Exception:
            pass

    fallback = _extract_windows_regex(text)
    if fallback:
        return {
            "windows": fallback,
            "summary": "Parsed from explicit times in your message (install Ollama for full natural-language parsing).",
        }
    raise ValueError(
        "Could not parse your schedule. Install **Ollama** (free) from https://ollama.ai, run `ollama pull llama3.2`, "
        "start Ollama, then try again — or type explicit windows like `07:00-10:00` and `16:00-23:00`."
    )
