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


def extract_first_youtube_link(message) -> str | None:
    from func.youtube_summary import extract_youtube_link

    youtube_link = extract_youtube_link(str(getattr(message, "content", "") or ""))
    return youtube_link or None
