"""Image serving view for ESP32 PhotoFrame."""

from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN, IMAGE_ENDPOINT_PATH

_LOGGER = logging.getLogger(__name__)


class PhotoFrameImageView(HomeAssistantView):
    """View to serve images to the photoframe."""

    url = IMAGE_ENDPOINT_PATH
    name = "api:esp32_photoframe:image"
    requires_auth = False  # Photoframe doesn't support auth

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Serve the configured image."""
        # Get the configured media entity from integration data
        # For now, we'll look for a configured entity in the integration options

        # Try to find the first photoframe integration
        photoframe_entries = [
            entry for entry in self.hass.config_entries.async_entries(DOMAIN)
        ]

        if not photoframe_entries:
            _LOGGER.error("No PhotoFrame integration configured")
            return web.Response(status=404, text="No PhotoFrame integration configured")

        # Get the first entry's options
        entry = photoframe_entries[0]
        options = entry.options or {}

        # Get the configured media entity
        media_entity_id = options.get("media_entity_id")

        if not media_entity_id:
            _LOGGER.warning("No media entity configured for PhotoFrame image serving")
            return web.Response(status=404, text="No media entity configured")

        # Get the entity state
        state = self.hass.states.get(media_entity_id)
        if state is None:
            _LOGGER.error("Media entity %s not found", media_entity_id)
            return web.Response(status=404, text=f"Entity {media_entity_id} not found")

        # Handle different entity types
        if state.domain == "camera":
            # Get camera image
            from homeassistant.components.camera import async_get_image

            try:
                image = await async_get_image(self.hass, media_entity_id)
                return web.Response(
                    body=image.content,
                    content_type=image.content_type,
                    headers={
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                        "Expires": "0",
                    },
                )
            except Exception as err:
                _LOGGER.error(
                    "Error getting image from camera %s: %s", media_entity_id, err
                )
                return web.Response(status=500, text=f"Error getting image: {err}")

        elif state.domain == "image":
            # Get image entity's image
            try:
                # Image entities store their image URL in entity_picture attribute
                entity_picture = state.attributes.get("entity_picture")
                if not entity_picture:
                    return web.Response(status=404, text="Image entity has no picture")

                # Fetch the image from the entity_picture URL
                from homeassistant.helpers.aiohttp_client import async_get_clientsession

                session = async_get_clientsession(self.hass)

                # Build full URL if it's a relative path
                if entity_picture.startswith("/"):
                    # It's a local URL, fetch from HA
                    base_url = self.hass.config.api.base_url
                    full_url = f"{base_url}{entity_picture}"
                else:
                    full_url = entity_picture

                async with session.get(full_url) as response:
                    if response.status != 200:
                        return web.Response(
                            status=response.status, text="Failed to fetch image"
                        )

                    image_data = await response.read()
                    content_type = response.headers.get("Content-Type", "image/jpeg")

                    return web.Response(
                        body=image_data,
                        content_type=content_type,
                        headers={
                            "Cache-Control": "no-cache, no-store, must-revalidate",
                            "Pragma": "no-cache",
                            "Expires": "0",
                        },
                    )
            except Exception as err:
                _LOGGER.error(
                    "Error getting image from entity %s: %s", media_entity_id, err
                )
                return web.Response(status=500, text=f"Error getting image: {err}")

        else:
            _LOGGER.error("Entity %s is not a camera or image entity", media_entity_id)
            return web.Response(
                status=400,
                text=f"Entity {media_entity_id} is not a camera or image entity",
            )


class PhotoFrameBatteryView(HomeAssistantView):
    """View to receive battery data from the photoframe."""

    url = "/api/esp32_photoframe/battery"
    name = "api:esp32_photoframe:battery"
    requires_auth = False  # Photoframe doesn't support auth

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Receive battery data from photoframe."""
        try:
            data = await request.json()
            battery_level = data.get("battery_level")
            battery_voltage = data.get("battery_voltage")
            charging = data.get("charging")
            usb_connected = data.get("usb_connected")
            battery_connected = data.get("battery_connected")

            _LOGGER.info(
                "Received battery push: level=%s%%, voltage=%smV, charging=%s, usb=%s, battery=%s",
                battery_level,
                battery_voltage,
                charging,
                usb_connected,
                battery_connected,
            )

            # Update coordinator data for all photoframe integrations
            # Find the coordinator and update its data
            for entry_id, coordinator in self.hass.data.get(DOMAIN, {}).items():
                if hasattr(coordinator, "data"):
                    # Update battery data in coordinator
                    coordinator.data["battery"] = {
                        "battery_level": battery_level,
                        "battery_voltage": battery_voltage,
                        "charging": charging,
                        "usb_connected": usb_connected,
                        "battery_connected": battery_connected,
                    }
                    # Update last update time for availability tracking
                    from datetime import datetime

                    coordinator._last_update_time = datetime.now()
                    # Notify listeners of the update
                    coordinator.async_set_updated_data(coordinator.data)
                    break

            return web.Response(status=200, text="OK")
        except Exception as err:
            _LOGGER.error("Error processing battery data: %s", err)
            return web.Response(status=400, text=f"Error: {err}")


async def async_setup_image_view(hass: HomeAssistant) -> None:
    """Set up the image serving view."""
    hass.http.register_view(PhotoFrameImageView(hass))
    hass.http.register_view(PhotoFrameBatteryView(hass))
    _LOGGER.info(
        "Registered PhotoFrame image serving endpoint at %s", IMAGE_ENDPOINT_PATH
    )
    _LOGGER.info(
        "Registered PhotoFrame battery endpoint at /api/esp32_photoframe/battery"
    )
