from dataclasses import dataclass


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


def extract_first_youtube_link(message) -> str | None:
    from func.youtube_summary import extract_youtube_link

    youtube_link = extract_youtube_link(str(getattr(message, "content", "") or ""))
    return youtube_link or None
