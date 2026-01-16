"""DataUpdateCoordinator for ESP32 PhotoFrame."""

from __future__ import annotations

import logging
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

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library."""
        # This is only called during initial setup or manual refresh
        # Normal operation relies on push updates from the device
        try:
            # Fetch config data
            config_data = await self._fetch_config()

            # Try to fetch battery data
            battery_data = await self._fetch_battery()

            # If we got battery data, update our cache
            if battery_data:
                self._last_battery_data = battery_data
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
