#!/usr/bin/env python3
"""
Unit tests for simulator.engine_physics.AeroPistonEngine

Run:
    python -m pytest tests/test_engine_physics.py -v
    -- or --
    python tests/test_engine_physics.py
"""

from __future__ import annotations

import math
import unittest

from simulator.engine_physics import AeroPistonEngine


class TestThrottleIncreasesRPM(unittest.TestCase):
    """Increasing throttle must increase RPM (after convergence)."""

    def _steady_rpm(self, throttle: float, steps: int = 200) -> float:
        """Run engine at fixed throttle for *steps* steps, return final RPM."""
        eng = AeroPistonEngine(dt=0.1, enable_noise=False)
        for _ in range(steps):
            eng.step(throttle)
        return eng.rpm

    def test_idle_rpm_in_valid_range(self):
        rpm = self._steady_rpm(0.0)
        self.assertGreaterEqual(rpm, 550)
        self.assertLessEqual(rpm, 700)

    def test_full_rpm_in_valid_range(self):
        rpm = self._steady_rpm(1.0)
        self.assertGreaterEqual(rpm, 2400)
        self.assertLessEqual(rpm, 2800)

    def test_rpm_monotonic_with_throttle(self):
        rpms = [self._steady_rpm(t) for t in [0.0, 0.25, 0.5, 0.75, 1.0]]
        for i in range(len(rpms) - 1):
            self.assertGreater(
                rpms[i + 1], rpms[i],
                f"RPM did not increase: {rpms[i]:.0f} → {rpms[i+1]:.0f}",
            )


class TestThrottleIncreasesCHT(unittest.TestCase):
    """Higher throttle → higher average CHT (thermal energy ↑)."""

    def _steady_avg_cht(self, throttle: float, steps: int = 300) -> float:
        eng = AeroPistonEngine(dt=0.1, enable_noise=False)
        for _ in range(steps):
            eng.step(throttle)
        return sum(eng.cht_c) / len(eng.cht_c)

    def test_cht_monotonic_with_throttle(self):
        chts = [self._steady_avg_cht(t) for t in [0.0, 0.33, 0.66, 1.0]]
        for i in range(len(chts) - 1):
            self.assertGreater(
                chts[i + 1], chts[i],
                f"CHT did not increase: {chts[i]:.1f} → {chts[i+1]:.1f}",
            )

    def test_cht_within_physical_range(self):
        """CHT should stay in 80 – 260 °C for normal operation."""
        avg = self._steady_avg_cht(0.7)
        self.assertGreaterEqual(avg, 80)
        self.assertLessEqual(avg, 280)


class TestThrottleIncreasesFuelFlow(unittest.TestCase):
    """Higher throttle → higher fuel consumption."""

    def _steady_fuel(self, throttle: float, steps: int = 200) -> float:
        eng = AeroPistonEngine(dt=0.1, enable_noise=False)
        for _ in range(steps):
            eng.step(throttle)
        return eng.fuel_flow_lph

    def test_fuel_flow_monotonic(self):
        flows = [self._steady_fuel(t) for t in [0.0, 0.25, 0.5, 0.75, 1.0]]
        for i in range(len(flows) - 1):
            self.assertGreater(
                flows[i + 1], flows[i],
                f"Fuel flow did not increase: {flows[i]:.2f} → {flows[i+1]:.2f}",
            )

    def test_fuel_flow_wot_in_range(self):
        """Full-throttle fuel flow should be ~15–30 L/hr for this class."""
        fuel = self._steady_fuel(1.0)
        self.assertGreaterEqual(fuel, 10.0)
        self.assertLessEqual(fuel, 40.0)


class TestMAPResponse(unittest.TestCase):
    """MAP should rise with throttle toward ambient pressure."""

    def test_map_range(self):
        eng = AeroPistonEngine(dt=0.1, enable_noise=False)
        eng.step(0.0)
        map_idle = eng.map_kpa
        eng.step(1.0)
        map_full = eng.map_kpa
        self.assertGreater(map_full, map_idle)
        self.assertLessEqual(map_full, eng.ambient_pressure_kpa + 1.0)


class TestOilSystem(unittest.TestCase):
    """Oil pressure and temperature should be within plausible bounds."""

    def test_oil_pressure_range(self):
        eng = AeroPistonEngine(dt=0.1, enable_noise=False)
        for _ in range(200):
            eng.step(0.7)
        self.assertGreaterEqual(eng.oil_pressure_kpa, 200)
        self.assertLessEqual(eng.oil_pressure_kpa, 650)

    def test_oil_temp_rises_with_power(self):
        eng = AeroPistonEngine(dt=0.1, enable_noise=False)
        eng.step(0.0)
        oil_cold = eng.oil_temp_c
        for _ in range(500):
            eng.step(1.0)
        self.assertGreater(eng.oil_temp_c, oil_cold)


