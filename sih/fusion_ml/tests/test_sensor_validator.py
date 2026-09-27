#!/usr/bin/env python3
"""
Unit tests for fusion_ml.sensor_validator.SensorValidator

Run:
    pytest -v fusion_ml/tests/test_sensor_validator.py
"""

from __future__ import annotations

import math
import pytest

from fusion_ml.sensor_validator import (
    SensorValidator,
    SanitizedFrame,
    IsolationReason,
    ALL_CHANNELS,
    NUM_CHANNELS,
    PHYSICAL_BOUNDS,
)


# ══════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════

def _make_frame(
    rpm: float = 2100.0,
    cht: list | None = None,
    egt: list | None = None,
    **kwargs,
) -> dict:
    """Build a minimal telemetry frame dict."""
    cht = cht or [180.0, 178.0, 182.0, 176.0]
    egt = egt or [740.0, 738.0, 742.0, 736.0]
    base = {
        "rpm": rpm,
        "map_kpa": kwargs.get("map_kpa", 75.0),
        "fuel_flow_lph": kwargs.get("fuel_flow_lph", 12.0),
        "equivalence_ratio": kwargs.get("equivalence_ratio", 0.85),
        "cht_c": cht,
        "egt_c": egt,
        "oil_pressure_kpa": kwargs.get("oil_pressure_kpa", 400.0),
        "oil_temp_c": kwargs.get("oil_temp_c", 90.0),
        "vibration_rms_g": kwargs.get("vibration_rms_g", 1.5),
        "air_density_kg_m3": kwargs.get("air_density_kg_m3", 1.0),
        "ambient_temp_c": kwargs.get("ambient_temp_c", 10.0),
        "ambient_pressure_kpa": kwargs.get("ambient_pressure_kpa", 80.0),
    }
    return base


# ══════════════════════════════════════════════════════════════════
#  1.  Basic functionality
# ══════════════════════════════════════════════════════════════════

class TestBasicValidation:
    """SanitizedFrame structure and normal-frame passthrough."""

    def test_returns_sanitized_frame(self):
        v = SensorValidator(buffer_size=600)
        frame = _make_frame()
        result = v.validate(frame)
        assert isinstance(result, SanitizedFrame)

    def test_all_channels_valid_for_normal_frame(self):
        """A normal frame should pass all channels."""
        v = SensorValidator(buffer_size=600)
        frame = _make_frame()
        result = v.validate(frame)
        assert all(result.sensor_mask), "Some channels isolated on normal frame"
        assert len(result.isolation_flags) == 0
        assert len(result.sensor_mask) == NUM_CHANNELS

    def test_valid_sensors_has_all_channels(self):
        v = SensorValidator(buffer_size=600)
        result = v.validate(_make_frame())
        for ch in ALL_CHANNELS:
            assert ch in result.valid_sensors, f"Missing channel: {ch}"

    def test_frame_counter_increments(self):
        v = SensorValidator(buffer_size=600)
        assert v.total_frames == 0
        v.validate(_make_frame())
        v.validate(_make_frame())
        assert v.total_frames == 2

    def test_all_values_contains_every_channel(self):
        v = SensorValidator(buffer_size=600)
        result = v.validate(_make_frame(rpm=2200.0))
        assert result.all_values["rpm"] == 2200.0
        assert len(result.all_values) == NUM_CHANNELS


# ══════════════════════════════════════════════════════════════════
#  2.  Freeze / flatline detection
# ══════════════════════════════════════════════════════════════════

