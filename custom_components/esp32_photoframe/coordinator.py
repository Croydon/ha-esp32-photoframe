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

from .const import (
    API_BATTERY,
    API_CONFIG,
    API_DISPLAY_IMAGE,
    API_OTA_STATUS,
    API_SENSOR,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class PhotoFrameCoordinator(DataUpdateCoordinator):
    """Class to manage fetching PhotoFrame data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.host = entry.data[CONF_HOST]
        self.session = async_get_clientsession(hass)
        self.entry = entry

        # Will be resolved async in first refresh
        self.resolved_ip: str | None = None

        # Store last known battery data to preserve when device is asleep
        self._last_battery_data = {}

        # Store last known OTA data to preserve when device is asleep
        self._last_ota_data = {}

        # Store last known sensor data to preserve when device is asleep
        self._last_sensor_data = {}

        # Store cached image uploaded by device (for deep sleep support)
        self._cached_image: bytes | None = None

        # Track device online/offline state (set by explicit notifications)
        self._device_online: bool = True

        # Track last update time for availability
        self._last_update_time: datetime | None = None
        self._availability_timeout = timedelta(minutes=2)  # Device offline after 2 min
        self._availability_check_interval = timedelta(
            minutes=1
        )  # Check periodically when offline
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
            # Poll every 10 minutes for battery and OTA updates
            # Device will be marked offline after 2 minutes of no response
            update_interval=timedelta(minutes=10),
        )

        # Start availability monitoring task
        self._availability_check_task = hass.async_create_task(
            self._availability_check_loop()
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library."""
        # Called periodically and when device sends notification
        # Notifications provide immediate updates, polling provides regular battery/OTA checks
        try:
            # Resolve hostname to IP if not already done (for mDNS support)
            if self.resolved_ip is None:
                import socket

                hostname = (
                    self.host.replace("http://", "")
                    .replace("https://", "")
                    .split(":")[0]
                )
                try:
                    # Use asyncio to avoid blocking
                    loop = asyncio.get_event_loop()
                    self.resolved_ip = await loop.run_in_executor(
                        None, socket.gethostbyname, hostname
                    )
                    _LOGGER.info("Resolved %s to IP %s", hostname, self.resolved_ip)
                except socket.gaierror:
                    self.resolved_ip = hostname  # Use as-is if resolution fails
                    _LOGGER.warning("Failed to resolve %s, using as-is", hostname)

            # Try to fetch config data (may fail if device is asleep)
            _LOGGER.debug("Fetching config data from %s", self.host)
            config_data = await self._fetch_config()
            _LOGGER.debug("Config data fetched: %s", bool(config_data))

            # Try to fetch battery data
            _LOGGER.debug("Fetching battery data from %s", self.host)
            battery_data = await self._fetch_battery()

            # If we got battery data, update our cache and timestamp
            if battery_data:
                _LOGGER.debug(
                    "Battery data fetched successfully: %s%%",
                    battery_data.get("battery_level"),
                )
                self._last_battery_data = battery_data
                self._last_update_time = datetime.now()
            # Otherwise, use the last known battery data
            else:
                _LOGGER.debug("Using cached battery data")
                battery_data = self._last_battery_data

            # Try to fetch OTA data
            _LOGGER.debug("Fetching OTA status from %s", self.host)
            ota_data = await self._fetch_ota_status()

            # If we got OTA data, update our cache
            if ota_data:
                _LOGGER.debug(
                    "OTA data fetched successfully: %s", ota_data.get("current_version")
                )
                self._last_ota_data = ota_data
            # Otherwise, use the last known OTA data
            else:
                _LOGGER.debug("Using cached OTA data")
                ota_data = self._last_ota_data

            # Try to fetch sensor data
            _LOGGER.debug("Fetching sensor data from %s", self.host)
            sensor_data = await self._fetch_sensor()

            # If we got sensor data, update our cache
            if sensor_data:
                _LOGGER.debug(
                    "Sensor data fetched successfully: %.1f°C, %.1f%%",
                    sensor_data.get("temperature", 0),
                    sensor_data.get("humidity", 0),
                )
                self._last_sensor_data = sensor_data
            # Otherwise, use the last known sensor data
            else:
                _LOGGER.debug("Using cached sensor data")
                sensor_data = self._last_sensor_data

            # Try to fetch current image (may fail if device is asleep)
            _LOGGER.debug("Fetching current image from %s", self.host)
            try:
                await self.fetch_current_image()
            except (aiohttp.ClientError, UpdateFailed):
                # Keep existing cached image if fetch fails
                _LOGGER.debug("Failed to fetch current image, keeping cached version")

            return {
                "config": config_data,
                "battery": battery_data,
                "ota": ota_data,
                "sensor": sensor_data,
            }
        except (aiohttp.ClientError, UpdateFailed) as err:
            # Device is likely offline/asleep - use cached data instead of failing
            if self._last_battery_data or self._last_ota_data:
                _LOGGER.debug("Device offline/asleep, using cached values: %s", err)
                return {
                    "config": {},
                    "battery": self._last_battery_data,
                    "ota": self._last_ota_data,
                    "sensor": self._last_sensor_data,
                }
            # Only fail if we have no cached data at all (first time setup)
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

    async def _fetch_ota_status(self) -> dict[str, Any]:
        """Fetch OTA status data from photoframe."""
        try:
            async with self.session.get(
                f"{self.host}{API_OTA_STATUS}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    _LOGGER.debug(
                        "OTA status endpoint returned HTTP %s", response.status
                    )
                    return {}
                data = await response.json()
                # Extract the fields we need from the OTA status response
                return {
                    "current_version": data.get("current_version", ""),
                    "latest_version": data.get("latest_version", ""),
                    "state": data.get("state", "idle"),
                }
        except aiohttp.ClientError as err:
            _LOGGER.debug("Failed to fetch OTA status: %s", err)
            return {}

    async def _fetch_sensor(self) -> dict[str, Any]:
        """Fetch sensor data (temperature/humidity) from photoframe."""
        try:
            async with self.session.get(
                f"{self.host}{API_SENSOR}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    _LOGGER.debug("Sensor endpoint returned HTTP %s", response.status)
                    return {}
                data = await response.json()
                # Only return data if sensor is available and read was successful
                if data.get("status") == "ok":
                    return {
                        "temperature": data.get("temperature"),
                        "humidity": data.get("humidity"),
                        "available": True,
                    }
                else:
                    _LOGGER.debug(
                        "Sensor not available or read error: %s", data.get("status")
                    )
                    return {"available": False}
        except aiohttp.ClientError as err:
            _LOGGER.debug("Failed to fetch sensor data: %s", err)
            return {}

    async def fetch_current_image(self) -> None:
        """Fetch and cache the current image from the device."""
        try:
            from .const import API_CURRENT_IMAGE

            async with self.session.get(
                f"{self.host}{API_CURRENT_IMAGE}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    self._cached_image = await response.read()
                    _LOGGER.debug(
                        "Fetched and cached current image (%d bytes)",
                        len(self._cached_image),
                    )
                elif response.status == 404:
                    _LOGGER.debug("No image currently displayed on device")
                    # Don't clear cache - keep showing last known image
                else:
                    _LOGGER.debug(
                        "Failed to fetch current image: HTTP %s", response.status
                    )
                    # Don't clear cache - keep showing last known image
        except aiohttp.ClientError as err:
            _LOGGER.debug("Failed to fetch current image: %s", err)
            # Don't clear cache - preserve last known image for offline support

    async def async_set_config(self, config: dict[str, Any]) -> bool:
        """Set configuration on the photoframe (partial update using PATCH)."""
        try:
            async with self.session.patch(
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
        """Return if device is available based on explicit online/offline state and timeout.

        Device is considered available if:
        1. Explicitly marked as online (_device_online = True), AND
        2. Either has recent successful update OR within timeout period
        """
        # If device explicitly notified offline, it's unavailable
        if not self._device_online:
            return False

        # If no update time recorded yet, unavailable
        if self._last_update_time is None:
            return False

        # Check if within timeout period
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
                # Wait before retrying to avoid tight loop on persistent errors
                await asyncio.sleep(60)
