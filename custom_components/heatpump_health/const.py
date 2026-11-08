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

# Données constructeur, entités météo/intérieures & isolation du bâtiment
CONF_CLIMATE_ENTITY = "climate_entity"
CONF_INDOOR_TEMP_SENSORS = "indoor_temp_sensors"
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor"
CONF_OUTDOOR_HUMIDITY_SENSOR = "outdoor_humidity_sensor"
CONF_COP_NOMINAL = "cop_nominal"
CONF_EER_NOMINAL = "eer_nominal"
CONF_KW_CHAUD = "kw_chaud"
CONF_KW_FROID = "kw_froid"
CONF_SURFACE_M2 = "surface_m2"
CONF_CEILING_HEIGHT = "hauteur_plafond"

# Valeurs par défaut
DEFAULT_THRESHOLD_W = 50
DEFAULT_DELAY_OFF = 30
DEFAULT_MAX_CYCLES = 30000
DEFAULT_SEUIL_FAIBLE = 8
DEFAULT_SEUIL_ELEVE = 15
DEFAULT_INITIAL_CYCLES = 0
DEFAULT_CEILING_HEIGHT = 2.5

# Comportement interne
ROLLING_WINDOW_DAYS = 7
STORAGE_VERSION = 1
UPDATE_INTERVAL_SECONDS = 60  # rafraîchissement périodique (durée en cours, intégration kWh/DJU)
PERIODIC_SAVE_SECONDS = 900  # sauvegarde intermédiaire toutes les 15 min
MAX_INTEGRATION_GAP_SECONDS = 300  # plafond d'intégration (évite de compter une coupure HA)

# Suivi énergétique par DJU (norme Météo-France / COSTIC : base 18 °C + DJU réel sur T° int)
DJU_BASE_TEMP_C = 18.0
MIN_DJU_TODAY = 0.1  # seuil minimal de DJU accumulés sur le jour en cours pour afficher kWh/DJU
MIN_DJU_DAILY = 0.5  # seuil minimal de DJU sur une journée complète (évite le bruit hors saison)
MIN_TRACKED_HOURS_FOR_ARCHIVE = 18.0  # couverture minimale d'une journée pour consolider la veille

# Signal dispatcher envoyé à chaque mise à jour des données
SIGNAL_UPDATE = f"{DOMAIN}_update"

# Niveaux de l'indice d'usure
NIVEAU_FAIBLE = "faible"
NIVEAU_MOYEN = "moyen"
NIVEAU_ELEVE = "eleve"

# Niveaux d'isolation thermique (basés sur le coefficient G en W/(m³·K))
ISOLATION_TRES_PERFORMANT = "tres_performant"  # G <= 0.45 (RE2020 / Passif)
ISOLATION_TRES_BONNE = "tres_bonne"            # 0.45 < G <= 0.75 (RT2012 / BBC)
ISOLATION_BONNE = "bonne"                      # 0.75 < G <= 1.05 (RT2005 / RT2000)
ISOLATION_MOYENNE = "moyenne"                  # 1.05 < G <= 1.40 (Années 1980-1990)
ISOLATION_PASSOIRE = "passoire"                # G > 1.40 (Avant 1975)

# Modes de fonctionnement dérivés de l'entité climate
MODE_CHAUFFAGE = "chauffage"
MODE_CLIMATISATION = "climatisation"
MODE_ARRET = "arret"
MODE_INCONNU = "inconnu"
