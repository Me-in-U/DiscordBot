import json
import logging
from dataclasses import asdict
from datetime import datetime

from util.db import execute_query, fetch_all

logger = logging.getLogger(__name__)


async def deliver_event(bot, event, source, process_event, default_process):
    if process_event is not default_process:
        return await process_event(bot, event)
    revision = event.serial if source == "jma" else event.revision
    key = f"{source}:{event.event_id}:{revision}"
    payload = json.dumps(asdict(event), default=lambda value: value.isoformat(), ensure_ascii=False)
    await execute_query("INSERT IGNORE INTO earthquake_pending (event_key,source,payload) VALUES (%s,%s,%s)", (key,source,payload))
    results = await process_event(bot,event)
    if not any(result.status == "error" for result in results):
        await execute_query("DELETE FROM earthquake_pending WHERE event_key=%s", (key,))
    return results


async def retry_pending_events(bot):
    from util.earthquake.emsc import EmscEvent
    from util.earthquake.jma_eew import JmaEewEvent, JmaEewWarnArea
    from util.earthquake.emsc_alerts import process_emsc_event
    from util.earthquake.alerts import process_jma_eew_event
    rows = await fetch_all("SELECT * FROM earthquake_pending ORDER BY created_at LIMIT 100")
    for row in rows:
        try:
            data = json.loads(row["payload"])
            for key in ("occurred_at", "updated_at", "announced_at", "origin_at"):
                if data.get(key):
                    data[key] = datetime.fromisoformat(data[key])
            if row["source"] == "jma":
                data["warn_areas"] = tuple(JmaEewWarnArea(**value) for value in data["warn_areas"])
                event = JmaEewEvent(**data)
                process = process_jma_eew_event
            else:
                event = EmscEvent(**data)
                process = process_emsc_event
            results = await deliver_event(bot,event,row["source"],process,process)
            if any(result.status == "error" for result in results):
                await execute_query("UPDATE earthquake_pending SET created_at=CURRENT_TIMESTAMP WHERE event_key=%s", (row["event_key"],))
        except Exception:
            # Move failures behind newer events so one bad record cannot starve the queue.
            await execute_query("UPDATE earthquake_pending SET created_at=CURRENT_TIMESTAMP WHERE event_key=%s", (row["event_key"],))
            logger.exception("Earthquake retry failed: %s", row["event_key"])
