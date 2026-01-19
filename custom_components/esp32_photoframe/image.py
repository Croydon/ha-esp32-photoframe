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
        self._attr_unique_id = f"{entry.entry_id}_image"
        self._attr_name = "Current image"
        self._attr_device_info = coordinator.device_info
        self._attr_image_last_updated = datetime.now()

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Only update if we actually have a new image
        # This prevents clearing the cache during rotation when the device hasn't finished yet
        if self.coordinator._cached_image:
            # Update timestamp to trigger image refresh in HA frontend
            self._attr_image_last_updated = datetime.now()
            # Clear cached image URL to force HA to refetch
            self._cached_image_content = None

        super()._handle_coordinator_update()
        # Explicitly notify HA to update the entity state
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        """Return image bytes, with caching for offline support."""
        # If we have a cached image, return it immediately
        # Don't fetch on every call to avoid disrupting the image during rotation
        # The cache will be updated by coordinator refresh after rotation completes
        if self.coordinator._cached_image:
            return self.coordinator._cached_image

        # Only fetch if we don't have a cached image yet (initial load)
        await self.coordinator.fetch_current_image()
        return self.coordinator._cached_image

    @property
    def available(self) -> bool:
        """Image is available if device is online or we have a cached image."""
        # Available if device is online
        if self.coordinator.last_update_success:
            return True
        # Or if we have a cached image (for offline support)
        return self.coordinator._cached_image is not None
