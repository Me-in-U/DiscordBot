from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from util.db import (
    DB_SCHEMA_VERSION,
    close_db_pool,
    get_schema_version,
    run_schema_migrations,
)
from util.logging_utils import configure_logging

logger = logging.getLogger(__name__)


async def main() -> None:
    configure_logging()
    logger.info("Starting DB schema migration: target_version=%s", DB_SCHEMA_VERSION)
    try:
        await run_schema_migrations()
        current_version = await get_schema_version()
        logger.info("DB schema migration complete: current_version=%s", current_version)
    finally:
        await close_db_pool()


if __name__ == "__main__":
    asyncio.run(main())
