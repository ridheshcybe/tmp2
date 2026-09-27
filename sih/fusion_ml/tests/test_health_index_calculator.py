#!/usr/bin/env python3
"""
Unit tests for fusion_ml.health_index_calculator.HealthIndexCalculator

Run:
    pytest -v fusion_ml/tests/test_health_index_calculator.py
"""

from __future__ import annotations

import pytest

from fusion_ml.health_index_calculator import (
    HealthIndexCalculator,
    HealthReport,
    HealthStatus,
    NOMINAL,
    THRESHOLDS,
)


# ══════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════

def _nominal_frame(**overrides) -> dict:
    """Build a healthy nominal engine frame."""
    base = {
        "rpm": 2200, "map_kpa": 78, "fuel_flow_lph": 13.0,
        "cht_c": [178.0, 177.0, 179.0, 176.0],
        "egt_c": [740.0, 738.0, 742.0, 736.0],
        "oil_pressure_kpa": 410.0, "oil_temp_c": 88.0,
        "vibration_rms_g": 1.45, "equivalence_ratio": 0.85,
    }
    base.update(overrides)
    return base


def _faulty_lean_burn_frame() -> dict:
    """Simulate LEAN_BURN_RUNAWAY: high EGT, high CHT, low fuel."""
    return {
        "rpm": 1950, "map_kpa": 60, "fuel_flow_lph": 7.0,
        "cht_c": [248.0, 245.0, 250.0, 243.0],
        "egt_c": [900.0, 895.0, 905.0, 890.0],
        "oil_pressure_kpa": 350.0, "oil_temp_c": 110.0,
        "vibration_rms_g": 1.85, "equivalence_ratio": 0.58,
    }


def _faulty_piston_ring_frame() -> dict:
    """Simulate PISTON_RING_WEAR: low RPM, high vibration, high oil temp."""
    return {
        "rpm": 1700, "map_kpa": 70, "fuel_flow_lph": 16.0,
        "cht_c": [200.0, 230.0, 195.0, 225.0],  # high spread
        "egt_c": [780.0, 810.0, 770.0, 800.0],
        "oil_pressure_kpa": 200.0, "oil_temp_c": 130.0,
        "vibration_rms_g": 2.1, "equivalence_ratio": 0.82,
    }


# ══════════════════════════════════════════════════════════════════
#  1.  Basic output structure
# ══════════════════════════════════════════════════════════════════

class TestOutputStructure:
    """Verify output dict has all required keys and valid types."""

    def test_output_has_required_keys(self):
        calc = HealthIndexCalculator()
        result = calc.compute(raw_frame=_nominal_frame())
        required = {
            "engine_health_index", "combustion_efficiency",
            "thermal_balance_spread", "health_status",
        }
        assert required.issubset(set(result.keys())), (
            f"Missing keys: {required - set(result.keys())}"
        )

    def test_output_has_sub_indices(self):
        calc = HealthIndexCalculator()
        result = calc.compute(raw_frame=_nominal_frame())
        assert "thermal_strain_index" in result
        assert "mechanical_stress_index" in result
        assert "lubrication_health" in result
        assert "model_anomaly_residual" in result

    def test_ehi_in_valid_range(self):
        calc = HealthIndexCalculator()
        result = calc.compute(raw_frame=_nominal_frame())
        ehi = result["engine_health_index"]
        assert 0.0 <= ehi <= 100.0, f"EHI = {ehi}, expected 0–100"

    def test_health_status_valid(self):
        calc = HealthIndexCalculator()
        result = calc.compute(raw_frame=_nominal_frame())
        assert result["health_status"] in {
            HealthStatus.NORMAL, HealthStatus.DEGRADED, HealthStatus.CRITICAL,
        }

    def test_combustion_efficiency_range(self):
        calc = HealthIndexCalculator()
        result = calc.compute(raw_frame=_nominal_frame())
        assert 0.0 <= result["combustion_efficiency"] <= 100.0


# ══════════════════════════════════════════════════════════════════
#  2.  Nominal frame → healthy
# ══════════════════════════════════════════════════════════════════

class TestNominalHealthy:
    """A nominal frame should produce a high EHI and NORMAL status."""

    def test_ehi_above_70(self):
        calc = HealthIndexCalculator()
        result = calc.compute(raw_frame=_nominal_frame())
        assert result["engine_health_index"] >= 70.0, (
            f"Nominal EHI = {result['engine_health_index']}, expected ≥ 70"
        )

    def test_status_normal(self):
        calc = HealthIndexCalculator()
        result = calc.compute(raw_frame=_nominal_frame())
        assert result["health_status"] == HealthStatus.NORMAL


