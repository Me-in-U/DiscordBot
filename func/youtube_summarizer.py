from __future__ import annotations

import asyncio

from api.chatGPT import custom_prompt_model
from common.openai_prompt import build_prompt
from func.youtube_post import YouTubePostInfo, build_youtube_post_summary_input


COMMENTS_SUMMARY_PROMPT_ID = "pmpt_68abfada6cc8819392effc146b3a39730a3a8fd787c57011"
COMMENTS_SUMMARY_PROMPT_VERSION = "13"
YOUTUBE_SUMMARY_PROMPT_ID = "pmpt_68ac079c0d1081958393a758f0b6f4cc01c6576daa0b0eb7"
YOUTUBE_SUMMARY_PROMPT_VERSION = "11"
YOUTUBE_POST_SUMMARY_PROMPT_ID = "pmpt_6aedb39c5eb88190bfc93fa1dbfd5f3f05961944c524521a"
YOUTUBE_POST_SUMMARY_PROMPT_VERSION = "1"


async def summarize_comments_with_gpt(comments: list) -> str:
    comments_text = "\n".join(comments)
    response_text = await asyncio.to_thread(
        custom_prompt_model,
        prompt=build_prompt(
            COMMENTS_SUMMARY_PROMPT_ID,
            COMMENTS_SUMMARY_PROMPT_VERSION,
            {"comments_text": comments_text},
        ),
    )
    return response_text


async def summarize_text_with_gpt(youtube_text: str) -> str:
    response_text = await asyncio.to_thread(
        custom_prompt_model,
        prompt=build_prompt(
            YOUTUBE_SUMMARY_PROMPT_ID,
            YOUTUBE_SUMMARY_PROMPT_VERSION,
            {"youtube_text": youtube_text},
        ),
    )
    return response_text


async def summarize_youtube_post_with_gpt(post_info: YouTubePostInfo) -> str:
    post_input = build_youtube_post_summary_input(post_info)
    return await asyncio.to_thread(
        custom_prompt_model,
        prompt=build_prompt(YOUTUBE_POST_SUMMARY_PROMPT_ID, YOUTUBE_POST_SUMMARY_PROMPT_VERSION),
        max_output_tokens=400,
        image_content=[{"role": "user", "content": [{"type": "input_text", "text": post_input}]}],
    )