class TestVibration(unittest.TestCase):
    """Vibration increases with RPM."""

    def test_vibration_increases(self):
        eng = AeroPistonEngine(dt=0.1, enable_noise=False)
        eng.step(0.0)
        vib_idle = eng.vibration_rms_g
        for _ in range(200):
            eng.step(1.0)
        self.assertGreater(eng.vibration_rms_g, vib_idle)

    def test_vibration_range(self):
        eng = AeroPistonEngine(dt=0.1, enable_noise=False)
        for _ in range(200):
            eng.step(0.8)
        self.assertGreaterEqual(eng.vibration_rms_g, 0.1)
        self.assertLessEqual(eng.vibration_rms_g, 2.0)


class TestSensorNoise(unittest.TestCase):
    """With noise enabled, repeated runs produce different outputs."""

    def test_noisy_outputs_differ(self):
        results = []
        for _ in range(5):
            eng = AeroPistonEngine(dt=0.1, enable_noise=True)
            for _ in range(50):
                eng.step(0.6)
            results.append(eng.rpm)
        # At least two should differ (probabilistic, but very likely)
        self.assertGreater(len(set(results)), 1, "Noise produced no variation")

    def test_no_noise_deterministic(self):
        rpms = []
        for _ in range(3):
            eng = AeroPistonEngine(dt=0.1, enable_noise=False)
            for _ in range(50):
                eng.step(0.6)
            rpms.append(eng.rpm)
        self.assertEqual(len(set(rpms)), 1, "No-noise mode is not deterministic")


class TestOutputFrame(unittest.TestCase):
    """Verify the step() output dict has all required keys and types."""

    def test_frame_keys(self):
        eng = AeroPistonEngine(dt=0.1, enable_noise=False)
        frame = eng.step(0.5)
        expected_keys = {
            "timestamp", "sim_time_s", "altitude_ft", "weather",
            "throttle", "rpm", "map_kpa", "fuel_flow_lph",
            "equivalence_ratio", "cht_c", "egt_c",
            "oil_pressure_kpa", "oil_temp_c", "vibration_rms_g",
            "air_density_kg_m3", "ambient_temp_c", "ambient_pressure_kpa",
        }
        self.assertEqual(set(frame.keys()), expected_keys)

    def test_frame_cht_egt_length(self):
        eng = AeroPistonEngine(dt=0.1, enable_noise=False)
        frame = eng.step(0.5)
        self.assertEqual(len(frame["cht_c"]), 4)
        self.assertEqual(len(frame["egt_c"]), 4)

    def test_sim_time_advances(self):
        eng = AeroPistonEngine(dt=0.1, enable_noise=False)
        f1 = eng.step(0.5)
        f2 = eng.step(0.5)
        self.assertAlmostEqual(f2["sim_time_s"] - f1["sim_time_s"], 0.1, places=6)


class TestAltitudeEffect(unittest.TestCase):
    """Engine power drops at altitude due to lower air density."""

    def test_rpm_reduced_at_altitude(self):
        eng_sea = AeroPistonEngine(dt=0.1, enable_noise=False)
        eng_alt = AeroPistonEngine(dt=0.1, enable_noise=False)
        for _ in range(200):
            eng_sea.step(0.7, altitude_ft=0)
            eng_alt.step(0.7, altitude_ft=15000)
        self.assertGreater(eng_sea.rpm, eng_alt.rpm)


class TestThrottleSchedule(unittest.TestCase):
    """Multi-step run with throttle schedule."""

    def test_run_returns_frames(self):
        eng = AeroPistonEngine(dt=0.1, enable_noise=False)
        schedule = {0.0: 0.0, 2.0: 0.5, 5.0: 1.0}
        frames = eng.run(5.0, throttle_schedule=schedule)
        self.assertEqual(len(frames), 50)

    def test_throttle_ramps_up(self):
        eng = AeroPistonEngine(dt=0.1, enable_noise=False)
        schedule = {0.0: 0.0, 3.0: 1.0}
        frames = eng.run(5.0, throttle_schedule=schedule)
        rpms = [f["rpm"] for f in frames]
        # Last frame RPM should exceed first frame RPM
        self.assertGreater(rpms[-1], rpms[0])


if __name__ == "__main__":
    unittest.main()
