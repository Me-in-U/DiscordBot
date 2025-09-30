from datetime import datetime


def get_recent_messages(client, guild_id: int, limit: int = 20):
    def _format_content(c):
        if isinstance(c, str):
            return c.strip()
        if isinstance(c, list):
            texts, images = [], []
            for part in c:
                if not isinstance(part, dict):
                    continue
                # type 분기
                ptype = part.get("type")
                if ptype == "input_text":
                    txt = part.get("text", "")
                    if isinstance(txt, str) and txt.strip():
                        texts.append(txt.strip())
                elif ptype == "input_image":
                    url = part.get("image_url")
                    if isinstance(url, str) and url.strip():
                        images.append(url.strip())
            text_part = " ".join(texts) if texts else ""
            if images:
                img_part = (
                    f"(image: {images[0]})"
                    if len(images) == 1
                    else f"(images: {len(images)}개)"
                )
                return f"{text_part} {img_part}".strip()
            return text_part
        return str(c)

    def _parse_time(m):
        t = m.get("time", "")
        try:
            return datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime(1970, 1, 1)

    # 길드별 저장 구조: USER_MESSAGES[guild_id][author] = [msg,...]
    root = getattr(client, "USER_MESSAGES", {})
    if not isinstance(root, dict):
        print("get_recent_messages: USER_MESSAGES 타입 오류 ->", type(root))
        return ""
    guild_map = root.get(guild_id) or {}
    if not isinstance(guild_map, dict):
        print("get_recent_messages: 길드 맵이 dict가 아님 ->", type(guild_map))
        return ""

    # 길드 내 모든 유저 메시지 평탄화(+ author 주입)
    all_msgs = []
    for author, msgs in guild_map.items():
        if isinstance(msgs, list):
            for m in msgs:
                all_msgs.append({**m, "author": author})

    print(f"get_recent_messages[guild={guild_id}]: 집계된 메시지 수 = {len(all_msgs)}")

    if not all_msgs:
        return ""

    # 최신순 정렬 → 최근 limit개 → 보기 좋게 오래된→최신으로
    all_msgs.sort(key=_parse_time, reverse=True)
    recent = list(reversed(all_msgs[:limit]))

    lines = []
    for m in recent:
        author = m.get("author", "unknown")
        role = m.get("role", "user")
        content = _format_content(m.get("content", ""))
        t = m.get("time", "")
        lines.append(f"[{t}] {author}({role}): {content}")

    print(f"\n최근 메시지 데이터 요청됨 (guild={guild_id})", lines)
    return "\n".join(lines)
