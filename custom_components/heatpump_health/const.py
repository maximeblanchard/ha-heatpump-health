"""Constantes pour l'intégration HeatPump-Health."""
from __future__ import annotations

DOMAIN = "heatpump_health"

# Clés de configuration
CONF_POWER_SENSOR = "power_sensor"
CONF_THRESHOLD_W = "threshold_w"
CONF_DELAY_OFF = "delay_off_seconds"
CONF_MAX_CYCLES = "max_cycles"
CONF_SEUIL_FAIBLE = "seuil_cycles_faible"
CONF_SEUIL_ELEVE = "seuil_cycles_eleve"
CONF_INSTALL_DATE = "install_date"
CONF_INITIAL_CYCLES = "initial_cycles"

# Données constructeur et entités pour le calcul de rendement (COP/EER théorique)
CONF_CLIMATE_ENTITY = "climate_entity"
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor"
CONF_OUTDOOR_HUMIDITY_SENSOR = "outdoor_humidity_sensor"
CONF_COP_NOMINAL = "cop_nominal"
CONF_EER_NOMINAL = "eer_nominal"
CONF_SCOP = "scop"
CONF_SEER = "seer"
CONF_KW_CHAUD = "kw_chaud"
CONF_KW_FROID = "kw_froid"

# Valeurs par défaut
DEFAULT_THRESHOLD_W = 50
DEFAULT_DELAY_OFF = 30
DEFAULT_MAX_CYCLES = 30000
DEFAULT_SEUIL_FAIBLE = 8
DEFAULT_SEUIL_ELEVE = 15
DEFAULT_INITIAL_CYCLES = 0

# Comportement interne
ROLLING_WINDOW_DAYS = 7
STORAGE_VERSION = 1
UPDATE_INTERVAL_SECONDS = 60  # rafraîchissement des capteurs "temps écoulé" pendant un cycle

# Signal dispatcher envoyé à chaque mise à jour des données
SIGNAL_UPDATE = f"{DOMAIN}_update"

# Niveaux de l'indice d'usure
NIVEAU_FAIBLE = "faible"
NIVEAU_MOYEN = "moyen"
NIVEAU_ELEVE = "eleve"

# Modes de fonctionnement dérivés de l'entité climate
MODE_CHAUFFAGE = "chauffage"
MODE_CLIMATISATION = "climatisation"
MODE_ARRET = "arret"
MODE_INCONNU = "inconnu"

