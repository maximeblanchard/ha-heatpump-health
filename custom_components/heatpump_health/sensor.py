"""Plateforme sensor pour HeatPump-Health."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_UPDATE
from .tracker import HeatPumpHealthTracker


@dataclass(frozen=True, kw_only=True)
class HeatPumpHealthSensorDescription(SensorEntityDescription):
    """Description d'un indicateur HeatPump-Health, avec sa fonction de calcul."""

    value_fn: Callable[[HeatPumpHealthTracker], object]
    attributes_fn: Callable[[HeatPumpHealthTracker], dict] | None = None


SENSOR_DESCRIPTIONS: tuple[HeatPumpHealthSensorDescription, ...] = (
    HeatPumpHealthSensorDescription(
        key="cycles_total",
        translation_key="cycles_total",
        icon="mdi:counter",
        native_unit_of_measurement="cycles",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda t: t.total_cycles,
    ),
    HeatPumpHealthSensorDescription(
        key="usure_pourcentage",
        translation_key="usure_pourcentage",
        icon="mdi:gauge",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.usure_pourcentage,
    ),
    HeatPumpHealthSensorDescription(
        key="temps_fonctionnement_total",
        translation_key="temps_fonctionnement_total",
        icon="mdi:clock-outline",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda t: t.temps_fonctionnement_total_h,
    ),
    HeatPumpHealthSensorDescription(
        key="temps_fonctionnement_7j",
        translation_key="temps_fonctionnement_7j",
        icon="mdi:clock-outline",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.temps_fonctionnement_7j_h,
    ),
    HeatPumpHealthSensorDescription(
        key="cycles_aujourdhui",
        translation_key="cycles_aujourdhui",
        icon="mdi:calendar-today",
        native_unit_of_measurement="cycles",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda t: t.daily_cycles,
    ),
    HeatPumpHealthSensorDescription(
        key="cycles_7j",
        translation_key="cycles_7j",
        icon="mdi:calendar-week",
        native_unit_of_measurement="cycles",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.cycles_7j,
    ),
    HeatPumpHealthSensorDescription(
        key="duree_moyenne_cycle_7j",
        translation_key="duree_moyenne_cycle_7j",
        icon="mdi:timer-outline",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.duree_moyenne_cycle_7j_min,
    ),
    HeatPumpHealthSensorDescription(
        key="duree_moyenne_cycle_totale",
        translation_key="duree_moyenne_cycle_totale",
        icon="mdi:timer-outline",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.duree_moyenne_cycle_totale_min,
    ),
    HeatPumpHealthSensorDescription(
        key="taux_usure_quotidien",
        translation_key="taux_usure_quotidien",
        icon="mdi:trending-up",
        native_unit_of_measurement="cycles/j",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.taux_usure_quotidien_cycles,
    ),
    HeatPumpHealthSensorDescription(
        key="usure_quotidienne",
        translation_key="usure_quotidienne",
        icon="mdi:trending-up",
        native_unit_of_measurement="%/j",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.usure_quotidienne_pourcent,
    ),
    HeatPumpHealthSensorDescription(
        key="duree_vie_restante_jours",
        translation_key="duree_vie_restante_jours",
        icon="mdi:calendar-clock",
        native_unit_of_measurement="d",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.duree_vie_restante_jours,
    ),
    HeatPumpHealthSensorDescription(
        key="duree_vie_restante_annees",
        translation_key="duree_vie_restante_annees",
        icon="mdi:calendar-clock",
        native_unit_of_measurement="an",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.duree_vie_restante_annees,
    ),
    HeatPumpHealthSensorDescription(
        key="indice_usure_7j",
        translation_key="indice_usure_7j",
        icon="mdi:speedometer",
        device_class=SensorDeviceClass.ENUM,
        options=["faible", "moyen", "eleve"],
        value_fn=lambda t: t.indice_usure_7j,
    ),
    # -- Rendement (COP/EER théorique) -- #
    HeatPumpHealthSensorDescription(
        key="temperature_exterieure",
        translation_key="temperature_exterieure",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.temperature_exterieure,
    ),
    HeatPumpHealthSensorDescription(
        key="humidite_exterieure",
        translation_key="humidite_exterieure",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.humidite_exterieure,
    ),
    HeatPumpHealthSensorDescription(
        key="mode_fonctionnement",
        translation_key="mode_fonctionnement",
        icon="mdi:heat-pump",
        device_class=SensorDeviceClass.ENUM,
        options=["chauffage", "climatisation", "arret", "inconnu"],
        value_fn=lambda t: t.mode_fonctionnement,
    ),
    HeatPumpHealthSensorDescription(
        key="cop_instantane",
        translation_key="cop_instantane",
        icon="mdi:fire",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda t: t.cop_instantane,
        attributes_fn=lambda t: {
            "cop_nominal": t.cop_nominal,
            "eta_calibre": round(t.eta_heating, 3) if t.eta_heating else None,
            "temperature_interieure_utilisee": t.temperature_interieure_actuelle,
            "consigne_climate": t.consigne_climate,
        },
    ),
    HeatPumpHealthSensorDescription(
        key="eer_instantane",
        translation_key="eer_instantane",
        icon="mdi:snowflake",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda t: t.eer_instantane,
        attributes_fn=lambda t: {
            "eer_nominal": t.eer_nominal,
            "eta_calibre": round(t.eta_cooling, 3) if t.eta_cooling else None,
            "temperature_interieure_utilisee": t.temperature_interieure_actuelle,
            "consigne_climate": t.consigne_climate,
        },
    ),
    HeatPumpHealthSensorDescription(
        key="puissance_restituee",
        translation_key="puissance_restituee",
        icon="mdi:radiator",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.puissance_restituee_kw,
        attributes_fn=lambda t: {
            "puissance_absorbee_kw": round(t.puissance_absorbee_kw, 3),
            "mode": t.mode_fonctionnement,
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Crée les entités sensor à partir des descriptions ci-dessus."""
    tracker: HeatPumpHealthTracker = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HeatPumpHealthSensor(tracker, entry, description) for description in SENSOR_DESCRIPTIONS
    )


class HeatPumpHealthSensor(SensorEntity):
    """Un indicateur d'usure calculé de la PAC."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: HeatPumpHealthSensorDescription

    def __init__(
        self, tracker: HeatPumpHealthTracker, entry: ConfigEntry, description: HeatPumpHealthSensorDescription
    ) -> None:
        self.entity_description = description
        self._tracker = tracker
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="HeatPump-Health (intégration personnalisée)",
            model="Suivi d'usure virtuel",
        )
        self._signal = f"{SIGNAL_UPDATE}_{entry.entry_id}"

    @property
    def native_value(self):
        return self.entity_description.value_fn(self._tracker)

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self._tracker)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._signal, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
