"""DataUpdateCoordinator for ESP32 PhotoFrame."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import API_BATTERY, API_CONFIG, API_DISPLAY_IMAGE, DOMAIN

_LOGGER = logging.getLogger(__name__)


class PhotoFrameCoordinator(DataUpdateCoordinator):
    """Class to manage fetching PhotoFrame data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.host = entry.data[CONF_HOST]
        self.session = async_get_clientsession(hass)
        self.entry = entry

        # Store last known battery data to preserve when device is asleep
        self._last_battery_data = {}

        # Track last update time for availability
        self._last_update_time: datetime | None = None
        self._availability_timeout = timedelta(minutes=2)  # Device offline after 2 min
        self._availability_check_interval = timedelta(
            minutes=1
        )  # Check every 5 min when offline
        self._availability_check_task: asyncio.Task | None = None

        # Centralized device info for all entities
        self.device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "ESP32-S3-PhotoPainter",
            "manufacturer": "Waveshare",
            "model": "ESP32-S3-PhotoPainter",
        }

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # No automatic polling - rely on push updates from device
            update_interval=None,
        )

        # Start availability monitoring task
        self._availability_check_task = hass.async_create_task(
            self._availability_check_loop()
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library."""
        # This is only called during initial setup or manual refresh
        # Normal operation relies on push updates from the device
        try:
            # Fetch config data
            config_data = await self._fetch_config()

            # Try to fetch battery data
            battery_data = await self._fetch_battery()

            # If we got battery data, update our cache and timestamp
            if battery_data:
                self._last_battery_data = battery_data
                self._last_update_time = datetime.now()
            # Otherwise, use the last known battery data
            else:
                battery_data = self._last_battery_data

            return {
                "config": config_data,
                "battery": battery_data,
            }
        except aiohttp.ClientError as err:
            # If we have cached data, use it instead of failing
            if self._last_battery_data:
                _LOGGER.warning("Failed to fetch data, using cached values: %s", err)
                return {
                    "config": {},
                    "battery": self._last_battery_data,
                }
            raise UpdateFailed(f"Error communicating with API: {err}")

    async def _fetch_config(self) -> dict[str, Any]:
        """Fetch config from photoframe."""
        try:
            async with self.session.get(
                f"{self.host}{API_CONFIG}",
                timeout=aiohttp.ClientTimeout(
                    total=60
                ),  # Long timeout for image processing
            ) as response:
                if response.status != 200:
                    raise UpdateFailed(f"HTTP {response.status}")
                return await response.json()
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Failed to fetch config: {err}")

    async def _fetch_battery(self) -> dict[str, Any]:
        """Fetch battery data from photoframe."""
        try:
            async with self.session.get(
                f"{self.host}{API_BATTERY}",
                timeout=aiohttp.ClientTimeout(
                    total=60
                ),  # Long timeout for image processing
            ) as response:
                if response.status != 200:
                    _LOGGER.debug("Battery endpoint returned HTTP %s", response.status)
                    return {}
                return await response.json()
        except aiohttp.ClientError as err:
            _LOGGER.debug("Failed to fetch battery data: %s", err)
            return {}

    async def async_set_config(self, config: dict[str, Any]) -> bool:
        """Set configuration on the photoframe."""
        try:
            async with self.session.post(
                f"{self.host}{API_CONFIG}",
                json=config,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    _LOGGER.error("Failed to set config: HTTP %s", response.status)
                    return False
                await self.async_request_refresh()
                return True
        except aiohttp.ClientError as err:
            _LOGGER.error("Failed to set config: %s", err)
            return False

    async def async_display_image(self, image_data: bytes) -> bool:
        """Send image to photoframe for display."""
        try:
            async with self.session.post(
                f"{self.host}{API_DISPLAY_IMAGE}",
                data=image_data,
                headers={"Content-Type": "image/jpeg"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    _LOGGER.error("Failed to display image: HTTP %s", response.status)
                    return False
                return True
        except aiohttp.ClientError as err:
            _LOGGER.error("Failed to display image: %s", err)
            return False

    @property
    def available(self) -> bool:
        """Return if device is available based on last update time."""
        if self._last_update_time is None:
            return False

        time_since_update = datetime.now() - self._last_update_time
        return time_since_update < self._availability_timeout

    async def _availability_check_loop(self) -> None:
        """Periodically check device availability when offline."""
        while True:
            try:
                # Wait for the check interval
                await asyncio.sleep(self._availability_check_interval.total_seconds())

                # Only check if device is currently unavailable
                if not self.available:
                    _LOGGER.debug("Device unavailable, checking if it's back online")
                    try:
                        # Try to refresh data to check if device is back
                        await self.async_request_refresh()
                        if self.available:
                            _LOGGER.info("Device is back online")
                    except Exception as err:
                        _LOGGER.debug("Availability check failed: %s", err)
            except asyncio.CancelledError:
                _LOGGER.debug("Availability check task cancelled")
                break
            except Exception as err:
                _LOGGER.error("Error in availability check loop: %s", err)
                # Continue the loop even if there's an error
                await asyncio.sleep(60)  # Wait a bit before retrying
