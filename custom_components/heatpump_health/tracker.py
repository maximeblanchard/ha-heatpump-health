"""Cœur de la logique : détection des cycles marche/arrêt, suivi DJU/kWh et indicateurs."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
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
    DJU_BASE_TEMP_C,
    DOMAIN,
    ISOLATION_BONNE,
    ISOLATION_MOYENNE,
    ISOLATION_PASSOIRE,
    ISOLATION_TRES_BONNE,
    ISOLATION_TRES_PERFORMANT,
    MAX_INTEGRATION_GAP_SECONDS,
    MIN_DJU_DAILY,
    MIN_DJU_TODAY,
    MIN_TRACKED_HOURS_FOR_ARCHIVE,
    MODE_ARRET,
    MODE_CHAUFFAGE,
    MODE_CLIMATISATION,
    MODE_INCONNU,
    NIVEAU_ELEVE,
    NIVEAU_FAIBLE,
    NIVEAU_MOYEN,
    PERIODIC_SAVE_SECONDS,
    ROLLING_WINDOW_DAYS,
    SIGNAL_UPDATE,
    STORAGE_VERSION,
    UPDATE_INTERVAL_SECONDS,
)
from .performance import (
    calibrate_eta_cooling,
    calibrate_eta_heating,
    calculate_heat_loss_g,
    calculate_heat_loss_h,
    estimate_cop_heating,
    estimate_eer_cooling,
    incremental_dju,
)

_LOGGER = logging.getLogger(__name__)


class HeatPumpHealthTracker:
    """Suit l'état marche/arrêt de la PAC, l'usure, l'efficacité (kWh/DJU) et l'isolation."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")

        self._unsub_state: CALLBACK_TYPE | None = None
        self._unsub_interval: CALLBACK_TYPE | None = None
        self._unsub_midnight: CALLBACK_TYPE | None = None
        self._unsub_pending_off: CALLBACK_TYPE | None = None
        self._unsub_performance: CALLBACK_TYPE | None = None
        self._unsub_stop: CALLBACK_TYPE | None = None

        # État des cycles et usure
        self.is_running: bool = False
        self.cycle_start: datetime | None = None
        self._pending_off_since: datetime | None = None
        self._loaded_saved_at: datetime | None = None

        self.initial_cycles: int = 0
        self.has_install_date: bool = False
        self.total_cycles: int = 0
        self.measured_cycles: int = 0
        self.total_duration_min: float = 0.0
        self.last_cycle_duration_min: float = 0.0
        self.start_date: datetime = dt_util.utcnow()
        self.current_day: date = dt_util.now().date()
        self.daily_cycles: int = 0
        self.cycle_history: list[dict[str, Any]] = []  # [{"end": iso, "duration_min": float}]

        # Suivi énergétique quotidien (kWh électrique, kWh thermique, DJU base 18°C & DJU réel)
        self.daily_energy_kwh: float = 0.0
        self.daily_thermal_energy_kwh: float = 0.0
        self.daily_dju: float = 0.0
        self.daily_dju_reel: float = 0.0
        self.daily_tracked_seconds: float = 0.0
        self.daily_tracked_reel_seconds: float = 0.0
        self.dju_history: list[dict[str, Any]] = []

        # Curseurs d'intégration temps réel (somme de Riemann à gauche)
        self._last_energy_ts: datetime | None = None
        self._last_power_w: float | None = None
        self._last_dju_ts: datetime | None = None
        self._last_outdoor_temp_c: float | None = None
        self._last_indoor_temp_c: float | None = None
        self._last_save_ts: datetime | None = None

    # ------------------------------------------------------------------ #
    # Configuration (options modifiables après coup via l'Options Flow)
    # ------------------------------------------------------------------ #
    def _opt(self, key: str, default: Any = None) -> Any:
        """Lit l'option active (ou la donnée initiale si OptionsFlow n'a jamais été soumis)."""
        source = self.entry.options if self.entry.options else self.entry.data
        return source.get(key, default)

    @property
    def power_sensor(self) -> str:
        return self.entry.data[CONF_POWER_SENSOR]

    @property
    def threshold_w(self) -> float:
        return float(self._opt(CONF_THRESHOLD_W, DEFAULT_THRESHOLD_W))

    @property
    def delay_off(self) -> int:
        return int(self._opt(CONF_DELAY_OFF, DEFAULT_DELAY_OFF))

    @property
    def max_cycles(self) -> int:
        return int(self._opt(CONF_MAX_CYCLES, DEFAULT_MAX_CYCLES))

    @property
    def seuil_faible(self) -> float:
        return float(self._opt(CONF_SEUIL_FAIBLE, DEFAULT_SEUIL_FAIBLE))

    @property
    def seuil_eleve(self) -> float:
        return float(self._opt(CONF_SEUIL_ELEVE, DEFAULT_SEUIL_ELEVE))

    # -- Rendement (COP/EER théorique), capteurs intérieurs & DJU -- #
    @property
    def climate_entity(self) -> str | None:
        return self._opt(CONF_CLIMATE_ENTITY)

    @property
    def indoor_temp_sensors(self) -> list[str]:
        val = self._opt(CONF_INDOOR_TEMP_SENSORS)
        if not val:
            return []
        if isinstance(val, str):
            return [val]
        return [str(e) for e in val if e]

    @property
    def outdoor_temp_sensor(self) -> str | None:
        return self._opt(CONF_OUTDOOR_TEMP_SENSOR)

    @property
    def outdoor_humidity_sensor(self) -> str | None:
        return self._opt(CONF_OUTDOOR_HUMIDITY_SENSOR)

    @property
    def cop_nominal(self) -> float | None:
        value = self._opt(CONF_COP_NOMINAL)
        return float(value) if value is not None else None

    @property
    def eer_nominal(self) -> float | None:
        value = self._opt(CONF_EER_NOMINAL)
        return float(value) if value is not None else None

    @property
    def kw_chaud(self) -> float | None:
        value = self._opt(CONF_KW_CHAUD)
        return float(value) if value is not None else None

    @property
    def kw_froid(self) -> float | None:
        value = self._opt(CONF_KW_FROID)
        return float(value) if value is not None else None

    # -- Bâtiment et isolation -- #
    @property
    def surface_m2(self) -> float | None:
        value = self._opt(CONF_SURFACE_M2)
        return float(value) if value is not None else None

    @property
    def hauteur_plafond(self) -> float:
        value = self._opt(CONF_CEILING_HEIGHT, DEFAULT_CEILING_HEIGHT)
        return float(value) if value is not None else DEFAULT_CEILING_HEIGHT

    @property
    def volume_m3(self) -> float | None:
        if self.surface_m2 is None:
            return None
        return round(self.surface_m2 * self.hauteur_plafond, 1)

    @property
    def eta_heating(self) -> float | None:
        """Facteur d'efficacité réel/Carnot, calibré sur le COP nominal déclaré."""
        cop_nom = self.cop_nominal
        return calibrate_eta_heating(cop_nom) if cop_nom else None

    @property
    def eta_cooling(self) -> float | None:
        """Facteur d'efficacité réel/Carnot, calibré sur l'EER nominal déclaré."""
        eer_nom = self.eer_nominal
        return calibrate_eta_cooling(eer_nom) if eer_nom else None

    @property
    def has_cop_config(self) -> bool:
        return bool(
            (self.climate_entity or self.indoor_temp_sensors)
            and self.outdoor_temp_sensor
            and self.cop_nominal
        )

    @property
    def has_eer_config(self) -> bool:
        return bool(
            (self.climate_entity or self.indoor_temp_sensors)
            and self.outdoor_temp_sensor
            and self.eer_nominal
        )

    @property
    def has_dju_reel_config(self) -> bool:
        return bool(self.outdoor_temp_sensor and self.indoor_temp_sensors)

    @property
    def has_thermal_loss_config(self) -> bool:
        """Nécessite au minimum le capteur extérieur et le COP nominal."""
        return bool(self.outdoor_temp_sensor and self.cop_nominal)

    @property
    def has_insulation_rating_config(self) -> bool:
        """Nécessite la déperdition thermique et la surface habitable."""
        return bool(self.has_thermal_loss_config and self.surface_m2 and self.surface_m2 > 0)

    @property
    def performance_entities(self) -> list[str]:
        """Entités à surveiller pour rafraîchir le rendement et les DJU."""
        entities = [
            e
            for e in (self.climate_entity, self.outdoor_temp_sensor, self.outdoor_humidity_sensor)
            if e
        ]
        for sensor_id in self.indoor_temp_sensors:
            if sensor_id not in entities:
                entities.append(sensor_id)
        return entities

    # ------------------------------------------------------------------ #
    # Cycle de vie de l'intégration
    # ------------------------------------------------------------------ #
    async def async_setup(self) -> None:
        """Charge les données persistées et démarre les écouteurs."""
        await self._async_load()
        if self._rollover_day_if_needed():
            await self._async_save()

        now = dt_util.utcnow()
        self._last_power_w = self._read_power_w()
        self._last_energy_ts = now
        self._last_outdoor_temp_c = self.temperature_exterieure
        self._last_indoor_temp_c = self.temperature_interieure_moyenne
        self._last_dju_ts = now
        self._last_save_ts = now

        self._unsub_state = async_track_state_change_event(
            self.hass, [self.power_sensor], self._handle_power_event
        )
        self._unsub_interval = async_track_time_interval(
            self.hass, self._handle_periodic_refresh, timedelta(seconds=UPDATE_INTERVAL_SECONDS)
        )
        self._unsub_midnight = async_track_time_change(
            self.hass, self._handle_midnight, hour=0, minute=0, second=0
        )
        if self.performance_entities:
            self._unsub_performance = async_track_state_change_event(
                self.hass, self.performance_entities, self._handle_performance_event
            )
        self._unsub_stop = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._handle_ha_stop
        )

        current = self.hass.states.get(self.power_sensor)
        if current is not None:
            self._evaluate_power(current, startup_fallback_end=self._loaded_saved_at)

    async def async_unload(self) -> None:
        """Sauvegarde les compteurs en cours et coupe tous les écouteurs."""
        self._accrue_energy_and_dju(dt_util.utcnow())
        for unsub in (
            self._unsub_state,
            self._unsub_interval,
            self._unsub_midnight,
            self._unsub_pending_off,
            self._unsub_performance,
            self._unsub_stop,
        ):
            if unsub is not None:
                unsub()
        self._unsub_state = None
        self._unsub_interval = None
        self._unsub_midnight = None
        self._unsub_pending_off = None
        self._unsub_performance = None
        self._unsub_stop = None
        await self._async_save()

    async def _handle_ha_stop(self, _event: Event) -> None:
        """Persiste proprement l'état lors de l'arrêt de Home Assistant."""
        self._unsub_stop = None
        self._accrue_energy_and_dju(dt_util.utcnow())
        await self._async_save()

    # ------------------------------------------------------------------ #
    # Persistance (survit aux redémarrages de Home Assistant)
    # ------------------------------------------------------------------ #
    async def _async_load(self) -> None:
        stored = await self._store.async_load()
        if stored is None:
            self.initial_cycles = int(
                self.entry.data.get(CONF_INITIAL_CYCLES, DEFAULT_INITIAL_CYCLES)
            )
            self.total_cycles = self.initial_cycles
            self.measured_cycles = 0
            install_date = self.entry.data.get(CONF_INSTALL_DATE)
            parsed = dt_util.parse_date(install_date) if install_date else None
            self.has_install_date = parsed is not None
            self.start_date = (
                dt_util.start_of_local_day(parsed) if parsed else dt_util.utcnow()
            )
            self.current_day = dt_util.now().date()
            await self._async_save()
            return

        self.total_cycles = int(stored.get("total_cycles", 0))
        self.total_duration_min = float(stored.get("total_duration_min", 0.0))
        self.last_cycle_duration_min = float(stored.get("last_cycle_duration_min", 0.0))
        self.start_date = dt_util.parse_datetime(stored["start_date"]) or dt_util.utcnow()
        self.current_day = dt_util.parse_date(stored["current_day"]) or dt_util.now().date()
        self.daily_cycles = int(stored.get("daily_cycles", 0))
        self.cycle_history = stored.get("cycle_history", [])
        self.is_running = bool(stored.get("is_running", False))
        cycle_start = stored.get("cycle_start")
        self.cycle_start = dt_util.parse_datetime(cycle_start) if cycle_start else None

        self.initial_cycles = int(
            stored.get(
                "initial_cycles",
                self.entry.data.get(CONF_INITIAL_CYCLES, DEFAULT_INITIAL_CYCLES),
            )
        )
        self.has_install_date = bool(
            stored.get("has_install_date", bool(self.entry.data.get(CONF_INSTALL_DATE)))
        )
        in_progress = 1 if self.is_running else 0
        default_measured = max(self.total_cycles - self.initial_cycles - in_progress, 0)
        self.measured_cycles = int(stored.get("measured_cycles", default_measured))

        self.daily_energy_kwh = float(stored.get("daily_energy_kwh", 0.0))
        self.daily_thermal_energy_kwh = float(stored.get("daily_thermal_energy_kwh", 0.0))
        self.daily_dju = float(stored.get("daily_dju", 0.0))
        self.daily_dju_reel = float(stored.get("daily_dju_reel", 0.0))
        self.daily_tracked_seconds = float(stored.get("daily_tracked_seconds", 0.0))
        self.daily_tracked_reel_seconds = float(
            stored.get("daily_tracked_reel_seconds", 0.0)
        )
        self.dju_history = stored.get("dju_history", [])

        saved_at = stored.get("saved_at")
        self._loaded_saved_at = dt_util.parse_datetime(saved_at) if saved_at else None

        self._prune_history()
        self._prune_dju_history()

    async def _async_save(self) -> None:
        now = dt_util.utcnow()
        self._last_save_ts = now
        await self._store.async_save(
            {
                "initial_cycles": self.initial_cycles,
                "has_install_date": self.has_install_date,
                "total_cycles": self.total_cycles,
                "measured_cycles": self.measured_cycles,
                "total_duration_min": self.total_duration_min,
                "last_cycle_duration_min": self.last_cycle_duration_min,
                "start_date": self.start_date.isoformat(),
                "current_day": self.current_day.isoformat(),
                "daily_cycles": self.daily_cycles,
                "cycle_history": self.cycle_history,
                "is_running": self.is_running,
                "cycle_start": self.cycle_start.isoformat() if self.cycle_start else None,
                "daily_energy_kwh": self.daily_energy_kwh,
                "daily_thermal_energy_kwh": self.daily_thermal_energy_kwh,
                "daily_dju": self.daily_dju,
                "daily_dju_reel": self.daily_dju_reel,
                "daily_tracked_seconds": self.daily_tracked_seconds,
                "daily_tracked_reel_seconds": self.daily_tracked_reel_seconds,
                "dju_history": self.dju_history,
                "saved_at": now.isoformat(),
            }
        )

    def _schedule_save(self) -> None:
        self.hass.async_create_task(self._async_save(), name="heatpump_health_save")

    # ------------------------------------------------------------------ #
    # Intégration continue kWh, DJU base 18°C & DJU réel (T_int - T_ext)
    # ------------------------------------------------------------------ #
    def _read_power_w(self) -> float | None:
        state = self.hass.states.get(self.power_sensor)
        if state is None or state.state in ("unknown", "unavailable", None):
            return None
        try:
            return max(float(state.state), 0.0)
        except (ValueError, TypeError):
            return None

    def _accrue_energy_and_dju(self, now: datetime) -> bool:
        """Intègre l'énergie électrique/thermique et les DJU depuis le dernier point."""
        changed = False
        prev_power_w = self._last_power_w

        if self._last_energy_ts is not None and prev_power_w is not None:
            dt_e = (now - self._last_energy_ts).total_seconds()
            if 0.0 < dt_e <= MAX_INTEGRATION_GAP_SECONDS:
                # Les DJU et déperditions concernent le mode chauffage
                if self.mode_fonctionnement != MODE_CLIMATISATION and prev_power_w > 0.0:
                    elec_kwh = (prev_power_w / 1000.0) * (dt_e / 3600.0)
                    self.daily_energy_kwh += elec_kwh
                    changed = True

                    cop = self.cop_instantane
                    if cop is None and self.cop_nominal is not None:
                        cop = self.cop_nominal
                    if cop is not None and cop > 0.0:
                        self.daily_thermal_energy_kwh += elec_kwh * cop

        self._last_energy_ts = now
        self._last_power_w = self._read_power_w()

        if self.outdoor_temp_sensor:
            if self._last_dju_ts is not None and self._last_outdoor_temp_c is not None:
                dt_d = (now - self._last_dju_ts).total_seconds()
                if 0.0 < dt_d <= MAX_INTEGRATION_GAP_SECONDS:
                    added_dju = incremental_dju(
                        self._last_outdoor_temp_c, dt_d, DJU_BASE_TEMP_C
                    )
                    if added_dju > 0.0:
                        self.daily_dju += added_dju
                        changed = True
                    if prev_power_w is not None:
                        self.daily_tracked_seconds += dt_d

                    if self._last_indoor_temp_c is not None:
                        added_reel = incremental_dju(
                            self._last_outdoor_temp_c, dt_d, self._last_indoor_temp_c
                        )
                        if added_reel > 0.0:
                            self.daily_dju_reel += added_reel
                            changed = True
                        if prev_power_w is not None:
                            self.daily_tracked_reel_seconds += dt_d

            self._last_dju_ts = now
            self._last_outdoor_temp_c = self.temperature_exterieure
            self._last_indoor_temp_c = self.temperature_interieure_moyenne

        return changed

    # ------------------------------------------------------------------ #
    # Détection marche / arrêt
    # ------------------------------------------------------------------ #
    @callback
    def _handle_power_event(self, event: Event) -> None:
        now = dt_util.utcnow()
        self._accrue_energy_and_dju(now)
        if self._rollover_day_if_needed():
            self._schedule_save()

        new_state: State | None = event.data.get("new_state")
        if new_state is None:
            return
        self._evaluate_power(new_state)

    @callback
    def _handle_performance_event(self, event: Event) -> None:
        """La météo, la T° intérieure ou le mode climate a changé : on intègre et on rafraîchit."""
        now = dt_util.utcnow()
        self._accrue_energy_and_dju(now)
        if self._rollover_day_if_needed():
            self._schedule_save()
        self._notify()

    def _evaluate_power(
        self, state: State, startup_fallback_end: datetime | None = None
    ) -> None:
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return

        above_threshold = value > self.threshold_w

        if above_threshold:
            self._cancel_pending_off()
            if not self.is_running:
                self._start_cycle()
            else:
                self._notify()
        elif self.is_running and self._unsub_pending_off is None:
            self._schedule_pending_off(fallback_since=startup_fallback_end)

    def _start_cycle(self) -> None:
        self.is_running = True
        self.cycle_start = dt_util.utcnow()
        self._pending_off_since = None
        self.total_cycles += 1
        self._rollover_day_if_needed()
        self.daily_cycles += 1
        self._schedule_save()
        self._notify()

    def _schedule_pending_off(self, fallback_since: datetime | None = None) -> None:
        self._pending_off_since = fallback_since or dt_util.utcnow()
        if self.delay_off <= 0:
            self._confirm_off(self._pending_off_since)
            return
        self._unsub_pending_off = async_call_later(
            self.hass, self.delay_off, self._confirm_off
        )

    def _cancel_pending_off(self) -> None:
        if self._unsub_pending_off is not None:
            self._unsub_pending_off()
            self._unsub_pending_off = None
        self._pending_off_since = None

    @callback
    def _confirm_off(self, _now: Any) -> None:
        self._unsub_pending_off = None
        end = self._pending_off_since or dt_util.utcnow()
        self._pending_off_since = None
        if not self.is_running or self.cycle_start is None:
            return

        duration_min = max((end - self.cycle_start).total_seconds() / 60.0, 0.0)
        self.is_running = False
        self.last_cycle_duration_min = round(duration_min, 2)
        self.total_duration_min += duration_min
        self.measured_cycles += 1
        self.cycle_history.append({"end": end.isoformat(), "duration_min": duration_min})
        self._prune_history()
        self.cycle_start = None
        self._schedule_save()
        self._notify()

    # ------------------------------------------------------------------ #
    # Entretien périodique et bascule de minuit
    # ------------------------------------------------------------------ #
    @callback
    def _handle_periodic_refresh(self, _now: Any) -> None:
        """Intègre kWh/DJU chaque minute et rafraîchit les capteurs actifs."""
        now = dt_util.utcnow()
        accrued = self._accrue_energy_and_dju(now)
        rolled = self._rollover_day_if_needed()
        pruned = self._prune_history()

        if rolled or (
            self._last_save_ts is not None
            and (now - self._last_save_ts).total_seconds() >= PERIODIC_SAVE_SECONDS
        ):
            self._schedule_save()

        if self.is_running or accrued or rolled or pruned:
            self._notify()

    @callback
    def _handle_midnight(self, _now: Any) -> None:
        now = dt_util.utcnow()
        self._accrue_energy_and_dju(now)
        self._rollover_day_if_needed()
        self._schedule_save()
        self._notify()

    def _rollover_day_if_needed(self) -> bool:
        """Archive la journée écoulée à minuit et réinitialise les compteurs journaliers."""
        today = dt_util.now().date()
        if today == self.current_day:
            return False

        days_gap = (today - self.current_day).days
        tracked_h = self.daily_tracked_seconds / 3600.0
        tracked_reel_h = self.daily_tracked_reel_seconds / 3600.0
        if (
            days_gap == 1
            and self.outdoor_temp_sensor
            and tracked_h >= MIN_TRACKED_HOURS_FOR_ARCHIVE
        ):
            day_iso = self.current_day.isoformat()
            self.dju_history = [
                item for item in self.dju_history if item.get("date") != day_iso
            ]
            self.dju_history.append(
                {
                    "date": day_iso,
                    "kwh": round(self.daily_energy_kwh, 4),
                    "kwh_th": round(self.daily_thermal_energy_kwh, 4),
                    "dju": round(self.daily_dju, 4),
                    "dju_reel": round(self.daily_dju_reel, 4),
                    "tracked_h": round(tracked_h, 2),
                    "tracked_reel_h": round(tracked_reel_h, 2),
                }
            )

        self.current_day = today
        self.daily_cycles = 0
        self.daily_energy_kwh = 0.0
        self.daily_thermal_energy_kwh = 0.0
        self.daily_dju = 0.0
        self.daily_dju_reel = 0.0
        self.daily_tracked_seconds = 0.0
        self.daily_tracked_reel_seconds = 0.0
        self._prune_history()
        self._prune_dju_history()
        return True

    def _prune_history(self) -> bool:
        cutoff = dt_util.utcnow() - timedelta(days=ROLLING_WINDOW_DAYS)
        pruned = []
        for item in self.cycle_history:
            end = dt_util.parse_datetime(item["end"])
            if end and end > cutoff:
                pruned.append(item)
        changed = len(pruned) != len(self.cycle_history)
        self.cycle_history = pruned
        return changed

    def _prune_dju_history(self) -> None:
        cutoff_date = dt_util.now().date() - timedelta(days=ROLLING_WINDOW_DAYS)
        pruned = []
        for item in self.dju_history:
            parsed = dt_util.parse_date(item.get("date", ""))
            if parsed and parsed >= cutoff_date:
                pruned.append(item)
        self.dju_history = pruned

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    # ------------------------------------------------------------------ #
    # Indicateurs d'usure exposés aux entités sensor.*
    # ------------------------------------------------------------------ #
    @property
    def current_cycle_elapsed_min(self) -> float:
        if not self.is_running or self.cycle_start is None:
            return 0.0
        effective_now = self._pending_off_since or dt_util.utcnow()
        return max((effective_now - self.cycle_start).total_seconds() / 60.0, 0.0)

    @property
    def usure_pourcentage(self) -> float:
        if self.max_cycles <= 0:
            return 0.0
        return round((self.total_cycles / self.max_cycles) * 100, 2)

    @property
    def temps_fonctionnement_total_h(self) -> float:
        return round((self.total_duration_min + self.current_cycle_elapsed_min) / 60, 2)

    @property
    def cycles_7j(self) -> int:
        return len(self.cycle_history) + (1 if self.is_running else 0)

    @property
    def temps_fonctionnement_7j_h(self) -> float:
        completed = sum(item["duration_min"] for item in self.cycle_history)
        in_progress = min(self.current_cycle_elapsed_min, ROLLING_WINDOW_DAYS * 1440.0)
        return round((completed + in_progress) / 60, 2)

    @property
    def duree_moyenne_cycle_7j_min(self) -> float:
        if not self.cycle_history:
            return 0.0
        total = sum(item["duration_min"] for item in self.cycle_history)
        return round(total / len(self.cycle_history), 2)

    @property
    def duree_moyenne_cycle_totale_min(self) -> float:
        if self.measured_cycles <= 0:
            return 0.0
        return round(self.total_duration_min / self.measured_cycles, 2)

    @property
    def jours_depuis_installation(self) -> float:
        delta = dt_util.utcnow() - self.start_date
        return max(delta.total_seconds() / 86400.0, 1.0)

    @property
    def taux_usure_quotidien_cycles(self) -> float:
        cycles_ref = (
            self.total_cycles
            if self.has_install_date
            else max(self.total_cycles - self.initial_cycles, 0)
        )
        return round(cycles_ref / self.jours_depuis_installation, 2)

    @property
    def usure_quotidienne_pourcent(self) -> float:
        if self.max_cycles <= 0:
            return 0.0
        return round((self.taux_usure_quotidien_cycles / self.max_cycles) * 100, 4)

    @property
    def duree_vie_restante_jours(self) -> float:
        taux = self.taux_usure_quotidien_cycles
        if taux <= 0:
            return 0.0
        restant = max(self.max_cycles - self.total_cycles, 0)
        return round(restant / taux, 0)

    @property
    def duree_vie_restante_annees(self) -> float:
        return round(self.duree_vie_restante_jours / 365, 1)

    @property
    def indice_usure_7j(self) -> str:
        moyenne_jour = self.cycles_7j / ROLLING_WINDOW_DAYS
        if moyenne_jour >= self.seuil_eleve:
            return NIVEAU_ELEVE
        if moyenne_jour >= self.seuil_faible:
            return NIVEAU_MOYEN
        return NIVEAU_FAIBLE

    # ------------------------------------------------------------------ #
    # Indicateurs DJU (base 18°C) & DJU réel (T_int moyenne - T_ext)
    # ------------------------------------------------------------------ #
    @property
    def daily_tracked_hours(self) -> float:
        return self.daily_tracked_seconds / 3600.0

    @property
    def daily_tracked_reel_hours(self) -> float:
        return self.daily_tracked_reel_seconds / 3600.0

    @property
    def date_veille(self) -> str:
        return (dt_util.now().date() - timedelta(days=1)).isoformat()

    @property
    def _veille_entry(self) -> dict[str, Any] | None:
        veille = self.date_veille
        for item in reversed(self.dju_history):
            if item.get("date") == veille:
                return item
        return None

    @property
    def dju_veille(self) -> float | None:
        entry = self._veille_entry
        return round(entry["dju"], 2) if entry is not None else None

    @property
    def dju_reel_veille(self) -> float | None:
        entry = self._veille_entry
        if entry is None or "dju_reel" not in entry:
            return None
        if entry.get("tracked_reel_h", 0.0) < MIN_TRACKED_HOURS_FOR_ARCHIVE:
            return None
        return round(entry["dju_reel"], 2)

    @property
    def energie_veille_kwh(self) -> float | None:
        entry = self._veille_entry
        return round(entry["kwh"], 3) if entry is not None else None

    @property
    def kwh_par_dju_aujourdhui(self) -> float | None:
        if self.daily_dju < MIN_DJU_TODAY:
            return None
        return round(self.daily_energy_kwh / self.daily_dju, 2)

    @property
    def kwh_par_dju_veille(self) -> float | None:
        entry = self._veille_entry
        if entry is None or entry["dju"] < MIN_DJU_DAILY:
            return None
        return round(entry["kwh"] / entry["dju"], 2)

    @property
    def energie_7j_kwh(self) -> float:
        if self.dju_history:
            return round(sum(item["kwh"] for item in self.dju_history), 3)
        return round(self.daily_energy_kwh, 3)

    @property
    def dju_7j(self) -> float:
        if self.dju_history:
            return round(sum(item["dju"] for item in self.dju_history), 2)
        return round(self.daily_dju, 2)

    @property
    def kwh_par_dju_7j(self) -> float | None:
        if self.dju_history:
            total_kwh = sum(item["kwh"] for item in self.dju_history)
            total_dju = sum(item["dju"] for item in self.dju_history)
            if total_dju < MIN_DJU_DAILY:
                return None
            return round(total_kwh / total_dju, 2)
        return self.kwh_par_dju_aujourdhui

    # -- Indicateurs DJU réel (compensés par la température intérieure moyenne) -- #
    @property
    def _dju_reel_history(self) -> list[dict[str, Any]]:
        return [
            item
            for item in self.dju_history
            if item.get("tracked_reel_h", 0.0) >= MIN_TRACKED_HOURS_FOR_ARCHIVE
        ]

    @property
    def jours_reel_comptabilises_7j(self) -> int:
        return len(self._dju_reel_history)

    @property
    def energie_reel_7j_kwh(self) -> float:
        reel_days = self._dju_reel_history
        if reel_days:
            return round(sum(item["kwh"] for item in reel_days), 3)
        return round(self.daily_energy_kwh, 3)

    @property
    def dju_reel_7j(self) -> float:
        reel_days = self._dju_reel_history
        if reel_days:
            return round(sum(item.get("dju_reel", 0.0) for item in reel_days), 2)
        return round(self.daily_dju_reel, 2)

    @property
    def kwh_par_dju_reel_aujourdhui(self) -> float | None:
        if self.daily_dju_reel < MIN_DJU_TODAY:
            return None
        return round(self.daily_energy_kwh / self.daily_dju_reel, 2)

    @property
    def kwh_par_dju_reel_veille(self) -> float | None:
        entry = self._veille_entry
        if (
            entry is None
            or entry.get("tracked_reel_h", 0.0) < MIN_TRACKED_HOURS_FOR_ARCHIVE
            or entry.get("dju_reel", 0.0) < MIN_DJU_DAILY
        ):
            return None
        return round(entry["kwh"] / entry["dju_reel"], 2)

    @property
    def kwh_par_dju_reel_7j(self) -> float | None:
        reel_days = self._dju_reel_history
        if reel_days:
            total_kwh = sum(item["kwh"] for item in reel_days)
            total_dju_reel = sum(item.get("dju_reel", 0.0) for item in reel_days)
            if total_dju_reel < MIN_DJU_DAILY:
                return None
            return round(total_kwh / total_dju_reel, 2)
        return self.kwh_par_dju_reel_aujourdhui

    # ------------------------------------------------------------------ #
    # Déperdition thermique globale H (W/K) & isolation G (W/(m³·K))
    # ------------------------------------------------------------------ #
    def _calculate_h(self, kwh_th: float, dju: float) -> float | None:
        """H = (Q_thermique / DJU) * (1000 / 24) en W/K."""
        if dju < MIN_DJU_DAILY or kwh_th <= 0.0:
            return None
        return calculate_heat_loss_h(kwh_th, dju)

    @property
    def h_7j(self) -> float | None:
        """Déperdition globale H (W/K) calculée sur les 7 derniers jours."""
        valid_days = self._dju_reel_history if self.has_dju_reel_config else [
            item for item in self.dju_history if item.get("tracked_h", 0.0) >= MIN_TRACKED_HOURS_FOR_ARCHIVE
        ]
        if not valid_days:
            return None
        cop_ref = self.cop_nominal or 1.0
        total_kwh_th = sum(item.get("kwh_th", item["kwh"] * cop_ref) for item in valid_days)
        dju_key = "dju_reel" if self.has_dju_reel_config else "dju"
        total_dju = sum(item.get(dju_key, 0.0) for item in valid_days)
        return self._calculate_h(total_kwh_th, total_dju)

    @property
    def h_veille(self) -> float | None:
        """Déperdition globale H (W/K) de la veille."""
        entry = self._veille_entry
        if entry is None:
            return None
        tracked = entry.get("tracked_reel_h", 0.0) if self.has_dju_reel_config else entry.get("tracked_h", 0.0)
        if tracked < MIN_TRACKED_HOURS_FOR_ARCHIVE:
            return None
        cop_ref = self.cop_nominal or 1.0
        kwh_th = entry.get("kwh_th", entry["kwh"] * cop_ref)
        dju_val = entry.get("dju_reel" if self.has_dju_reel_config else "dju", 0.0)
        return self._calculate_h(kwh_th, dju_val)

    @property
    def deperdition_thermique_h(self) -> float | None:
        """Déperdition thermique globale H (W/K) : 7 jours en priorité, repli veille puis jour en cours."""
        val_7j = self.h_7j
        if val_7j is not None:
            return val_7j
        val_veille = self.h_veille
        if val_veille is not None:
            return val_veille
        active_dju = self.daily_dju_reel if self.has_dju_reel_config else self.daily_dju
        return self._calculate_h(self.daily_thermal_energy_kwh, active_dju)

    @property
    def coefficient_deperdition_g(self) -> float | None:
        """Coefficient de déperdition volumique G (W/(m³·K)) = H / Volume."""
        h = self.deperdition_thermique_h
        vol = self.volume_m3
        if h is None or vol is None or vol <= 0:
            return None
        return calculate_heat_loss_g(h, vol)

    @property
    def g_7j(self) -> float | None:
        h = self.h_7j
        vol = self.volume_m3
        if h is None or vol is None or vol <= 0:
            return None
        return calculate_heat_loss_g(h, vol)

    @property
    def g_veille(self) -> float | None:
        h = self.h_veille
        vol = self.volume_m3
        if h is None or vol is None or vol <= 0:
            return None
        return calculate_heat_loss_g(h, vol)

    @property
    def qualite_isolation(self) -> str | None:
        """Niveau d'isolation estimé d'après le coefficient volumique G (normes RT)."""
        g = self.coefficient_deperdition_g
        if g is None:
            return None
        if g <= 0.45:
            return ISOLATION_TRES_PERFORMANT
        if g <= 0.75:
            return ISOLATION_TRES_BONNE
        if g <= 1.05:
            return ISOLATION_BONNE
        if g <= 1.40:
            return ISOLATION_MOYENNE
        return ISOLATION_PASSOIRE

    # ------------------------------------------------------------------ #
    # Rendement (COP/EER théorique) & températures — lecture live
    # ------------------------------------------------------------------ #
    def _read_float(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", None):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    @property
    def _valid_indoor_sensor_values(self) -> list[float]:
        values: list[float] = []
        for entity_id in self.indoor_temp_sensors:
            val = self._read_float(entity_id)
            if val is not None:
                values.append(val)
        return values

    @property
    def active_indoor_temp_sensors_count(self) -> int:
        return len(self._valid_indoor_sensor_values)

    @property
    def temperature_interieure_moyenne(self) -> float | None:
        """Moyenne arithmétique des capteurs de température intérieure disponibles."""
        values = self._valid_indoor_sensor_values
        if not values:
            return None
        return round(sum(values) / len(values), 2)

    @property
    def temperature_exterieure(self) -> float | None:
        return self._read_float(self.outdoor_temp_sensor)

    @property
    def humidite_exterieure(self) -> float | None:
        return self._read_float(self.outdoor_humidity_sensor)

    @property
    def mode_fonctionnement(self) -> str:
        """Mode réel déduit de l'entité climate : chauffage/climatisation/arrêt/inconnu."""
        climate_id = self.climate_entity
        if not climate_id:
            # Sans entité climate : si la PAC tourne et qu'aucun mode froid n'est déclaré, c'est du chauffage
            if self.is_running and self.cop_nominal is not None and self.eer_nominal is None:
                return MODE_CHAUFFAGE
            return MODE_ARRET if not self.is_running else MODE_INCONNU

        state = self.hass.states.get(climate_id)
        if state is None:
            return MODE_INCONNU

        action = state.attributes.get("hvac_action")
        if action == "heating":
            return MODE_CHAUFFAGE
        if action == "cooling":
            return MODE_CLIMATISATION
        if action in ("idle", "off", "fan", "drying"):
            return MODE_ARRET

        if state.state == "heat":
            return MODE_CHAUFFAGE
        if state.state == "cool":
            return MODE_CLIMATISATION
        if state.state == "off":
            return MODE_ARRET
        return MODE_INCONNU

    @property
    def consigne_climate(self) -> float | None:
        """La consigne demandée (cible)."""
        climate_id = self.climate_entity
        if not climate_id:
            return None
        state = self.hass.states.get(climate_id)
        if state is None:
            return None
        temperature = state.attributes.get("temperature")
        if temperature is not None:
            try:
                return float(temperature)
            except (ValueError, TypeError):
                pass
        low = state.attributes.get("target_temp_low")
        high = state.attributes.get("target_temp_high")
        if low is not None and high is not None:
            try:
                return (float(low) + float(high)) / 2
            except (ValueError, TypeError):
                return None
        return None

    @property
    def temperature_interieure_actuelle(self) -> float | None:
        """Température intérieure MESURÉE par l'entité climate (current_temperature)."""
        climate_id = self.climate_entity
        if not climate_id:
            return None
        state = self.hass.states.get(climate_id)
        if state is None:
            return None
        current = state.attributes.get("current_temperature")
        if current is None:
            return None
        try:
            return float(current)
        except (ValueError, TypeError):
            return None

    @property
    def temperature_interieure_effective(self) -> float | None:
        """Température intérieure retenue (moyenne capteurs int., sinon climate, sinon consigne)."""
        t_sensors = self.temperature_interieure_moyenne
        if t_sensors is not None:
            return t_sensors
        t_climate = self.temperature_interieure_actuelle
        return t_climate if t_climate is not None else self.consigne_climate

    @property
    def source_temperature_interieure(self) -> str | None:
        if self.temperature_interieure_moyenne is not None:
            return "capteurs_interieurs"
        if self.temperature_interieure_actuelle is not None:
            return "climate_mesuree"
        if self.consigne_climate is not None:
            return "consigne"
        return None

    @property
    def puissance_absorbee_kw(self) -> float:
        power_w = self._read_power_w()
        return (power_w / 1000.0) if power_w is not None else 0.0

    @property
    def cop_instantane(self) -> float | None:
        if not self.is_running or self.mode_fonctionnement != MODE_CHAUFFAGE:
            return None
        eta = self.eta_heating
        t_ext = self.temperature_exterieure
        t_int = self.temperature_interieure_effective
        if eta is None or t_ext is None or t_int is None:
            return None
        return estimate_cop_heating(t_ext, t_int, eta, self.humidite_exterieure)

    @property
    def eer_instantane(self) -> float | None:
        if not self.is_running or self.mode_fonctionnement != MODE_CLIMATISATION:
            return None
        eta = self.eta_cooling
        t_ext = self.temperature_exterieure
        t_int = self.temperature_interieure_effective
        if eta is None or t_ext is None or t_int is None:
            return None
        return estimate_eer_cooling(t_ext, t_int, eta)

    @property
    def puissance_restituee_kw(self) -> float | None:
        mode = self.mode_fonctionnement
        if mode == MODE_CHAUFFAGE:
            rendement = self.cop_instantane
            capacite = self.kw_chaud
        elif mode == MODE_CLIMATISATION:
            rendement = self.eer_instantane
            capacite = self.kw_froid
        else:
            return None
        if rendement is None:
            return None
        puissance = self.puissance_absorbee_kw * rendement
        if capacite:
            puissance = min(puissance, capacite * 1.5)
        return round(puissance, 2)

    async def async_reset(self) -> None:
        """Remet à zéro tous les compteurs (ex: remplacement du compresseur)."""
        self._cancel_pending_off()
        self.initial_cycles = 0
        self.has_install_date = False
        self.total_cycles = 0
        self.measured_cycles = 0
        self.total_duration_min = 0.0
        self.last_cycle_duration_min = 0.0
        self.cycle_history = []
        self.daily_cycles = 0
        self.daily_energy_kwh = 0.0
        self.daily_thermal_energy_kwh = 0.0
        self.daily_dju = 0.0
        self.daily_dju_reel = 0.0
        self.daily_tracked_seconds = 0.0
        self.daily_tracked_reel_seconds = 0.0
        self.dju_history = []
        self.current_day = dt_util.now().date()
        self.start_date = dt_util.utcnow()
        self.is_running = False
        self.cycle_start = None

        now = dt_util.utcnow()
        self._last_energy_ts = now
        self._last_power_w = self._read_power_w()
        self._last_dju_ts = now
        self._last_outdoor_temp_c = self.temperature_exterieure
        self._last_indoor_temp_c = self.temperature_interieure_moyenne

        await self._async_save()
        self._notify()

        current = self.hass.states.get(self.power_sensor)
        if current is not None:
            self._evaluate_power(current)
