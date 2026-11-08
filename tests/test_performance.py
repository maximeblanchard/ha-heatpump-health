"""Tests unitaires du modèle thermodynamique, du calcul des DJU et de la syntaxe du composant."""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
COMPONENT_DIR = ROOT_DIR / "custom_components" / "heatpump_health"

# Charge performance.py directement sans exiger l'installation complète de Home Assistant
_spec = importlib.util.spec_from_file_location(
    "heatpump_health_performance", COMPONENT_DIR / "performance.py"
)
assert _spec is not None and _spec.loader is not None
perf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = perf
_spec.loader.exec_module(perf)


def test_all_component_python_files_parse_cleanly() -> None:
    py_files = list(COMPONENT_DIR.glob("*.py"))
    assert len(py_files) >= 8
    for py_file in py_files:
        source = py_file.read_text(encoding="utf-8")
        ast.parse(source, filename=str(py_file))


def test_dew_point_magnus_at_saturation_equals_dry_bulb() -> None:
    assert perf.dew_point_magnus(5.0, 100.0) == pytest.approx(5.0, abs=1e-3)
    assert perf.dew_point_magnus(-2.0, 100.0) == pytest.approx(-2.0, abs=1e-3)


def test_calibration_matches_nominal_at_en14511_reference_points() -> None:
    eta_h = perf.calibrate_eta_heating(4.25)
    assert eta_h is not None
    assert perf.estimate_cop_heating(
        perf.HEATING_REF_T_EXT, perf.HEATING_REF_T_INT, eta_h, 87.0
    ) == 4.25
    assert perf.estimate_cop_heating(
        perf.HEATING_REF_T_EXT, perf.HEATING_REF_T_INT, eta_h, 30.0
    ) == 4.25

    eta_c = perf.calibrate_eta_cooling(3.91)
    assert eta_c is not None
    assert perf.estimate_eer_cooling(
        perf.COOLING_REF_T_EXT, perf.COOLING_REF_T_INT, eta_c
    ) == 3.91


def test_defrost_factor_penalizes_humid_cold_not_dry_air() -> None:
    # Air froid mais sec (HR 30-40%) : point de rosée sous la température batterie -> pas de givre
    assert perf.defrost_factor(5.0, 30.0) == 1.0
    assert perf.defrost_factor(1.5, 40.0) == 1.0

    # Brouillard givrant vers +1.5°C / HR 98% : forte pénalité de dégivrage
    fog_factor = perf.defrost_factor(1.5, 98.0)
    assert 0.75 <= fog_factor < 0.80

    # Pluie froide humide à +5°C / HR 95% : dégradation modérée mais bien présente
    damp_5c = perf.defrost_factor(5.0, 95.0)
    assert 0.88 <= damp_5c < 0.96

    # Hors zone de givrage ou sans capteur d'humidité -> aucune pénalité
    assert perf.defrost_factor(10.0, 99.0) == 1.0
    assert perf.defrost_factor(-10.0, 95.0) == 1.0
    assert perf.defrost_factor(1.5, None) == 1.0


def test_cop_clamping_on_extreme_temperatures() -> None:
    eta_h = perf.calibrate_eta_heating(4.5)
    assert eta_h is not None
    assert perf.estimate_cop_heating(19.0, 20.0, eta_h, 50.0) == perf.COP_MAX_CLAMP
    assert perf.estimate_cop_heating(35.0, 20.0, eta_h, 50.0) is None
    cop_cold = perf.estimate_cop_heating(-25.0, 22.0, eta_h, 80.0)
    assert cop_cold is not None
    assert cop_cold >= perf.COP_MIN_CLAMP


def test_incremental_dju_base_18_and_real_indoor_temp() -> None:
    # Base 18°C standard
    assert perf.incremental_dju(8.0, 86400.0) == pytest.approx(10.0)
    assert perf.incremental_dju(8.0, 43200.0) == pytest.approx(5.0)
    assert perf.incremental_dju(18.0, 86400.0) == 0.0
    assert perf.incremental_dju(24.5, 86400.0) == 0.0
    assert perf.incremental_dju(0.0, 0.0) == 0.0

    # DJU réel basé sur la température intérieure moyenne (ex: 21.5°C int, 8.0°C ext -> 13.5 DJU/24h)
    assert perf.incremental_dju(8.0, 86400.0, base_temp_c=21.5) == pytest.approx(13.5)
    assert perf.incremental_dju(22.0, 86400.0, base_temp_c=21.5) == 0.0


def test_heat_loss_h_and_g_calculation() -> None:
    # Maison de 100 m² / hauteur 2.5m = volume 250 m³
    # 96 kWh thermiques consommés sur 20 DJU
    # H = (96 / 20) * (1000 / 24) = 4.8 * 41.6667 = 200.0 W/K
    h = perf.calculate_heat_loss_h(96.0, 20.0)
    assert h == pytest.approx(200.0, abs=0.1)

    # G = H / Volume = 200 / 250 = 0.80 W/(m³·K)
    g = perf.calculate_heat_loss_g(h, 250.0)
    assert g == 0.80

    # Cas limites
    assert perf.calculate_heat_loss_h(0.0, 10.0) is None
    assert perf.calculate_heat_loss_h(50.0, 0.0) is None
    assert perf.calculate_heat_loss_g(200.0, 0.0) is None
