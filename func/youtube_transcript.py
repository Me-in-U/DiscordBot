from __future__ import annotations

import logging
import re


logger = logging.getLogger(__name__)


def read_subtitles_file(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        clean_lines = []
        seen = set()

        for line in lines:
            line = line.strip()
            if line.startswith("WEBVTT") or re.match(r"\d{2}:\d{2}:\d{2}\.\d{3}", line):
                continue

            line = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", line)
            line = re.sub(r"</?c>", "", line)
            if line and line not in seen:
                clean_lines.append(line)
                seen.add(line)

        return remove_unnecessary_line_breaks("\n".join(clean_lines))
    except OSError:
        logger.warning("자막 파일 읽기 중 오류가 발생했습니다: path=%s", file_path, exc_info=True)
        return ""


def remove_unnecessary_line_breaks(text: str) -> str:
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r"([다요습니다])\s+", r"\1\n", text)
    return text.strip()
