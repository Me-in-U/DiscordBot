from functools import wraps
from util.db import transaction, fetch_one
from util.youtube.subscriptions import get_youtube_subscription


def subscription_operation(func):
    @wraps(func)
    async def wrapped(subscription, *args, **kwargs):
        if any(key.startswith("update_") for key in kwargs):
            return await func(subscription, *args, **kwargs)
        async with transaction():
            await fetch_one("SELECT id FROM youtube_subscriptions WHERE id=%s FOR UPDATE", (subscription.id,))
            latest = await get_youtube_subscription(subscription.id)
            if latest is None:
                return subscription
            return await func(latest, *args, **kwargs)
    return wrapped