# ══════════════════════════════════════════════════════════════════
#  3.  LEAN_BURN_RUNAWAY → EHI drops below 60%
# ══════════════════════════════════════════════════════════════════

class TestLeanBurnRunaway:
    """Verify EHI drops smoothly below 60% during lean burn fault."""

    def test_ehi_below_60(self):
        """Progressive lean burn must push EHI below 60%."""
        calc = HealthIndexCalculator()
        frame = _faulty_lean_burn_frame()
        result = calc.compute(raw_frame=frame)
        assert result["engine_health_index"] < 60.0, (
            f"Lean burn EHI = {result['engine_health_index']}, "
            f"expected < 60"
        )

    def test_status_not_normal(self):
        calc = HealthIndexCalculator()
        result = calc.compute(raw_frame=_faulty_lean_burn_frame())
        assert result["health_status"] != HealthStatus.NORMAL

    def test_egt_spikes(self):
        """Lean burn should cause EGT to spike above alarm."""
        calc = HealthIndexCalculator()
        frame = _faulty_lean_burn_frame()
        result = calc.compute(raw_frame=frame)
        # Thermal strain should be low (high temps = low health)
        assert result["thermal_strain_index"] < 60.0, (
            f"Thermal strain = {result['thermal_strain_index']}, "
            f"expected < 60 for lean burn"
        )

    def test_progressive_degradation(self):
        """EHI should decrease progressively as lean burn worsens."""
        calc = HealthIndexCalculator()
        ehis = []

        # Progressively worsen EGT/CHT
        for egt_boost in [0, 30, 60, 90, 120]:
            frame = _nominal_frame()
            base_egt = [740.0, 738.0, 742.0, 736.0]
            base_cht = [178.0, 177.0, 179.0, 176.0]
            frame["egt_c"] = [e + egt_boost for e in base_egt]
            frame["cht_c"] = [c + egt_boost * 0.4 for c in base_cht]
            frame["fuel_flow_lph"] = 13.0 - egt_boost * 0.04
            result = calc.compute(raw_frame=frame)
            ehis.append(result["engine_health_index"])

        # EHI should be monotonically decreasing
        for i in range(len(ehis) - 1):
            assert ehis[i] >= ehis[i + 1], (
                f"EHI not decreasing: {ehis[i]:.1f} → {ehis[i+1]:.1f}"
            )

        # Final EHI should be below 60
        assert ehis[-1] < 60.0, (
            f"Final lean burn EHI = {ehis[-1]:.1f}, expected < 60"
        )


# ══════════════════════════════════════════════════════════════════
#  4.  PISTON_RING_WEAR → EHI drops below 60%
# ══════════════════════════════════════════════════════════════════

class TestPistonRingWear:
    """Verify EHI drops below 60% during piston ring wear fault."""

    def test_ehi_below_60(self):
        calc = HealthIndexCalculator()
        frame = _faulty_piston_ring_frame()
        result = calc.compute(raw_frame=frame)
        assert result["engine_health_index"] < 60.0, (
            f"Piston ring wear EHI = {result['engine_health_index']}, "
            f"expected < 60"
        )

    def test_vibration_high(self):
        calc = HealthIndexCalculator()
        frame = _faulty_piston_ring_frame()
        result = calc.compute(raw_frame=frame)
        assert result["mechanical_stress_index"] < 70.0, (
            f"Mechanical stress = {result['mechanical_stress_index']}, "
            f"expected < 70 for ring wear"
        )

    def test_thermal_imbalance_high(self):
        """Ring wear causes uneven cylinder temperatures."""
        calc = HealthIndexCalculator()
        frame = _faulty_piston_ring_frame()
        result = calc.compute(raw_frame=frame)
        assert result["thermal_balance_spread"] > 5.0, (
            f"Thermal balance spread = {result['thermal_balance_spread']}, "
            f"expected > 5 for ring wear"
        )

    def test_progressive_degradation(self):
        """EHI should decrease progressively as ring wear worsens."""
        calc = HealthIndexCalculator()
        ehis = []

        for vib in [1.5, 1.8, 2.0, 2.3, 2.6]:
            frame = _nominal_frame()
            frame["vibration_rms_g"] = vib
            frame["rpm"] = 2200 - (vib - 1.5) * 400
            frame["oil_temp_c"] = 88 + (vib - 1.5) * 30
            result = calc.compute(raw_frame=frame)
            ehis.append(result["engine_health_index"])

        for i in range(len(ehis) - 1):
            assert ehis[i] >= ehis[i + 1]

        assert ehis[-1] < 60.0


# ══════════════════════════════════════════════════════════════════
#  5.  Combustion Degradation Metric
# ══════════════════════════════════════════════════════════════════

