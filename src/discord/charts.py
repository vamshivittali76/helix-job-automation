"""
Chart generation for Discord bot.

Generates matplotlib PNG images for stats visualization,
uploaded as Discord file attachments.
"""

import io
import threading
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

_chart_lock = threading.Lock()

_DARK_RC = {
    "figure.facecolor": "#2b2d31",
    "axes.facecolor": "#1e1f22",
    "axes.edgecolor": "#4e5058",
    "axes.labelcolor": "#dbdee1",
    "text.color": "#dbdee1",
    "xtick.color": "#b5bac1",
    "ytick.color": "#b5bac1",
    "grid.color": "#3b3d44",
    "font.family": "sans-serif",
    "font.size": 10,
}


def _fig_to_bytes(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="#2b2d31")
    buf.seek(0)
    plt.close(fig)
    return buf


def chart_weekly(stats_by_day: dict) -> io.BytesIO:
    """
    Bar chart: jobs found vs applied per day over last 7 days.
    stats_by_day: {date_str: {"found": int, "applied": int}}
    """
    with _chart_lock, matplotlib.rc_context(_DARK_RC):
        return _chart_weekly_inner(stats_by_day)


def _chart_weekly_inner(stats_by_day: dict) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(8, 4))

    dates = sorted(stats_by_day.keys())[-7:]
    found = [stats_by_day.get(d, {}).get("found", 0) for d in dates]
    applied = [stats_by_day.get(d, {}).get("applied", 0) for d in dates]
    labels = [d[-5:] for d in dates]

    x = range(len(dates))
    w = 0.35
    ax.bar([i - w / 2 for i in x], found, w, label="Found", color="#5865f2")
    ax.bar([i + w / 2 for i in x], applied, w, label="Applied", color="#57f287")

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Jobs")
    ax.set_title("Weekly Activity")
    ax.legend()
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.grid(axis="y", alpha=0.3)

    return _fig_to_bytes(fig)


def chart_sources(by_source: dict) -> io.BytesIO:
    """Pie chart: jobs by source. by_source: {source_name: count}"""
    with _chart_lock, matplotlib.rc_context(_DARK_RC):
        return _chart_sources_inner(by_source)


def _chart_sources_inner(by_source: dict) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(6, 6))

    if not by_source:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", fontsize=14)
        return _fig_to_bytes(fig)

    colors = ["#5865f2", "#57f287", "#fee75c", "#ed4245", "#eb459e",
              "#f0b232", "#5bc0de", "#9b59b6"]
    labels = list(by_source.keys())
    sizes = list(by_source.values())

    ax.pie(sizes, labels=labels, colors=colors[:len(labels)], autopct="%1.0f%%",
           startangle=90, textprops={"color": "#dbdee1"})
    ax.set_title("Jobs by Source")

    return _fig_to_bytes(fig)


def chart_scores(scores: list[float]) -> io.BytesIO:
    """Histogram: score distribution."""
    with _chart_lock, matplotlib.rc_context(_DARK_RC):
        return _chart_scores_inner(scores)


def _chart_scores_inner(scores: list[float]) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(8, 4))

    if not scores:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", fontsize=14)
        return _fig_to_bytes(fig)

    ax.hist(scores, bins=20, range=(0, 100), color="#5865f2", edgecolor="#1e1f22")
    ax.set_xlabel("Match Score")
    ax.set_ylabel("Number of Jobs")
    ax.set_title("Score Distribution")
    ax.grid(axis="y", alpha=0.3)

    return _fig_to_bytes(fig)


def chart_funnel(stats: dict) -> io.BytesIO:
    """Horizontal funnel chart: new -> review -> approved -> applied -> interview -> offer."""
    with _chart_lock, matplotlib.rc_context(_DARK_RC):
        return _chart_funnel_inner(stats)


def _chart_funnel_inner(stats: dict) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(8, 4))

    stages = [
        ("New", stats.get("new", 0)),
        ("Review", stats.get("pending_review", 0)),
        ("Approved", stats.get("approved", 0)),
        ("Applied", stats.get("applied", 0)),
        ("Interview", stats.get("interview", 0)),
        ("Offer", stats.get("offer", 0)),
    ]
    labels = [s[0] for s in stages]
    values = [s[1] for s in stages]
    colors = ["#5865f2", "#f0b232", "#57f287", "#5bc0de", "#eb459e", "#fee75c"]

    ax.barh(labels[::-1], values[::-1], color=colors[::-1], height=0.6)
    for i, (lbl, val) in enumerate(zip(labels[::-1], values[::-1])):
        ax.text(val + 0.5, i, str(val), va="center", fontsize=11, fontweight="bold")

    ax.set_xlabel("Count")
    ax.set_title("Application Funnel")
    ax.grid(axis="x", alpha=0.3)

    return _fig_to_bytes(fig)


def chart_seniority(stats: dict) -> io.BytesIO:
    """Bar chart: jobs by seniority level."""
    with _chart_lock, matplotlib.rc_context(_DARK_RC):
        return _chart_seniority_inner(stats)


def _chart_seniority_inner(stats: dict) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(7, 4))

    levels = ["entry", "mid", "senior", "lead", "executive"]
    counts = [stats.get(f"seniority_{l}", 0) for l in levels]
    colors = ["#57f287", "#5865f2", "#f0b232", "#ed4245", "#eb459e"]

    ax.bar([l.title() for l in levels], counts, color=colors)
    ax.set_ylabel("Jobs")
    ax.set_title("Jobs by Seniority Level")
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.grid(axis="y", alpha=0.3)

    for i, v in enumerate(counts):
        ax.text(i, v + 0.3, str(v), ha="center", fontweight="bold")

    return _fig_to_bytes(fig)


def get_daily_stats_from_db() -> dict:
    """Query DB for daily found/applied counts over the last 7 days."""
    from src.tracker.db import get_connection
    conn = get_connection()
    result = {}
    for i in range(7):
        d = (datetime.now() - timedelta(days=6 - i)).strftime("%Y-%m-%d")
        found = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE date_found LIKE ?", (f"{d}%",)
        ).fetchone()[0]
        applied = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE date_applied LIKE ?", (f"{d}%",)
        ).fetchone()[0]
        result[d] = {"found": found, "applied": applied}
    conn.close()
    return result
