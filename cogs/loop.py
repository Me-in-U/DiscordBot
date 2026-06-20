import asyncio
from dataclasses import replace
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
from util.channel_settings import get_channel
from util.celebration import refresh_celebration_messages
from util.db import fetch_all, fetch_one, execute_query
from util.dday import refresh_dday_messages
from util.env_utils import getenv_clean
from util.maplestory_events import refresh_sunday_maple_messages
from func.find1557 import clearCount
from util.youtube_subscriptions import (
    YouTubeSubscription,
    delete_legacy_youtube_live_checker_setting,
    find_youtube_subscriptions_by_channel_id,
    get_youtube_subscription,
    list_all_youtube_subscriptions,
    update_youtube_community_notification_state,
    update_youtube_subscription_state,
    update_youtube_upload_notification_state,
    update_youtube_websub_state,
)
from util.youtube_community import (
    YouTubeCommunityPost,
    fetch_latest_youtube_community_posts,
    find_new_youtube_community_posts,
    trim_notified_community_post_ids,
)
from util.youtube_websub import (
    YOUTUBE_HUB_URL,
    YouTubeVideoStatus,
    build_youtube_feed_topic_url,
    build_youtube_live_notification_message,
    build_youtube_upload_notification_message,
    classify_video_item,
    parse_youtube_atom_entries,
    should_send_youtube_upload_alert,
    should_process_youtube_feed_update,
)


YOUTUBE_CHANNEL_TYPE = "youtube"
YOUTUBE_WEBSUB_LEASE_SECONDS = 604800
YOUTUBE_PENDING_CHECK_INTERVAL_SECONDS = 300
YOUTUBE_PENDING_EARLY_WINDOW = timedelta(minutes=15)
YOUTUBE_PENDING_EXPIRE_WINDOW = timedelta(hours=24)
YOUTUBE_FEED_FALLBACK_INTERVAL_SECONDS = 300
YOUTUBE_FEED_FALLBACK_MAX_ENTRIES = 5


class LoopTasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.presence_update_task.start()
        self.new_day_clear.start()
        self.weekly_1557_report.start()
        api_key = getenv_clean("GOOGLE_API_KEY")
        self._youtube = build("youtube", "v3", developerKey=api_key)
        self._legacy_youtube_setting_removed = False
        self._youtube_feed_checked_at: dict[int, datetime] = {}
        self._youtube_feed_seen_updates: dict[int, dict[str, str]] = {}
        self.youtube_notification_check.start()
        self.youtube_community_check.start()
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

        dday_results = await refresh_dday_messages(self.bot)
        dday_success_count = 0
        for result in dday_results:
            if result.status == "ok":
                dday_success_count += 1
                continue
            if result.status == "skipped":
                continue
            print(
                f"DDAY 공지 갱신 실패: guild={result.guild_id} "
                f"channel={result.channel_id} error={result.error}"
            )

        if dday_success_count:
            print(f"[{datetime.now(SEOUL_TZ)}] DDAY 공지 {dday_success_count}개 채널 전송 완료.")

        if datetime.now(SEOUL_TZ).weekday() == 6:
            sunday_maple_results = await refresh_sunday_maple_messages(self.bot)
            sunday_maple_success_count = 0
            for result in sunday_maple_results:
                if result.status == "ok":
                    sunday_maple_success_count += 1
                    continue
                if result.status == "skipped":
                    continue
                print(
                    f"썬데이메이플 공지 전송 실패: guild={result.guild_id} "
                    f"channel={result.channel_id} error={result.error}"
                )

            if sunday_maple_success_count:
                print(
                    f"[{datetime.now(SEOUL_TZ)}] "
                    f"썬데이메이플 공지 {sunday_maple_success_count}개 채널 전송 완료."
                )

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
        if not callback_url:
            return False

        if subscription_id is None:
            subscriptions = await list_all_youtube_subscriptions()
        else:
            subscription = await get_youtube_subscription(subscription_id)
            subscriptions = [subscription] if subscription is not None else []
        subscriptions = [
            subscription
            for subscription in subscriptions
            if subscription.live_alert_enabled or subscription.upload_alert_enabled
        ]
        if not subscriptions:
            return True

        success_count = 0
        for subscription in subscriptions:
            subscribed = await self._request_youtube_websub(
                subscription,
                callback_url=callback_url,
                mode="subscribe",
            )
            if not subscribed:
                continue
            success_count += 1
            await update_youtube_websub_state(
                subscription.id,
                websub_subscribed_at=datetime.now(timezone.utc),
                websub_lease_seconds=YOUTUBE_WEBSUB_LEASE_SECONDS,
            )
        return success_count == len(subscriptions)

    async def unsubscribe_youtube_websub_subscription(
        self,
        subscription: YouTubeSubscription,
    ) -> bool:
        callback_url = self._build_youtube_websub_callback_url()
        if not callback_url:
            return False
        return await self._request_youtube_websub(
            subscription,
            callback_url=callback_url,
            mode="unsubscribe",
        )

    async def _request_youtube_websub(
        self,
        subscription: YouTubeSubscription,
        *,
        callback_url: str,
        mode: str,
    ) -> bool:
        data = {
            "hub.mode": mode,
            "hub.topic": build_youtube_feed_topic_url(subscription.channel_id),
            "hub.callback": callback_url,
            "hub.verify": "async",
        }
        if mode == "subscribe":
            data["hub.lease_seconds"] = str(YOUTUBE_WEBSUB_LEASE_SECONDS)

        async with aiohttp.ClientSession(trust_env=False) as session:
            async with session.post(YOUTUBE_HUB_URL, data=data) as response:
                if response.status < 200 or response.status >= 300:
                    body = await response.text()
                    print(
                        "YouTube WebSub 요청 실패: "
                        f"mode={mode} channel={subscription.channel_id} "
                        f"status={response.status} body={body}"
                    )
                    return False
        return True

    async def _fetch_youtube_video_status(self, video_id: str):
        def _fetch_video_item():
            response = (
                self._youtube.videos()
                .list(
                    part="snippet,liveStreamingDetails,status,contentDetails",
                    id=video_id,
                    maxResults=1,
                )
                .execute()
            )
            items = response.get("items", [])
            return items[0] if items else None

        item = await asyncio.to_thread(_fetch_video_item)
        return classify_video_item(item) if item else None

    async def _fetch_youtube_feed_entries(
        self,
        session: aiohttp.ClientSession,
        subscription: YouTubeSubscription,
    ):
        topic_url = build_youtube_feed_topic_url(subscription.channel_id)
        async with session.get(topic_url) as response:
            if response.status < 200 or response.status >= 300:
                body = await response.text()
                print(
                    "YouTube Atom feed 조회 실패: "
                    f"channel={subscription.channel_id} "
                    f"status={response.status} body={body[:300]}"
                )
                return []
            atom_xml = await response.text()
        return parse_youtube_atom_entries(atom_xml)

    def _get_notified_video_ids(self, subscription: YouTubeSubscription) -> set[str]:
        return {str(video_id) for video_id in subscription.notified_video_ids if video_id}

    def _get_notified_upload_video_ids(
        self,
        subscription: YouTubeSubscription,
    ) -> set[str]:
        return {
            str(video_id)
            for video_id in subscription.notified_upload_video_ids
            if video_id
        }

    def _get_notified_community_post_ids(
        self,
        subscription: YouTubeSubscription,
    ) -> set[str]:
        return {
            str(post_id)
            for post_id in subscription.notified_community_post_ids
            if post_id
        }

    def _should_poll_youtube_feed(self, subscription_id: int) -> bool:
        now = datetime.now(timezone.utc)
        last_checked = self._youtube_feed_checked_at.get(subscription_id)
        if (
            last_checked
            and now - last_checked
            < timedelta(seconds=YOUTUBE_FEED_FALLBACK_INTERVAL_SECONDS)
        ):
            return False
        self._youtube_feed_checked_at[subscription_id] = now
        return True

    def _should_process_youtube_feed_entry(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
        entry_updated: str,
    ) -> bool:
        seen_updates = self._youtube_feed_seen_updates.setdefault(subscription.id, {})
        return should_process_youtube_feed_update(
            video_id=video_id,
            entry_updated=entry_updated,
            seen_updates=seen_updates,
            pending_videos=subscription.pending_videos,
            notified_video_ids=subscription.notified_video_ids,
            notified_upload_video_ids=subscription.notified_upload_video_ids,
        )

    def _remember_youtube_feed_entry_seen(
        self,
        subscription_id: int,
        video_id: str,
        entry_updated: str,
    ) -> None:
        seen_updates = self._youtube_feed_seen_updates.setdefault(subscription_id, {})
        seen_updates[video_id] = entry_updated
        if len(seen_updates) > 50:
            for old_video_id in list(seen_updates)[: len(seen_updates) - 50]:
                seen_updates.pop(old_video_id, None)

    async def _poll_youtube_feed_fallback(
        self,
        subscription: YouTubeSubscription,
        session: aiohttp.ClientSession,
    ) -> YouTubeSubscription | None:
        if not self._should_poll_youtube_feed(subscription.id):
            return subscription

        try:
            entries = await self._fetch_youtube_feed_entries(session, subscription)
        except Exception as e:
            print(
                "YouTube Atom feed 처리 오류: "
                f"channel={subscription.channel_id} error={e}"
            )
            return subscription

        for entry in entries[:YOUTUBE_FEED_FALLBACK_MAX_ENTRIES]:
            if entry.channel_id != subscription.channel_id:
                continue

            entry_updated = entry.updated or entry.published
            if not self._should_process_youtube_feed_entry(
                subscription,
                entry.video_id,
                entry_updated,
            ):
                continue

            await self._process_youtube_video_candidate(subscription, entry.video_id)
            self._remember_youtube_feed_entry_seen(
                subscription.id,
                entry.video_id,
                entry_updated,
            )
            refreshed = await get_youtube_subscription(subscription.id)
            if refreshed is None:
                return None
            subscription = refreshed

        return subscription

    async def _mark_youtube_video_notified(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
    ) -> YouTubeSubscription:
        notified_ids = [str(current_id) for current_id in subscription.notified_video_ids]
        if video_id not in notified_ids:
            notified_ids.append(video_id)
        notified_ids = notified_ids[-30:]
        pending = dict(subscription.pending_videos)
        pending.pop(video_id, None)
        await update_youtube_subscription_state(
            subscription.id,
            pending_videos=pending,
            notified_video_ids=notified_ids,
        )
        return replace(
            subscription,
            pending_videos=pending,
            notified_video_ids=notified_ids,
        )

    async def _mark_youtube_upload_video_notified(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
    ) -> YouTubeSubscription:
        notified_ids = [
            str(current_id) for current_id in subscription.notified_upload_video_ids
        ]
        if video_id not in notified_ids:
            notified_ids.append(video_id)
        notified_ids = notified_ids[-30:]
        await update_youtube_upload_notification_state(
            subscription.id,
            notified_upload_video_ids=notified_ids,
        )
        return replace(subscription, notified_upload_video_ids=notified_ids)

    async def _mark_youtube_community_post_notified(
        self,
        subscription: YouTubeSubscription,
        post_id: str,
    ) -> YouTubeSubscription:
        notified_ids = [str(current_id) for current_id in subscription.notified_community_post_ids]
        if post_id not in notified_ids:
            notified_ids.append(post_id)
        notified_ids = trim_notified_community_post_ids(notified_ids)
        await update_youtube_community_notification_state(
            subscription.id,
            notified_community_post_ids=notified_ids,
        )
        return replace(subscription, notified_community_post_ids=notified_ids)

    async def _remember_pending_youtube_video(
        self,
        subscription: YouTubeSubscription,
        status,
    ) -> YouTubeSubscription:
        pending = dict(subscription.pending_videos)
        pending[status.video_id] = {
            "title": status.title,
            "channelId": status.channel_id,
            "scheduledStartTime": status.scheduled_start_time,
            "lastCheckedAt": datetime.now(timezone.utc).isoformat(),
        }
        await update_youtube_subscription_state(
            subscription.id,
            pending_videos=pending,
            notified_video_ids=subscription.notified_video_ids,
        )
        return replace(subscription, pending_videos=pending)

    async def _remove_pending_youtube_video(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
    ) -> YouTubeSubscription:
        pending = dict(subscription.pending_videos)
        pending.pop(video_id, None)
        await update_youtube_subscription_state(
            subscription.id,
            pending_videos=pending,
            notified_video_ids=subscription.notified_video_ids,
        )
        return replace(subscription, pending_videos=pending)

    async def _send_youtube_live_notification(
        self,
        subscription: YouTubeSubscription,
        status,
    ) -> bool:
        if status.video_id in self._get_notified_video_ids(subscription):
            return False

        target = await self._resolve_youtube_notification_target(
            subscription,
            "라이브",
        )
        if target is None:
            return False

        await target.send(build_youtube_live_notification_message(status.video_id))
        return True

    async def _send_youtube_upload_notification(
        self,
        subscription: YouTubeSubscription,
        status,
    ) -> bool:
        if status.video_id in self._get_notified_upload_video_ids(subscription):
            return False

        target = await self._resolve_youtube_notification_target(
            subscription,
            "영상",
        )
        if target is None:
            return False

        await target.send(
            build_youtube_upload_notification_message(
                subscription.channel_name,
                status.title,
                status.video_id,
            )
        )
        return True

    async def _send_youtube_community_notification(
        self,
        subscription: YouTubeSubscription,
        post: YouTubeCommunityPost,
    ) -> bool:
        if post.post_id in self._get_notified_community_post_ids(subscription):
            return False

        target = await self._resolve_youtube_notification_target(
            subscription,
            "커뮤니티",
        )
        if target is None:
            return False

        description = _truncate_discord_text(post.text or "본문 없음", 900)
        embed = discord.Embed(
            title=f"{subscription.channel_name} 커뮤니티 게시물",
            description=description,
            url=post.url,
            color=discord.Color.red(),
        )
        if post.author:
            embed.set_author(name=post.author)
        if post.published_time:
            embed.add_field(name="게시 시각", value=post.published_time, inline=True)
        if post.attachment_urls:
            embed.set_image(url=post.attachment_urls[0])

        await target.send(
            content=f"## 📝 {subscription.channel_name} 새 커뮤니티 게시물\n{post.url}",
            embed=embed,
        )
        return True

    async def _resolve_youtube_notification_target(
        self,
        subscription: YouTubeSubscription,
        alert_label: str,
    ):
        target_channel_id = await get_channel(subscription.guild_id, YOUTUBE_CHANNEL_TYPE)
        if target_channel_id is None:
            print(
                f"YouTube {alert_label} 알림 채널이 설정되지 않았습니다. "
                f"guild={subscription.guild_id} channel={subscription.channel_id}"
            )
            return None

        target = self.bot.get_channel(target_channel_id)
        if target is None:
            try:
                target = await self.bot.fetch_channel(target_channel_id)
            except discord.DiscordException:
                print(
                    f"YouTube {alert_label} 알림 대상 채널을 찾을 수 없습니다. "
                    f"guild={subscription.guild_id} channel_id={target_channel_id}"
                )
                return None

        return target

    async def _process_youtube_video_candidate(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
    ) -> str:
        try:
            status = await self._fetch_youtube_video_status(video_id)
        except HttpError as e:
            print(f"YouTube videos.list 에러: {e}")
            return "error"

        if status is None:
            await self._remove_pending_youtube_video(subscription, video_id)
            return "missing"

        if status.channel_id and status.channel_id != subscription.channel_id:
            await self._remove_pending_youtube_video(subscription, video_id)
            return "channel_mismatch"

        if status.status == YouTubeVideoStatus.LIVE:
            if not subscription.live_alert_enabled:
                await self._remove_pending_youtube_video(subscription, video_id)
                return "live_disabled"
            if status.video_id in self._get_notified_video_ids(subscription):
                return "duplicate"
            sent = await self._send_youtube_live_notification(subscription, status)
            if sent:
                await self._mark_youtube_video_notified(subscription, status.video_id)
                return "notified"
            await self._remember_pending_youtube_video(subscription, status)
            return "live_pending"

        if status.status == YouTubeVideoStatus.UPCOMING:
            if not subscription.live_alert_enabled:
                await self._remove_pending_youtube_video(subscription, video_id)
                return "upcoming_disabled"
            await self._remember_pending_youtube_video(subscription, status)
            return "upcoming"

        if status.status == YouTubeVideoStatus.UPLOAD:
            await self._remove_pending_youtube_video(subscription, video_id)
            if status.video_id in self._get_notified_upload_video_ids(subscription):
                return "duplicate_upload"
            if not should_send_youtube_upload_alert(
                upload_alert_enabled=subscription.upload_alert_enabled,
                upload_alert_enabled_at=subscription.upload_alert_enabled_at,
                published_at=status.published_at,
            ):
                return "upload_disabled"
            sent = await self._send_youtube_upload_notification(subscription, status)
            if sent:
                await self._mark_youtube_upload_video_notified(
                    subscription,
                    status.video_id,
                )
                return "upload_notified"
            return "upload_send_failed"

        if status.status == YouTubeVideoStatus.SHORTS:
            await self._remove_pending_youtube_video(subscription, video_id)
            return "shorts_skipped"

        await self._remove_pending_youtube_video(subscription, video_id)
        return "not_live"

    async def _poll_youtube_community_posts(
        self,
        subscription: YouTubeSubscription,
    ) -> YouTubeSubscription:
        if not subscription.community_alert_enabled:
            return subscription

        try:
            posts = await fetch_latest_youtube_community_posts(
                subscription.channel_id,
                limit=10,
            )
        except Exception as e:
            print(
                "YouTube 커뮤니티 게시물 조회 실패: "
                f"channel={subscription.channel_id} error={e}"
            )
            return subscription

        if not posts:
            return subscription

        if not subscription.notified_community_post_ids:
            notified_ids = trim_notified_community_post_ids(
                [post.post_id for post in posts]
            )
            await update_youtube_community_notification_state(
                subscription.id,
                notified_community_post_ids=notified_ids,
            )
            return replace(subscription, notified_community_post_ids=notified_ids)

        new_posts = find_new_youtube_community_posts(
            posts,
            subscription.notified_community_post_ids,
        )
        for post in reversed(new_posts):
            sent = await self._send_youtube_community_notification(
                subscription,
                post,
            )
            if sent:
                subscription = await self._mark_youtube_community_post_notified(
                    subscription,
                    post.post_id,
                )

        return subscription

    async def handle_youtube_websub_notification(self, atom_xml: str) -> dict:
        entries = parse_youtube_atom_entries(atom_xml)

        result = {
            "received": len(entries),
            "processed": 0,
            "ignored": 0,
            "results": [],
        }
        for entry in entries:
            subscriptions = await find_youtube_subscriptions_by_channel_id(
                entry.channel_id
            )
            if not subscriptions:
                result["ignored"] += 1
                continue

            for subscription in subscriptions:
                outcome = await self._process_youtube_video_candidate(
                    subscription,
                    entry.video_id,
                )
                result["processed"] += 1
                result["results"].append(
                    {
                        "guild_id": subscription.guild_id,
                        "subscription_id": subscription.id,
                        "video_id": entry.video_id,
                        "status": outcome,
                    }
                )

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
    async def youtube_notification_check(self):
        """WebSub 후보와 Atom feed fallback 후보를 videos.list로 확인합니다."""
        try:
            await self._delete_legacy_youtube_live_checker_setting_once()
            subscriptions = await list_all_youtube_subscriptions()
            async with aiohttp.ClientSession(trust_env=False) as session:
                for subscription in subscriptions:
                    subscription = await self._poll_youtube_feed_fallback(
                        subscription,
                        session,
                    )
                    if subscription is None:
                        continue

                    pending = dict(subscription.pending_videos)
                    if not pending:
                        continue

                    for video_id, pending_entry in list(pending.items()):
                        if not isinstance(pending_entry, dict):
                            subscription = await self._remove_pending_youtube_video(
                                subscription,
                                str(video_id),
                            )
                            pending = dict(subscription.pending_videos)
                            continue
                        if not self._should_check_pending_youtube_video(pending_entry):
                            continue

                        pending_entry["lastCheckedAt"] = datetime.now(
                            timezone.utc
                        ).isoformat()
                        pending[str(video_id)] = pending_entry
                        await update_youtube_subscription_state(
                            subscription.id,
                            pending_videos=pending,
                            notified_video_ids=subscription.notified_video_ids,
                        )
                        subscription = replace(subscription, pending_videos=pending)
                        await self._process_youtube_video_candidate(
                            subscription,
                            str(video_id),
                        )
                        refreshed = await get_youtube_subscription(subscription.id)
                        if refreshed is None:
                            break
                        subscription = refreshed
                        pending = dict(subscription.pending_videos)
        except Exception as e:
            print(f"YouTube 알림 후보 확인 오류: {e}")

    @tasks.loop(minutes=10)
    async def youtube_community_check(self):
        """커뮤니티 알림이 켜진 유튜브 구독의 새 게시물을 확인합니다."""
        try:
            subscriptions = await list_all_youtube_subscriptions()
            for subscription in subscriptions:
                if not subscription.community_alert_enabled:
                    continue
                await self._poll_youtube_community_posts(subscription)
        except Exception as e:
            print(f"YouTube 커뮤니티 알림 확인 오류: {e}")

    @tasks.loop(hours=12)
    async def youtube_websub_renewal(self):
        """YouTube WebSub 구독을 주기적으로 갱신합니다."""
        try:
            subscribed = await self.ensure_youtube_websub_subscription()
            if subscribed:
                print("YouTube WebSub 구독 갱신 요청 완료")
        except Exception as e:
            print(f"YouTube WebSub 구독 갱신 오류: {e}")

    @youtube_notification_check.before_loop
    async def before_youtube_notification_check(self):
        print("-------------YouTube 알림 체크 대기중...---------------")
        await self.bot.wait_until_ready()

    @youtube_community_check.before_loop
    async def before_youtube_community_check(self):
        print("-------------YouTube 커뮤니티 알림 체크 대기중...---------------")
        await self.bot.wait_until_ready()

    @youtube_websub_renewal.before_loop
    async def before_youtube_websub_renewal(self):
        print("-------------YouTube WebSub 구독 갱신 대기중...---------------")
        await self.bot.wait_until_ready()


async def setup(bot):
    """Cog를 봇에 추가합니다."""
    await bot.add_cog(LoopTasks(bot))
    print("LoopTasks Cog : setup 완료!")


def _truncate_discord_text(text: str, max_length: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."
