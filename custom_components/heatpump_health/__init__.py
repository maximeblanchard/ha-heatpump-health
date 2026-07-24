"""L'intégration HeatPump-Health."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .tracker import HeatPumpHealthTracker

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialise l'intégration à partir d'une entrée de configuration."""
    tracker = HeatPumpHealthTracker(hass, entry)
    await tracker.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = tracker

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge une entrée de configuration."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        tracker: HeatPumpHealthTracker = hass.data[DOMAIN].pop(entry.entry_id)
        await tracker.async_unload()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recharge l'entrée quand les options changent (nouveaux seuils, etc.)."""
    await hass.config_entries.async_reload(entry.entry_id)
