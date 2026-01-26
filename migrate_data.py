import asyncio
import json
import os
from util.db import pool, execute_query, get_db_pool, close_db_pool

# JSON Files
FILES = {
    "1557": "1557Counter.json",
    "channel_settings": "channel_settings.json",
    "gambling": "gambling_balance.json",
    "scheduler": "message_scheduler.json",
    "panel": "panelMessageIds.json",
    "settings": "settingData.json",
    "special_days": "special_days.json",
}


async def create_tables():
    print("Creating tables...")

    # 1557 Counter
    await execute_query(
        """
        CREATE TABLE IF NOT EXISTS counter_1557 (
            user_id VARCHAR(32) PRIMARY KEY,
            count INT NOT NULL DEFAULT 0
        );
    """
    )

    # Channel Settings
    await execute_query(
        """
        CREATE TABLE IF NOT EXISTS channel_settings (
            guild_id VARCHAR(32) NOT NULL,
            channel_type VARCHAR(32) NOT NULL,
            channel_id VARCHAR(32) NOT NULL,
            PRIMARY KEY (guild_id, channel_type)
        );
    """
    )

    # Gambling Balances
    await execute_query(
        """
        CREATE TABLE IF NOT EXISTS gambling_balances (
            guild_id VARCHAR(32) NOT NULL,
            user_id VARCHAR(32) NOT NULL,
            balance BIGINT DEFAULT 0,
            last_daily DATE,
            wins INT DEFAULT 0,
            losses INT DEFAULT 0,
            bj_wins INT DEFAULT 0,
            bj_losses INT DEFAULT 0,
            bj_pushes INT DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );
    """
    )

    # Scheduled Messages
    await execute_query(
        """
        CREATE TABLE IF NOT EXISTS scheduled_messages (
            id VARCHAR(36) PRIMARY KEY,
            guild_id VARCHAR(32),
            channel_id VARCHAR(32),
            user_id VARCHAR(32),
            trigger_time DATETIME,
            message TEXT,
            created_at DATETIME,
            type VARCHAR(20),
            repeat_type VARCHAR(20),
            repeat_value VARCHAR(50),
            is_recurring BOOLEAN DEFAULT FALSE
        );
    """
    )

    # Panel Messages
    await execute_query(
        """
        CREATE TABLE IF NOT EXISTS panel_messages (
            guild_id VARCHAR(32) PRIMARY KEY,
            message_id VARCHAR(32)
        );
    """
    )

    # Setting Data
    await execute_query(
        """
        CREATE TABLE IF NOT EXISTS setting_data (
            setting_key VARCHAR(64) PRIMARY KEY,
            setting_value JSON
        );
    """
    )

    # Special Days
    await execute_query(
        """
        CREATE TABLE IF NOT EXISTS special_days (
            id INT AUTO_INCREMENT PRIMARY KEY,
            day_key VARCHAR(10) NOT NULL,
            event_name VARCHAR(255) NOT NULL
        );
    """
    )
    print("Tables created.")


def load_json(filename):
    if not os.path.exists(filename):
        return None
    try:
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return None
            return json.loads(content)
    except Exception as e:
        print(f"Error reading {filename}: {e}")
        return None


async def migrate_data():
    print("Migrating data...")

    # 1. 1557 Counter
    data = load_json(FILES["1557"])
    if data:
        for user_id, count in data.items():
            await execute_query(
                "INSERT IGNORE INTO counter_1557 (user_id, count) VALUES (%s, %s)",
                (user_id, count),
            )
    print("Migrated 1557Counter")

    # 2. Channel Settings
    data = load_json(FILES["channel_settings"])
    if data:
        for guild_id, channels in data.items():
            for c_type, c_id in channels.items():
                await execute_query(
                    "INSERT IGNORE INTO channel_settings (guild_id, channel_type, channel_id) VALUES (%s, %s, %s)",
                    (guild_id, c_type, c_id),
                )
    print("Migrated Channel Settings")

    # 3. Gambling Balances
    data = load_json(FILES["gambling"])
    if data:
        for guild_id, users in data.items():
            for user_id, stats in users.items():
                last_daily = stats.get("last_daily")
                if last_daily == "None" or not last_daily:
                    last_daily = None

                await execute_query(
                    """INSERT IGNORE INTO gambling_balances 
                       (guild_id, user_id, balance, last_daily, wins, losses, bj_wins, bj_losses, bj_pushes)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        guild_id,
                        user_id,
                        stats.get("balance", 0),
                        last_daily,
                        stats.get("wins", 0),
                        stats.get("losses", 0),
                        stats.get("bj_wins", 0),
                        stats.get("bj_losses", 0),
                        stats.get("bj_pushes", 0),
                    ),
                )
    print("Migrated Gambling Balances")

    # 4. Message Scheduler
    data = load_json(FILES["scheduler"])
    if data and isinstance(data, list):
        for item in data:
            trigger_time = item.get("trigger_time")
            if trigger_time:
                # Assuming ISO format, needs conversion if necessary, or DB handles it
                trigger_time = trigger_time.replace("T", " ")

            created_at = item.get("created_at")
            if created_at:
                created_at = created_at.replace("T", " ")

            await execute_query(
                """INSERT IGNORE INTO scheduled_messages
                   (id, guild_id, channel_id, user_id, trigger_time, message, created_at, type, repeat_type, repeat_value, is_recurring)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    item.get("id"),
                    item.get("guild_id"),
                    item.get("channel_id"),
                    item.get("user_id"),
                    trigger_time,
                    item.get("message"),
                    created_at,
                    item.get("type"),
                    item.get("repeat_type"),
                    item.get("repeat_value"),
                    item.get("is_recurring", False),
                ),
            )
    print("Migrated Scheduled Messages")

    # 5. Panel Messages
    data = load_json(FILES["panel"])
    if data:
        for guild_id, message_id in data.items():
            await execute_query(
                "INSERT IGNORE INTO panel_messages (guild_id, message_id) VALUES (%s, %s)",
                (guild_id, message_id),
            )
    print("Migrated Panel Messages")

    # 6. Setting Data
    data = load_json(FILES["settings"])
    if data:
        for key, value in data.items():
            await execute_query(
                "INSERT IGNORE INTO setting_data (setting_key, setting_value) VALUES (%s, %s)",
                (key, json.dumps(value)),
            )
    print("Migrated Setting Data")

    # 7. Special Days
    data = load_json(FILES["special_days"])
    if data:
        for day, events in data.items():
            for event in events:
                await execute_query(
                    "INSERT IGNORE INTO special_days (day_key, event_name) VALUES (%s, %s)",
                    (day, event),
                )
    print("Migrated Special Days")


async def main():
    try:
        await create_tables()
        await migrate_data()
        print("Migration complete!")
    finally:
        await close_db_pool()


if __name__ == "__main__":
    asyncio.run(main())
