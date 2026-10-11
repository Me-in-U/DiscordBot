from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit

import aiohttp
import discord

from common.http import EXTERNAL_HTTP_TIMEOUT
from common.openai_prompt import build_prompt
from util.codex_resets.events import CODEX_RESET_CHANNEL_TYPE, resolve_codex_reset_channel
from util.codex_resets.sender import _truncate_text
from util.db import execute_query, fetch_one
from util.guild.channel_settings import get_channels_by_purpose


TIBO_URL = "https://codex-resets.com/tibo-28"
TIBO_SUMMARY_PROMPT_ID = "pmpt_6acb1292a3d081949de6159ba2e7b8980f0a4220cb94db05"
TIBO_SUMMARY_PROMPT_VERSION = "1"
logger = logging.getLogger(__name__)
_state_lock = asyncio.Lock()
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass(frozen=True, slots=True)
class TiboLogEntry:
    entry_id: str
    day: int
    date: str
    kind: str
    title: str
    description: str
    source_url: str

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


class _TiboLogParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.entries = []
        self.has_ledger = False
        self.has_rows = False
        self.day = None
        self.date = None
        self.entry = None
        self.badge = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        field = self.stack[-1][1] if self.stack else None
        if "challenge-ledger" in classes:
            self.has_ledger = True
        if tag == "li" and "challenge-row" in classes:
            self.has_rows = True
            self.day = int(attrs.get("id", "").removeprefix("day-"))
            if not 1 <= self.day <= 28:
                raise ValueError("Invalid Tibo challenge day")
            self.date = None
            self.badge = []
        if self.day is not None and tag == "time":
            self.date = date.fromisoformat(attrs.get("datetime", "")).isoformat()
        if self.day is not None and "challenge-badge" in classes:
            self.badge = []
            field = "badge"
        if self.day is not None and tag == "article" and "challenge-entry" in classes:
            kind = next((value.removeprefix("challenge-entry--") for value in classes if value.startswith("challenge-entry--")), "")
            # Reset articles omit the type class; their preceding badge carries the type.
            if not kind:
                kind = {"reset": "reset", "banked reset": "banked-reset", "improvement": "improvement"}.get(
                    " ".join("".join(self.badge).split()).lower(), ""
                )
            if kind not in {"improvement", "reset", "banked-reset"}:
                raise ValueError("Unknown Tibo log entry type")
            self.entry = {"entry_id": attrs.get("id", ""), "kind": kind, "title": [], "description": [], "source_url": ""}
        if self.entry is not None:
            if tag == "h3":
                field = "title"
            elif tag == "p":
                field = "description"
                self.entry[field].append(" ")
            elif tag == "a" and field == "title":
                self.entry["source_url"] = attrs.get("href", "")
        if tag in {"script", "style"}:
            field = None
        if tag not in _VOID_TAGS:
            self.stack.append((tag, field))
        elif tag == "br":
            self.handle_data(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data):
        field = self.stack[-1][1] if self.stack else None
        if self.day is not None and field == "badge":
            self.badge.append(data)
        if self.entry is not None and field in {"title", "description"}:
            self.entry[field].append(data)

    def handle_endtag(self, tag):
        if tag == "article" and self.entry is not None:
            title = " ".join("".join(self.entry["title"]).split())
            description = " ".join("".join(self.entry["description"]).split())
            if not self.entry["entry_id"] or not title or not description or not self.date:
                raise ValueError("Incomplete Tibo log entry")
            source = self.entry["source_url"]
            parsed = urlsplit(source)
            if parsed.scheme != "https" or parsed.netloc not in {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}:
                source = f"{TIBO_URL}#{quote(self.entry['entry_id'], safe='%')}"
            self.entries.append(TiboLogEntry(self.entry["entry_id"], self.day, self.date, self.entry["kind"], title, description, source))
            self.entry = None
        if tag == "li":
            self.day = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def parse_tibo_daily_log(html: str) -> tuple[TiboLogEntry, ...]:
    parser = _TiboLogParser()
    parser.feed(html)
    parser.close()
    if not parser.has_ledger or not parser.has_rows or parser.entry is not None:
        raise ValueError("Tibo Daily log markup is missing or incomplete")
    ids = [entry.entry_id for entry in parser.entries]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate Tibo log entry IDs")
    return tuple(sorted(parser.entries, key=lambda entry: entry.day))


async def fetch_tibo_daily_log() -> tuple[TiboLogEntry, ...]:
    async with aiohttp.ClientSession(timeout=EXTERNAL_HTTP_TIMEOUT) as session:
        async with session.get(TIBO_URL, headers={"User-Agent": "DiscordBot Tibo Daily log notifier"}, timeout=aiohttp.ClientTimeout(total=15)) as response:
            response.raise_for_status()
            return parse_tibo_daily_log(await response.text())


async def summarize_tibo_daily_log(entries: tuple[TiboLogEntry, ...]) -> tuple[tuple[str, str], ...]:
    from api.chatGPT import custom_prompt_model

    content = json.dumps([{"title": entry.title, "description": entry.description} for entry in entries], ensure_ascii=False)
    result = await asyncio.to_thread(
        custom_prompt_model,
        prompt=build_prompt(TIBO_SUMMARY_PROMPT_ID, TIBO_SUMMARY_PROMPT_VERSION),
        image_content=[
            {"role": "user", "content": [{"type": "input_text", "text": content}]}
        ],
    )
    payload = json.loads(result)
    if not isinstance(payload, dict) or set(payload) != {"announcements"}:
        raise ValueError("Invalid Tibo summary response")
    payload = payload["announcements"]
    if not isinstance(payload, list) or len(payload) != len(entries):
        raise ValueError("Translation must include every Tibo announcement")
    summaries = []
    for item in payload:
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key].strip() for key in ("title", "summary")):
            raise ValueError("Invalid Tibo translation result")
        if not any("\uac00" <= char <= "\ud7a3" for char in item["summary"]):
            raise ValueError("Tibo summary must be in Korean")
        summaries.append((item["title"].strip().replace("\u00b7", ", "), item["summary"].strip().replace("\u00b7", ", ")))
    return tuple(summaries)