class TestFreezeDetection:
    """Sensor freeze should trigger after buffer fills with static values."""

    def test_frozen_channel_isolated(self):
        """Freezing one channel for 600 frames triggers ISOLATED_FROZEN."""
        v = SensorValidator(buffer_size=600)
        frozen_val = 185.0

        for i in range(600):
            frame = _make_frame()
            frame["cht_c"][1] = frozen_val  # freeze CHT_2
            v.validate(frame)

        result = v.validate(_make_frame())  # 601st frame
        cht2_flags = [
            f for f in result.isolation_flags
            if f["channel"] == "cht_2_c"
        ]
        assert len(cht2_flags) > 0, "CHT_2 not flagged as frozen"
        assert cht2_flags[0]["reason"] == IsolationReason.FROZEN

    def test_other_channels_not_frozen(self):
        """Only the frozen channel should be isolated."""
        v = SensorValidator(buffer_size=600)
        for _ in range(600):
            frame = _make_frame()
            frame["cht_c"][1] = 185.0  # freeze CHT_2 only
            v.validate(frame)

        result = v.validate(_make_frame())
        cht2_idx = ALL_CHANNELS.index("cht_2_c")

        # CHT_2 should be False
        assert not result.sensor_mask[cht2_idx]

        # Other channels should be True
        for idx, ch in enumerate(ALL_CHANNELS):
            if idx == cht2_idx:
                continue
            assert result.sensor_mask[idx], f"{ch} unexpectedly isolated"

    def test_not_frozen_before_buffer_full(self):
        """Freeze detection should NOT trigger before buffer is full."""
        v = SensorValidator(buffer_size=600)
        for _ in range(599):
            frame = _make_frame()
            frame["cht_c"][1] = 185.0
            result = v.validate(frame)

        # Buffer not full yet — should not be frozen
        cht2_flags = [
            f for f in result.isolation_flags
            if f["channel"] == "cht_2_c"
        ]
        assert len(cht2_flags) == 0, "Freeze detected before buffer full"

    def test_variable_channel_not_frozen(self):
        """A channel with normal variance should never be flagged frozen."""
        v = SensorValidator(buffer_size=600)
        import random
        rng = random.Random(42)

        for _ in range(650):
            frame = _make_frame()
            # Add small noise to CHT_1
            frame["cht_c"][0] = 180.0 + rng.gauss(0, 0.5)
            v.validate(frame)

        result = v.validate(_make_frame())
        cht1_flags = [
            f for f in result.isolation_flags
            if f["channel"] == "cht_1_c"
            and f["reason"] == IsolationReason.FROZEN
        ]
        assert len(cht1_flags) == 0, "Variable channel incorrectly frozen"


# ══════════════════════════════════════════════════════════════════
#  3.  Out-of-bounds detection
# ══════════════════════════════════════════════════════════════════

class TestOutOfBoundsDetection:
    """Values outside physical bounds should be flagged immediately."""

    def test_rpm_too_high(self):
        v = SensorValidator(buffer_size=600)
        frame = _make_frame(rpm=7000.0)  # above 6000 limit
        result = v.validate(frame)
        assert not result.sensor_mask[ALL_CHANNELS.index("rpm")]
        rpm_flags = [
            f for f in result.isolation_flags if f["channel"] == "rpm"
        ]
        assert len(rpm_flags) > 0
        assert rpm_flags[0]["reason"] == IsolationReason.OUT_OF_BOUNDS

    def test_rpm_negative(self):
        v = SensorValidator(buffer_size=600)
        frame = _make_frame(rpm=-100.0)
        result = v.validate(frame)
        assert not result.sensor_mask[ALL_CHANNELS.index("rpm")]

    def test_cht_above_limit(self):
        v = SensorValidator(buffer_size=600)
        frame = _make_frame(cht=[400.0, 180.0, 182.0, 176.0])  # CHT_1 > 350
        result = v.validate(frame)
        assert not result.sensor_mask[ALL_CHANNELS.index("cht_1_c")]

    def test_cht_below_limit(self):
        v = SensorValidator(buffer_size=600)
        frame = _make_frame(cht=[-30.0, 180.0, 182.0, 176.0])
        result = v.validate(frame)
        assert not result.sensor_mask[ALL_CHANNELS.index("cht_1_c")]

    def test_oil_pressure_low(self):
        v = SensorValidator(buffer_size=600)
        frame = _make_frame(oil_pressure_kpa=30.0)  # below 50 limit
        result = v.validate(frame)
        assert not result.sensor_mask[ALL_CHANNELS.index("oil_pressure_kpa")]

    def test_vibration_high(self):
        v = SensorValidator(buffer_size=600)
        frame = _make_frame(vibration_rms_g=6.0)  # above 5.0 limit
        result = v.validate(frame)
        assert not result.sensor_mask[ALL_CHANNELS.index("vibration_rms_g")]

    def test_out_of_bounds_not_in_valid(self):
        """OOB channel should not appear in valid_sensors."""
        v = SensorValidator(buffer_size=600)
        frame = _make_frame(rpm=7000.0)
        result = v.validate(frame)
        assert "rpm" not in result.valid_sensors

    def test_oob_does_not_corrupt_buffer(self):
        """An OOB value should not be appended to the buffer."""
        v = SensorValidator(buffer_size=600)
        # Send 5 normal frames
        for _ in range(5):
            v.validate(_make_frame(rpm=2100.0))
        # Send 1 OOB frame
        v.validate(_make_frame(rpm=7000.0))
        # Send 5 more normal frames
        for _ in range(5):
            v.validate(_make_frame(rpm=2100.0))

        stats = v.get_channel_stats("rpm")
        # Buffer should have 10 entries (5 + 1 OOB skipped + 5), not 11
        assert stats["buffer_len"] == 10


