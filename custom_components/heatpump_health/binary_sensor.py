"""Plateforme binary_sensor : état marche/arrêt de la PAC."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_UPDATE
from .tracker import HeatPumpHealthTracker


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    tracker: HeatPumpHealthTracker = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeatPumpHealthRunningBinarySensor(tracker, entry)])


class HeatPumpHealthRunningBinarySensor(BinarySensorEntity):
    """Indique si la PAC est actuellement en cycle de fonctionnement."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "en_fonctionnement"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, tracker: HeatPumpHealthTracker, entry: ConfigEntry) -> None:
        self._tracker = tracker
        self._attr_unique_id = f"{entry.entry_id}_en_fonctionnement"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="HeatPump-Health (intégration personnalisée)",
            model="Suivi d'usure virtuel",
        )
        self._signal = f"{SIGNAL_UPDATE}_{entry.entry_id}"

    @property
    def is_on(self) -> bool:
        return self._tracker.is_running

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._signal, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
