import asyncio
import json
from datetime import datetime, timedelta, time, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp
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
from util.youtube_websub import (
    YOUTUBE_HUB_URL,
    YouTubeVideoStatus,
    build_youtube_feed_topic_url,
    classify_video_item,
    parse_youtube_atom_entries,
)


YOUTUBE_LIVE_SETTING_KEY = "youtubeLiveChecker"
YOUTUBE_WEBSUB_LEASE_SECONDS = 604800
YOUTUBE_PENDING_CHECK_INTERVAL_SECONDS = 300
YOUTUBE_PENDING_EARLY_WINDOW = timedelta(minutes=15)
YOUTUBE_PENDING_EXPIRE_WINDOW = timedelta(hours=24)


class LoopTasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.presence_update_task.start()
        self.new_day_clear.start()
        self.weekly_1557_report.start()
        api_key = getenv_clean("GOOGLE_API_KEY")
        self._youtube = build("youtube", "v3", developerKey=api_key)
        self.youtube_live_check.start()
        self.youtube_websub_renewal.start()
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

    async def _load_youtube_live_config(self) -> dict:
        query = "SELECT setting_value FROM setting_data WHERE setting_key = %s"
        row = await fetch_one(query, (YOUTUBE_LIVE_SETTING_KEY,))
        if not row or not row["setting_value"]:
            return {}

        value = row["setting_value"]
        return json.loads(value) if isinstance(value, str) else dict(value)

    async def _save_youtube_live_config(self, cfg: dict) -> None:
        json_str = json.dumps(cfg, ensure_ascii=False)
        query = """
        INSERT INTO setting_data (setting_key, setting_value)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE setting_value = %s
        """
        await execute_query(
            query,
            (YOUTUBE_LIVE_SETTING_KEY, json_str, json_str),
        )

    def _build_youtube_websub_callback_url(self) -> str:
        callback_url = getenv_clean("YOUTUBE_WEBSUB_CALLBACK_URL", "").strip()
        if not callback_url:
            return ""

        verify_token = getenv_clean("YOUTUBE_WEBSUB_VERIFY_TOKEN", "").strip()
        if not verify_token:
            return callback_url

        split = urlsplit(callback_url)
        query_items = dict(parse_qsl(split.query, keep_blank_values=True))
        query_items.setdefault("token", verify_token)
        return urlunsplit(
            (
                split.scheme,
                split.netloc,
                split.path,
                urlencode(query_items),
                split.fragment,
            )
        )

    async def ensure_youtube_websub_subscription(self) -> bool:
        cfg = await self._load_youtube_live_config()
        channel_id = cfg.get("youtubeChannelId")
        callback_url = self._build_youtube_websub_callback_url()
        if not channel_id or not callback_url:
            return False

        data = {
            "hub.mode": "subscribe",
            "hub.topic": build_youtube_feed_topic_url(channel_id),
            "hub.callback": callback_url,
            "hub.verify": "async",
            "hub.lease_seconds": str(YOUTUBE_WEBSUB_LEASE_SECONDS),
        }

        async with aiohttp.ClientSession(trust_env=False) as session:
            async with session.post(YOUTUBE_HUB_URL, data=data) as response:
                if response.status < 200 or response.status >= 300:
                    body = await response.text()
                    print(f"YouTube WebSub 구독 요청 실패: {response.status} {body}")
                    return False

        cfg["websubSubscribedAt"] = datetime.now(timezone.utc).isoformat()
        cfg["websubLeaseSeconds"] = YOUTUBE_WEBSUB_LEASE_SECONDS
        await self._save_youtube_live_config(cfg)
        return True

    async def _fetch_youtube_video_status(self, video_id: str):
        def _fetch_video_item():
            response = (
                self._youtube.videos()
                .list(
                    part="snippet,liveStreamingDetails,status",
                    id=video_id,
                    maxResults=1,
                )
                .execute()
            )
            items = response.get("items", [])
            return items[0] if items else None

        item = await asyncio.to_thread(_fetch_video_item)
        return classify_video_item(item) if item else None

    def _get_notified_video_ids(self, cfg: dict) -> set[str]:
        notified_ids = cfg.get("notifiedVideoIds", [])
        return {str(video_id) for video_id in notified_ids if video_id}

    def _mark_youtube_video_notified(self, cfg: dict, video_id: str) -> None:
        notified_ids = [
            str(current_id)
            for current_id in cfg.get("notifiedVideoIds", [])
            if current_id
        ]
        if video_id not in notified_ids:
            notified_ids.append(video_id)
        cfg["notifiedVideoIds"] = notified_ids[-30:]

    def _remember_pending_youtube_video(self, cfg: dict, status) -> None:
        pending = cfg.setdefault("pendingVideos", {})
        pending[status.video_id] = {
            "title": status.title,
            "channelId": status.channel_id,
            "scheduledStartTime": status.scheduled_start_time,
            "lastCheckedAt": datetime.now(timezone.utc).isoformat(),
        }

    def _remove_pending_youtube_video(self, cfg: dict, video_id: str) -> None:
        pending = cfg.get("pendingVideos")
        if isinstance(pending, dict):
            pending.pop(video_id, None)

    async def _send_youtube_live_notification(self, cfg: dict, status) -> bool:
        if status.video_id in self._get_notified_video_ids(cfg):
            return False

        target = self.bot.get_channel(SONPANNO_GUILD_ID)
        if target is None:
            print("YouTube 라이브 알림 대상 채널을 찾을 수 없습니다.")
            return False

        title = f"**{status.title}** " if status.title else ""
        await target.send(f"📺 {title}LIVE 시작! ▶ https://youtu.be/{status.video_id}")
        self._mark_youtube_video_notified(cfg, status.video_id)
        self._remove_pending_youtube_video(cfg, status.video_id)
        cfg["loop"] = False
        await self._save_youtube_live_config(cfg)
        self.youtube_live_check.stop()
        return True

    async def _process_youtube_video_candidate(
        self, cfg: dict, video_id: str
    ) -> str:
        try:
            status = await self._fetch_youtube_video_status(video_id)
        except HttpError as e:
            print(f"YouTube videos.list 에러: {e}")
            return "error"

        if status is None:
            self._remove_pending_youtube_video(cfg, video_id)
            await self._save_youtube_live_config(cfg)
            return "missing"

        if status.status == YouTubeVideoStatus.LIVE:
            if cfg.get("loop", False):
                if status.video_id in self._get_notified_video_ids(cfg):
                    return "duplicate"
                sent = await self._send_youtube_live_notification(cfg, status)
                if sent:
                    return "notified"

                self._remember_pending_youtube_video(cfg, status)
                await self._save_youtube_live_config(cfg)
                return "live_pending"

            self._remember_pending_youtube_video(cfg, status)
            await self._save_youtube_live_config(cfg)
            return "live_pending"

        if status.status == YouTubeVideoStatus.UPCOMING:
            self._remember_pending_youtube_video(cfg, status)
            await self._save_youtube_live_config(cfg)
            return "upcoming"

        self._remove_pending_youtube_video(cfg, video_id)
        await self._save_youtube_live_config(cfg)
        return "not_live"

    async def handle_youtube_websub_notification(self, atom_xml: str) -> dict:
        cfg = await self._load_youtube_live_config()
        configured_channel_id = cfg.get("youtubeChannelId")
        entries = parse_youtube_atom_entries(atom_xml)

        result = {
            "received": len(entries),
            "processed": 0,
            "ignored": 0,
            "results": [],
        }
        for entry in entries:
            if configured_channel_id and entry.channel_id != configured_channel_id:
                result["ignored"] += 1
                continue

            outcome = await self._process_youtube_video_candidate(
                cfg,
                entry.video_id,
            )
            result["processed"] += 1
            result["results"].append({"video_id": entry.video_id, "status": outcome})
            cfg = await self._load_youtube_live_config()

        return result

    def _parse_youtube_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _should_check_pending_youtube_video(self, pending_entry: dict) -> bool:
        now = datetime.now(timezone.utc)
        last_checked = self._parse_youtube_datetime(pending_entry.get("lastCheckedAt"))
        if (
            last_checked
            and now - last_checked
            < timedelta(seconds=YOUTUBE_PENDING_CHECK_INTERVAL_SECONDS)
        ):
            return False

        scheduled_start = self._parse_youtube_datetime(
            pending_entry.get("scheduledStartTime")
        )
        if scheduled_start is None:
            return True

        return (
            scheduled_start - YOUTUBE_PENDING_EARLY_WINDOW
            <= now
            <= scheduled_start + YOUTUBE_PENDING_EXPIRE_WINDOW
        )

    @tasks.loop(seconds=60)
    async def youtube_live_check(self):
        """WebSub로 받은 라이브 후보만 videos.list로 확인합니다."""
        try:
            cfg = await self._load_youtube_live_config()
            if not cfg.get("loop", False):
                return

            pending = cfg.get("pendingVideos", {})
            if not isinstance(pending, dict) or not pending:
                return

            for video_id, pending_entry in list(pending.items()):
                if not isinstance(pending_entry, dict):
                    self._remove_pending_youtube_video(cfg, str(video_id))
                    continue
                if not self._should_check_pending_youtube_video(pending_entry):
                    continue

                pending_entry["lastCheckedAt"] = datetime.now(timezone.utc).isoformat()
                await self._save_youtube_live_config(cfg)
                await self._process_youtube_video_candidate(cfg, str(video_id))
                cfg = await self._load_youtube_live_config()
        except Exception as e:
            print(f"YouTube 라이브 후보 확인 오류: {e}")

    @tasks.loop(hours=12)
    async def youtube_websub_renewal(self):
        """YouTube WebSub 구독을 주기적으로 갱신합니다."""
        try:
            subscribed = await self.ensure_youtube_websub_subscription()
            if subscribed:
                print("YouTube WebSub 구독 갱신 요청 완료")
        except Exception as e:
            print(f"YouTube WebSub 구독 갱신 오류: {e}")

    @youtube_live_check.before_loop
    async def before_youtube_live_check(self):
        print("-------------YouTube 라이브 체크 대기중...---------------")
        await self.bot.wait_until_ready()

    @youtube_websub_renewal.before_loop
    async def before_youtube_websub_renewal(self):
        print("-------------YouTube WebSub 구독 갱신 대기중...---------------")
        await self.bot.wait_until_ready()


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(LoopTasks(bot))
    print("LoopTasks Cog : setup 완료!")
