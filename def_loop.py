from datetime import datetime, time
import json

import discord
from discord.ext import commands, tasks

from bot import CHANNEL_ID, SEOUL_TZ
from requests_riot import get_rank_data


class LoopTasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.presence_update_task.start()
        self.new_day_clear.start()
        self.update_rank_data.start()
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

    @tasks.loop(time=time(hour=0, minute=0, tzinfo=SEOUL_TZ))  # 매일 자정
    async def new_day_clear(self):
        """매일 자정에 user_messages를 초기화."""
        target_channel = self.bot.get_channel(CHANNEL_ID)
        if not target_channel:
            print("대상 채널을 찾을 수 없습니다.")
            return

        self.bot.USER_MESSAGES = {}
        print(f"[{datetime.now()}] user_messages 초기화 완료.")
        await target_channel.send("📢 새로운 하루가 시작됩니다.")

    @tasks.loop(time=time(hour=0, minute=0, tzinfo=SEOUL_TZ))  # 매일 자정
    async def update_rank_data(self):
        """매일 자정에 랭킹 정보를 업데이트합니다."""
        target_channel = self.bot.get_channel(CHANNEL_ID)
        if not target_channel:
            print("대상 채널을 찾을 수 없습니다.")
            return

        if self.daily_rank_loop:
            try:
                await target_channel.send(
                    "📢 새로운 하루가 시작됩니다. 일일 솔랭 정보 출력"
                )
                today_rank_data = get_rank_data(self.game_name, self.tag_line, "solo")

                # JSON 파일 로드 및 업데이트
                with open(self.bot.SETTING_DATA, "r", encoding="utf-8") as file:
                    settings = json.load(file)

                yesterday_data = settings["dailySoloRank"]["yesterdayData"]

                # 새로운 유저 확인
                if (
                    yesterday_data["game_name"] != today_rank_data["game_name"]
                    or yesterday_data["tag_line"] != today_rank_data["tag_line"]
                ):
                    await target_channel.send("🆕 새로운 유저가 감지되었습니다!")
                    settings["dailySoloRank"]["yesterdayData"] = today_rank_data
                    rank_update_message = self.print_rank_data(today_rank_data)
                else:
                    # 어제 데이터를 업데이트
                    settings["dailySoloRank"]["yesterdayData"] = today_rank_data
                    rank_update_message = self.print_rank_data(
                        today_rank_data, yesterday_data
                    )
                await target_channel.send(rank_update_message)

                # JSON 파일 저장
                with open(self.bot.SETTING_DATA, "w", encoding="utf-8") as file:
                    json.dump(settings, file, ensure_ascii=False, indent=4)

            except Exception as e:
                await target_channel.send(
                    f"❌ 랭킹 정보를 업데이트하는 중 오류가 발생했습니다: {e}"
                )


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(LoopTasks(bot))
    print("LoopTasks Cog : setup 완료!")
