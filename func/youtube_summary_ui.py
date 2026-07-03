from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import discord

from func.youtube_links import (
    YOUTUBE_POST_KIND,
    YOUTUBE_VIDEO_KIND,
    extract_youtube_link,
    get_youtube_link_kind,
)
from util.logging_utils import log_user_error


logger = logging.getLogger(__name__)
SummaryProcessor = Callable[[str], Awaitable[str]]


def get_youtube_prompt_text(link_kind: str) -> str:
    if link_kind == YOUTUBE_POST_KIND:
        return "유튜브 게시물 요약을 진행하시겠습니까?"
    return "유튜브 영상 요약을 진행하시겠습니까?"


def get_youtube_summary_title(link_kind: str) -> str:
    if link_kind == YOUTUBE_POST_KIND:
        return "**[게시물 요약]**"
    return "**[영상 3줄 요약]**"


class YouTubeSummaryView(discord.ui.View):
    def __init__(
        self,
        youtube_url: str,
        link_kind: str,
        processor: SummaryProcessor | None = None,
    ):
        super().__init__(timeout=300)
        self.youtube_url = youtube_url
        self.link_kind = link_kind
        self._processor = processor
        self.original_message: discord.Message | None = None

    @discord.ui.button(label="요약하기", style=discord.ButtonStyle.primary)
    async def yes_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True, thinking=False)

        button.disabled = True
        button.label = "요약 진행중"
        button.style = discord.ButtonStyle.success
        if self.original_message:
            await self.original_message.edit(view=self)

        try:
            processor = self._processor or _load_default_processor()
            summary_result = await processor(self.youtube_url)

            if self.original_message:
                await self.original_message.edit(
                    content=f"{get_youtube_summary_title(self.link_kind)}\n{summary_result}",
                    view=None,
                )

        except Exception as exc:
            button.disabled = True
            button.label = "오류!"
            button.style = discord.ButtonStyle.danger
            if self.original_message:
                await self.original_message.edit(
                    content=log_user_error(
                        logger,
                        "유튜브 요약",
                        exc,
                        extra={"youtube_url": self.youtube_url},
                    ),
                    view=self,
                )

        self.stop()

    async def on_timeout(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
                child.label = "기간만료!"
                child.style = discord.ButtonStyle.danger
        if self.original_message:
            await self.original_message.edit(content="5분이내만 가능", view=self)

            await asyncio.sleep(60)
            try:
                await self.original_message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.debug("유튜브 요약 안내 메시지 삭제 실패", exc_info=True)


async def check_youtube_link(
    message,
    processor: SummaryProcessor | None = None,
) -> None:
    youtube_url = extract_youtube_link(message.content)
    if youtube_url:
        link_kind = get_youtube_link_kind(youtube_url) or YOUTUBE_VIDEO_KIND
        view = YouTubeSummaryView(youtube_url, link_kind, processor=processor)
        sent_msg = await message.reply(
            content=get_youtube_prompt_text(link_kind),
            view=view,
        )
        view.original_message = sent_msg


def _load_default_processor() -> SummaryProcessor:
    from func.youtube_summary import process_youtube_link

    return process_youtube_link
