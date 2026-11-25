from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

from util.db import execute_query, fetch_one
from util.guild.channel_settings import set_channel

CHANNEL_TYPE = "disaster_sms"
API_URL = "https://www.safetydata.go.kr/V2/api/DSSP-IF-00247"
SOURCE_URL = "https://safetydata.go.kr/disaster-data/disasterNotificationDetail"
KST = timezone(timedelta(hours=9))
CHANNEL_LOCK = asyncio.Lock()

_EXERCISE = re.compile(
    r"\[(?:[^\[\]]{0,24})?(?:훈련|시험|테스트|연습|수능)[^\[\]]{0,20}\]"
    r"|(?:훈련|시험|테스트|연습)(?:용|을\s*위한)?\s*(?:재난문자|문자\s*발송|경보|상황|안내)"
    r"|(?:민방위|민방공|공습|대피|방재|재난대응)\s*(?:대비\s*)?(?:훈련|연습)"
    r"|(?:훈련|연습)(?:입니다|에\s*따른|의\s*일환)|(?:모의|가상)\s*(?:상황|훈련|경보)"
    r"|수능\s*(?:부정행위|시험)|대학수학능력시험|시험\s*송출|실제\s*상황이\s*아닙니다"
)
_FOLLOW_UP = re.compile(
    r"경보(?:를|가)?\s*(?:발령\s*)?해제|대피\s*(?:(?:명령|지시|권고)(?:을|가)?\s*)?해제"
    r"|대피령(?:을|이)?\s*해제|일상\s*(?:으로\s*)?복귀|귀가\s*(?:가능|바랍니다)"
    r"|정정|오발(?:령|송)|잘못\s*(?:발송|송출)|발령\s*취소"
)
_CIVIL_WARNING = re.compile(r"(?:경계|공습|화생방|핵)\s*경보")
_EVACUATION = re.compile(
    r"대피\s*(?:명령|령|지시)|대피소로\s*이동|(?:즉시|신속히)\s*대피"
    r"|대피해\s*주시기|대피(?:하|해)\s*(?:십시오|세요)|대피\s*바랍니다"
    r"|(?:실내|건물\s*(?:내|안)|지하\s*시설)[^.!?\n]{0,20}대피"
)
_DANGER = re.compile(
    r"테러|방사(?:선|능|성물질)|원전|댐\s*붕괴|급류|범람|침수|홍수|산불|산사태"
    r"|폭발|화재|화학물질|유독가스|지진해일"
)


def classify_notice(row: dict, *, related: bool = False) -> str | None:
    body = str(row.get("MSG_CN") or "").strip()
    if not body or _EXERCISE.search(body):
        return None

    category = row.get("DST_SE_NM")
    level = row.get("EMRG_STEP_NM")
    civil = category == "민방공" or bool(_CIVIL_WARNING.search(body))
    tsunami = category == "지진해일" and bool(re.search(r"해일\s*경보", body))
    if _FOLLOW_UP.search(body) or (related and "해제" in body):
        if related or civil or tsunami or level == "위급재난" or (
            _DANGER.search(body)
            and (level == "긴급재난" or _EVACUATION.search(body))
        ):
            return "update"
        return None

    if level == "위급재난" or (civil and _CIVIL_WARNING.search(body)) or tsunami:
        return "alert"
    if _EVACUATION.search(body) and (
        level == "긴급재난" or re.search(r"대피\s*(?:명령|령|지시)", body)
    ):
        if not re.search(r"대피\s*(?:권고|훈련|준비|예정)", body):
            return "alert"
    return None


def notice_time(row: dict) -> datetime:
    timestamp = datetime.fromisoformat(str(row["CRT_DT"]).strip().replace("/", "-"))
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=KST)
    return timestamp.astimezone(KST)


def _state_key(guild_id: int) -> str:
    return f"disasterSms:{guild_id}"


async def load_state(guild_id: int, channel_id: int) -> dict:
    row = await fetch_one(
        "SELECT setting_value FROM setting_data WHERE setting_key = %s",
        (_state_key(guild_id),),
    )
    if row:
        state = json.loads(row["setting_value"])
        if state["channel_id"] == channel_id:
            return state
    return {"channel_id": channel_id, "since": datetime.now(KST).isoformat(), "serial": 0, "alerts": {}}


async def save_state(guild_id: int, state: dict) -> None:
    payload = json.dumps(state, ensure_ascii=False)
    await execute_query(
        "INSERT INTO setting_data (setting_key, setting_value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE setting_value = %s",
        (_state_key(guild_id), payload, payload),
    )


async def configure_channel(guild_id: int, channel_id: int | None) -> None:
    async with CHANNEL_LOCK:
        if channel_id is None:
            await set_channel(guild_id, CHANNEL_TYPE, None)
            await execute_query(
                "DELETE FROM setting_data WHERE setting_key = %s", (_state_key(guild_id),)
            )
            return
        state = await load_state(guild_id, channel_id)
        await save_state(guild_id, state)
        await set_channel(guild_id, CHANNEL_TYPE, channel_id)
