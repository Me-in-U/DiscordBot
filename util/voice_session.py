from functools import wraps
from contextlib import asynccontextmanager
import asyncio
from weakref import WeakValueDictionary

_locks = WeakValueDictionary()

def voice_lock(guild_id):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    return _locks.setdefault((loop, guild_id), asyncio.Lock())

def voice_operation(func):
    @wraps(func)
    async def wrapped(self, interaction):
        if interaction.guild is None:
            return await func(self, interaction)
        async with voice_lock(interaction.guild.id):
            return await func(self, interaction)
    return wrapped
