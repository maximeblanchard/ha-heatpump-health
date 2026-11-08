"""Modèle thermodynamique simplifié (COP/EER théorique), DJU et isolation (H & G).

Approche retenue pour le COP/EER : COP de Carnot théorique (limite thermodynamique
idéale d'une pompe à chaleur, cf. second principe de la thermodynamique), mis à
l'échelle par un facteur d'efficacité "eta" calibré une seule fois à partir du
COP/EER NOMINAL déclaré par le fabricant, au point de référence normalisé EN 14511
pour une PAC air/air :
  - Chauffage : air extérieur 7°C / air intérieur 20°C  (point "A7/A20")
  - Froid     : air extérieur 35°C / air intérieur 27°C (point "A35/A27")

    COP_carnot(T_ext, T_int) = T_condenseur_K / (T_condenseur_K - T_evaporateur_K)
    eta = COP_nominal / COP_carnot(point de référence EN 14511)
    COP_théorique(T_ext, T_int) = eta × COP_carnot(T_ext, T_int) × correction_givre

En chauffage, une correction de givrage dégrade le COP dans la plage [-7°C, +7°C]
uniquement lorsque le point de rosée de l'air extérieur (formule de Magnus-Tetens)
dépasse la température estimée de la batterie extérieure sous 0°C (air froid ET
humide, typiquement HR > ~68-70%).

Pour le suivi énergétique quotidien, les Degrés-Jours Unifiés (DJU) de chauffage
sont intégrés en continu :
- DJU standard : base 18°C (norme Météo-France / COSTIC)
- DJU réel : basé sur la température intérieure moyenne mesurée (T_int - T_ext)

La déperdition thermique globale H (W/K) et le coefficient volumique G (W/(m³·K))
quantifient l'isolation thermique du logement :
  H (W/K) = (Q_thermique_kWh / DJU) × (1000 / 24)
  G (W/(m³·K)) = H / Volume

⚠️ Le COP/EER reste une ESTIMATION physique simplifiée (calibrée pour l'air/air ;
plus approximative sur une PAC air/eau en loi d'eau), pas une mesure métrologique.
"""
from __future__ import annotations

import math

KELVIN_OFFSET = 273.15

# Points de référence EN 14511 (air/air), utilisés pour calibrer le modèle sur les
# valeurs nominales déclarées par le fabricant.
HEATING_REF_T_EXT = 7.0
HEATING_REF_T_INT = 20.0
COOLING_REF_T_EXT = 35.0
COOLING_REF_T_INT = 27.0

# Écart approximatif entre la température de l'air et la température du fluide
# frigorigène à l'évaporateur/condenseur (pincement thermique typique).
APPROACH_DELTA = 5.0

# Zone de température extérieure où la batterie extérieure descend sous 0°C tout en
# brassant un air suffisamment chargé en humidité absolue pour givrer fortement.
DEFROST_ZONE_LOW = -7.0
DEFROST_ZONE_HIGH = 7.0
DEFROST_PEAK_TEMP = 1.5  # zone critique (+1°C/+2°C) où le givrage réel est maximal
DEFROST_MAX_DERATE = 0.25  # dégradation maximale (25%) par brouillard givrant

# Bornes de sécurité pour éviter des valeurs aberrantes quand l'écart de
# température tend vers zéro (le COP de Carnot diverge mathématiquement).
COP_MIN_CLAMP = 0.5
COP_MAX_CLAMP = 10.0

# Température de base standard pour les DJU chauffage (Météo-France / COSTIC)
DJU_BASE_TEMP_C = 18.0


def dew_point_magnus(t_dry_c: float, rh_percent: float) -> float:
    """Température du point de rosée en °C (formule de Magnus-Tetens, OMM).

    Valide sur -40°C .. +50°C avec une incertitude typique < 0,2°C.
    """
    rh = max(min(rh_percent, 100.0), 1.0)
    a = 17.625
    b = 243.04
    gamma = (a * t_dry_c) / (b + t_dry_c) + math.log(rh / 100.0)
    return (b * gamma) / (a - gamma)


def _carnot_ratio_heating(t_ext_c: float, t_int_c: float) -> float | None:
    t_evap_k = (t_ext_c - APPROACH_DELTA) + KELVIN_OFFSET
    t_cond_k = (t_int_c + APPROACH_DELTA) + KELVIN_OFFSET
    delta = t_cond_k - t_evap_k
    if delta <= 0.5:
        return None
    return t_cond_k / delta


