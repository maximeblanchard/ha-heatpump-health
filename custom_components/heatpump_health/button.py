"""Plateforme button : réinitialisation manuelle des compteurs d'usure."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .tracker import HeatPumpHealthTracker


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    tracker: HeatPumpHealthTracker = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeatPumpHealthResetButton(tracker, entry)])


class HeatPumpHealthResetButton(ButtonEntity):
    """Bouton pour remettre à zéro les compteurs (ex: remplacement du compresseur)."""

    _attr_has_entity_name = True
    _attr_translation_key = "reset_compteurs"
    _attr_icon = "mdi:restart-alert"

    def __init__(self, tracker: HeatPumpHealthTracker, entry: ConfigEntry) -> None:
        self._tracker = tracker
        self._attr_unique_id = f"{entry.entry_id}_reset"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="HeatPump-Health (intégration personnalisée)",
            model="Suivi d'usure virtuel",
        )

    async def async_press(self) -> None:
        await self._tracker.async_reset()
