from __future__ import annotations

import logging

from util.music.logging import make_music_debug_logger

logger = logging.getLogger("cogs.music")
DEFAULT_MUSIC_CHANNEL_NAME = "🎵ㆍ神-음악채널"
MUSIC_CHANNEL_TYPE = "music"
MAX_QUEUE_DISPLAY = 10
IDLE_DISCONNECT_SECONDS = 300
MSG_NO_PLAYING = "❌ 재생 중인 음악이 없습니다."
dbg = make_music_debug_logger(logger)
