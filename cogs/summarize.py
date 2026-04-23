import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from api.chatGPT import custom_prompt_model
from func.youtube_summary import (
    YOUTUBE_POST_KIND,
    YouTubeLinkCandidate,
    get_recent_youtube_links_with_titles,
    get_youtube_summary_title,
    process_youtube_link,
)
from util.get_recent_messages import get_recent_messages


def _truncate_select_text(text: str, max_length: int = 100) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def _build_recent_youtube_list_message(
    candidates: list[YouTubeLinkCandidate],
) -> str:
    lines = [
        f"최근 유튜브 링크 {len(candidates)}개를 찾았습니다. 요약할 항목을 선택해 주세요."
    ]
    for index, candidate in enumerate(candidates, start=1):
        link_label = "게시물" if candidate.link_kind == YOUTUBE_POST_KIND else "영상"
        lines.append(f"{index}. [{link_label}] {candidate.title}")
    return "\n".join(lines)


class YouTubeSummarySelect(discord.ui.Select):
    def __init__(
        self, candidates: list[YouTubeLinkCandidate], requester_id: int
    ) -> None:
        options = []
        for index, candidate in enumerate(candidates, start=1):
            link_label = "게시물" if candidate.link_kind == YOUTUBE_POST_KIND else "영상"
            options.append(
                discord.SelectOption(
                    label=_truncate_select_text(candidate.title),
                    description=f"{index}번째 {link_label} 링크",
                    value=str(index - 1),
                )
            )

        super().__init__(
            placeholder="요약할 항목을 선택해 주세요",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="youtube_summary_select",
        )
        self.candidates = candidates
        self.requester_id = requester_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "이 선택 메뉴는 명령어를 실행한 사용자만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        selected_candidate = self.candidates[int(self.values[0])]
        self.view.disable_items()
        await interaction.response.edit_message(
            content=(
                "선택한 항목을 요약 중입니다...\n"
                f"**제목**: {selected_candidate.title}\n"
                f"**링크**: {selected_candidate.url}"
            ),
            view=self.view,
        )

        try:
            summary_result = await process_youtube_link(selected_candidate.url)
        except Exception as e:
            await self.view.original_message.edit(
                content=f"오류가 발생했습니다: {e}",
                view=None,
            )
            self.view.stop()
            return

        await self.view.original_message.edit(
            content=(
                f"**선택한 항목**: {selected_candidate.title}\n"
                f"{get_youtube_summary_title(selected_candidate.link_kind)}\n"
                f"{summary_result}"
            ),
            view=None,
        )
        self.view.stop()


class YouTubeSummarySelectionView(discord.ui.View):
    def __init__(
        self,
        candidates: list[YouTubeLinkCandidate],
        requester_id: int,
        initial_content: str,
    ) -> None:
        super().__init__(timeout=300)
        self.original_message: discord.Message | None = None
        self.initial_content = initial_content
        self.add_item(YouTubeSummarySelect(candidates, requester_id))

    def disable_items(self) -> None:
        for child in self.children:
            child.disabled = True

    async def on_timeout(self) -> None:
        self.disable_items()
        if self.original_message is None:
            return

        try:
            await self.original_message.edit(
                content=(
                    f"{self.initial_content}\n\n"
                    "선택 시간이 만료되었습니다. `/요약`을 다시 실행해 주세요."
                ),
                view=self,
            )
        except discord.NotFound:
            pass


class SummarizeCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("SummarizeCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT -> SummarizeCommands Cog : on ready!")

    @app_commands.command(name="대화요약", description="최근 채팅 내용을 요약합니다.")
    @app_commands.describe(
        추가_요청="추가로 원하는 요약 사항이 있으면 입력하세요. (선택)"
    )
    async def conversation_summary(
        self, interaction: discord.Interaction, 추가_요청: str | None = None
    ):
        """
        커맨드 요약 처리
        오늘의 메시지 전체 요약
        """
        # 저장된 모든 대화 기록 확인
        if not self.bot.USER_MESSAGES:
            await interaction.response.send_message("**요약할 대화 내용이 없습니다.**")
            return

        # 최초 응답: "요약 중..." 메시지를 보냅니다.
        await interaction.response.send_message("요약 중...", ephemeral=False)

        # 요약 요청 메시지 생성
        request_message = 추가_요청 or ""

        # ChatGPT에 메시지 전달
        try:
            response = await asyncio.to_thread(
                custom_prompt_model,
                prompt={
                    "id": "pmpt_68ac08b66784819785d89655eaaaa7470bc0cc5deddb37d9",
                    "version": "3",
                    "variables": {
                        "recent_messages": get_recent_messages(
                            client=self.bot, guild_id=interaction.guild.id, limit=150
                        ),
                        "additional_requests": request_message,
                    },
                },
            )
        except Exception as e:
            response = f"Error: {e}"

        # 응답 출력
        sent_msg = await interaction.original_response()
        await sent_msg.edit(content=response)

    @app_commands.command(
        name="요약",
        description="최근 유튜브 링크 10개의 제목을 보여주고 선택한 항목을 요약합니다.",
    )
    async def youtube_summary(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        if interaction.channel is None:
            await interaction.edit_original_response(
                content="**현재 채널 정보를 확인할 수 없습니다.**"
            )
            return

        candidates = await get_recent_youtube_links_with_titles(
            interaction.channel,
            max_links=10,
            history_limit=300,
        )
        if not candidates:
            await interaction.edit_original_response(
                content="**이 채널에서 최근 유튜브 링크를 찾지 못했습니다.**"
            )
            return

        content = _build_recent_youtube_list_message(candidates)
        view = YouTubeSummarySelectionView(
            candidates,
            requester_id=interaction.user.id,
            initial_content=content,
        )
        await interaction.edit_original_response(content=content, view=view)
        view.original_message = await interaction.original_response()


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(SummarizeCommands(bot))
    print("SummarizeCommands Cog : setup 완료!")
