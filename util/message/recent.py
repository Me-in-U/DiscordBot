import logging
from datetime import datetime


logger = logging.getLogger(__name__)


def _format_content(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts, images = [], []
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type == "input_text":
                text = part.get("text", "")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
            elif part_type == "input_image":
                url = part.get("image_url")
                if isinstance(url, str) and url.strip():
                    images.append(url.strip())

        text_part = " ".join(texts) if texts else ""
        if images:
            image_part = (
                f"(image: {images[0]})"
                if len(images) == 1
                else f"(images: {len(images)}개)"
            )
            return f"{text_part} {image_part}".strip()
        return text_part
    return str(content)


def _extract_image_urls(content) -> tuple[str, ...]:
    if not isinstance(content, list):
        return ()

    urls = []
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "input_image":
            continue
        url = part.get("image_url")
        if isinstance(url, str) and url.strip():
            urls.append(url.strip())
    return tuple(urls)


def _parse_time(message):
    timestamp = message.get("time", "")
    try:
        return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return datetime(1970, 1, 1)


def _get_recent_entries(client, guild_id: int, limit: int) -> list[dict]:
    root = getattr(client, "USER_MESSAGES", {})
    if not isinstance(root, dict):
        logger.warning("get_recent_messages: USER_MESSAGES 타입 오류 -> %s", type(root))
        return []

    guild_map = root.get(guild_id) or {}
    if not isinstance(guild_map, dict):
        logger.warning("get_recent_messages: 길드 맵이 dict가 아님 -> %s", type(guild_map))
        return []

    all_messages = []
    for author, messages in guild_map.items():
        if not isinstance(messages, list):
            continue
        for message in messages:
            if isinstance(message, dict):
                all_messages.append({**message, "author": author})

    logger.debug(
        "get_recent_messages[guild=%s]: 집계된 메시지 수 = %s",
        guild_id,
        len(all_messages),
    )
    all_messages.sort(key=_parse_time, reverse=True)
    return list(reversed(all_messages[: max(limit, 0)]))


def get_recent_messages(client, guild_id: int, limit: int = 20):
    recent = _get_recent_entries(client, guild_id, limit)
    if not recent:
        return ""

    lines = []
    for message in recent:
        author = message.get("author", "unknown")
        role = message.get("role", "user")
        content = _format_content(message.get("content", ""))
        timestamp = message.get("time", "")
        lines.append(f"[{timestamp}] {author}({role}): {content}")

    logger.debug("최근 메시지 데이터 요청됨 (guild=%s): %s", guild_id, lines)
    return "\n".join(lines)


def get_recent_message_images(
    client,
    guild_id: int,
    limit: int = 150,
    max_images: int = 4,
) -> tuple[tuple[str, str], ...]:
    if max_images <= 0:
        return ()

    images = []
    for message in _get_recent_entries(client, guild_id, limit):
        author = message.get("author", "unknown")
        timestamp = message.get("time", "")
        for index, url in enumerate(
            _extract_image_urls(message.get("content", "")),
            start=1,
        ):
            label = f"[{timestamp}] {author} 메시지 첨부 이미지 {index}"
            images.append((label, url))

    return tuple(images[-max_images:])
