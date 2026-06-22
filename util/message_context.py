from dataclasses import dataclass
import logging

import discord


logger = logging.getLogger(__name__)


IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}
IMAGE_ONLY_LABEL = "(이미지)"


@dataclass(frozen=True, slots=True)
class MessageActionTarget:
    text: str
    image_url: str | None

    @property
    def has_input(self) -> bool:
        return bool(self.text or self.image_url)


@dataclass(frozen=True, slots=True)
class SurroundingMessageContext:
    previous_messages: str = ""
    following_messages: str = ""


def _is_image_attachment(attachment) -> bool:
    content_type = str(getattr(attachment, "content_type", "") or "").lower()
    if content_type.startswith("image/"):
        return True

    filename = str(getattr(attachment, "filename", "") or "").lower()
    return any(filename.endswith(extension) for extension in IMAGE_EXTENSIONS)


def _first_image_url(attachments) -> str | None:
    for attachment in attachments or []:
        if not _is_image_attachment(attachment):
            continue

        url = getattr(attachment, "url", None)
        if url:
            return str(url)

    return None


def build_message_action_target(message) -> MessageActionTarget:
    return MessageActionTarget(
        text=str(getattr(message, "content", "") or "").strip(),
        image_url=_first_image_url(getattr(message, "attachments", []) or []),
    )


def build_message_select_label(
    content: str,
    image_url: str | None = None,
    max_length: int = 50,
) -> str:
    normalized = str(content or "").strip()
    if not normalized and image_url:
        return IMAGE_ONLY_LABEL
    if not normalized:
        return "(내용 없음)"
    return normalized[:max_length] + ("..." if len(normalized) > max_length else "")


def build_recent_message_option(message) -> dict | None:
    target = build_message_action_target(message)
    if not target.has_input or target.text.startswith("/"):
        return None

    return {
        "content": target.text,
        "id": getattr(message, "id"),
        "image_url": target.image_url,
    }


def _is_same_author(left, right) -> bool:
    if left is None or right is None:
        return False
    if left is right:
        return True

    left_id = getattr(left, "id", None)
    right_id = getattr(right, "id", None)
    return left_id is not None and left_id == right_id


def _author_display_name(message) -> str:
    author = getattr(message, "author", None)
    for attribute in ("display_name", "global_name", "name"):
        value = getattr(author, attribute, None)
        if value:
            return str(value)

    if author is not None:
        return str(author)
    return "Unknown"


def _format_context_message(message) -> str:
    target = build_message_action_target(message)
    content_parts = []
    if target.text:
        content_parts.append(target.text)
    if target.image_url:
        content_parts.append("(이미지 첨부)")

    content = " ".join(content_parts).strip() or "(내용 없음)"
    return f"{_author_display_name(message)}: {content}"


def _is_surrounding_context_candidate(message, bot_user=None) -> bool:
    if bot_user is not None and _is_same_author(
        getattr(message, "author", None),
        bot_user,
    ):
        return False

    target = build_message_action_target(message)
    if not target.has_input:
        return False
    return not target.text.startswith("/")


async def build_surrounding_message_context(
    message,
    *,
    bot_user=None,
    limit: int = 10,
) -> SurroundingMessageContext:
    channel = getattr(message, "channel", None)
    if channel is None or limit <= 0:
        return SurroundingMessageContext()

    fetch_limit = limit * 5
    try:
        previous_messages = []
        async for context_message in channel.history(
            limit=fetch_limit,
            before=message,
            oldest_first=False,
        ):
            if not _is_surrounding_context_candidate(context_message, bot_user):
                continue
            previous_messages.append(context_message)
            if len(previous_messages) >= limit:
                break
        previous_messages.reverse()

        following_messages = []
        async for context_message in channel.history(
            limit=fetch_limit,
            after=message,
            oldest_first=True,
        ):
            if not _is_surrounding_context_candidate(context_message, bot_user):
                continue
            following_messages.append(context_message)
            if len(following_messages) >= limit:
                break
    except (discord.Forbidden, discord.HTTPException):
        logger.debug("주변 메시지 컨텍스트 조회 실패", exc_info=True)
        return SurroundingMessageContext()

    return SurroundingMessageContext(
        previous_messages="\n".join(
            _format_context_message(context_message)
            for context_message in previous_messages
        ),
        following_messages="\n".join(
            _format_context_message(context_message)
            for context_message in following_messages
        ),
    )


def extract_first_youtube_link(message) -> str | None:
    from func.youtube_summary import extract_youtube_link

    youtube_link = extract_youtube_link(str(getattr(message, "content", "") or ""))
    return youtube_link or None
