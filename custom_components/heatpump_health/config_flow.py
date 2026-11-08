"""Config flow pour HeatPump-Health."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CEILING_HEIGHT,
    CONF_CLIMATE_ENTITY,
    CONF_COP_NOMINAL,
    CONF_DELAY_OFF,
    CONF_EER_NOMINAL,
    CONF_INDOOR_TEMP_SENSORS,
    CONF_INITIAL_CYCLES,
    CONF_INSTALL_DATE,
    CONF_KW_CHAUD,
    CONF_KW_FROID,
    CONF_MAX_CYCLES,
    CONF_OUTDOOR_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_POWER_SENSOR,
    CONF_SEUIL_ELEVE,
    CONF_SEUIL_FAIBLE,
    CONF_SURFACE_M2,
    CONF_THRESHOLD_W,
    DEFAULT_CEILING_HEIGHT,
    DEFAULT_DELAY_OFF,
    DEFAULT_INITIAL_CYCLES,
    DEFAULT_MAX_CYCLES,
    DEFAULT_SEUIL_ELEVE,
    DEFAULT_SEUIL_FAIBLE,
    DEFAULT_THRESHOLD_W,
    DOMAIN,
)

CONF_NAME = "name"


def _number(unit: str, minimum: float = 0, maximum: float = 200000, step: float = 1) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


def _suggest(defaults: dict[str, Any], key: str) -> dict[str, Any]:
    value = defaults.get(key)
    if value is None or value == []:
        return {}
    return {"description": {"suggested_value": value}}


def _performance_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Schéma partagé entre l'étape d'installation et les options (rendement, DJU & isolation)."""
    return vol.Schema(
        {
            vol.Optional(CONF_CLIMATE_ENTITY, **_suggest(defaults, CONF_CLIMATE_ENTITY)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Optional(
                CONF_INDOOR_TEMP_SENSORS, **_suggest(defaults, CONF_INDOOR_TEMP_SENSORS)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=True)
            ),
            vol.Optional(
                CONF_OUTDOOR_TEMP_SENSOR, **_suggest(defaults, CONF_OUTDOOR_TEMP_SENSOR)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_OUTDOOR_HUMIDITY_SENSOR, **_suggest(defaults, CONF_OUTDOOR_HUMIDITY_SENSOR)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Optional(CONF_COP_NOMINAL, **_suggest(defaults, CONF_COP_NOMINAL)): _number(
                "", minimum=1, maximum=10, step=0.01
            ),
            vol.Optional(CONF_EER_NOMINAL, **_suggest(defaults, CONF_EER_NOMINAL)): _number(
                "", minimum=1, maximum=10, step=0.01
            ),
            vol.Optional(CONF_KW_CHAUD, **_suggest(defaults, CONF_KW_CHAUD)): _number(
                "kW", minimum=0.5, maximum=100, step=0.1
            ),
            vol.Optional(CONF_KW_FROID, **_suggest(defaults, CONF_KW_FROID)): _number(
                "kW", minimum=0.5, maximum=100, step=0.1
            ),
            vol.Optional(CONF_SURFACE_M2, **_suggest(defaults, CONF_SURFACE_M2)): _number(
                "m²", minimum=10, maximum=2000, step=1
            ),
            vol.Optional(
                CONF_CEILING_HEIGHT,
                default=defaults.get(CONF_CEILING_HEIGHT, DEFAULT_CEILING_HEIGHT),
            ): _number("m", minimum=1.8, maximum=6.0, step=0.1),
        }
    )


class HeatPumpHealthConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gère l'écran d'installation initial (2 étapes : base, puis rendement/DJU/isolation)."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = user_input or {}

        if user_input is not None:
            if user_input[CONF_SEUIL_FAIBLE] >= user_input[CONF_SEUIL_ELEVE]:
                errors[CONF_SEUIL_ELEVE] = "invalid_thresholds"

            install_date = user_input.get(CONF_INSTALL_DATE)
            if install_date:
                parsed = dt_util.parse_date(install_date)
                if parsed is None or parsed > dt_util.now().date():
                    errors[CONF_INSTALL_DATE] = "future_install_date"

            if not errors:
                await self.async_set_unique_id(user_input[CONF_POWER_SENSOR])
                self._abort_if_unique_id_configured()
                self._data.update(user_input)
                return await self.async_step_performance()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Pompe à chaleur")): selector.TextSelector(),
                vol.Required(
                    CONF_POWER_SENSOR, **_suggest(defaults, CONF_POWER_SENSOR)
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_THRESHOLD_W, default=defaults.get(CONF_THRESHOLD_W, DEFAULT_THRESHOLD_W)
                ): _number("W", minimum=0, maximum=5000),
                vol.Required(
                    CONF_DELAY_OFF, default=defaults.get(CONF_DELAY_OFF, DEFAULT_DELAY_OFF)
                ): _number("s", minimum=0, maximum=600),
                vol.Required(
                    CONF_MAX_CYCLES, default=defaults.get(CONF_MAX_CYCLES, DEFAULT_MAX_CYCLES)
                ): _number("cycles", minimum=1000, maximum=500000),
                vol.Required(
                    CONF_SEUIL_FAIBLE, default=defaults.get(CONF_SEUIL_FAIBLE, DEFAULT_SEUIL_FAIBLE)
                ): _number("cycles/j", minimum=0, maximum=100),
                vol.Required(
                    CONF_SEUIL_ELEVE, default=defaults.get(CONF_SEUIL_ELEVE, DEFAULT_SEUIL_ELEVE)
                ): _number("cycles/j", minimum=0, maximum=100),
                vol.Optional(
                    CONF_INSTALL_DATE, **_suggest(defaults, CONF_INSTALL_DATE)
                ): selector.DateSelector(),
                vol.Optional(
                    CONF_INITIAL_CYCLES, default=defaults.get(CONF_INITIAL_CYCLES, DEFAULT_INITIAL_CYCLES)
                ): _number("cycles", minimum=0, maximum=500000),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_performance(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Étape optionnelle : entités météo/intérieures/climate (DJU & COP/EER) et isolation."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

        return self.async_show_form(
            step_id="performance", data_schema=_performance_schema({})
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> HeatPumpHealthOptionsFlow:
        return HeatPumpHealthOptionsFlow()


class HeatPumpHealthOptionsFlow(config_entries.OptionsFlow):
    """Permet d'ajuster les seuils, les capteurs intérieurs/extérieurs, le rendement et l'isolation après l'installation."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input[CONF_SEUIL_FAIBLE] >= user_input[CONF_SEUIL_ELEVE]:
                errors[CONF_SEUIL_ELEVE] = "invalid_thresholds"
            if not errors:
                return self.async_create_entry(title="", data=user_input)

        current = (
            user_input
            if user_input is not None
            else (dict(self.config_entry.options) if self.config_entry.options else dict(self.config_entry.data))
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_THRESHOLD_W, default=current.get(CONF_THRESHOLD_W, DEFAULT_THRESHOLD_W)
                ): _number("W", minimum=0, maximum=5000),
                vol.Required(
                    CONF_DELAY_OFF, default=current.get(CONF_DELAY_OFF, DEFAULT_DELAY_OFF)
                ): _number("s", minimum=0, maximum=600),
                vol.Required(
                    CONF_MAX_CYCLES, default=current.get(CONF_MAX_CYCLES, DEFAULT_MAX_CYCLES)
                ): _number("cycles", minimum=1000, maximum=500000),
                vol.Required(
                    CONF_SEUIL_FAIBLE, default=current.get(CONF_SEUIL_FAIBLE, DEFAULT_SEUIL_FAIBLE)
                ): _number("cycles/j", minimum=0, maximum=100),
                vol.Required(
                    CONF_SEUIL_ELEVE, default=current.get(CONF_SEUIL_ELEVE, DEFAULT_SEUIL_ELEVE)
                ): _number("cycles/j", minimum=0, maximum=100),
            }
        ).extend(_performance_schema(current).schema)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
