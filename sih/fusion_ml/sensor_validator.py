#!/usr/bin/env python3
"""
Sensor Validator — Real-Time Telemetry Sanitisation
====================================================
Validates incoming 10 Hz telemetry frames from the Aero Piston Engine
digital twin.  Maintains per-channel FIFO circular buffers and detects:

* **Sensor freeze / flatline** — variance ≈ 0 over the rolling window.
* **Out-of-range** — values exceeding physical operational bounds.

Output is a :class:`SanitizedFrame` containing clean values, a boolean
sensor mask, and isolation flags — ready for downstream fusion and
anomaly-detection models.

Usage
-----
    from fusion_ml.sensor_validator import SensorValidator

    validator = SensorValidator(buffer_size=600)
    for frame in telemetry_stream:
        result = validator.validate(frame)
        if result.isolation_flags:
            print("Warnings:", result.isolation_flags)
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


# ══════════════════════════════════════════════════════════════════
#  Physical operational bounds per sensor channel
# ══════════════════════════════════════════════════════════════════
#  (lower_bound, upper_bound) — values outside are flagged OOB.

PHYSICAL_BOUNDS: Dict[str, tuple[float, float]] = {
    "rpm":               (0.0,     6_000.0),
    "map_kpa":           (20.0,     120.0),
    "fuel_flow_lph":     (0.0,      60.0),
    "equivalence_ratio": (0.3,      1.3),
    "cht_1_c":          (-20.0,    350.0),
    "cht_2_c":          (-20.0,    350.0),
    "cht_3_c":          (-20.0,    350.0),
    "cht_4_c":          (-20.0,    350.0),
    "egt_1_c":          (100.0, 1_100.0),
    "egt_2_c":          (100.0, 1_100.0),
    "egt_3_c":          (100.0, 1_100.0),
    "egt_4_c":          (100.0, 1_100.0),
    "oil_pressure_kpa":  (50.0,    700.0),
    "oil_temp_c":        (20.0,    200.0),
    "vibration_rms_g":   (0.0,      5.0),
    "air_density_kg_m3": (0.1,      2.0),
    "ambient_temp_c":    (-60.0,    60.0),
    "ambient_pressure_kpa": (10.0, 120.0),
}

# Channels that are *derived* from atmosphere — still validated but
# rarely go out of range in normal operation.
ENVIRONMENTAL_CHANNELS = {
    "air_density_kg_m3", "ambient_temp_c", "ambient_pressure_kpa",
}

# All monitored numerical sensor channels
ALL_CHANNELS: List[str] = [
    "rpm", "map_kpa", "fuel_flow_lph", "equivalence_ratio",
    "cht_1_c", "cht_2_c", "cht_3_c", "cht_4_c",
    "egt_1_c", "egt_2_c", "egt_3_c", "egt_4_c",
    "oil_pressure_kpa", "oil_temp_c", "vibration_rms_g",
    "air_density_kg_m3", "ambient_temp_c", "ambient_pressure_kpa",
]

NUM_CHANNELS = len(ALL_CHANNELS)

# Freeze-detection threshold: variance below this over the full
# buffer (600 samples = 60 s at 10 Hz) is considered frozen.
FREEZE_VARIANCE_THRESHOLD = 1e-6


# ══════════════════════════════════════════════════════════════════
#  Isolation flag enum
# ══════════════════════════════════════════════════════════════════

class IsolationReason:
    FROZEN = "ISOLATED_FROZEN"
    OUT_OF_BOUNDS = "ISOLATED_OUT_OF_BOUNDS"
    STALE = "ISOLATED_STALE"


# ══════════════════════════════════════════════════════════════════
#  Sanitised output
# ══════════════════════════════════════════════════════════════════

@dataclass
class SanitizedFrame:
    """
    Result of :meth:`SensorValidator.validate`.

    Attributes
    ----------
    valid_sensors : dict
        Channel→value mapping for sensors that passed validation.
        Isolated channels are excluded.
    sensor_mask : list[bool]
        Boolean mask, one entry per channel in ``ALL_CHANNELS``.
        ``True`` = valid, ``False`` = isolated.
    isolation_flags : list[dict]
        Each entry: ``{"channel": str, "reason": str, "value": float}``.
    all_values : dict
        Channel→value mapping for *all* channels (including isolated),
        useful for logging and debugging.
    """

    valid_sensors: Dict[str, float] = field(default_factory=dict)
    sensor_mask: List[bool] = field(default_factory=list)
    isolation_flags: List[Dict[str, Any]] = field(default_factory=list)
    all_values: Dict[str, float] = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════
#  SensorValidator
# ══════════════════════════════════════════════════════════════════

class SensorValidator:
    """
    Real-time sensor sanitisation for 10 Hz telemetry.

    Parameters
    ----------
    buffer_size : int
        Rolling FIFO window length in samples.  Default 600 (= 60 s
        at 10 Hz).
    freeze_variance_threshold : float
        Rolling-variance threshold below which a channel is declared
        frozen.  Default ``1e-6``.
    """

    def __init__(
        self,
        buffer_size: int = 600,
        freeze_variance_threshold: float = FREEZE_VARIANCE_THRESHOLD,
    ) -> None:
        self.buffer_size = buffer_size
        self.freeze_threshold = freeze_variance_threshold

        # Per-channel FIFO buffers: channel_name → deque(maxlen=N)
        self._buffers: Dict[str, Deque[float]] = {
            ch: deque(maxlen=buffer_size) for ch in ALL_CHANNELS
        }

        # Running sums for online variance (Welford's algorithm)
        self._count: Dict[str, int] = {ch: 0 for ch in ALL_CHANNELS}
        self._mean: Dict[str, float] = {ch: 0.0 for ch in ALL_CHANNELS}
        self._m2: Dict[str, float] = {ch: 0.0 for ch in ALL_CHANNELS}

        # Frame counter
        self._total_frames: int = 0

    # ── Public API ─────────────────────────────────────────────

    @property
    def total_frames(self) -> int:
        return self._total_frames

    def validate(self, frame: Dict[str, Any]) -> SanitizedFrame:
        """
        Validate a single telemetry frame.

        Parameters
        ----------
        frame : dict
            Raw telemetry frame (as produced by ``FaultInjector.step()``
            or the WebSocket streamer).

        Returns
        -------
        SanitizedFrame
            Sanitised output with valid_sensors, sensor_mask, and
            isolation_flags.
        """
        self._total_frames += 1
        flags: List[Dict[str, Any]] = []
        mask: List[bool] = [True] * NUM_CHANNELS
        valid: Dict[str, float] = {}
        all_vals: Dict[str, float] = {}

        # ── Extract sensor values from frame ──
        raw = self._extract_channels(frame)

        for idx, ch in enumerate(ALL_CHANNELS):
            value = raw[ch]
            all_vals[ch] = value

            # ── 1. Physical range check ──
            lo, hi = PHYSICAL_BOUNDS[ch]
            if value < lo or value > hi:
                mask[idx] = False
                flags.append({
                    "channel": ch,
                    "reason": IsolationReason.OUT_OF_BOUNDS,
                    "value": value,
                    "bounds": (lo, hi),
                })
                continue  # skip buffer update for OOB values

            # ── 2. Update FIFO buffer & online variance ──
            buf = self._buffers[ch]
            buf.append(value)
            self._update_running_stats(ch, value)

            # ── 3. Freeze / flatline detection ──
            if len(buf) >= self.buffer_size:
                var = self._rolling_variance(ch)
                if var < self.freeze_threshold:
                    mask[idx] = False
                    flags.append({
                        "channel": ch,
                        "reason": IsolationReason.FROZEN,
                        "value": value,
                        "variance": var,
                    })
                    continue  # don't add to valid if frozen

            # ── Channel passed all checks ──
            valid[ch] = value

        return SanitizedFrame(
            valid_sensors=valid,
            sensor_mask=mask,
            isolation_flags=flags,
            all_values=all_vals,
        )

    def reset(self) -> None:
        """Clear all buffers and state."""
        for ch in ALL_CHANNELS:
            self._buffers[ch].clear()
            self._count[ch] = 0
            self._mean[ch] = 0.0
            self._m2[ch] = 0.0
        self._total_frames = 0

    # ── Internal helpers ───────────────────────────────────────

    def _extract_channels(self, frame: Dict[str, Any]) -> Dict[str, float]:
        """
        Flatten a telemetry frame into a dict keyed by ALL_CHANNELS names.

        Handles both formats:
        - Flat dict: ``{"rpm": 2100, "cht_1_c": 180, ...}``
        - Nested cht/egt lists: ``{"rpm": 2100, "cht": [180, ...], ...}``
        """
        raw: Dict[str, float] = {}

        for ch in ALL_CHANNELS:
            # Direct key lookup
            if ch in frame:
                raw[ch] = float(frame[ch])
            elif ch.startswith("cht_") and "cht_c" in frame:
                # fault_injector format: cht_c = [c1, c2, c3, c4]
                cyl_idx = int(ch.split("_")[1]) - 1
                cht_list = frame["cht_c"]
                raw[ch] = float(cht_list[cyl_idx]) if cyl_idx < len(cht_list) else 0.0
            elif ch.startswith("cht_") and "cht" in frame:
                # streamer format: cht = [c1, c2, c3, c4]
                cyl_idx = int(ch.split("_")[1]) - 1
                cht_list = frame["cht"]
                raw[ch] = float(cht_list[cyl_idx]) if cyl_idx < len(cht_list) else 0.0
            elif ch.startswith("egt_") and "egt_c" in frame:
                cyl_idx = int(ch.split("_")[1]) - 1
                egt_list = frame["egt_c"]
                raw[ch] = float(egt_list[cyl_idx]) if cyl_idx < len(egt_list) else 0.0
            elif ch.startswith("egt_") and "egt" in frame:
                cyl_idx = int(ch.split("_")[1]) - 1
                egt_list = frame["egt"]
                raw[ch] = float(egt_list[cyl_idx]) if cyl_idx < len(egt_list) else 0.0
            elif ch == "vibration_rms_g" and "vibration_rms" in frame:
                raw[ch] = float(frame["vibration_rms"])
            else:
                # Default to 0.0 if channel not found
                raw[ch] = 0.0

        return raw

    def _update_running_stats(self, channel: str, value: float) -> None:
        """Welford's online algorithm for running mean and variance."""
        self._count[channel] += 1
        delta = value - self._mean[channel]
        self._mean[channel] += delta / self._count[channel]
        delta2 = value - self._mean[channel]
        self._m2[channel] += delta * delta2

    def _rolling_variance(self, channel: str) -> float:
        """
        Compute variance of the current buffer contents.

        Uses the buffer directly (not Welford's) because the FIFO
        means old samples expire — Welford would need a correction
        term.  For N=600, direct computation is still fast (< 1 µs).
        """
        buf = self._buffers[channel]
        n = len(buf)
        if n < 2:
            return float("inf")
        mean = sum(buf) / n
        return sum((x - mean) ** 2 for x in buf) / n

    def get_channel_stats(self, channel: str) -> Dict[str, float]:
        """Return current running statistics for a channel."""
        n = self._count[channel]
        variance = self._m2[channel] / n if n > 1 else 0.0
        return {
            "count": n,
            "mean": self._mean[channel],
            "variance": variance,
            "buffer_len": len(self._buffers[channel]),
        }


