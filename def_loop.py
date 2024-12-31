from datetime import time

import discord
from discord.ext import commands, tasks

from bot import CHANNEL_ID, SEOUL_TZ


class LoopTasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.presence_update_task.start()
        print("LoopTasks Cog : init 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT on_ready() -> LoopTasks Cog : on ready!")

    @tasks.loop(seconds=10)
    async def presence_update_task(self):
        """1분마다 Discord 봇 상태(Presence)를 갱신합니다."""
        total_messages = sum(
            len(msg_list) for msg_list in self.bot.USER_MESSAGES.values()
        )
        formatted_total_messages = f"{total_messages:,}"
        # discord.Activity를 명시적으로 사용
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"!도움 | {formatted_total_messages}개의 채팅 메시지",
        )
        await self.bot.change_presence(activity=activity)

    @presence_update_task.before_loop
    async def before_presence_update_task(self):
        print("봇 on ready 대기중...")
        await self.bot.wait_until_ready()


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(LoopTasks(bot))
    print("LoopTasks Cog : setup 완료!")
