#!/usr/bin/env python3
"""
Unit tests for simulator.fault_injector.FaultInjector

Run:
    python -m pytest tests/test_fault_injector.py -v
"""

from __future__ import annotations

import unittest

from simulator.fault_injector import FaultInjector, FaultType
from simulator.engine_physics import NUM_CYLINDERS


class _BaseTestCase(unittest.TestCase):
    """Shared helpers for fault-injector tests."""

    def _make_injector(self, throttle: float = 0.7, warmup_s: float = 10.0) -> FaultInjector:
        inj = FaultInjector(dt=0.1, enable_noise=False)
        steps = int(warmup_s / inj.dt)
        for _ in range(steps):
            inj.step(throttle=throttle)
        return inj


class TestLeanBurnRunaway(unittest.TestCase):
    """Lean burn: EGT spikes, CHT climbs, fuel flow drops."""

    def _run_with_fault(self, duration_s: float, severity: float) -> dict:
        inj = self._make_injector()
        inj.trigger_fault(FaultType.LEAN_BURN_RUNAWAY, severity=severity, rate_per_sec=0.05)
        for _ in range(int(duration_s / inj.dt)):
            frame = inj.step(throttle=0.7)
        return frame

    def test_egt_spikes(self):
        frame = self._run_with_fault(30.0, severity=0.8)
        max_egt = max(frame["egt_c"])
        # Normal cruise EGT ~700-800; lean runaway should push above 850
        self.assertGreater(max_egt, 800, f"EGT did not spike: {max_egt:.1f}°C")

    def test_cht_climbs(self):
        inj = self._make_injector()
        inj.trigger_fault(FaultType.LEAN_BURN_RUNAWAY, severity=0.9, rate_per_sec=0.05)
        # Sample CHT at start and end
        f_start = inj.step(0.7)
        for _ in range(200):
            f_end = inj.step(0.7)
        avg_cht_start = sum(f_start["cht_c"]) / NUM_CYLINDERS
        avg_cht_end = sum(f_end["cht_c"]) / NUM_CYLINDERS
        self.assertGreater(avg_cht_end, avg_cht_start)

    def test_fuel_flow_decreases(self):
        inj = self._make_injector()
        inj.trigger_fault(FaultType.LEAN_BURN_RUNAWAY, severity=0.7, rate_per_sec=0.04)
        f_clean = inj.step(0.7)
        for _ in range(300):
            f_faulty = inj.step(0.7)
        self.assertLess(f_faulty["fuel_flow_lph"], f_clean["fuel_flow_lph"])

    def test_labels_correct(self):
        frame = self._run_with_fault(5.0, 0.5)
        self.assertTrue(frame["fault_labels"][FaultType.LEAN_BURN_RUNAWAY]["active"])
        self.assertGreater(frame["fault_labels"][FaultType.LEAN_BURN_RUNAWAY]["progress"], 0)


class TestPistonRingWear(unittest.TestCase):
    """Ring wear: RPM ↓, vibration ↑, oil temp ↑."""

    def _run_with_fault(self, duration_s: float) -> dict:
        inj = self._make_injector()
        inj.trigger_fault(FaultType.PISTON_RING_WEAR, severity=0.8, rate_per_sec=0.015)
        for _ in range(int(duration_s / inj.dt)):
            frame = inj.step(throttle=0.7)
        return frame

    def test_rpm_drops(self):
        inj = self._make_injector()
        inj.trigger_fault(FaultType.PISTON_RING_WEAR, severity=0.9, rate_per_sec=0.02)
        f_clean = inj.step(0.7)
        for _ in range(300):
            f_faulty = inj.step(0.7)
        self.assertLess(faulty["rpm"], f_clean["rpm"])

    def test_vibration_increases(self):
        inj = self._make_injector()
        inj.trigger_fault(FaultType.PISTON_RING_WEAR, severity=0.8, rate_per_sec=0.02)
        f_clean = inj.step(0.7)
        for _ in range(200):
            f_faulty = inj.step(0.7)
        self.assertGreater(faulty["vibration_rms_g"], f_clean["vibration_rms_g"])

    def test_oil_temp_rises(self):
        inj = self._make_injector()
        inj.trigger_fault(FaultType.PISTON_RING_WEAR, severity=0.9, rate_per_sec=0.02)
        f_clean = inj.step(0.7)
        for _ in range(200):
            f_faulty = inj.step(0.7)
        self.assertGreater(faulty["oil_temp_c"], f_clean["oil_temp_c"])

    def test_labels_correct(self):
        frame = self._run_with_fault(5.0)
        self.assertTrue(frame["fault_labels"][FaultType.PISTON_RING_WEAR]["active"])