# ══════════════════════════════════════════════════════════════════
#  Demo / test runner
# ══════════════════════════════════════════════════════════════════

def _demo_freeze_detection() -> None:
    """
    Demonstrate CHT_2 freeze detection over 700 frames.
    The CHT_2 value is frozen at frame 100, and the validator
    should flag it as ISOLATED_FROZEN after 600 frames of buffer fill.
    """
    from simulator.engine_physics import AeroPistonEngine

    print("\n  Sensor Freeze Detection Demo — CHT_2 frozen at frame 100")
    print("  " + "─" * 60)

    engine = AeroPistonEngine(dt=0.1, enable_noise=True)
    validator = SensorValidator(buffer_size=600)
    frozen_value = 185.0

    header = (
        f"  {'Frame':>6}  {'CHT_2':>7}  {'Mask_2':>7}  "
        f"{'Buffer':>7}  {'Variance':>10}  {'Flags':<30}"
    )
    print(header)
    print("  " + "─" * 68)

    for i in range(700):
        # Generate normal frame
        frame = engine.step(throttle=0.7, altitude_ft=15_000)

        # Freeze CHT_2 starting at frame 100
        if i >= 100:
            frame["cht_c"][1] = frozen_value

        result = validator.validate(frame)

        # Print every 50 frames + the frame where isolation triggers
        cht2_idx = ALL_CHANNELS.index("cht_2_c")
        mask_2 = result.sensor_mask[cht2_idx]
        stats = validator.get_channel_stats("cht_2_c")

        if i % 50 == 0 or (not mask_2 and i > 590 and i % 5 == 0):
            flag_str = "; ".join(
                f"{f['channel']}={f['reason']}" for f in result.isolation_flags
            )
            print(
                f"  {i:>6}  "
                f"{result.all_values.get('cht_2_c', 0):>7.1f}  "
                f"{'✓' if mask_2 else '✗':>7}  "
                f"{stats['buffer_len']:>7}  "
                f"{stats['variance']:>10.8f}  "
                f"{flag_str:<30}"
            )

    print("  " + "─" * 68)
    print("  Demo complete.\n")


if __name__ == "__main__":
    _demo_freeze_detection()
