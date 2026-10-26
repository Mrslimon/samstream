"""Parsing a link into a YouTube video id."""

import pytest
from aiosamstream import youtube_id


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?si=xyz", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=30s", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/abc123DEF_-", "abc123DEF_-"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://example.com/video.mp4", None),
        ("https://www.youtube.com/", None),
        ("https://www.youtube.com/watch?v=tooshort", None),
        ("not a url", None),
    ],
)
def test_youtube_id(url: str, expected: str | None) -> None:
    assert youtube_id(url) == expected
