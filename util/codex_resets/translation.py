from __future__ import annotations

import asyncio
import json

from common.openai_prompt import build_prompt
from util.codex_resets.fetcher import CodexResetEvent


CODEX_RESET_TRANSLATION_PROMPT_ID = "pmpt_6acb11b275008195b640735bc30880b60285ae979fb0bf4d"
CODEX_RESET_TRANSLATION_PROMPT_VERSION = "2"


async def translate_codex_reset(event: CodexResetEvent) -> str:
    from api.chatGPT import custom_prompt_model

    source = json.dumps(
        {"text": event.text, "reset_type": event.reset_type}, ensure_ascii=False
    )
    result = await asyncio.to_thread(
        custom_prompt_model,
        prompt=build_prompt(
            CODEX_RESET_TRANSLATION_PROMPT_ID,
            CODEX_RESET_TRANSLATION_PROMPT_VERSION,
        ),
        image_content=[
            {"role": "user", "content": [{"type": "input_text", "text": source}]}
        ],
    )
    payload = json.loads(result)
    if not isinstance(payload, dict) or set(payload) != {"translation"}:
        raise ValueError("Invalid Codex reset translation response")
    translated = payload["translation"]
    if not isinstance(translated, str) or not translated.strip():
        raise ValueError("Codex reset translation is empty")
    if not any("\uac00" <= char <= "\ud7a3" for char in translated):
        raise ValueError("Codex reset translation must be in Korean")
    return translated.strip().replace("\u00b7", ", ")
