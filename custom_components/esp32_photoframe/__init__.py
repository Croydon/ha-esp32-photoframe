"""The ESP32 PhotoFrame integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import PhotoFrameCoordinator
from .view import async_setup_image_view

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.TEXT,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ESP32 PhotoFrame from a config entry."""
    coordinator = PhotoFrameCoordinator(hass, entry)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services and image serving endpoint (only once)
    if len(hass.data[DOMAIN]) == 1:
        await async_setup_services(hass, coordinator)
        await async_setup_image_view(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)

        # Cancel availability check task
        if coordinator._availability_check_task:
            coordinator._availability_check_task.cancel()
            try:
                await coordinator._availability_check_task
            except Exception:
                pass

    return unload_ok


async def async_setup_services(
    hass: HomeAssistant, coordinator: PhotoFrameCoordinator
) -> None:
    """Set up services for the integration."""
    from .services import async_register_services

    async_register_services(hass, coordinator)
