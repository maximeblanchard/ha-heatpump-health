"""Modèle thermodynamique simplifié pour l'estimation du COP/EER théorique.

Approche retenue : COP de Carnot théorique (limite thermodynamique idéale d'une
pompe à chaleur, cf. second principe de la thermodynamique), mis à l'échelle par
un facteur d'efficacité "eta" calibré une seule fois à partir du COP/EER NOMINAL
déclaré par le fabricant, au point de référence normalisé EN 14511 :
  - Chauffage : air extérieur 7°C / consigne intérieure 20°C  (point "A7")
  - Froid     : air extérieur 35°C / consigne intérieure 27°C (point "A35")

    COP_carnot(T_ext, T_int) = T_condenseur_K / (T_condenseur_K - T_evaporateur_K)
    eta = COP_nominal / COP_carnot(point de référence EN 14511)
    COP_théorique(T_ext, T_int) = eta × COP_carnot(T_ext, T_int) × correction_givre

En chauffage, une correction supplémentaire est appliquée dans la plage de
température où le givrage de l'unité extérieure dégrade les performances réelles
au-delà de la simple perte thermodynamique. Elle est basée sur la température du
thermomètre humide, calculée avec l'approximation de Stull (2011) — une formule
météorologique publique et générique, indépendante de tout fabricant.

⚠️ Ceci reste une ESTIMATION physique simplifiée, pas une mesure. Le COP/EER réel
dépend de nombreux facteurs non modélisés ici (givrage réel, charge partielle,
vieillissement, qualité d'installation, dégivrage actif, etc.). Précision indicative
uniquement — utile pour repérer des tendances et anomalies, pas comme valeur
métrologique.
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
# frigorigène à l'évaporateur/condenseur. Paramètre de modèle (non mesuré) — une
# pompe à chaleur réelle a un pincement thermique de cet ordre de grandeur.
APPROACH_DELTA = 5.0

# Zone de température extérieure où le givrage de l'unité extérieure dégrade le
# COP réel en chauffage, au-delà de la perte thermodynamique pure.
DEFROST_ZONE_LOW = -5.0
DEFROST_ZONE_HIGH = 8.0
DEFROST_MAX_DERATE = 0.25  # dégradation maximale (25%) au cœur de la zone à risque

# Bornes de sécurité pour éviter des valeurs aberrantes quand l'écart de
# température tend vers zéro (le COP de Carnot diverge mathématiquement).
COP_MIN_CLAMP = 0.5
COP_MAX_CLAMP = 10.0


def wet_bulb_stull(t_dry_c: float, rh_percent: float) -> float:
    """Température du thermomètre humide (approximation de Stull, 2011).

    Stull, R. (2011), "Wet-Bulb Temperature from Relative Humidity and Air
    Temperature", Journal of Applied Meteorology and Climatology, 50(11).
    Valide approximativement pour -20°C < T < 50°C et 5% < RH < 99%.
    """
    rh = max(min(rh_percent, 99.0), 5.0)
    t = t_dry_c
    return (
        t * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(t + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh**1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


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
    """Facteur de dégradation (0-1) lié au risque de givrage de l'unité extérieure."""
    if rh_percent is None:
        return 1.0
    if not (DEFROST_ZONE_LOW <= t_ext_c <= DEFROST_ZONE_HIGH):
        return 1.0
    tw = wet_bulb_stull(t_ext_c, rh_percent)
    # Risque maximal quand le thermomètre humide est proche de 0°C (formation de givre)
    risk = max(0.0, 1 - abs(tw) / 4.0)
    # Pondération triangulaire : plus faible aux bords de la zone à risque
    center = (DEFROST_ZONE_LOW + DEFROST_ZONE_HIGH) / 2
    half_width = (DEFROST_ZONE_HIGH - DEFROST_ZONE_LOW) / 2
    position_weight = max(0.0, 1 - abs(t_ext_c - center) / half_width)
    severity = risk * position_weight
    return 1 - DEFROST_MAX_DERATE * severity


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
