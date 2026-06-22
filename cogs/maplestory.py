import logging

import discord
from discord import app_commands
from discord.ext import commands

from util.guild.channel_settings import set_channel
from util.maplestory.events import (
    MAPLESTORY_NOTICE_CHANNEL_TYPE,
    build_sunday_maple_event_embeds,
    fetch_sunday_maple_event,
    seed_maplestory_notice_state_for_guild,
)


logger = logging.getLogger(__name__)


class MapleStoryCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("MapleStoryCommands Cog : init 로드 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        print("DISCORD_CLIENT -> MapleStoryCommands Cog : on ready!")

    async def _require_guild_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "이 명령어는 길드에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return False
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "길드 멤버만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message(
            "관리자 권한이 있는 사용자만 메이플 공지 구독을 설정할 수 있습니다.",
            ephemeral=True,
        )
        return False

    @app_commands.command(
        name="썬데이메이플",
        description="진행 중인 스페셜 썬데이 메이플 이벤트 본문 이미지를 보여줍니다.",
    )
    async def sunday_maple(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            event = await fetch_sunday_maple_event()
        except Exception:
            logger.exception("썬데이메이플 이벤트 조회 실패")
            await interaction.followup.send(
                "⚠️ 메이플스토리 이벤트 정보를 가져오는 중 오류가 발생했습니다.",
                ephemeral=True,
            )
            return

        if event is None:
            await interaction.followup.send(
                "현재 진행중인 이벤트에 스페셜 썬데이 메이플이 없습니다."
            )
            return

        if not event.image_urls:
            await interaction.followup.send(
                f"스페셜 썬데이 메이플 이벤트는 찾았지만 본문 이미지를 찾지 못했습니다.\n{event.url}"
            )
            return

        await interaction.followup.send(embeds=build_sunday_maple_event_embeds(event))

    @app_commands.command(
        name="메이플공지구독",
        description="현재 채널에서 메이플스토리 새 공지와 수정 공지 알림을 받거나 해제합니다.",
    )
    @app_commands.describe(status="true면 현재 채널로 구독하고 false면 구독을 해제합니다.")
    @app_commands.rename(status="상태")
    async def configure_maplestory_notice_subscription(
        self,
        interaction: discord.Interaction,
        status: bool,
    ) -> None:
        if not await self._require_guild_admin(interaction):
            return

        guild_id = int(interaction.guild_id)
        if not status:
            await set_channel(guild_id, MAPLESTORY_NOTICE_CHANNEL_TYPE, None)
            await interaction.response.send_message(
                "메이플스토리 공지 구독을 해제했습니다.",
                ephemeral=True,
            )
            return

        if interaction.channel_id is None:
            await interaction.response.send_message(
                "현재 채널을 확인할 수 없어 구독을 설정하지 못했습니다.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        await set_channel(
            guild_id,
            MAPLESTORY_NOTICE_CHANNEL_TYPE,
            int(interaction.channel_id),
        )

        try:
            seeded_count = await seed_maplestory_notice_state_for_guild(guild_id)
        except Exception:
            logger.exception("메이플스토리 공지 초기 상태 저장 실패: guild_id=%s", guild_id)
            await interaction.followup.send(
                "메이플스토리 공지 구독을 설정했습니다.\n"
                "다만 최신 공지 초기 상태 저장에 실패해 다음 확인 때 초기화됩니다.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "메이플스토리 공지 구독을 설정했습니다.\n"
            f"알림 채널: <#{int(interaction.channel_id)}>\n"
            f"현재 최신 공지 {seeded_count}개는 전송하지 않고 이후 새 공지/수정 공지만 알립니다.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MapleStoryCommands(bot))
    print("MapleStoryCommands Cog : setup 완료!")