# ══════════════════════════════════════════════════════════════════
#  4.  Reset
# ══════════════════════════════════════════════════════════════════

class TestReset:
    """reset() should clear all buffers and counters."""

    def test_reset_clears_buffers(self):
        v = SensorValidator(buffer_size=600)
        for _ in range(700):
            v.validate(_make_frame())
        assert v.total_frames == 700

        v.reset()
        assert v.total_frames == 0
        for ch in ALL_CHANNELS:
            stats = v.get_channel_stats(ch)
            assert stats["buffer_len"] == 0
            assert stats["count"] == 0


# ══════════════════════════════════════════════════════════════════
#  5.  CHT_2 freeze scenario (full scenario test)
# ══════════════════════════════════════════════════════════════════

class TestCHT2FreezeScenario:
    """
    End-to-end test: simulate 700 frames with CHT_2 frozen starting
    at frame 100.  Verify isolation triggers after 600 frames while
    all other channels remain active.
    """

    def test_cht2_freeze_triggers_after_600_frames(self):
        v = SensorValidator(buffer_size=600)
        frozen_val = 185.0
        freeze_start = 100
        isolation_triggered = False
        isolation_frame = None

        for i in range(700):
            frame = _make_frame()
            if i >= freeze_start:
                frame["cht_c"][1] = frozen_val

            result = v.validate(frame)

            cht2_flags = [
                f for f in result.isolation_flags
                if f["channel"] == "cht_2_c"
                and f["reason"] == IsolationReason.FROZEN
            ]
            if cht2_flags and not isolation_triggered:
                isolation_triggered = True
                isolation_frame = i

        assert isolation_triggered, "CHT_2 freeze was never detected"
        # Should trigger at frame 600 (100 start + 600 buffer fill)
        assert isolation_frame >= 600, (
            f"Isolation triggered too early at frame {isolation_frame}, "
            f"expected ≥ 600"
        )

    def test_other_channels_survive_cht2_freeze(self):
        """After CHT_2 isolation, all other channels should remain valid."""
        v = SensorValidator(buffer_size=600)
        for i in range(650):
            frame = _make_frame()
            if i >= 100:
                frame["cht_c"][1] = 185.0
            v.validate(frame)

        result = v.validate(_make_frame())
        cht2_idx = ALL_CHANNELS.index("cht_2_c")

        for idx, ch in enumerate(ALL_CHANNELS):
            if idx == cht2_idx:
                assert not result.sensor_mask[idx], "CHT_2 should be isolated"
            else:
                assert result.sensor_mask[idx], (
                    f"{ch} unexpectedly isolated during CHT_2 freeze"
                )

    def test_frozen_channel_excluded_from_valid_sensors(self):
        """Isolated channels should not appear in valid_sensors dict."""
        v = SensorValidator(buffer_size=600)
        for _ in range(601):
            frame = _make_frame()
            frame["cht_c"][1] = 185.0
            v.validate(frame)

        result = v.validate(_make_frame())
        assert "cht_2_c" not in result.valid_sensors
        # But cht_1_c should still be present
        assert "cht_1_c" in result.valid_sensors


# ══════════════════════════════════════════════════════════════════
#  6.  Multiple simultaneous faults
# ══════════════════════════════════════════════════════════════════

class TestMultipleSimultaneousFaults:
    """Two channels can be frozen simultaneously."""

    def test_two_channels_frozen(self):
        v = SensorValidator(buffer_size=600)
        for _ in range(601):
            frame = _make_frame()
            frame["cht_c"][1] = 185.0  # freeze CHT_2
            frame["egt_c"][0] = 740.0  # freeze EGT_1
            v.validate(frame)

        result = v.validate(_make_frame())
        frozen_channels = {
            f["channel"] for f in result.isolation_flags
            if f["reason"] == IsolationReason.FROZEN
        }
        assert "cht_2_c" in frozen_channels
        assert "egt_1_c" in frozen_channels


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
