"""Cœur de la logique : détection des cycles marche/arrêt et calcul des indicateurs."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, State, callback
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
    MODE_ARRET,
    MODE_CHAUFFAGE,
    MODE_CLIMATISATION,
    MODE_INCONNU,
    ROLLING_WINDOW_DAYS,
    SIGNAL_UPDATE,
    STORAGE_VERSION,
    UPDATE_INTERVAL_SECONDS,
)
from .performance import (
    calibrate_eta_cooling,
    calibrate_eta_heating,
    estimate_cop_heating,
    estimate_eer_cooling,
)

_LOGGER = logging.getLogger(__name__)


class HeatPumpHealthTracker:
    """Suit l'état marche/arrêt de la PAC et maintient les statistiques d'usure."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")

        self._unsub_state: CALLBACK_TYPE | None = None
        self._unsub_interval: CALLBACK_TYPE | None = None
        self._unsub_midnight: CALLBACK_TYPE | None = None
        self._unsub_pending_off: CALLBACK_TYPE | None = None
        self._unsub_performance: CALLBACK_TYPE | None = None

        self.is_running: bool = False
        self.cycle_start: datetime | None = None
        self.total_cycles: int = 0
        self.total_duration_min: float = 0.0
        self.last_cycle_duration_min: float = 0.0
        self.start_date: datetime = dt_util.utcnow()
        self.current_day: date = dt_util.now().date()
        self.daily_cycles: int = 0
        self.cycle_history: list[dict[str, Any]] = []  # [{"end": iso, "duration_min": float}]

    # ------------------------------------------------------------------ #
    # Configuration (options modifiables après coup via l'Options Flow)
    # ------------------------------------------------------------------ #
    @property
    def power_sensor(self) -> str:
        return self.entry.data[CONF_POWER_SENSOR]

    @property
    def threshold_w(self) -> float:
        return self.entry.options.get(
            CONF_THRESHOLD_W, self.entry.data.get(CONF_THRESHOLD_W, DEFAULT_THRESHOLD_W)
        )

    @property
    def delay_off(self) -> int:
        return self.entry.options.get(
            CONF_DELAY_OFF, self.entry.data.get(CONF_DELAY_OFF, DEFAULT_DELAY_OFF)
        )

    @property
    def max_cycles(self) -> int:
        return self.entry.options.get(
            CONF_MAX_CYCLES, self.entry.data.get(CONF_MAX_CYCLES, DEFAULT_MAX_CYCLES)
        )

    @property
    def seuil_faible(self) -> float:
        return self.entry.options.get(
            CONF_SEUIL_FAIBLE, self.entry.data.get(CONF_SEUIL_FAIBLE, DEFAULT_SEUIL_FAIBLE)
        )

    @property
    def seuil_eleve(self) -> float:
        return self.entry.options.get(
            CONF_SEUIL_ELEVE, self.entry.data.get(CONF_SEUIL_ELEVE, DEFAULT_SEUIL_ELEVE)
        )

    # -- Rendement (COP/EER théorique) -- #
    @property
    def climate_entity(self) -> str | None:
        return self.entry.data.get(CONF_CLIMATE_ENTITY)

    @property
    def outdoor_temp_sensor(self) -> str | None:
        return self.entry.data.get(CONF_OUTDOOR_TEMP_SENSOR)

    @property
    def outdoor_humidity_sensor(self) -> str | None:
        return self.entry.data.get(CONF_OUTDOOR_HUMIDITY_SENSOR)

    @property
    def cop_nominal(self) -> float | None:
        value = self.entry.options.get(CONF_COP_NOMINAL, self.entry.data.get(CONF_COP_NOMINAL))
        return float(value) if value is not None else None

    @property
    def eer_nominal(self) -> float | None:
        value = self.entry.options.get(CONF_EER_NOMINAL, self.entry.data.get(CONF_EER_NOMINAL))
        return float(value) if value is not None else None

    @property
    def kw_chaud(self) -> float | None:
        value = self.entry.options.get(CONF_KW_CHAUD, self.entry.data.get(CONF_KW_CHAUD))
        return float(value) if value is not None else None

    @property
    def kw_froid(self) -> float | None:
        value = self.entry.options.get(CONF_KW_FROID, self.entry.data.get(CONF_KW_FROID))
        return float(value) if value is not None else None

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
    def performance_entities(self) -> list[str]:
        """Entités à surveiller pour rafraîchir le calcul de rendement."""
        return [
            e
            for e in (self.climate_entity, self.outdoor_temp_sensor, self.outdoor_humidity_sensor)
            if e
        ]

    # ------------------------------------------------------------------ #
    # Cycle de vie de l'intégration
    # ------------------------------------------------------------------ #
    async def async_setup(self) -> None:
        """Charge les données persistées et démarre l'écoute du capteur de puissance."""
        await self._async_load()

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

        # Si la PAC tourne déjà au démarrage de HA, on ne rate pas l'état courant
        current = self.hass.states.get(self.power_sensor)
        if current is not None:
            self._evaluate_power(current)

    async def async_unload(self) -> None:
        """Coupe tous les écouteurs (déchargement/rechargement de l'entrée)."""
        for unsub in (
            self._unsub_state,
            self._unsub_interval,
            self._unsub_midnight,
            self._unsub_pending_off,
            self._unsub_performance,
        ):
            if unsub is not None:
                unsub()

    # ------------------------------------------------------------------ #
    # Persistance (survit aux redémarrages de Home Assistant)
    # ------------------------------------------------------------------ #
    async def _async_load(self) -> None:
        stored = await self._store.async_load()
        if stored is None:
            # Première installation : on initialise depuis les valeurs du config_flow
            self.total_cycles = self.entry.data.get(CONF_INITIAL_CYCLES, DEFAULT_INITIAL_CYCLES)
            install_date = self.entry.data.get(CONF_INSTALL_DATE)
            if install_date:
                parsed = dt_util.parse_date(install_date)
                self.start_date = dt_util.start_of_local_day(parsed) if parsed else dt_util.utcnow()
            else:
                self.start_date = dt_util.utcnow()
            self.current_day = dt_util.now().date()
            await self._async_save()
            return

        self.total_cycles = stored.get("total_cycles", 0)
        self.total_duration_min = stored.get("total_duration_min", 0.0)
        self.last_cycle_duration_min = stored.get("last_cycle_duration_min", 0.0)
        self.start_date = dt_util.parse_datetime(stored["start_date"]) or dt_util.utcnow()
        self.current_day = dt_util.parse_date(stored["current_day"]) or dt_util.now().date()
        self.daily_cycles = stored.get("daily_cycles", 0)
        self.cycle_history = stored.get("cycle_history", [])
        self.is_running = stored.get("is_running", False)
        cycle_start = stored.get("cycle_start")
        self.cycle_start = dt_util.parse_datetime(cycle_start) if cycle_start else None

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "total_cycles": self.total_cycles,
                "total_duration_min": self.total_duration_min,
                "last_cycle_duration_min": self.last_cycle_duration_min,
                "start_date": self.start_date.isoformat(),
                "current_day": self.current_day.isoformat(),
                "daily_cycles": self.daily_cycles,
                "cycle_history": self.cycle_history,
                "is_running": self.is_running,
                "cycle_start": self.cycle_start.isoformat() if self.cycle_start else None,
            }
        )

    def _schedule_save(self) -> None:
        self.hass.async_create_task(self._async_save(), name="heatpump_health_save")

    # ------------------------------------------------------------------ #
    # Détection marche / arrêt
    # ------------------------------------------------------------------ #
    @callback
    def _handle_power_event(self, event) -> None:
        new_state: State | None = event.data.get("new_state")
        if new_state is None:
            return
        self._evaluate_power(new_state)

    @callback
    def _handle_performance_event(self, event) -> None:
        """La météo, l'humidité ou le mode climate a changé : on rafraîchit le rendement."""
        self._notify()

    def _evaluate_power(self, state: State) -> None:
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return

        above_threshold = value > self.threshold_w

        if above_threshold:
            # Une remontée de puissance annule un arrêt en attente (dégivrage,
            # modulation) et démarre un cycle si la PAC était réellement à l'arrêt.
            self._cancel_pending_off()
            if not self.is_running:
                self._start_cycle()
        elif self.is_running and self._unsub_pending_off is None:
            self._schedule_pending_off()

    def _start_cycle(self) -> None:
        self.is_running = True
        self.cycle_start = dt_util.utcnow()
        self.total_cycles += 1
        self._maybe_reset_daily_counter()
        self.daily_cycles += 1
        self._schedule_save()
        self._notify()

    def _schedule_pending_off(self) -> None:
        self._unsub_pending_off = async_call_later(self.hass, self.delay_off, self._confirm_off)

    def _cancel_pending_off(self) -> None:
        if self._unsub_pending_off is not None:
            self._unsub_pending_off()
            self._unsub_pending_off = None

    @callback
    def _confirm_off(self, _now) -> None:
        self._unsub_pending_off = None
        if not self.is_running or self.cycle_start is None:
            return

        end = dt_util.utcnow()
        duration_min = (end - self.cycle_start).total_seconds() / 60
        self.is_running = False
        self.last_cycle_duration_min = round(duration_min, 2)
        self.total_duration_min += duration_min
        self.cycle_history.append({"end": end.isoformat(), "duration_min": duration_min})
        self._prune_history()
        self.cycle_start = None
        self._schedule_save()
        self._notify()

    # ------------------------------------------------------------------ #
    # Entretien périodique
    # ------------------------------------------------------------------ #
    @callback
    def _handle_periodic_refresh(self, _now) -> None:
        """Rafraîchit les capteurs pendant qu'un cycle est en cours (temps écoulé)."""
        if self.is_running:
            self._notify()

    @callback
    def _handle_midnight(self, _now) -> None:
        self._maybe_reset_daily_counter()
        self._prune_history()
        self._schedule_save()
        self._notify()

    def _maybe_reset_daily_counter(self) -> None:
        today = dt_util.now().date()
        if today != self.current_day:
            self.current_day = today
            self.daily_cycles = 0

    def _prune_history(self) -> None:
        cutoff = dt_util.utcnow() - timedelta(days=ROLLING_WINDOW_DAYS)
        pruned = []
        for item in self.cycle_history:
            end = dt_util.parse_datetime(item["end"])
            if end and end > cutoff:
                pruned.append(item)
        self.cycle_history = pruned

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    # ------------------------------------------------------------------ #
    # Indicateurs exposés aux entités sensor.*
    # ------------------------------------------------------------------ #
    @property
    def current_cycle_elapsed_min(self) -> float:
        if not self.is_running or self.cycle_start is None:
            return 0.0
        return (dt_util.utcnow() - self.cycle_start).total_seconds() / 60

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
        return len(self.cycle_history)

    @property
    def temps_fonctionnement_7j_h(self) -> float:
        total = sum(item["duration_min"] for item in self.cycle_history)
        return round(total / 60, 2)

    @property
    def duree_moyenne_cycle_7j_min(self) -> float:
        if not self.cycle_history:
            return 0.0
        total = sum(item["duration_min"] for item in self.cycle_history)
        return round(total / len(self.cycle_history), 2)

    @property
    def duree_moyenne_cycle_totale_min(self) -> float:
        if self.total_cycles <= 0:
            return 0.0
        return round(self.total_duration_min / self.total_cycles, 2)

    @property
    def jours_depuis_installation(self) -> float:
        delta = dt_util.utcnow() - self.start_date
        return max(delta.total_seconds() / 86400, 0.01)

    @property
    def taux_usure_quotidien_cycles(self) -> float:
        return round(self.total_cycles / self.jours_depuis_installation, 2)

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
            return "eleve"
        if moyenne_jour >= self.seuil_faible:
            return "moyen"
        return "faible"

    # ------------------------------------------------------------------ #
    # Rendement (COP/EER théorique) — lecture live des entités sources
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
            return MODE_INCONNU
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

        # hvac_action indisponible : on retombe sur le mode demandé (moins précis
        # en mode "auto"/"heat_cool", où le sens réel n'est pas déterminable ici)
        if state.state == "heat":
            return MODE_CHAUFFAGE
        if state.state == "cool":
            return MODE_CLIMATISATION
        if state.state == "off":
            return MODE_ARRET
        return MODE_INCONNU

    @property
    def consigne_climate(self) -> float | None:
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
    def puissance_absorbee_kw(self) -> float:
        state = self.hass.states.get(self.power_sensor)
        if state is None:
            return 0.0
        try:
            return max(float(state.state), 0.0) / 1000
        except (ValueError, TypeError):
            return 0.0

    @property
    def cop_instantane(self) -> float | None:
        if not self.is_running or self.mode_fonctionnement != MODE_CHAUFFAGE:
            return None
        eta = self.eta_heating
        t_ext = self.temperature_exterieure
        t_int = self.consigne_climate
        if eta is None or t_ext is None or t_int is None:
            return None
        return estimate_cop_heating(t_ext, t_int, eta, self.humidite_exterieure)

    @property
    def eer_instantane(self) -> float | None:
        if not self.is_running or self.mode_fonctionnement != MODE_CLIMATISATION:
            return None
        eta = self.eta_cooling
        t_ext = self.temperature_exterieure
        t_int = self.consigne_climate
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
        self.total_cycles = 0
        self.total_duration_min = 0.0
        self.last_cycle_duration_min = 0.0
        self.cycle_history = []
        self.daily_cycles = 0
        self.current_day = dt_util.now().date()
        self.start_date = dt_util.utcnow()
        self.is_running = False
        self.cycle_start = None
        self._cancel_pending_off()
        await self._async_save()
        self._notify()