def _carnot_ratio_cooling(t_ext_c: float, t_int_c: float) -> float | None:
    t_evap_k = (t_int_c - APPROACH_DELTA) + KELVIN_OFFSET
    t_cond_k = (t_ext_c + APPROACH_DELTA) + KELVIN_OFFSET
    delta = t_cond_k - t_evap_k
    if delta <= 0.5:
        return None
    return t_evap_k / delta


def calibrate_eta_heating(cop_nominal: float) -> float | None:
    """Calcule le facteur d'efficacité réel/Carnot à partir du COP nominal."""
    ref = _carnot_ratio_heating(HEATING_REF_T_EXT, HEATING_REF_T_INT)
    if not ref:
        return None
    return cop_nominal / ref


def calibrate_eta_cooling(eer_nominal: float) -> float | None:
    """Calcule le facteur d'efficacité réel/Carnot à partir de l'EER nominal."""
    ref = _carnot_ratio_cooling(COOLING_REF_T_EXT, COOLING_REF_T_INT)
    if not ref:
        return None
    return eer_nominal / ref


def defrost_factor(t_ext_c: float, rh_percent: float | None) -> float:
    """Facteur de dégradation (0.75-1.0) lié au givrage de l'unité extérieure.

    Le givre n'apparaît que si la batterie est sous 0°C (T_coil = T_ext - 5K <= 0)
    ET si le point de rosée de l'air extérieur dépasse T_coil (condensation de la
    vapeur d'eau sur les ailettes gelées, soit HR > ~68-70%).
    """
    if rh_percent is None:
        return 1.0
    if not (DEFROST_ZONE_LOW < t_ext_c < DEFROST_ZONE_HIGH):
        return 1.0

    t_coil = t_ext_c - APPROACH_DELTA
    if t_coil > 0.0:
        return 1.0

    t_dew = dew_point_magnus(t_ext_c, rh_percent)
    moisture_excess = t_dew - t_coil
    if moisture_excess <= 0.0:
        return 1.0
    moisture_risk = min(moisture_excess / APPROACH_DELTA, 1.0)

    if t_ext_c >= DEFROST_PEAK_TEMP:
        temp_weight = (DEFROST_ZONE_HIGH - t_ext_c) / (DEFROST_ZONE_HIGH - DEFROST_PEAK_TEMP)
    else:
        temp_weight = (t_ext_c - DEFROST_ZONE_LOW) / (DEFROST_PEAK_TEMP - DEFROST_ZONE_LOW)

    severity = max(0.0, min(moisture_risk * temp_weight, 1.0))
    return 1.0 - DEFROST_MAX_DERATE * severity


def estimate_cop_heating(
    t_ext_c: float, t_int_c: float, eta_heating: float, rh_percent: float | None
) -> float | None:
    """COP théorique instantané en mode chauffage."""
    ratio = _carnot_ratio_heating(t_ext_c, t_int_c)
    if ratio is None:
        return None
    cop = eta_heating * ratio * defrost_factor(t_ext_c, rh_percent)
    return round(min(max(cop, COP_MIN_CLAMP), COP_MAX_CLAMP), 2)


def estimate_eer_cooling(t_ext_c: float, t_int_c: float, eta_cooling: float) -> float | None:
    """EER théorique instantané en mode climatisation."""
    ratio = _carnot_ratio_cooling(t_ext_c, t_int_c)
    if ratio is None:
        return None
    eer = eta_cooling * ratio
    return round(min(max(eer, COP_MIN_CLAMP), COP_MAX_CLAMP), 2)


def incremental_dju(
    t_ext_c: float, dt_seconds: float, base_temp_c: float = DJU_BASE_TEMP_C
) -> float:
    """Fraction de DJU accumulée pendant un pas de temps dt_seconds."""
    if dt_seconds <= 0.0 or t_ext_c >= base_temp_c:
        return 0.0
    return (base_temp_c - t_ext_c) * (dt_seconds / 86400.0)


def calculate_heat_loss_h(kwh_th: float, dju: float) -> float | None:
    """Déperdition thermique globale H (W/K) = (Q_thermique_kWh / DJU) * (1000 / 24)."""
    if dju <= 0.0 or kwh_th <= 0.0:
        return None
    return round((kwh_th / dju) * (1000.0 / 24.0), 1)


def calculate_heat_loss_g(h_w_k: float, volume_m3: float) -> float | None:
    """Coefficient de déperdition volumique G (W/(m³·K)) = H / Volume."""
    if volume_m3 <= 0.0 or h_w_k <= 0.0:
        return None
    return round(h_w_k / volume_m3, 2)
