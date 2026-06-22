from __future__ import annotations

import logging
from typing import Protocol

from googleapiclient.errors import HttpError

from util.youtube_subscriptions import YouTubeSubscription
from util.youtube.websub import (
    YouTubeVideoLiveStatus,
    YouTubeVideoStatus,
    should_send_youtube_upload_alert,
)


logger = logging.getLogger(__name__)


class YouTubeVideoCandidateOwner(Protocol):
    async def _fetch_youtube_video_status(
        self,
        video_id: str,
    ) -> YouTubeVideoLiveStatus | None: ...

    async def _remove_pending_youtube_video(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
    ) -> YouTubeSubscription: ...

    def _get_notified_video_ids(self, subscription: YouTubeSubscription) -> set[str]: ...

    def _get_notified_upload_video_ids(
        self,
        subscription: YouTubeSubscription,
    ) -> set[str]: ...

    async def _send_youtube_live_notification(
        self,
        subscription: YouTubeSubscription,
        status: YouTubeVideoLiveStatus,
    ) -> bool: ...

    async def _send_youtube_upload_notification(
        self,
        subscription: YouTubeSubscription,
        status: YouTubeVideoLiveStatus,
    ) -> bool: ...

    async def _mark_youtube_video_notified(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
    ) -> YouTubeSubscription: ...

    async def _mark_youtube_upload_video_notified(
        self,
        subscription: YouTubeSubscription,
        video_id: str,
    ) -> YouTubeSubscription: ...

    async def _remember_pending_youtube_video(
        self,
        subscription: YouTubeSubscription,
        status: YouTubeVideoLiveStatus,
    ) -> YouTubeSubscription: ...


async def process_youtube_video_candidate(
    owner: YouTubeVideoCandidateOwner,
    subscription: YouTubeSubscription,
    video_id: str,
) -> str:
    try:
        status = await owner._fetch_youtube_video_status(video_id)
    except HttpError:
        logger.exception("YouTube videos.list 에러: video_id=%s", video_id)
        return "error"

    if status is None:
        await owner._remove_pending_youtube_video(subscription, video_id)
        return "missing"

    if status.channel_id and status.channel_id != subscription.channel_id:
        await owner._remove_pending_youtube_video(subscription, video_id)
        return "channel_mismatch"

    if status.status == YouTubeVideoStatus.LIVE:
        if not subscription.live_alert_enabled:
            await owner._remove_pending_youtube_video(subscription, video_id)
            return "live_disabled"
        if status.video_id in owner._get_notified_video_ids(subscription):
            return "duplicate"
        sent = await owner._send_youtube_live_notification(subscription, status)
        if sent:
            await owner._mark_youtube_video_notified(subscription, status.video_id)
            return "notified"
        await owner._remember_pending_youtube_video(subscription, status)
        return "live_pending"

    if status.status == YouTubeVideoStatus.UPCOMING:
        if not subscription.live_alert_enabled:
            await owner._remove_pending_youtube_video(subscription, video_id)
            return "upcoming_disabled"
        await owner._remember_pending_youtube_video(subscription, status)
        return "upcoming"

    if status.status == YouTubeVideoStatus.UPLOAD:
        await owner._remove_pending_youtube_video(subscription, video_id)
        if status.video_id in owner._get_notified_upload_video_ids(subscription):
            return "duplicate_upload"
        if not should_send_youtube_upload_alert(
            upload_alert_enabled=subscription.upload_alert_enabled,
            upload_alert_enabled_at=subscription.upload_alert_enabled_at,
            published_at=status.published_at,
        ):
            return "upload_disabled"
        sent = await owner._send_youtube_upload_notification(subscription, status)
        if sent:
            await owner._mark_youtube_upload_video_notified(
                subscription,
                status.video_id,
            )
            return "upload_notified"
        return "upload_send_failed"

    if status.status == YouTubeVideoStatus.SHORTS:
        await owner._remove_pending_youtube_video(subscription, video_id)
        return "shorts_skipped"

    await owner._remove_pending_youtube_video(subscription, video_id)
    return "not_live"
