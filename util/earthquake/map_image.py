from __future__ import annotations

import asyncio
import io
import logging
import math
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont

from util.earthquake.jma_eew import JmaEewEvent


EARTHQUAKE_MAP_FILENAME = "earthquake-map.png"
EARTHQUAKE_MAP_WIDTH = 640
EARTHQUAKE_MAP_HEIGHT = 360
EARTHQUAKE_MAP_ZOOM = 7
OSM_TILE_SIZE = 256
OSM_TILE_CACHE_SECONDS = 7 * 24 * 60 * 60
OSM_TILE_URL = "https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
OSM_USER_AGENT = (
    "DiscordBot-EarthquakeMap/1.0 "
    "(+https://github.com/Me-in-U/DiscordBot)"
)
OSM_TILE_CACHE_DIR = (
    Path(tempfile.gettempdir()) / "discordbot-earthquake-osm-tiles"
)

logger = logging.getLogger(__name__)
LoadTile = Callable[[int, int, int], Awaitable[bytes]]


async def build_jma_eew_map_file(
    event: JmaEewEvent,
    *,
    load_tile: LoadTile | None = None,
) -> discord.File | None:
    if event.latitude is None or event.longitude is None:
        return None

    try:
        requests = _tile_requests(
            event.latitude,
            event.longitude,
            zoom=EARTHQUAKE_MAP_ZOOM,
            width=EARTHQUAKE_MAP_WIDTH,
            height=EARTHQUAKE_MAP_HEIGHT,
        )
        if load_tile is None:
            tile_bytes = await _load_default_tiles(requests)
        else:
            tile_bytes = await asyncio.gather(
                *(
                    load_tile(EARTHQUAKE_MAP_ZOOM, normalized_x, tile_y)
                    for _, tile_y, normalized_x in requests
                )
            )
        image_bytes = await asyncio.to_thread(
            _render_map,
            event.latitude,
            event.longitude,
            requests,
            tile_bytes,
        )
    except (
        aiohttp.ClientError,
        asyncio.TimeoutError,
        OSError,
        ValueError,
    ):
        logger.warning(
            "지진 추정 진원 지도 생성 실패: event=%s serial=%s",
            event.event_id,
            event.serial,
            exc_info=True,
        )
        return None

    return discord.File(
        io.BytesIO(image_bytes),
        filename=EARTHQUAKE_MAP_FILENAME,
    )


def build_openstreetmap_url(event: JmaEewEvent) -> str | None:
    if event.latitude is None or event.longitude is None:
        return None
    return (
        "https://www.openstreetmap.org/"
        f"?mlat={event.latitude:.4f}&mlon={event.longitude:.4f}"
        f"#map={EARTHQUAKE_MAP_ZOOM}/{event.latitude:.4f}/{event.longitude:.4f}"
    )


async def _load_default_tiles(
    requests: list[tuple[int, int, int]],
) -> list[bytes]:
    timeout = aiohttp.ClientTimeout(total=15, connect=5)
    async with aiohttp.ClientSession(
        timeout=timeout,
        headers={"User-Agent": OSM_USER_AGENT},
    ) as session:
        return await asyncio.gather(
            *(
                _load_osm_tile(
                    session,
                    EARTHQUAKE_MAP_ZOOM,
                    normalized_x,
                    tile_y,
                )
                for _, tile_y, normalized_x in requests
            )
        )


async def _load_osm_tile(
    session: aiohttp.ClientSession,
    zoom: int,
    tile_x: int,
    tile_y: int,
) -> bytes:
    cache_path = (
        OSM_TILE_CACHE_DIR
        / str(zoom)
        / str(tile_x)
        / f"{tile_y}.png"
    )
    cached = await _read_cached_tile(cache_path)
    if cached is not None and cached[1]:
        return cached[0]

    url = OSM_TILE_URL.format(zoom=zoom, x=tile_x, y=tile_y)
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                raise ValueError(f"OSM tile content type is {content_type!r}")
            tile_bytes = await response.read()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        if cached is not None:
            return cached[0]
        raise

    await asyncio.to_thread(
        cache_path.parent.mkdir,
        parents=True,
        exist_ok=True,
    )
    await asyncio.to_thread(cache_path.write_bytes, tile_bytes)
    return tile_bytes


