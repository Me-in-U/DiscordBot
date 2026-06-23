H_BAR = "\u2015"


def format_music_time(seconds: int) -> str:
    normalized = max(0, int(seconds or 0))
    minutes, remaining_seconds = divmod(normalized, 60)
    return f"{minutes:02}:{remaining_seconds:02}"


def _clamp_elapsed(elapsed: int, total: int) -> int:
    normalized_elapsed = max(0, int(elapsed or 0))
    normalized_total = max(0, int(total or 0))
    if normalized_total == 0:
        return 0
    return min(normalized_elapsed, normalized_total)


def make_progress_bar(elapsed: int, total: int, length: int = 23) -> tuple[str, int]:
    normalized_length = max(0, int(length or 0))
    normalized_total = max(0, int(total or 0))
    if normalized_total == 0:
        return "▱" * normalized_length, 0

    normalized_elapsed = _clamp_elapsed(elapsed, normalized_total)
    filled = int(normalized_length * normalized_elapsed / normalized_total)
    return "▰" * filled + "▱" * (normalized_length - filled), filled


def make_timeline_line(elapsed: int, total: int, length: int = 16) -> str:
    normalized_total = max(0, int(total or 0))
    normalized_elapsed = _clamp_elapsed(elapsed, normalized_total)
    elapsed_fmt = format_music_time(normalized_elapsed)
    total_fmt = format_music_time(normalized_total)
    pct = int(normalized_elapsed / normalized_total * 100) if normalized_total else 0
    _, filled = make_progress_bar(normalized_elapsed, normalized_total, length)
    normalized_length = max(0, int(length or 0))
    left = H_BAR * filled
    right = H_BAR * (normalized_length - filled)
    return f"{left}{elapsed_fmt}{right} {total_fmt} ({pct}%)"
