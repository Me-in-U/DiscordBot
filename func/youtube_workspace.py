from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

YOUTUBE_AUDIO_FILENAME = "youtube_audio.mp3"
YOUTUBE_SUBTITLE_TEMPLATE = "youtube_subtitles.%(ext)s"


def youtube_audio_path(workspace: str | Path) -> Path:
    return Path(workspace) / YOUTUBE_AUDIO_FILENAME


def subtitle_output_template(workspace: str | Path) -> str:
    return str(Path(workspace) / YOUTUBE_SUBTITLE_TEMPLATE)


@contextmanager
def youtube_summary_workspace() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="youtube-summary-") as workspace:
        yield Path(workspace)
