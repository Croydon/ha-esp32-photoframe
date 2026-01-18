"""Image platform for ESP32 PhotoFrame integration."""

from __future__ import annotations

import logging
from datetime import datetime

import aiohttp
from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PhotoFrameCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the image platform."""
    coordinator: PhotoFrameCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PhotoFrameImage(coordinator, entry)])


class PhotoFrameImage(CoordinatorEntity, ImageEntity):
    """Image entity showing the current displayed image."""

    _attr_has_entity_name = True
    _attr_name = "Current image"

    def __init__(self, coordinator: PhotoFrameCoordinator, entry: ConfigEntry) -> None:
        """Initialize the image entity."""
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._attr_unique_id = f"{entry.entry_id}_current_image"
        self._attr_device_info = coordinator.device_info
        self._attr_image_last_updated = datetime.now()
        self._cached_image: bytes | None = None

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_image_last_updated = datetime.now()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Return image bytes, with caching for offline support."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.coordinator.host}/api/current_image"
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        # Cache successful response
                        self._cached_image = await response.read()
                        _LOGGER.debug("Image fetched and cached successfully")
                        return self._cached_image

                    if response.status == 404:
                        _LOGGER.debug(
                            "No image currently displayed, returning cached image"
                        )
                        return self._cached_image

                    _LOGGER.warning(
                        "Failed to get current image: %s, returning cached image",
                        response.status,
                    )
                    return self._cached_image

        except Exception as err:
            _LOGGER.debug(
                "Device offline or unreachable (%s), returning cached image", err
            )
            return self._cached_image

    @property
    def available(self) -> bool:
        """Return if image is available."""
        return self.coordinator.available
