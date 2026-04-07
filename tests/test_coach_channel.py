"""Unit tests for Helix Coach channel helpers (no Discord)."""

from src.discord.coach_channel import extract_urls, split_discord_chunks


def test_extract_urls_trims_trailing_punctuation():
    assert extract_urls("See https://example.com/job/123) for details") == [
        "https://example.com/job/123"
    ]


def test_extract_urls_multiple():
    urls = extract_urls("a https://a.com/x b https://b.com/y")
    assert urls == ["https://a.com/x", "https://b.com/y"]


def test_split_discord_chunks_short():
    assert split_discord_chunks("hello") == ["hello"]


def test_split_discord_chunks_long():
    s = "word " * 500
    chunks = split_discord_chunks(s, limit=100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
