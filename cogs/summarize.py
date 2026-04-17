import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from api.chatGPT import custom_prompt_model
from func.youtube_summary import (
    find_latest_youtube_link_in_channel,
    get_youtube_summary_title,
    process_youtube_link,
)
from util.get_recent_messages import get_recent_messages


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
        description="현재 채널의 가장 최근 유튜브 링크를 찾아 바로 요약합니다.",
    )
    async def youtube_summary(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        if interaction.channel is None:
            await interaction.edit_original_response(
                content="**현재 채널 정보를 확인할 수 없습니다.**"
            )
            return

        latest_link = await find_latest_youtube_link_in_channel(interaction.channel)
        if not latest_link:
            await interaction.edit_original_response(
                content="**이 채널에서 최근 유튜브 링크를 찾지 못했습니다.**"
            )
            return

        youtube_url, link_kind = latest_link
        try:
            summary_result = await process_youtube_link(youtube_url)
        except Exception as e:
            await interaction.edit_original_response(content=f"오류가 발생했습니다: {e}")
            return

        await interaction.edit_original_response(
            content=f"{get_youtube_summary_title(link_kind)}\n{summary_result}"
        )


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(SummarizeCommands(bot))
    print("SummarizeCommands Cog : setup 완료!")