class TestCombustionDegradationMetric:
    """CDM should reflect BSFC quality."""

    def test_nominal_cdm_high(self):
        calc = HealthIndexCalculator()
        result = calc.compute(raw_frame=_nominal_frame())
        assert result["combustion_efficiency"] >= 70.0

    def test_zero_fuel_gives_zero_cdm(self):
        calc = HealthIndexCalculator()
        frame = _nominal_frame(fuel_flow_lph=0.0)
        result = calc.compute(raw_frame=frame)
        assert result["combustion_efficiency"] == 0.0

    def test_lean_burn_cdm_drops(self):
        """Lean burn reduces combustion efficiency."""
        calc = HealthIndexCalculator()
        normal = calc.compute(raw_frame=_nominal_frame())
        faulty = calc.compute(raw_frame=_faulty_lean_burn_frame())
        assert faulty["combustion_efficiency"] < normal["combustion_efficiency"]


# ══════════════════════════════════════════════════════════════════
#  6.  Cylinder Thermal Balance
# ══════════════════════════════════════════════════════════════════

class TestCylinderThermalBalance:
    """Thermal balance should detect cylinder imbalance."""

    def test_balanced_cylinders_low_spread(self):
        calc = HealthIndexCalculator()
        frame = _nominal_frame()
        result = calc.compute(raw_frame=frame)
        assert result["thermal_balance_spread"] < 5.0, (
            f"Nominal spread = {result['thermal_balance_spread']}, "
            f"expected < 5"
        )

    def test_imbalanced_cylinders_high_spread(self):
        calc = HealthIndexCalculator()
        frame = _nominal_frame()
        frame["cht_c"] = [170.0, 240.0, 175.0, 230.0]  # high spread
        result = calc.compute(raw_frame=frame)
        assert result["thermal_balance_spread"] > 15.0


# ══════════════════════════════════════════════════════════════════
#  7.  Edge cases
# ══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Boundary conditions and error handling."""

    def test_zero_rpm(self):
        """Zero RPM should not crash."""
        calc = HealthIndexCalculator()
        frame = _nominal_frame(rpm=0, fuel_flow_lph=0, vibration_rms_g=0.1)
        result = calc.compute(raw_frame=frame)
        assert 0.0 <= result["engine_health_index"] <= 100.0

    def test_max_values(self):
        """Extreme values should not crash."""
        calc = HealthIndexCalculator()
        frame = _nominal_frame(
            cht_c=[340.0, 345.0, 350.0, 335.0],
            egt_c=[1050.0, 1060.0, 1070.0, 1040.0],
            vibration_rms_g=4.9,
            oil_pressure_kpa=55.0,
            oil_temp_c=195.0,
        )
        result = calc.compute(raw_frame=frame)
        assert result["health_status"] == HealthStatus.CRITICAL

    def test_missing_frame_raises(self):
        calc = HealthIndexCalculator()
        with pytest.raises(ValueError):
            calc.compute(raw_frame=None)

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError):
            HealthIndexCalculator(ehi_weights={"a": 0.5, "b": 0.3})


# ══════════════════════════════════════════════════════════════════
#  8.  Integration with FaultInjector
# ══════════════════════════════════════════════════════════════════

class TestFaultInjectorIntegration:
    """Use real FaultInjector frames to validate EHI degradation."""

    @staticmethod
    def _run_fault(
        fault_type: str, severity: float, rate: float, steps: int = 300,
    ) -> list:
        from simulator.fault_injector import FaultInjector
        inj = FaultInjector(dt=0.1, enable_noise=False)
        for _ in range(100):
            inj.step(0.7)
        inj.trigger_fault(fault_type, severity, rate)
        frames = []
        for _ in range(steps):
            frames.append(inj.step(0.7))
        return frames

    def test_lean_burn_real_engine(self):
        """Real lean burn fault must push EHI below 60%."""
        calc = HealthIndexCalculator()
        frames = self._run_fault("LEAN_BURN_RUNAWAY", 0.8, 0.04, 300)

        ehis = [calc.compute(raw_frame=f)["engine_health_index"] for f in frames]
        min_ehi = min(ehis)
        assert min_ehi < 60.0, (
            f"Real lean burn min EHI = {min_ehi:.1f}, expected < 60"
        )

    def test_piston_ring_real_engine(self):
        """Real piston ring wear must push EHI below 60%."""
        calc = HealthIndexCalculator()
        frames = self._run_fault("PISTON_RING_WEAR", 0.8, 0.03, 400)

        ehis = [calc.compute(raw_frame=f)["engine_health_index"] for f in frames]
        min_ehi = min(ehis)
        assert min_ehi < 60.0, (
            f"Real piston ring min EHI = {min_ehi:.1f}, expected < 60"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