def build_tibo_daily_log_embed(
    entries: tuple[TiboLogEntry, ...],
    summaries: tuple[tuple[str, str], ...],
    *,
    updated: bool = False,
) -> discord.Embed:
    if not entries or len(entries) != len(summaries) or len(entries) > 23:
        raise ValueError("Invalid Tibo daily embed items")
    entry = entries[0]
    has_reset = any(item.kind in {"reset", "banked-reset"} for item in entries)
    has_improvement = any(item.kind == "improvement" for item in entries)
    label = "개선과 리셋 소식" if has_reset and has_improvement else "리셋 소식" if has_reset else "개선 소식"
    embed = discord.Embed(
        title=f"{'🔄' if has_reset else '🚀'} Day {entry.day:02d} / 28 | {label}",
        url=f"{TIBO_URL}#day-{entry.day}",
        description=f"오늘의 발표 {len(entries)}건을 한국어로 요약했습니다.",
        color=0xF2C14E if has_reset and has_improvement else 0xF28C45 if has_reset else 0x9B8AFB,
    )
    embed.set_author(name="Tibo의 28일 챌린지")
    summary_limit = max(100, min(400, 4500 // len(entries) - 200))
    for index, (item, (title, summary)) in enumerate(zip(entries, summaries), 1):
        kind = "적립형 리셋" if item.kind == "banked-reset" else "리셋" if item.kind == "reset" else "개선"
        value = f"{discord.utils.escape_markdown(_truncate_text(summary, summary_limit))}\n[원문 발표]({item.source_url})"
        if len(value) > 1024:
            raise ValueError("Tibo announcement exceeds embed field limit")
        embed.add_field(name=f"{index}. [{kind}] {_truncate_text(title, 100)}", value=value, inline=False)
    embed.add_field(name="발표 날짜 (PT)", value=entry.date)
    embed.add_field(name="업데이트", value="Daily log 갱신" if updated else "새 Daily log")
    embed.set_footer(text="Daily log | codex-resets.com 비공식 추적기")
    if len(embed) > 6000:
        raise ValueError("Tibo daily log exceeds total embed limit")
    return embed


async def reset_tibo_daily_log_state(guild_id: int) -> None:
    async with _state_lock:
        await execute_query("DELETE FROM setting_data WHERE setting_key = %s", (f"tiboDailyLog:{guild_id}",))


async def _save_state(guild_id: int, channel_id: int, fingerprints: dict[str, str]) -> None:
    await execute_query(
        "INSERT INTO setting_data (setting_key, setting_value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)",
        (f"tiboDailyLog:{guild_id}", json.dumps({"channelId": channel_id, "entries": fingerprints})),
    )


async def refresh_tibo_daily_log_notifications(bot: object) -> int:
    async with _state_lock:
        channels = await get_channels_by_purpose(CODEX_RESET_CHANNEL_TYPE)
        if not channels:
            return 0
        entries = await fetch_tibo_daily_log()
        current = {entry.entry_id: entry.fingerprint() for entry in entries}
        daily_entries: dict[int, tuple[TiboLogEntry, ...]] = {}
        for day in sorted({entry.day for entry in entries}):
            daily_entries[day] = tuple(entry for entry in entries if entry.day == day)
        summaries_by_day = {}
        sent_count = 0
        for guild_id, channel_id in channels.items():
            try:
                row = await fetch_one("SELECT setting_value FROM setting_data WHERE setting_key = %s", (f"tiboDailyLog:{guild_id}",))
                state = json.loads(row["setting_value"]) if row else None
                if state is None or state.get("channelId") != channel_id:
                    await _save_state(guild_id, channel_id, current)
                    continue
                fingerprints = state["entries"]
                if not isinstance(fingerprints, dict):
                    raise ValueError("Invalid Tibo Daily log state")
                changed = [entry for entry in entries if fingerprints.get(entry.entry_id) != current[entry.entry_id]]
                if not changed:
                    continue
                target = await resolve_codex_reset_channel(bot, channel_id)
                if target is None:
                    raise ValueError("Configured Tibo notification channel could not be resolved")
                for day in sorted({entry.day for entry in changed}):
                    day_entries = daily_entries[day]
                    if day not in summaries_by_day:
                        summaries_by_day[day] = await summarize_tibo_daily_log(day_entries)
                    updated = any(entry.entry_id in fingerprints for entry in day_entries)
                    embed = build_tibo_daily_log_embed(day_entries, summaries_by_day[day], updated=updated)
                    if updated:
                        changed_kinds = {entry.kind for entry in changed if entry.day == day}
                        labels = [label for kind, label in (
                            ("improvement", "개선"),
                            ("banked-reset", "**적립형 리셋**"),
                            ("reset", "리셋"),
                        ) if kind in changed_kinds]
                        await target.send(content=f"추가 {', '.join(labels)} 사항 업데이트", allowed_mentions=discord.AllowedMentions.none())
                    await target.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                    fingerprints.update({entry.entry_id: current[entry.entry_id] for entry in day_entries})
                    await _save_state(guild_id, channel_id, fingerprints)
                    sent_count += 1
            except Exception:
                logger.exception("Tibo Daily log 알림 실패: guild=%s channel=%s", guild_id, channel_id)
        return sent_count
