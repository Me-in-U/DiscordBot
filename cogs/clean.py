from __future__ import annotations

from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands


class Clean(commands.Cog):
    """메시지 정리 명령어 제공 Cog."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="clean",
        description="현재 채널에서 지정한 분(minutes) 동안의 메시지를 모두 삭제합니다 (관리자 전용).",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.describe(
        minutes="현재 시각부터 과거 몇 분까지 삭제할지(1~10080; 10080=7일)",
    )
    async def clean(
        self,
        interaction: discord.Interaction,
        minutes: app_commands.Range[int, 1, 10080],
    ) -> None:
        # 길드 내에서만 사용 가능
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "이 명령어는 길드 채널에서만 사용할 수 있습니다.", ephemeral=True
            )
            return

        # 관리자 권한 체크
        if (
            not isinstance(interaction.user, discord.Member)
            or not interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message(
                "관리자 권한이 있는 사용자만 사용할 수 있습니다.", ephemeral=True
            )
            return

        # 채널 타입 체크 (텍스트 채널에서 사용 권장)
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                "텍스트 채널(또는 스레드)에서만 사용할 수 있습니다.", ephemeral=True
            )
            return

        # 봇 권한 체크
        perms = channel.permissions_for(interaction.guild.me)  # type: ignore[arg-type]
        if not (perms.manage_messages and perms.read_message_history):
            await interaction.response.send_message(
                "봇에 '메시지 관리' 및 '메시지 기록 읽기' 권한이 필요합니다.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # 삭제 기준 시간: 현재부터 minutes분 전
        after = discord.utils.utcnow() - timedelta(minutes=int(minutes))

        reason = f"/clean by {interaction.user} (last {int(minutes)} minutes)"
        deleted_count = 0

        try:
            # purge가 지원되면 일괄 삭제 사용 (14일 이내 메시지 대상)
            if hasattr(channel, "purge"):
                deleted = await channel.purge(
                    after=after,
                    check=lambda m: not m.pinned,
                    reason=reason,
                )
                deleted_count = len(deleted)
            else:
                # 일부 채널 타입에서 purge 미지원 시 개별 삭제로 폴백
                async for message in channel.history(after=after, oldest_first=False):
                    if message.pinned:
                        continue
                    try:
                        await message.delete(reason=reason)
                        deleted_count += 1
                    except discord.Forbidden:
                        # 특정 메시지 삭제 권한 부족 시 건너뜀
                        continue

            await interaction.followup.send(
                f"🧹 삭제 완료: 최근 {int(minutes)}분 내 메시지 {deleted_count}개 삭제했습니다.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "권한이 부족하여 일부 또는 전부 삭제하지 못했습니다.", ephemeral=True
            )
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"삭제 중 오류가 발생했습니다: {e}", ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Clean(bot))
    print("Clean Cog : setup 완료!")
