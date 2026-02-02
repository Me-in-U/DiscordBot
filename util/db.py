import os
import aiomysql
import asyncio
from dotenv import load_dotenv

load_dotenv()

DB_HOST_FULL = os.getenv("DB_HOST", "localhost:3306")
if ":" in DB_HOST_FULL:
    DB_HOST, DB_PORT = DB_HOST_FULL.split(":")
    DB_PORT = int(DB_PORT)
else:
    DB_HOST = DB_HOST_FULL
    DB_PORT = 3306

DB_USER = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_DATABASE")

pool = None


async def get_db_pool():
    global pool
    if pool is None:
        pool = await aiomysql.create_pool(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            autocommit=True,
            charset="utf8mb4",
        )
    return pool


async def close_db_pool():
    global pool
    if pool:
        pool.close()
        await pool.wait_closed()
        pool = None


async def execute_query(query, args=None):
    """Executes a query (INSERT, UPDATE, DELETE) and returns lastrowid."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, args)
            return cur.lastrowid


async def fetch_one(query, args=None):
    """Fetches a single row."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(query, args)
            return await cur.fetchone()


async def fetch_all(query, args=None):
    """Fetches all rows."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(query, args)
            return await cur.fetchall()


async def create_tables():
    """Creates necessary tables if they do not exist."""
    queries = [
        """
        CREATE TABLE IF NOT EXISTS guild (
            guild_id BIGINT UNSIGNED PRIMARY KEY,
            guild_name VARCHAR(100)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """,
        """
        CREATE TABLE IF NOT EXISTS user (
            user_id BIGINT UNSIGNED PRIMARY KEY,
            username VARCHAR(100)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """,
        """
        CREATE TABLE IF NOT EXISTS channel_settings (
            guild_id BIGINT UNSIGNED NOT NULL,
            channel_type VARCHAR(32) NOT NULL,
            channel_id BIGINT UNSIGNED NOT NULL,
            PRIMARY KEY (guild_id, channel_type)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """,
        """
        CREATE TABLE IF NOT EXISTS gambling_balances (
            guild_id BIGINT UNSIGNED NOT NULL,
            user_id BIGINT UNSIGNED NOT NULL,
            balance BIGINT DEFAULT 0,
            last_daily DATE,
            wins INT DEFAULT 0,
            losses INT DEFAULT 0,
            bj_wins INT DEFAULT 0,
            bj_losses INT DEFAULT 0,
            bj_pushes INT DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """,
        """
        CREATE TABLE IF NOT EXISTS scheduled_messages (
            id VARCHAR(36) PRIMARY KEY,
            guild_id BIGINT UNSIGNED,
            channel_id BIGINT UNSIGNED,
            user_id BIGINT UNSIGNED,
            trigger_time DATETIME,
            message TEXT,
            created_at DATETIME,
            type VARCHAR(20),
            repeat_type VARCHAR(20),
            repeat_value VARCHAR(50),
            is_recurring BOOLEAN DEFAULT FALSE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """,
        """
        CREATE TABLE IF NOT EXISTS panel_messages (
            guild_id BIGINT UNSIGNED PRIMARY KEY,
            message_id BIGINT UNSIGNED
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """,
        """
        CREATE TABLE IF NOT EXISTS counter_1557 (
            user_id BIGINT UNSIGNED PRIMARY KEY,
            count INT NOT NULL DEFAULT 0
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """,
        """
        CREATE TABLE IF NOT EXISTS setting_data (
            setting_key VARCHAR(64) PRIMARY KEY,
            setting_value JSON
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """,
        """
        CREATE TABLE IF NOT EXISTS special_days (
            id INT AUTO_INCREMENT PRIMARY KEY,
            day_key VARCHAR(10) NOT NULL,
            event_name VARCHAR(255) NOT NULL
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """,
    ]
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Create tables if missing
            for query in queries:
                await cur.execute(query)

            # Ensure column types are BIGINT UNSIGNED for FK compatibility with backend
            await _ensure_bigint_unsigned(conn, "guild", "guild_id")
            await _ensure_bigint_unsigned(conn, "user", "user_id")
            await _ensure_bigint_unsigned(conn, "channel_settings", "guild_id")
            await _ensure_bigint_unsigned(conn, "channel_settings", "channel_id")
            await _ensure_bigint_unsigned(conn, "gambling_balances", "guild_id")
            await _ensure_bigint_unsigned(conn, "gambling_balances", "user_id")
            await _ensure_bigint_unsigned(conn, "scheduled_messages", "guild_id")
            await _ensure_bigint_unsigned(conn, "scheduled_messages", "channel_id")
            await _ensure_bigint_unsigned(conn, "scheduled_messages", "user_id")
            await _ensure_bigint_unsigned(conn, "panel_messages", "guild_id")
            await _ensure_bigint_unsigned(conn, "panel_messages", "message_id")
            await _ensure_bigint_unsigned(conn, "counter_1557", "user_id")


async def upsert_guild(guild_id, guild_name):
    query = """
    INSERT INTO guild (guild_id, guild_name)
    VALUES (%s, %s)
    ON DUPLICATE KEY UPDATE guild_name = VALUES(guild_name)
    """
    # store Discord snowflake as numeric (BIGINT UNSIGNED)
    await execute_query(query, (int(guild_id), guild_name))


async def upsert_user(user_id, username):
    query = """
    INSERT INTO user (user_id, username)
    VALUES (%s, %s)
    ON DUPLICATE KEY UPDATE username = VALUES(username)
    """
    await execute_query(query, (int(user_id), username))


async def _ensure_bigint_unsigned(conn, table_name: str, column_name: str):
    """
    Ensures the given column is BIGINT UNSIGNED. If the column exists with
    a different type (e.g., VARCHAR), attempts to ALTER it.
    """
    query = (
        "SELECT DATA_TYPE, COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE table_schema = %s AND table_name = %s AND column_name = %s"
    )
    db_name = DB_NAME
    async with conn.cursor() as cur:
        await cur.execute(query, (db_name, table_name, column_name))
        row = await cur.fetchone()
        if row is None:
            return
        data_type, column_type = row
        needs_alter = (data_type != "bigint") or ("unsigned" not in column_type)
        if needs_alter:
            # Attempt to convert existing values and modify type.
            # If the column is part of PK, MySQL will alter the PK in place.
            alter_sql = f"ALTER TABLE {table_name} MODIFY COLUMN {column_name} BIGINT UNSIGNED NOT NULL"
            await cur.execute(alter_sql)
