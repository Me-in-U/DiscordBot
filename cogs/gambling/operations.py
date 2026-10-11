from contextlib import asynccontextmanager
from functools import wraps
from copy import deepcopy

from util.db import transaction, execute_query, fetch_one


@asynccontextmanager
async def financial_transaction(guild_id):
    async with transaction():
        await execute_query("INSERT IGNORE INTO financial_locks (guild_id) VALUES (%s)", (int(guild_id),))
        await fetch_one("SELECT guild_id FROM financial_locks WHERE guild_id=%s FOR UPDATE", (int(guild_id),))
        yield


def financial_operation(func):
    @wraps(func)
    async def wrapped(*args, **kwargs):
        from .services import BalanceService
        owner = args[0]
        service = (args[1] if hasattr(owner, 'response') else
                   getattr(owner, "balance", getattr(owner, "_balance", None)))
        if not isinstance(service, BalanceService):
            return await func(*args, **kwargs)
        guild_id = getattr(owner, "guild_id", None)
        if guild_id is None:
            guild_id = owner.guild.id
        interaction = owner if hasattr(owner, "response") else next((arg for arg in args[1:] if hasattr(arg, "response")), None)
        interaction_id = getattr(interaction, "id", None)
        state = {}
        buttons = []
        original_stop = getattr(owner, "stop", None)
        pending_stop = False
        def stop_after_commit():
            nonlocal pending_stop
            pending_stop = True
        try:
            async with financial_transaction(guild_id):
                state = {name: deepcopy(getattr(owner, name)) for name in
                         ("finished", "can_double", "current_bet", "player", "dealer", "deck", "parts", "claimed", "claimed_users", "btn_states", "round_id")
                         if hasattr(owner, name)}
                buttons = [(child, child.disabled, child.label, child.style) for child in getattr(owner, "children", []) if hasattr(child, "label")]

                if original_stop is not None:
                    owner.stop = stop_after_commit
                if interaction_id is not None:
                    processed = await fetch_one("SELECT interaction_id FROM financial_operations WHERE interaction_id=%s", (interaction_id,))
                    if processed:
                        await interaction.response.send_message("이미 처리된 요청입니다.", ephemeral=True)
                        return
                result = await func(*args, **kwargs)
                if interaction_id is not None:
                    await execute_query("INSERT INTO financial_operations (interaction_id) VALUES (%s)", (interaction_id,))
            if pending_stop:
                original_stop()
            return result
        except BaseException:
            for name, value in state.items():
                setattr(owner, name, value)
            for child, disabled, label, style in buttons:
                child.disabled, child.label, child.style = disabled, label, style
            raise
        finally:
            if original_stop is not None:
                owner.stop = original_stop
    return wrapped
