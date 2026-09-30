import logging
from decimal import Decimal

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

URL = "https://api.open-meteo.com/v1/forecast"

# Tests replace this with httpx.MockTransport. None = real network.
TRANSPORT: httpx.AsyncBaseTransport | None = None


async def current_weather(
    latitude: Decimal | None, longitude: Decimal | None
) -> tuple[float | None, int | None]:
    """(temp_c, weather_code), or (None, None) on any error. Never raises (11.3)."""
    if latitude is None or longitude is None:
        return None, None
    params = {
        "latitude": str(latitude),
        "longitude": str(longitude),
        "current": "temperature_2m,weather_code",
        "timezone": "America/Bogota",
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.WEATHER_TIMEOUT_SECONDS, transport=TRANSPORT
        ) as client:
            response = await client.get(URL, params=params)
            response.raise_for_status()
            current = response.json()["current"]
            return float(current["temperature_2m"]), int(current["weather_code"])
    except Exception:
        logger.warning("Weather unavailable", exc_info=True)
        return None, None
