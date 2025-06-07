import json
import os
from datetime import datetime, time

import discord
import holidays
from discord.ext import commands, tasks
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from api.riot import get_rank_data
from bot import CHANNEL_ID, TEST_CHANNEL_ID, SEOUL_TZ, load_recent_messages
from func.find1557 import clearCount

SPECIAL_DAYS_FILE = "special_days.json"


class LoopTasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.presence_update_task.start()
        self.new_day_clear.start()
        self.update_rank_data.start()
        self.weekly_1557_report.start()
        api_key = os.getenv("GOOGLE_API_KEY")
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
        total_messages = sum(
            len(msg_list) for msg_list in self.bot.USER_MESSAGES.values()
        )
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
        target_channel = self.bot.get_channel(CHANNEL_ID)
        if not target_channel:
            print("대상 채널을 찾을 수 없습니다.")
            return

        today = datetime.now().date()
        today_str = today.strftime("%m-%d")

        # 한국 공휴일 정보 가져오기
        holiday_kr = holidays.Korea()
        holiday_list = []
        if today in holiday_kr:
            holiday_list.append(f"🇰🇷 한국 공휴일: {holiday_kr[today]}")

        # JSON 파일에서 기념일 데이터 불러오기
        try:
            with open(SPECIAL_DAYS_FILE, "r", encoding="utf-8") as file:
                special_days = json.load(file)

            if today_str in special_days:
                holiday_list.extend(special_days[today_str])
        except Exception as e:
            print(f"❌ 기념일 JSON 파일을 불러오는 중 오류 발생: {e}")

        # 메시지 출력
        message = "📢 새로운 하루가 시작됩니다."
        if holiday_list:
            message += "\n### 기념일\n- " + "\n- ".join(holiday_list)

        await target_channel.send(message)

        # 유저 메시지 초기화 및 리로드
        self.bot.USER_MESSAGES = {}
        await load_recent_messages()
        print(f"[{datetime.now()}] user_messages 초기화 완료.")

    @tasks.loop(time=time(hour=0, minute=0, tzinfo=SEOUL_TZ))  # 매일 자정
    async def update_rank_data(self):
        """매일 자정에 랭킹 정보를 업데이트합니다."""
        target_channel = self.bot.get_channel(CHANNEL_ID)
        if not target_channel:
            print("대상 채널을 찾을 수 없습니다.")
            return

        if self.daily_rank_loop_enabled:
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
                    await target_channel.send("새로운 유저가 감지되었습니다!")
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

    @tasks.loop(time=time(hour=0, minute=0, tzinfo=SEOUL_TZ))  # 매일 자정 실행
    async def weekly_1557_report(self):
        """매주 월요일 00:00에 1557Counter.json의 사용자별 카운트를 출력."""
        now = datetime.now(SEOUL_TZ)
        r = now.weekday()
        if r != 0:  # 0=월요일
            return
        print(f"Debug {['월','화','수','목','금','토','일'][r]}요일")

        target_channel = self.bot.get_channel(CHANNEL_ID)
        if not target_channel:
            print("대상 채널을 찾을 수 없습니다.")
            return

        # JSON 파일 로드, 비어 있거나 손상된 경우 빈 dict로
        try:
            with open("1557Counter.json", "r", encoding="utf-8") as f:
                content = f.read().strip()
                data = json.loads(content) if content else {}
        except json.JSONDecodeError:
            print(
                "1557Counter.json이 비어 있거나 손상되었습니다. 빈 데이터로 초기화합니다."
            )
            data = {}
        except FileNotFoundError:
            print("1557Counter.json을 찾을 수 없습니다. 새로 생성합니다.")
            data = {}
        except Exception as e:
            print(f"1557Counter.json 로드 중 알 수 없는 오류: {e}")
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
        clearCount()

    @tasks.loop(seconds=120)
    async def youtube_live_check(self):
        """60초마다 특정 채널의 LIVE 시작 여부를 Discord에 알립니다."""
        # 설정 파일에서 loop 활성화 여부 및 채널 ID 로드
        with open(self.bot.SETTING_DATA, "r", encoding="utf-8") as f:
            settings = json.load(f)
        cfg = settings["youtubeLiveChecker"]
        if not cfg.get("loop", False):
            return  # loop 비활성화 상태면 동작 안 함

        channel_id = cfg.get("youtubeChannelId")
        try:
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
            vid = items[0]["id"]["videoId"] if items else None
        except HttpError as e:
            print(f"Youtube API 에러: {e}")
            return

        target = self.bot.get_channel(CHANNEL_ID)
        test_target = self.bot.get_channel(TEST_CHANNEL_ID)
        if vid and vid != self._last_live_id:
            await target.send(
                f"📺 **메이플스토리 LIVE 시작!** ▶ https://youtu.be/{vid}"
            )
            self._last_live_id = vid
            # 알림 후 loop 비활성화
            cfg["loop"] = False
            with open(self.bot.SETTING_DATA, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
            self.youtube_live_check.stop()
        else:
            await test_target.send("❌ 현재 LIVE가 없습니다.")
            self._last_live_id = None

    @youtube_live_check.before_loop
    async def before_youtube_live_check(self):
        print("-------------YouTube 라이브 체크 대기중...---------------")
        await self.bot.wait_until_ready()


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(LoopTasks(bot))
    print("LoopTasks Cog : setup 완료!")
