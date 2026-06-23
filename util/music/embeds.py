from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Protocol

from discord import Embed

from util.music.progress import make_progress_bar, make_timeline_line
from util.music.queue import QueuedTrack, build_queue_preview


PANEL_TITLE = "🎵 신창섭의 다해줬잖아"
PANEL_COLOR = 0xFFC0CB
UNKNOWN = "알 수 없음"


class MusicPlayerLike(Protocol):
    title: str | None
    requester: Any
    data: dict[str, Any]


def make_default_music_embed(
    *,
    bot_avatar_url: str,
    now: datetime | None = None,
) -> Embed:
    embed = Embed(
        title=PANEL_TITLE,
        description=(
            "명령어로 음악을 재생·일시정지·스킵할 수 있습니다.\n"
            "재생 이후 버튼을 통해 제어도 가능합니다.\n"
            "(재생 후 첫 대기열 추가 시 노래가 일시 끊길 수도 있습니다.)"
        ),
        color=PANEL_COLOR,
        timestamp=now or datetime.now(),
    )
    embed.add_field(
        name="❓ 사용법",
        value=(
            "• `/재생 <URL/검색어>`: 유튜브 <URL/검색어>로 즉시 재생\n"
            "• `/스킵`: 현재 재생중인 곡 스킵(다음 대기열 재생)\n"
            "• `/대기열`: 현재 대기열 확인\n"
            "• `/구간이동 <시간>`: 현재 곡의 위치 이동\n"
            "• `/반복`: 현재 곡 반복 모드 토글\n"
            "• `/대기열삭제 <번호>`, `/대기열비우기`, `/대기열이동`, `/셔플`: 대기열 관리\n"
            "• `/일시정지`, 현재 재생중인 곡 일시정지\n"
            "• `/다시재생`: 일시정지된 곡 다시재생\n"
            "• `/정지`: 노래 종료 후 신창섭 퇴장\n\n"
            "👉 재생시 생기는 버튼을 눌러도 동일 기능을 사용할 수 있습니다."
        ),
        inline=False,
    )
    embed.set_footer(
        text="정상화 해줬잖아. 그냥 다 해줬잖아.",
        icon_url=bot_avatar_url,
    )
    return embed


def make_playing_music_embed(
    player: MusicPlayerLike,
    *,
    queue: Iterable[QueuedTrack],
    is_loop: bool,
    is_paused: bool,
    elapsed: int = 0,
    fallback_requester_icon_url: str,
) -> Embed:
    total = player.data.get("duration", 0)
    embed = Embed(title=PANEL_TITLE, color=PANEL_COLOR)
    embed.set_thumbnail(url=player.data.get("thumbnail"))
    embed.add_field(name="곡 제목", value=player.title, inline=False)

    timeline = make_timeline_line(elapsed, total)
    bar, _ = make_progress_bar(elapsed, total)
    embed.add_field(name="진행", value=f"\n{timeline}\n`{bar}`", inline=False)

    queue_preview = build_queue_preview(queue)
    if queue_preview:
        queue_title, queue_value = queue_preview
        embed.add_field(name=queue_title, value=queue_value, inline=False)

    requester = player.requester
    requester_name = requester.display_name if requester else UNKNOWN
    requester_icon = (
        requester.display_avatar.url if requester else fallback_requester_icon_url
    )
    playback_status = "⏸️ 일시정지 상태" if is_paused else "▶️ 재생중..."
    loop_status = "켜짐" if is_loop else "꺼짐"

    embed.set_footer(
        text=f"신청자: {requester_name} | 반복: {loop_status} | {playback_status}",
        icon_url=requester_icon,
    )
    return embed