class TestOilLeakPressureLoss(unittest.TestCase):
    """Oil leak: pressure ↓, CHT ↑, oil temp ↑."""

    def _run_with_fault(self, duration_s: float) -> dict:
        inj = self._make_injector()
        inj.trigger_fault(FaultType.OIL_LEAK_PRESSURE_LOSS, severity=0.8, rate_per_sec=0.01)
        for _ in range(int(duration_s / inj.dt)):
            frame = inj.step(throttle=0.7)
        return frame

    def test_oil_pressure_drops(self):
        inj = self._make_injector()
        inj.trigger_fault(FaultType.OIL_LEAK_PRESSURE_LOSS, severity=0.9, rate_per_sec=0.02)
        f_clean = inj.step(0.7)
        for _ in range(300):
            f_faulty = inj.step(0.7)
        self.assertLess(faulty["oil_pressure_kpa"], f_clean["oil_pressure_kpa"])

    def test_cht_rises(self):
        inj = self._make_injector()
        inj.trigger_fault(FaultType.OIL_LEAK_PRESSURE_LOSS, severity=0.9, rate_per_sec=0.02)
        f_clean = inj.step(0.7)
        for _ in range(200):
            f_faulty = inj.step(0.7)
        avg_clean = sum(f_clean["cht_c"]) / NUM_CYLINDERS
        avg_faulty = sum(f_faulty["cht_c"]) / NUM_CYLINDERS
        self.assertGreater(avg_faulty, avg_clean)

    def test_labels_correct(self):
        frame = self._run_with_fault(5.0)
        self.assertTrue(frame["fault_labels"][FaultType.OIL_LEAK_PRESSURE_LOSS]["active"])


class TestSensorFreeze(unittest.TestCase):
    """Sensor freeze: specific CHT locked to static value."""

    def test_cht_frozen(self):
        inj = self._make_injector()
        # Capture the CHT value at trigger time
        snapshot = inj.engine.cht_c[2]  # cylinder index 2
        inj.trigger_fault(FaultType.SENSOR_FREEZE, severity=1.0, rate_per_sec=1.0, frozen_cyl=2)
        # Run and verify cyl 2 stays at snapshot
        for _ in range(100):
            frame = inj.step(throttle=0.7)
            self.assertAlmostEqual(
                frame["cht_c"][2], snapshot, places=1,
                msg=f"Cyl 2 CHT drifted: {frame['cht_c'][2]} vs {snapshot}",
            )

    def test_other_cylinders_not_frozen(self):
        inj = self._make_injector()
        inj.trigger_fault(FaultType.SENSOR_FREEZE, severity=1.0, frozen_cyl=2)
        vals_cyl0 = []
        for _ in range(50):
            frame = inj.step(throttle=0.7)
            vals_cyl0.append(frame["cht_c"][0])
        # Cyl 0 should vary (not all the same value)
        self.assertGreater(len(set(vals_cyl0)), 1)


class TestClearFaults(unittest.TestCase):
    """clear_faults() removes all active faults."""

    def test_clear(self):
        inj = self._make_injector()
        inj.trigger_fault(FaultType.LEAN_BURN_RUNAWAY, 0.5, 0.01)
        inj.trigger_fault(FaultType.OIL_LEAK_PRESSURE_LOSS, 0.3, 0.005)
        self.assertEqual(len(inj.active_faults), 2)
        inj.clear_faults()
        self.assertEqual(len(inj.active_faults), 0)
        frame = inj.step(0.7)
        for ft_name in FaultType.ALL:
            self.assertFalse(frame["fault_labels"][ft_name]["active"])


class TestMultipleFaults(unittest.TestCase):
    """Multiple faults can be active simultaneously."""

    def test_two_faults_active(self):
        inj = self._make_injector()
        inj.trigger_fault(FaultType.LEAN_BURN_RUNAWAY, 0.5, 0.01)
        inj.trigger_fault(FaultType.PISTON_RING_WEAR, 0.5, 0.01)
        frame = inj.step(0.7)
        self.assertIn(FaultType.LEAN_BURN_RUNAWAY, frame["faults_active"])
        self.assertIn(FaultType.PISTON_RING_WEAR, frame["faults_active"])
        self.assertNotIn(FaultType.OIL_LEAK_PRESSURE_LOSS, frame["faults_active"])


class TestInvalidFaultType(unittest.TestCase):
    """Unknown fault types raise ValueError."""

    def test_invalid(self):
        inj = FaultInjector()
        with self.assertRaises(ValueError):
            inj.trigger_fault("NONEXISTENT_FAULT", 0.5, 0.01)


if __name__ == "__main__":
    unittest.main()
