from collections.abc import Iterable
from typing import Protocol
import asyncio
import logging

logger = logging.getLogger(__name__)

def supervise_loop_tasks(owner, task_names):
    for name in task_names:
        loop = getattr(owner, name)
        async def recover(cog, error, *, target=loop):
            logger.error("Background loop failed; restarting: %s", target.coro.__name__, exc_info=(type(error), error, error.__traceback__))
            await asyncio.sleep(5)
            target.restart()
        loop.error(recover)


class LoopTask(Protocol):
    def is_running(self) -> bool: ...

    def start(self) -> None: ...

    def cancel(self) -> None: ...


def _get_loop_task(owner: object, task_name: str) -> LoopTask:
    task = getattr(owner, task_name)
    return task


def start_loop_tasks(owner: object, task_names: Iterable[str]) -> None:
    for task_name in task_names:
        task = _get_loop_task(owner, task_name)
        if task.is_running():
            continue
        task.start()


def cancel_loop_tasks(owner: object, task_names: Iterable[str]) -> None:
    for task_name in task_names:
        task = _get_loop_task(owner, task_name)
        if not task.is_running():
            continue
        task.cancel()
