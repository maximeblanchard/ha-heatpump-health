"""Plateforme sensor pour HeatPump-Health."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DJU_BASE_TEMP_C,
    DOMAIN,
    ISOLATION_BONNE,
    ISOLATION_MOYENNE,
    ISOLATION_PASSOIRE,
    ISOLATION_TRES_BONNE,
    ISOLATION_TRES_PERFORMANT,
    SIGNAL_UPDATE,
)
from .tracker import HeatPumpHealthTracker

UNIT_YEARS: str = getattr(UnitOfTime, "YEARS", "yr")


@dataclass(frozen=True, kw_only=True)
class HeatPumpHealthSensorDescription(SensorEntityDescription):
    """Description d'un indicateur HeatPump-Health, avec sa fonction de calcul."""

    value_fn: Callable[[HeatPumpHealthTracker], object]
    attributes_fn: Callable[[HeatPumpHealthTracker], dict[str, Any]] | None = None
    exists_fn: Callable[[HeatPumpHealthTracker], bool] = lambda _: True


SENSOR_DESCRIPTIONS: tuple[HeatPumpHealthSensorDescription, ...] = (
    # -- Usure et cycles (toujours créés) -- #
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
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.usure_pourcentage,
    ),
    HeatPumpHealthSensorDescription(
        key="temps_fonctionnement_total",
        translation_key="temps_fonctionnement_total",
        icon="mdi:clock-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda t: t.temps_fonctionnement_total_h,
    ),
    HeatPumpHealthSensorDescription(
        key="temps_fonctionnement_7j",
        translation_key="temps_fonctionnement_7j",
        icon="mdi:clock-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
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
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.duree_moyenne_cycle_7j_min,
    ),
    HeatPumpHealthSensorDescription(
        key="duree_moyenne_cycle_totale",
        translation_key="duree_moyenne_cycle_totale",
        icon="mdi:timer-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
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
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.duree_vie_restante_jours,
    ),
    HeatPumpHealthSensorDescription(
        key="duree_vie_restante_annees",
        translation_key="duree_vie_restante_annees",
        icon="mdi:calendar-clock",
        native_unit_of_measurement=UNIT_YEARS,
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
    # -- Suivi DJU standard (base 18 °C) & efficacité kWh/DJU -- #
    HeatPumpHealthSensorDescription(
        key="dju_aujourdhui",
        translation_key="dju_aujourdhui",
        icon="mdi:thermometer-lines",
        native_unit_of_measurement="DJU",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        exists_fn=lambda t: t.outdoor_temp_sensor is not None,
        value_fn=lambda t: round(t.daily_dju, 2),
        attributes_fn=lambda t: {
            "temperature_base_c": DJU_BASE_TEMP_C,
            "dju_veille": t.dju_veille,
            "dju_7j": t.dju_7j,
        },
    ),
    HeatPumpHealthSensorDescription(
        key="kwh_par_dju_aujourdhui",
        translation_key="kwh_par_dju_aujourdhui",
        icon="mdi:home-thermometer-outline",
        native_unit_of_measurement="kWh/DJU",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=lambda t: t.outdoor_temp_sensor is not None,
        value_fn=lambda t: t.kwh_par_dju_aujourdhui,
        attributes_fn=lambda t: {
            "energie_aujourdhui_kwh": round(t.daily_energy_kwh, 3),
            "dju_aujourdhui": round(t.daily_dju, 2),
            "heures_suivies_aujourdhui": round(t.daily_tracked_hours, 1),
            "temperature_base_c": DJU_BASE_TEMP_C,
        },
    ),
    HeatPumpHealthSensorDescription(
        key="kwh_par_dju_veille",
        translation_key="kwh_par_dju_veille",
        icon="mdi:calendar-arrow-left",
        native_unit_of_measurement="kWh/DJU",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=lambda t: t.outdoor_temp_sensor is not None,
        value_fn=lambda t: t.kwh_par_dju_veille,
        attributes_fn=lambda t: {
            "date_veille": t.date_veille,
            "energie_veille_kwh": t.energie_veille_kwh,
            "dju_veille": t.dju_veille,
        },
    ),
    HeatPumpHealthSensorDescription(
        key="kwh_par_dju_7j",
        translation_key="kwh_par_dju_7j",
        icon="mdi:chart-timeline-variant",
        native_unit_of_measurement="kWh/DJU",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=lambda t: t.outdoor_temp_sensor is not None,
        value_fn=lambda t: t.kwh_par_dju_7j,
        attributes_fn=lambda t: {
            "energie_7j_kwh": t.energie_7j_kwh,
            "dju_7j": t.dju_7j,
            "jours_comptabilises": len(t.dju_history),
        },
    ),
    # -- Suivi DJU réel prenant en compte la température intérieure moyenne -- #
    HeatPumpHealthSensorDescription(
        key="temperature_interieure_moyenne",
        translation_key="temperature_interieure_moyenne",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        exists_fn=lambda t: bool(t.indoor_temp_sensors),
        value_fn=lambda t: t.temperature_interieure_moyenne,
        attributes_fn=lambda t: {
            "capteurs_configures": t.indoor_temp_sensors,
            "capteurs_actifs": t.active_indoor_temp_sensors_count,
        },
    ),
    HeatPumpHealthSensorDescription(
        key="dju_reel_aujourdhui",
        translation_key="dju_reel_aujourdhui",
        icon="mdi:thermometer-auto",
        native_unit_of_measurement="DJU",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        exists_fn=lambda t: t.has_dju_reel_config,
        value_fn=lambda t: round(t.daily_dju_reel, 2),
        attributes_fn=lambda t: {
            "temperature_interieure_moyenne_c": t.temperature_interieure_moyenne,
            "dju_reel_veille": t.dju_reel_veille,
            "dju_reel_7j": t.dju_reel_7j,
        },
    ),
    HeatPumpHealthSensorDescription(
        key="kwh_par_dju_reel_aujourdhui",
        translation_key="kwh_par_dju_reel_aujourdhui",
        icon="mdi:home-thermometer",
        native_unit_of_measurement="kWh/DJU",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=lambda t: t.has_dju_reel_config,
        value_fn=lambda t: t.kwh_par_dju_reel_aujourdhui,
        attributes_fn=lambda t: {
            "energie_aujourdhui_kwh": round(t.daily_energy_kwh, 3),
            "dju_reel_aujourdhui": round(t.daily_dju_reel, 2),
            "temperature_interieure_moyenne_c": t.temperature_interieure_moyenne,
            "heures_suivies_aujourdhui": round(t.daily_tracked_reel_hours, 1),
        },
    ),
    HeatPumpHealthSensorDescription(
        key="kwh_par_dju_reel_veille",
        translation_key="kwh_par_dju_reel_veille",
        icon="mdi:calendar-arrow-left",
        native_unit_of_measurement="kWh/DJU",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=lambda t: t.has_dju_reel_config,
        value_fn=lambda t: t.kwh_par_dju_reel_veille,
        attributes_fn=lambda t: {
            "date_veille": t.date_veille,
            "energie_veille_kwh": t.energie_veille_kwh,
            "dju_reel_veille": t.dju_reel_veille,
        },
    ),
    HeatPumpHealthSensorDescription(
        key="kwh_par_dju_reel_7j",
        translation_key="kwh_par_dju_reel_7j",
        icon="mdi:chart-timeline-variant",
        native_unit_of_measurement="kWh/DJU",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=lambda t: t.has_dju_reel_config,
        value_fn=lambda t: t.kwh_par_dju_reel_7j,
        attributes_fn=lambda t: {
            "energie_7j_kwh": t.energie_reel_7j_kwh,
            "dju_reel_7j": t.dju_reel_7j,
            "jours_comptabilises": t.jours_reel_comptabilises_7j,
        },
    ),
    # -- Déperdition thermique globale H & isolation du bâtiment -- #
    HeatPumpHealthSensorDescription(
        key="deperdition_thermique_h",
        translation_key="deperdition_thermique_h",
        icon="mdi:home-thermometer-outline",
        native_unit_of_measurement="W/K",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        exists_fn=lambda t: t.has_thermal_loss_config,
        value_fn=lambda t: t.deperdition_thermique_h,
        attributes_fn=lambda t: {
            "h_7j": t.h_7j,
            "h_veille": t.h_veille,
            "dju_source": "dju_reel" if t.has_dju_reel_config else "dju_base_18",
            "deperdition_surfacique_w_m2_k": (
                round(t.deperdition_thermique_h / t.surface_m2, 2)
                if (t.deperdition_thermique_h is not None and t.surface_m2)
                else None
            ),
        },
    ),
    HeatPumpHealthSensorDescription(
        key="coefficient_deperdition_g",
        translation_key="coefficient_deperdition_g",
        icon="mdi:home-analytics",
        native_unit_of_measurement="W/(m³·K)",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=lambda t: t.has_insulation_rating_config,
        value_fn=lambda t: t.coefficient_deperdition_g,
        attributes_fn=lambda t: {
            "surface_m2": t.surface_m2,
            "hauteur_plafond_m": t.hauteur_plafond,
            "volume_m3": t.volume_m3,
            "g_7j": t.g_7j,
            "g_veille": t.g_veille,
            "deperdition_thermique_h_w_k": t.deperdition_thermique_h,
        },
    ),
    HeatPumpHealthSensorDescription(
        key="qualite_isolation",
        translation_key="qualite_isolation",
        icon="mdi:shield-home-outline",
        device_class=SensorDeviceClass.ENUM,
        options=[
            ISOLATION_TRES_PERFORMANT,
            ISOLATION_TRES_BONNE,
            ISOLATION_BONNE,
            ISOLATION_MOYENNE,
            ISOLATION_PASSOIRE,
        ],
        exists_fn=lambda t: t.has_insulation_rating_config,
        value_fn=lambda t: t.qualite_isolation,
        attributes_fn=lambda t: {
            "coefficient_g": t.coefficient_deperdition_g,
            "deperdition_thermique_h": t.deperdition_thermique_h,
        },
    ),
    # -- Rendement thermodynamique (créés uniquement selon les options renseignées) -- #
    HeatPumpHealthSensorDescription(
        key="temperature_exterieure",
        translation_key="temperature_exterieure",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=lambda t: t.outdoor_temp_sensor is not None,
        value_fn=lambda t: t.temperature_exterieure,
    ),
    HeatPumpHealthSensorDescription(
        key="humidite_exterieure",
        translation_key="humidite_exterieure",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=lambda t: t.outdoor_humidity_sensor is not None,
        value_fn=lambda t: t.humidite_exterieure,
    ),
    HeatPumpHealthSensorDescription(
        key="mode_fonctionnement",
        translation_key="mode_fonctionnement",
        icon="mdi:heat-pump",
        device_class=SensorDeviceClass.ENUM,
        options=["chauffage", "climatisation", "arret", "inconnu"],
        exists_fn=lambda t: t.climate_entity is not None,
        value_fn=lambda t: t.mode_fonctionnement,
    ),
    HeatPumpHealthSensorDescription(
        key="cop_instantane",
        translation_key="cop_instantane",
        icon="mdi:fire",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=lambda t: t.has_cop_config,
        value_fn=lambda t: t.cop_instantane,
        attributes_fn=lambda t: {
            "cop_nominal": t.cop_nominal,
            "eta_calibre": round(t.eta_heating, 3) if t.eta_heating else None,
            "temperature_interieure_utilisee": t.temperature_interieure_effective,
            "source_temperature_interieure": t.source_temperature_interieure,
            "consigne_climate": t.consigne_climate,
        },
    ),
    HeatPumpHealthSensorDescription(
        key="eer_instantane",
        translation_key="eer_instantane",
        icon="mdi:snowflake",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        exists_fn=lambda t: t.has_eer_config,
        value_fn=lambda t: t.eer_instantane,
        attributes_fn=lambda t: {
            "eer_nominal": t.eer_nominal,
            "eta_calibre": round(t.eta_cooling, 3) if t.eta_cooling else None,
            "temperature_interieure_utilisee": t.temperature_interieure_effective,
            "source_temperature_interieure": t.source_temperature_interieure,
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
        exists_fn=lambda t: t.has_cop_config or t.has_eer_config,
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
    """Crée les entités sensor pertinentes et nettoie les entités optionnelles désactivées."""
    tracker: HeatPumpHealthTracker = hass.data[DOMAIN][entry.entry_id]
    ent_reg = er.async_get(hass)

    active_descriptions: list[HeatPumpHealthSensorDescription] = []
    for description in SENSOR_DESCRIPTIONS:
        if description.exists_fn(tracker):
            active_descriptions.append(description)
        else:
            unique_id = f"{entry.entry_id}_{description.key}"
            if entity_id := ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id):
                ent_reg.async_remove(entity_id)

    async_add_entities(
        HeatPumpHealthSensor(tracker, entry, description) for description in active_descriptions
    )


class HeatPumpHealthSensor(SensorEntity):
    """Un indicateur calculé de la PAC."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: HeatPumpHealthSensorDescription

    def __init__(
        self,
        tracker: HeatPumpHealthTracker,
        entry: ConfigEntry,
        description: HeatPumpHealthSensorDescription,
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
    def extra_state_attributes(self) -> dict[str, Any] | None:
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
