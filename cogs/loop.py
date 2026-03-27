import asyncio
import json
import os
from datetime import datetime, time

import discord
from discord.ext import commands, tasks
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from api.riot import get_rank_data
from bot import (
    SONPANNO_GUILD_ID,
    SEOUL_TZ,
    load_recent_messages,
)
from util.celebration import refresh_celebration_messages
from util.db import fetch_all, fetch_one, execute_query
from util.env_utils import getenv_clean
from func.find1557 import clearCount


class LoopTasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.presence_update_task.start()
        self.new_day_clear.start()
        self.weekly_1557_report.start()
        api_key = getenv_clean("GOOGLE_API_KEY")
        self._youtube = build("youtube", "v3", developerKey=api_key)
        self._last_live_id = None
        self.youtube_live_check.start()
        print("LoopTasks Cog : init 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT -> LoopTasks Cog : on ready!")

    @tasks.loop(seconds=60)
    async def presence_update_task(self):
        """1분마다 Discord 봇 상태(Presence)를 갱신합니다."""
        # 길드별 -> 유저별 -> 메시지 리스트 구조를 합산
        total_messages = 0
        for guild_map in self.bot.USER_MESSAGES.values():
            if isinstance(guild_map, dict):
                for lst in guild_map.values():
                    if isinstance(lst, list):
                        total_messages += len(lst)
        formatted_total_messages = f"{total_messages:,}"
        # discord.Activity를 명시적으로 사용
        activity = discord.Activity(
            type=discord.ActivityType.playing,
            name=f"/도움 | {formatted_total_messages}개의 채팅 메시지 보관",
        )
        await self.bot.change_presence(activity=activity)

    @presence_update_task.before_loop
    async def before_presence_update_task(self):
        print("-------------봇 on ready 대기중...---------------")
        await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=0, minute=0, tzinfo=SEOUL_TZ))  # 매일 자정
    async def new_day_clear(self):
        """매일 자정에 user_messages를 초기화하고, 기념일 및 공휴일 정보를 알림."""
        results = await refresh_celebration_messages(self.bot)
        success_count = 0
        for result in results:
            if result.status == "ok":
                success_count += 1
                continue
            print(
                f"기념일 공지 갱신 실패: guild={result.guild_id} "
                f"channel={result.channel_id} error={result.error}"
            )

        if success_count:
            print(f"[{datetime.now(SEOUL_TZ)}] 기념일 공지 {success_count}개 채널 갱신 완료.")

        # 유저 메시지 초기화 및 리로드
        self.bot.USER_MESSAGES = {}
        await load_recent_messages()
        print(f"[{datetime.now(SEOUL_TZ)}] user_messages 초기화 완료.")

    @tasks.loop(time=time(hour=0, minute=1, tzinfo=SEOUL_TZ))  # 매일 자정 실행
    async def weekly_1557_report(self):
        """매주 월요일 00:00에 DB의 사용자별 1557 카운트를 출력."""
        now = datetime.now(SEOUL_TZ)
        r = now.weekday()
        if r != 0:  # 0=월요일
            return
        print(f"Debug {['월','화','수','목','금','토','일'][r]}요일")
        target_channel = self.bot.get_channel(SONPANNO_GUILD_ID)
        if not target_channel:
            print("대상 채널을 찾을 수 없습니다.")
            return

        # DB 로드
        try:
            query = "SELECT user_id, count FROM counter_1557"
            rows = await fetch_all(query)
            data = {row["user_id"]: row["count"] for row in rows}
        except Exception as e:
            print(f"1557Counter DB 로드 중 오류 발생: {e}")
            data = {}

        if not data:
            report = "📊 이번 주 1557 카운트 기록된 사용자가 없습니다."
        else:
            # count 내림차순으로 정렬
            sorted_items = sorted(data.items(), key=lambda x: x[1], reverse=True)
            lines = [f"<@{user_id}>: {count}번" for user_id, count in sorted_items]
            report = "# 📊 주간 1557 카운트 보고\n" + "\n".join(lines)

        await target_channel.send(report)
        print(f"[{now}] 주간 1557 카운트 보고 완료.")

        # 카운트 초기화
        await clearCount()

    @tasks.loop(seconds=120)
    async def youtube_live_check(self):
        """60초마다 특정 채널의 LIVE 시작 여부를 Discord에 알립니다."""
        key = "youtubeLiveChecker"
        try:
            query = "SELECT setting_value FROM setting_data WHERE setting_key = %s"
            row = await fetch_one(query, (key,))
            if not row or not row["setting_value"]:
                return

            cfg = (
                json.loads(row["setting_value"])
                if isinstance(row["setting_value"], str)
                else row["setting_value"]
            )

            if not cfg.get("loop", False):
                return  # loop 비활성화 상태면 동작 안 함

            channel_id = cfg.get("youtubeChannelId")
            try:
                def _fetch_live_video_id():
                    res = (
                        self._youtube.search()
                        .list(
                            part="snippet",
                            channelId=channel_id,
                            eventType="live",
                            type="video",
                            maxResults=1,
                        )
                        .execute()
                    )
                    items = res.get("items", [])
                    return items[0]["id"]["videoId"] if items else None

                vid = await asyncio.to_thread(_fetch_live_video_id)
            except HttpError as e:
                print(f"Youtube API 에러: {e}")
                return

            target = self.bot.get_channel(SONPANNO_GUILD_ID)

            if vid and vid != self._last_live_id:
                await target.send(
                    f"📺 **메이플스토리 LIVE 시작!** ▶ https://youtu.be/{vid}"
                )
                self._last_live_id = vid
                # 알림 후 loop 비활성화
                cfg["loop"] = False

                # DB 저장
                json_str = json.dumps(cfg, ensure_ascii=False)
                q2 = "INSERT INTO setting_data (setting_key, setting_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE setting_value = %s"
                await execute_query(q2, (key, json_str, json_str))

                self.youtube_live_check.stop()
            else:
                self._last_live_id = None
        except Exception as e:
            print(f"Loop error: {e}")

    @youtube_live_check.before_loop
    async def before_youtube_live_check(self):
        print("-------------YouTube 라이브 체크 대기중...---------------")
        await self.bot.wait_until_ready()


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(LoopTasks(bot))
    print("LoopTasks Cog : setup 완료!")
