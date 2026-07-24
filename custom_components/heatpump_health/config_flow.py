"""Config flow pour HeatPump-Health."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_COP_NOMINAL,
    CONF_DELAY_OFF,
    CONF_EER_NOMINAL,
    CONF_INITIAL_CYCLES,
    CONF_INSTALL_DATE,
    CONF_KW_CHAUD,
    CONF_KW_FROID,
    CONF_MAX_CYCLES,
    CONF_OUTDOOR_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_POWER_SENSOR,
    CONF_SCOP,
    CONF_SEER,
    CONF_SEUIL_ELEVE,
    CONF_SEUIL_FAIBLE,
    CONF_THRESHOLD_W,
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


def _performance_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Schéma partagé entre l'étape d'installation et les options (rendement).

    Utilise `description={"suggested_value": ...}` plutôt que `default=` : un champ
    laissé vide est alors simplement absent du résultat, au lieu de faire échouer la
    validation du sélecteur (qui refuse `None`) quand aucune valeur n'est encore connue.
    """

    def _suggest(key: str) -> dict[str, Any]:
        value = defaults.get(key)
        return {"description": {"suggested_value": value}} if value is not None else {}

    return vol.Schema(
        {
            vol.Optional(CONF_CLIMATE_ENTITY, **_suggest(CONF_CLIMATE_ENTITY)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Optional(
                CONF_OUTDOOR_TEMP_SENSOR, **_suggest(CONF_OUTDOOR_TEMP_SENSOR)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_OUTDOOR_HUMIDITY_SENSOR, **_suggest(CONF_OUTDOOR_HUMIDITY_SENSOR)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Optional(CONF_COP_NOMINAL, **_suggest(CONF_COP_NOMINAL)): _number(
                "", minimum=1, maximum=10, step=0.01
            ),
            vol.Optional(CONF_EER_NOMINAL, **_suggest(CONF_EER_NOMINAL)): _number(
                "", minimum=1, maximum=10, step=0.01
            ),
            vol.Optional(CONF_SCOP, **_suggest(CONF_SCOP)): _number(
                "", minimum=1, maximum=12, step=0.01
            ),
            vol.Optional(CONF_SEER, **_suggest(CONF_SEER)): _number(
                "", minimum=1, maximum=15, step=0.01
            ),
            vol.Optional(CONF_KW_CHAUD, **_suggest(CONF_KW_CHAUD)): _number(
                "kW", minimum=0.5, maximum=100, step=0.1
            ),
            vol.Optional(CONF_KW_FROID, **_suggest(CONF_KW_FROID)): _number(
                "kW", minimum=0.5, maximum=100, step=0.1
            ),
        }
    )


class HeatPumpHealthConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gère l'écran d'installation initial (2 étapes : base, puis rendement)."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_POWER_SENSOR])
            self._abort_if_unique_id_configured()
            self._data.update(user_input)
            return await self.async_step_performance()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Pompe à chaleur"): selector.TextSelector(),
                vol.Required(CONF_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_THRESHOLD_W, default=DEFAULT_THRESHOLD_W): _number(
                    "W", minimum=0, maximum=5000
                ),
                vol.Required(CONF_DELAY_OFF, default=DEFAULT_DELAY_OFF): _number(
                    "s", minimum=0, maximum=600
                ),
                vol.Required(CONF_MAX_CYCLES, default=DEFAULT_MAX_CYCLES): _number(
                    "cycles", minimum=1000, maximum=500000
                ),
                vol.Required(CONF_SEUIL_FAIBLE, default=DEFAULT_SEUIL_FAIBLE): _number(
                    "cycles/j", minimum=0, maximum=100
                ),
                vol.Required(CONF_SEUIL_ELEVE, default=DEFAULT_SEUIL_ELEVE): _number(
                    "cycles/j", minimum=0, maximum=100
                ),
                vol.Optional(CONF_INSTALL_DATE): selector.DateSelector(),
                vol.Optional(CONF_INITIAL_CYCLES, default=DEFAULT_INITIAL_CYCLES): _number(
                    "cycles", minimum=0, maximum=500000
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_performance(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Étape optionnelle : données constructeur + entités pour le COP/EER théorique."""
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
    """Permet d'ajuster les seuils et les données de rendement après l'installation."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options or self.config_entry.data
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
        return self.async_show_form(step_id="init", data_schema=schema)
