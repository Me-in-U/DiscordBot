from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse, urlunparse

logger = logging.getLogger(__name__)

YOUTUBE_URL_PATTERN = re.compile(
    r"(?P<url>(?:https?://)?(?:www\.)?(?:youtube\.com|youtu\.be)/[^\s<>()\[\]{}]+)"
)
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
YOUTUBE_POST_KIND = "post"
YOUTUBE_VIDEO_KIND = "video"


def strip_wrapping_punctuation(url: str) -> str:
    return url.strip().lstrip("<(").rstrip(">.,!?)]}\"'")


def ensure_https_scheme(url: str) -> str:
    if re.match(r"^http://", url, flags=re.IGNORECASE):
        return re.sub(r"^http://", "https://", url, count=1, flags=re.IGNORECASE)
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        return f"https://{url}"
    return url


def normalize_youtube_link(url: str) -> str:
    cleaned_url = ensure_https_scheme(strip_wrapping_punctuation(url))
    parsed = urlparse(cleaned_url)
    path = parsed.path or ""

    if path.startswith("/shorts/"):
        video_id = path.split("/shorts/", 1)[1].split("/", 1)[0]
        normalized = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                "/watch",
                "",
                f"v={video_id}",
                "",
            )
        )
        logger.debug("normalized YouTube shorts URL: %s", normalized)
        return normalized

    logger.debug("normalized YouTube URL: %s", cleaned_url)
    return cleaned_url


def get_youtube_link_kind(url: str) -> str | None:
    normalized_url = ensure_https_scheme(strip_wrapping_punctuation(url))
    parsed = urlparse(normalized_url)
    host = parsed.netloc.lower()
    if host not in YOUTUBE_HOSTS:
        return None

    path = parsed.path or ""
    if path.startswith("/post/") and extract_post_id(normalized_url):
        return YOUTUBE_POST_KIND

    if extract_video_id(normalized_url):
        return YOUTUBE_VIDEO_KIND

    return None


def extract_youtube_link(link: str) -> str:
    youtube_links = extract_youtube_links(link)
    return youtube_links[0] if youtube_links else ""


def extract_youtube_links(link: str) -> list[str]:
    youtube_links: list[str] = []
    for match in YOUTUBE_URL_PATTERN.finditer(link):
        candidate_url = normalize_youtube_link(match.group("url"))
        if get_youtube_link_kind(candidate_url):
            youtube_links.append(candidate_url)
    return youtube_links


def extract_video_id(url: str) -> str:
    normalized_url = normalize_youtube_link(url)
    parsed = urlparse(normalized_url)
    host = parsed.netloc.lower()
    path = parsed.path or ""

    if host == "youtu.be":
        return path.strip("/").split("/", 1)[0]

    if path == "/watch":
        return parse_qs(parsed.query).get("v", [""])[0]

    if path.startswith("/live/"):
        return path.split("/live/", 1)[1].split("/", 1)[0]

    if path.startswith("/shorts/"):
        return path.split("/shorts/", 1)[1].split("/", 1)[0]

    return ""


def extract_post_id(url: str) -> str:
    normalized_url = ensure_https_scheme(strip_wrapping_punctuation(url))
    parsed = urlparse(normalized_url)
    path = parsed.path or ""
    if path.startswith("/post/"):
        return path.split("/post/", 1)[1].split("/", 1)[0]
    return ""
