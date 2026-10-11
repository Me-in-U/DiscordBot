import asyncio
import hashlib
import json
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from weakref import WeakKeyDictionary, WeakValueDictionary

import discord
from discord.http import handle_message_parameters
from util.db import execute_query, fetch_one, transaction

_send_locks = WeakKeyDictionary()


def _payload(content, options):
    embeds = options.get("embeds") or ([options["embed"]] if options.get("embed") else [])
    return {"content": content or "", "embeds": [embed.to_dict() for embed in embeds]}


def _embed_text(value):
    result = {key: value[key] for key in ("title", "description", "url", "fields", "footer", "author") if key in value}
    for key in ("footer", "author"):
        if key in result:
            result[key] = {k: v for k, v in result[key].items() if not k.startswith("proxy_")}
    return result


async def _send_enforced(target, nonce, content, options):
    # discord.py does not expose Discord's enforce_nonce option on send().
    with handle_message_parameters(content=content, nonce=nonce, **options) as params:
        if params.payload is not None:
            params.payload["enforce_nonce"] = True
        else:
            for part in params.multipart:
                if part["name"] == "payload_json":
                    payload = json.loads(part["value"])
                    payload["enforce_nonce"] = True
                    part["value"] = json.dumps(payload)
        data = await target._state.http.send_message(target.id, params=params)
    return target._state.create_message(channel=target, data=data)


async def send_once(target, key, *args, **options):
    if not isinstance(target, (discord.TextChannel, discord.Thread)):
        return await target.send(*args, **options)
    content = args[0] if args else options.pop("content", None)
    delivery_key = hashlib.sha256(f"{target.id}:{key}".encode()).hexdigest()
    locks = _send_locks.setdefault(asyncio.get_running_loop(), WeakValueDictionary())
    lock = locks.setdefault(delivery_key, asyncio.Lock())
    options.setdefault("allowed_mentions", discord.AllowedMentions.none())
    async with lock:
        payload = json.dumps(_payload(content, options), ensure_ascii=False)
        await execute_query("INSERT IGNORE INTO notification_deliveries (delivery_key,channel_id,payload,created_at) VALUES (%s,%s,%s,%s)", (delivery_key,target.id,payload,datetime.now(timezone.utc).replace(tzinfo=None)))
        async with transaction():
            row = await fetch_one("SELECT * FROM notification_deliveries WHERE delivery_key=%s FOR UPDATE", (delivery_key,))
            if row["message_id"]:
                file = options.get("file")
                if file is not None:
                    file.close()
                return SimpleNamespace(id=int(row["message_id"]))
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if row["lease_until"] and row["lease_until"] > now:
                raise RuntimeError("알림 전송이 진행 중입니다.")
            await execute_query("UPDATE notification_deliveries SET attempted_at=COALESCE(attempted_at,%s),lease_until=%s WHERE delivery_key=%s", (now,now+timedelta(seconds=60),delivery_key))
        if row["attempted_at"]:
            expected = json.loads(row["payload"])
            after = row["created_at"].replace(tzinfo=timezone.utc)-timedelta(seconds=1)
            async for message in target.history(limit=100, after=after, oldest_first=True):
                if message.author.id == target._state.user.id and message.content == expected["content"] and [_embed_text(e.to_dict()) for e in message.embeds] == [_embed_text(e) for e in expected["embeds"]]:
                    await execute_query("UPDATE notification_deliveries SET message_id=%s,lease_until=NULL WHERE delivery_key=%s", (message.id,delivery_key))
                    file = options.get("file")
                    if file is not None:
                        file.close()
                    return message
            if now-row["attempted_at"] > timedelta(minutes=2):
                raise RuntimeError("알림 전송 결과가 불확실합니다. 중복 방지를 위해 관리자 확인이 필요합니다.")
        try:
            message = await _send_enforced(target, delivery_key[:24], content, options)
        except discord.HTTPException as exc:
            if 400 <= exc.status < 500:
                await execute_query("UPDATE notification_deliveries SET attempted_at=NULL,lease_until=NULL WHERE delivery_key=%s", (delivery_key,))
            raise
        await execute_query("UPDATE notification_deliveries SET message_id=%s,lease_until=NULL WHERE delivery_key=%s", (message.id,delivery_key))
        return message
