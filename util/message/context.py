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
MAX_SURROUNDING_CONTEXT_IMAGES = 4


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
    images: tuple["MessageContextImage", ...] = ()


@dataclass(frozen=True, slots=True)
class MessageContextImage:
    label: str
    url: str


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


def _format_context_message(message, image_label: str | None = None) -> str:
    target = build_message_action_target(message)
    content_parts = []
    if target.text:
        content_parts.append(target.text)
    if target.image_url:
        content_parts.append(
            f"({image_label})" if image_label else "(이미지 첨부)"
        )

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


def _collect_surrounding_context_images(
    previous_messages,
    following_messages,
    *,
    limit: int = MAX_SURROUNDING_CONTEXT_IMAGES,
) -> tuple[tuple[MessageContextImage, ...], dict[int, str]]:
    if limit <= 0:
        return (), {}

    candidates = []
    max_distance = max(len(previous_messages), len(following_messages))
    for distance in range(max_distance):
        if distance < len(previous_messages):
            candidates.append(("이전", previous_messages[-1 - distance]))
        if distance < len(following_messages):
            candidates.append(("이후", following_messages[distance]))

    images = []
    labels_by_message = {}
    section_counts = {"이전": 0, "이후": 0}
    for section, context_message in candidates:
        image_url = build_message_action_target(context_message).image_url
        if not image_url:
            continue

        section_counts[section] += 1
        label = f"{section} 메시지 첨부 이미지 {section_counts[section]}"
        images.append(MessageContextImage(label=label, url=image_url))
        labels_by_message[id(context_message)] = label
        if len(images) >= limit:
            break

    return tuple(images), labels_by_message


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

    context_images, image_labels = _collect_surrounding_context_images(
        previous_messages,
        following_messages,
    )

    return SurroundingMessageContext(
        previous_messages="\n".join(
            _format_context_message(
                context_message,
                image_labels.get(id(context_message)),
            )
            for context_message in previous_messages
        ),
        following_messages="\n".join(
            _format_context_message(
                context_message,
                image_labels.get(id(context_message)),
            )
            for context_message in following_messages
        ),
        images=context_images,
    )


def extract_first_youtube_link(message) -> str | None:
    from func.youtube_summary import extract_youtube_link

    youtube_link = extract_youtube_link(str(getattr(message, "content", "") or ""))
    return youtube_link or None