async def _read_cached_tile(
    cache_path: Path,
) -> tuple[bytes, bool] | None:
    try:
        stat = await asyncio.to_thread(cache_path.stat)
        tile_bytes = await asyncio.to_thread(cache_path.read_bytes)
    except OSError:
        return None
    is_fresh = time.time() - stat.st_mtime <= OSM_TILE_CACHE_SECONDS
    return tile_bytes, is_fresh


def _tile_requests(
    latitude: float,
    longitude: float,
    *,
    zoom: int,
    width: int,
    height: int,
) -> list[tuple[int, int, int]]:
    center_x, center_y = _world_pixel(latitude, longitude, zoom)
    left = center_x - width / 2
    top = center_y - height / 2
    first_x = math.floor(left / OSM_TILE_SIZE)
    last_x = math.floor((left + width - 1) / OSM_TILE_SIZE)
    first_y = math.floor(top / OSM_TILE_SIZE)
    last_y = math.floor((top + height - 1) / OSM_TILE_SIZE)
    tile_count = 2**zoom

    requests = []
    for tile_y in range(first_y, last_y + 1):
        if tile_y < 0 or tile_y >= tile_count:
            continue
        for tile_x in range(first_x, last_x + 1):
            requests.append((tile_x, tile_y, tile_x % tile_count))
    return requests


def _render_map(
    latitude: float,
    longitude: float,
    requests: list[tuple[int, int, int]],
    tile_bytes: list[bytes],
) -> bytes:
    center_x, center_y = _world_pixel(
        latitude,
        longitude,
        EARTHQUAKE_MAP_ZOOM,
    )
    left = center_x - EARTHQUAKE_MAP_WIDTH / 2
    top = center_y - EARTHQUAKE_MAP_HEIGHT / 2
    canvas = Image.new(
        "RGB",
        (EARTHQUAKE_MAP_WIDTH, EARTHQUAKE_MAP_HEIGHT),
        "white",
    )

    for (raw_x, tile_y, _), content in zip(
        requests,
        tile_bytes,
        strict=True,
    ):
        with Image.open(io.BytesIO(content)) as tile:
            canvas.paste(
                tile.convert("RGB"),
                (
                    round(raw_x * OSM_TILE_SIZE - left),
                    round(tile_y * OSM_TILE_SIZE - top),
                ),
            )

    draw = ImageDraw.Draw(canvas, "RGBA")
    marker_x = EARTHQUAKE_MAP_WIDTH // 2
    marker_y = EARTHQUAKE_MAP_HEIGHT // 2
    draw.polygon(
        [
            (marker_x, marker_y + 15),
            (marker_x - 9, marker_y - 4),
            (marker_x + 9, marker_y - 4),
        ],
        fill=(207, 45, 45, 255),
    )
    draw.ellipse(
        (marker_x - 11, marker_y - 17, marker_x + 11, marker_y + 5),
        fill=(207, 45, 45, 255),
        outline=(255, 255, 255, 255),
        width=2,
    )
    draw.ellipse(
        (marker_x - 3, marker_y - 9, marker_x + 3, marker_y - 3),
        fill=(255, 255, 255, 255),
    )

    attribution = "© OpenStreetMap contributors"
    attribution_font = ImageFont.load_default(size=12)
    text_box = draw.textbbox(
        (0, 0),
        attribution,
        font=attribution_font,
    )
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    padding = 4
    attribution_x = EARTHQUAKE_MAP_WIDTH - text_width - padding * 2
    attribution_y = EARTHQUAKE_MAP_HEIGHT - text_height - padding * 2
    draw.rectangle(
        (
            attribution_x,
            attribution_y,
            EARTHQUAKE_MAP_WIDTH,
            EARTHQUAKE_MAP_HEIGHT,
        ),
        fill=(255, 255, 255, 210),
    )
    draw.text(
        (attribution_x + padding, attribution_y + padding),
        attribution,
        fill=(20, 20, 20, 255),
        font=attribution_font,
    )

    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _world_pixel(
    latitude: float,
    longitude: float,
    zoom: int,
) -> tuple[float, float]:
    limited_latitude = max(min(float(latitude), 85.05112878), -85.05112878)
    normalized_longitude = ((float(longitude) + 180) % 360) - 180
    scale = OSM_TILE_SIZE * (2**zoom)
    x = (normalized_longitude + 180) / 360 * scale
    latitude_radians = math.radians(limited_latitude)
    y = (
        1
        - math.asinh(math.tan(latitude_radians)) / math.pi
    ) / 2 * scale
    return x, y
