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
            guild_id VARCHAR(20) PRIMARY KEY,
            guild_name VARCHAR(100)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """,
        """
        CREATE TABLE IF NOT EXISTS user (
            user_id VARCHAR(20) PRIMARY KEY,
            username VARCHAR(100)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """,
    ]
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for query in queries:
                await cur.execute(query)


async def upsert_guild(guild_id, guild_name):
    query = """
    INSERT INTO guild (guild_id, guild_name)
    VALUES (%s, %s)
    ON DUPLICATE KEY UPDATE guild_name = VALUES(guild_name)
    """
    await execute_query(query, (str(guild_id), guild_name))


async def upsert_user(user_id, username):
    query = """
    INSERT INTO user (user_id, username)
    VALUES (%s, %s)
    ON DUPLICATE KEY UPDATE username = VALUES(username)
    """
    await execute_query(query, (str(user_id), username))
