"""Number platform for ESP32 PhotoFrame."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PhotoFrameCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform."""
    coordinator: PhotoFrameCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        PhotoFrameRotationIntervalNumber(coordinator, entry),
    ]

    async_add_entities(entities)


class PhotoFrameRotationIntervalNumber(CoordinatorEntity, NumberEntity):
    """Rotation interval number for PhotoFrame."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = 1440
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: PhotoFrameCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_rotation_interval"
        self._attr_name = "Rotation interval"
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.available

    @property
    def native_value(self) -> float | None:
        """Return the current rotation interval in minutes."""
        config = self.coordinator.data.get("config", {})
        seconds = config.get("rotate_interval", 3600)
        return seconds / 60

    async def async_set_native_value(self, value: float) -> None:
        """Set the rotation interval (convert minutes to seconds)."""
        seconds = int(value * 60)
        await self.coordinator.async_set_config({"rotate_interval": seconds})
