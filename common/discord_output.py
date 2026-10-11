import io
import discord


def text_options(text):
    text = str(text or "").strip() or "응답 내용이 없습니다."
    if len(text) <= 2000:
        return {"content": text, "allowed_mentions": discord.AllowedMentions.none()}
    return {"content": "응답이 길어 파일로 첨부했습니다.",
            "file": discord.File(io.BytesIO(text.encode("utf-8")), filename="response.txt"),
            "allowed_mentions": discord.AllowedMentions.none()}


async def send_text(target, text, **kwargs):
    return await target.send(**text_options(text), **kwargs)


async def edit_text(message, text, **kwargs):
    options = text_options(text)
    file = options.pop("file", None)
    if file is not None:
        options["attachments"] = [file]
    return await message.edit(**options, **kwargs)
