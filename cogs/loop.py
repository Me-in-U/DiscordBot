import logging
from datetime import datetime, timedelta, time

import aiohttp
import discord
from discord.ext import commands, tasks
from googleapiclient.discovery import build

from bot import (
    SONPANNO_GUILD_ID,
    SEOUL_TZ,
    load_recent_messages,
)
from util.daily_refresh_runner import run_daily_refreshes
from util.env_utils import getenv_clean
from util.loop.task_lifecycle import cancel_loop_tasks, start_loop_tasks
from util.maplestory.notice_loop_runner import run_maplestory_notice_loop
from util.presence_status import build_presence_activity_name
from util.weekly_1557_reporter import run_weekly_1557_report
from util.youtube.community_polling import poll_youtube_community_posts
from util.youtube.feed_fallback import (
    YouTubeFeedFallbackState,
    poll_youtube_feed_fallback,
)
from util.youtube.notification_sender import (
    send_youtube_live_notification,
    send_youtube_upload_notification,
)
from util.youtube.subscriptions import (
    YouTubeSubscription,
    delete_legacy_youtube_live_checker_setting,
)
from util.youtube.notification_state import (
    mark_youtube_upload_video_notified,
    mark_youtube_video_notified,
    notified_id_set,
    remember_pending_youtube_video,
    remove_pending_youtube_video,
    should_check_pending_youtube_video,
)
from util.youtube.loop_runner import (
    run_youtube_community_posts,
    run_youtube_notification_candidates,
)
from util.youtube.video_status import fetch_youtube_video_status
from util.youtube.websub_notification import (
    handle_youtube_websub_notification,
)
from util.youtube.websub_renewal import run_youtube_websub_renewal
from util.youtube.websub_subscription import (
    build_configured_youtube_websub_callback_url,
    ensure_youtube_websub_subscription,
    unsubscribe_youtube_websub_subscription,
)
from util.youtube.video_candidate_runner import process_youtube_video_candidate


YOUTUBE_PENDING_CHECK_INTERVAL_SECONDS = 300
YOUTUBE_PENDING_EARLY_WINDOW = timedelta(minutes=15)
YOUTUBE_PENDING_EXPIRE_WINDOW = timedelta(hours=24)
YOUTUBE_FEED_FALLBACK_INTERVAL_SECONDS = 300
YOUTUBE_FEED_FALLBACK_MAX_ENTRIES = 5
LOOP_TASK_NAMES = (
    "presence_update_task",
    "new_day_clear",
    "weekly_1557_report",
    "youtube_notification_check",
    "youtube_community_check",
    "maplestory_notice_check",
    "youtube_websub_renewal",
)
logger = logging.getLogger(__name__)


class LoopTasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        api_key = getenv_clean("GOOGLE_API_KEY")
        self._youtube = build("youtube", "v3", developerKey=api_key)
        self._legacy_youtube_setting_removed = False
        self._youtube_feed_fallback = YouTubeFeedFallbackState()
        start_loop_tasks(self, LOOP_TASK_NAMES)
        print("LoopTasks Cog : init 완료!")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되었을 때 호출됩니다."""
        print("DISCORD_CLIENT -> LoopTasks Cog : on ready!")

    def cog_unload(self):
        cancel_loop_tasks(self, LOOP_TASK_NAMES)

    @tasks.loop(seconds=60)
    async def presence_update_task(self):
        """1분마다 Discord 봇 상태(Presence)를 갱신합니다."""
        activity = discord.Activity(
            type=discord.ActivityType.playing,
            name=build_presence_activity_name(self.bot.USER_MESSAGES),
        )
        await self.bot.change_presence(activity=activity)

    @presence_update_task.before_loop
    async def before_presence_update_task(self):
        print("-------------봇 on ready 대기중...---------------")
        await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=0, minute=0, tzinfo=SEOUL_TZ))  # 매일 자정
    async def new_day_clear(self):
        """매일 자정에 user_messages를 초기화하고, 기념일 및 공휴일 정보를 알림."""
        await run_daily_refreshes(
            self.bot,
            now=datetime.now(SEOUL_TZ),
            reload_recent_messages=load_recent_messages,
        )

    @tasks.loop(time=time(hour=0, minute=1, tzinfo=SEOUL_TZ))  # 매일 자정 실행
    async def weekly_1557_report(self):
        """매주 월요일 00:00에 DB의 사용자별 1557 카운트를 출력."""
        await run_weekly_1557_report(
            self.bot,
            target_channel_id=SONPANNO_GUILD_ID,
            now=datetime.now(SEOUL_TZ),
        )

    def _build_youtube_websub_callback_url(self) -> str:
        return build_configured_youtube_websub_callback_url(
            getenv_clean("YOUTUBE_WEBSUB_CALLBACK_URL", ""),
            getenv_clean("YOUTUBE_WEBSUB_VERIFY_TOKEN", ""),
        )

    async def _delete_legacy_youtube_live_checker_setting_once(self) -> None:
        if self._legacy_youtube_setting_removed:
            return
        await delete_legacy_youtube_live_checker_setting()
        self._legacy_youtube_setting_removed = True

    async def ensure_youtube_websub_subscription(
        self,
        subscription_id: int | None = None,
    ) -> bool:
        await self._delete_legacy_youtube_live_checker_setting_once()
        callback_url = self._build_youtube_websub_callback_url()
        return await ensure_youtube_websub_subscription(
            callback_url=callback_url,
            subscription_id=subscription_id,
        )

    async def unsubscribe_youtube_websub_subscription(
        self,
        subscription: YouTubeSubscription,
    ) -> bool:
        callback_url = self._build_youtube_websub_callback_url()
        return await unsubscribe_youtube_websub_subscription(
            subscription,
            callback_url=callback_url,
        )

    async def _fetch_youtube_video_status(self, video_id: str):
        return await fetch_youtube_video_status(self._youtube, video_id)

    def _get_notified_video_ids(self, subscription: YouTubeSubscription) -> set[str]:
        return notified_id_set(subscription.notified_video_ids)

    def _get_notified_upload_video_ids(
        self,
        subscription: YouTubeSubscription,
    ) -> set[str]:
        return notified_id_set(subscription.notified_upload_video_ids)

    async def _poll_youtube_feed_fallback(
        self,
        subscription: YouTubeSubscription,
        session: aiohttp.ClientSession,
    ) -> YouTubeSubscription | None:
        return await poll_youtube_feed_fallback(
            self._process_youtube_video_candidate,
            self._youtube_feed_fallback,
            subscription,
            session,
            interval_seconds=YOUTUBE_FEED_FALLBACK_INTERVAL_SECONDS,
            max_entries=YOUTUBE_FEED_FALLBACK_MAX_ENTRIES,
        )

    async def _mark_youtube_video_notified(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
    ) -> YouTubeSubscription:
        return await mark_youtube_video_notified(subscription, video_id)

    async def _mark_youtube_upload_video_notified(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
    ) -> YouTubeSubscription:
        return await mark_youtube_upload_video_notified(subscription, video_id)

    async def _remember_pending_youtube_video(
        self,
        subscription: YouTubeSubscription,
        status,
    ) -> YouTubeSubscription:
        return await remember_pending_youtube_video(subscription, status)

    async def _remove_pending_youtube_video(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
    ) -> YouTubeSubscription:
        return await remove_pending_youtube_video(subscription, video_id)

    async def _send_youtube_live_notification(
        self,
        subscription: YouTubeSubscription,
        status,
    ) -> bool:
        return await send_youtube_live_notification(self.bot, subscription, status)

    async def _send_youtube_upload_notification(
        self,
        subscription: YouTubeSubscription,
        status,
    ) -> bool:
        return await send_youtube_upload_notification(self.bot, subscription, status)

    async def _process_youtube_video_candidate(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
    ) -> str:
        return await process_youtube_video_candidate(self, subscription, video_id)

    async def _poll_youtube_community_posts(
        self,
        subscription: YouTubeSubscription,
    ) -> YouTubeSubscription:
        return await poll_youtube_community_posts(self.bot, subscription)

    async def handle_youtube_websub_notification(self, atom_xml: str) -> dict:
        return await handle_youtube_websub_notification(
            atom_xml,
            process_video_candidate=self._process_youtube_video_candidate,
        )

    def _should_check_pending_youtube_video(self, pending_entry: dict) -> bool:
        return should_check_pending_youtube_video(
            pending_entry,
            check_interval_seconds=YOUTUBE_PENDING_CHECK_INTERVAL_SECONDS,
            early_window=YOUTUBE_PENDING_EARLY_WINDOW,
            expire_window=YOUTUBE_PENDING_EXPIRE_WINDOW,
        )

    @tasks.loop(seconds=60)
    async def youtube_notification_check(self):
        """WebSub 후보와 Atom feed fallback 후보를 videos.list로 확인합니다."""
        try:
            await run_youtube_notification_candidates(self)
        except Exception:
            logger.exception("YouTube 알림 후보 확인 오류")

    @tasks.loop(minutes=10)
    async def youtube_community_check(self):
        """커뮤니티 알림이 켜진 유튜브 구독의 새 게시물을 확인합니다."""
        try:
            await run_youtube_community_posts(self)
        except Exception:
            logger.exception("YouTube 커뮤니티 알림 확인 오류")

    @tasks.loop(minutes=3)
    async def maplestory_notice_check(self):
        """메이플스토리 새 공지와 수정 공지를 확인합니다."""
        try:
            await run_maplestory_notice_loop(self.bot)
        except Exception:
            logger.exception("메이플스토리 공지 확인 오류")

    @tasks.loop(hours=12)
    async def youtube_websub_renewal(self):
        """YouTube WebSub 구독을 주기적으로 갱신합니다."""
        try:
            await run_youtube_websub_renewal(self)
        except Exception:
            logger.exception("YouTube WebSub 구독 갱신 오류")

    @youtube_notification_check.before_loop
    async def before_youtube_notification_check(self):
        print("-------------YouTube 알림 체크 대기중...---------------")
        await self.bot.wait_until_ready()

    @youtube_community_check.before_loop
    async def before_youtube_community_check(self):
        print("-------------YouTube 커뮤니티 알림 체크 대기중...---------------")
        await self.bot.wait_until_ready()

    @maplestory_notice_check.before_loop
    async def before_maplestory_notice_check(self):
        print("-------------메이플스토리 공지 알림 체크 대기중...---------------")
        await self.bot.wait_until_ready()

    @youtube_websub_renewal.before_loop
    async def before_youtube_websub_renewal(self):
        print("-------------YouTube WebSub 구독 갱신 대기중...---------------")
        await self.bot.wait_until_ready()


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(LoopTasks(bot))
    print("LoopTasks Cog : setup 완료!")
