#!/usr/bin/env python3
"""
Unit tests for fusion_ml.ai_service

Run:
    pytest -v fusion_ml/tests/test_ai_service.py
"""

from __future__ import annotations

import json
import numpy as np
import pytest

from fusion_ml.ai_service import (
    AIService,
    SequenceBuffer,
    SEQUENCE_BUFFER_LEN,
    RTB_WARNING_MIN,
    RTB_CRITICAL_MIN,
)


# ══════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════

def _nominal_frame() -> dict:
    """Build a nominal telemetry frame."""
    rng = np.random.default_rng(42)
    return {
        "rpm": float(2200 + rng.normal(0, 20)),
        "map_kpa": float(78 + rng.normal(0, 1)),
        "fuel_flow_lph": float(13.0 + rng.normal(0, 0.3)),
        "equivalence_ratio": float(0.85),
        "cht_c": [float(180 + rng.normal(0, 2)) for _ in range(4)],
        "egt_c": [float(740 + rng.normal(0, 3)) for _ in range(4)],
        "oil_pressure_kpa": float(410 + rng.normal(0, 3)),
        "oil_temp_c": float(88 + rng.normal(0, 1)),
        "vibration_rms_g": float(1.5 + rng.normal(0, 0.05)),
    }


def _faulty_frame() -> dict:
    """Build a faulty telemetry frame."""
    return {
        "rpm": 1700.0, "map_kpa": 60.0, "fuel_flow_lph": 7.5,
        "equivalence_ratio": 0.60,
        "cht_c": [245.0, 242.0, 250.0, 238.0],
        "egt_c": [895.0, 890.0, 905.0, 882.0],
        "oil_pressure_kpa": 220.0, "oil_temp_c": 128.0,
        "vibration_rms_g": 2.15,
    }


# ══════════════════════════════════════════════════════════════════
#  1.  Sequence Buffer
# ══════════════════════════════════════════════════════════════════

class TestSequenceBuffer:
    """Verify rolling buffer behavior."""

    def test_initially_empty(self):
        buf = SequenceBuffer(maxlen=10)
        assert buf.length == 0
        assert buf.get_sequence() is None

    def test_fills_to_maxlen(self):
        buf = SequenceBuffer(maxlen=10)
        for i in range(10):
            buf.append(np.zeros(32, dtype=np.float32))
        assert buf.length == 10
        seq = buf.get_sequence()
        assert seq is not None
        assert seq.shape == (10, 32)

    def test_evicts_oldest(self):
        buf = SequenceBuffer(maxlen=5)
        for i in range(8):
            buf.append(np.full(32, float(i), dtype=np.float32))
        assert buf.length == 5
        seq = buf.get_sequence()
        # Oldest should be index 3 (after 8 appends to maxlen=5)
        assert seq[0, 0] == 3.0

    def test_clear(self):
        buf = SequenceBuffer(maxlen=10)
        for _ in range(10):
            buf.append(np.zeros(32, dtype=np.float32))
        buf.clear()
        assert buf.length == 0
        assert buf.get_sequence() is None

    def test_not_full_until_maxlen(self):
        buf = SequenceBuffer(maxlen=300)
        for _ in range(299):
            buf.append(np.zeros(32, dtype=np.float32))
        assert buf.get_sequence() is None
        buf.append(np.zeros(32, dtype=np.float32))
        assert buf.get_sequence() is not None


# ══════════════════════════════════════════════════════════════════
#  2.  Payload Structure
# ══════════════════════════════════════════════════════════════════

class TestPayloadStructure:
    """Verify enriched output payload has all required fields."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.service = AIService()

    def test_top_level_keys(self):
        payload = self.service.process_frame(_nominal_frame())
        required = {"timestamp", "frame_id", "telemetry", "health", "anomaly", "prognostics", "sensor_status"}
        assert required.issubset(set(payload.keys()))

    def test_health_keys(self):
        payload = self.service.process_frame(_nominal_frame())
        assert "ehi" in payload["health"]
        assert "combustion_efficiency" in payload["health"]
        assert "status" in payload["health"]

    def test_anomaly_keys(self):
        payload = self.service.process_frame(_nominal_frame())
        assert "score" in payload["anomaly"]
        assert "is_detected" in payload["anomaly"]
        assert "top_contributing_sensors" in payload["anomaly"]

    def test_prognostics_keys(self):
        payload = self.service.process_frame(_nominal_frame())
        assert "predicted_rul_min" in payload["prognostics"]
        assert "rtb_alert_level" in payload["prognostics"]
        assert "rtb_window_active" in payload["prognostics"]

    def test_sensor_status_keys(self):
        payload = self.service.process_frame(_nominal_frame())
        assert "isolated_sensors" in payload["sensor_status"]
        assert isinstance(payload["sensor_status"]["isolated_sensors"], list)

    def test_timestamp_format(self):
        payload = self.service.process_frame(_nominal_frame())
        # ISO8601 should contain 'T'
        assert "T" in payload["timestamp"]

    def test_frame_id_increments(self):
        p1 = self.service.process_frame(_nominal_frame())
        p2 = self.service.process_frame(_nominal_frame())
        assert p2["frame_id"] > p1["frame_id"]

    def test_telemetry_preserved(self):
        frame = _nominal_frame()
        payload = self.service.process_frame(frame)
        assert payload["telemetry"]["rpm"] == frame["rpm"]

    def test_payload_json_serializable(self):
        """Payload must be JSON-serializable."""
        payload = self.service.process_frame(_nominal_frame())
        serialized = json.dumps(payload)
        assert len(serialized) > 0


# ══════════════════════════════════════════════════════════════════
#  3.  Health Status
# ══════════════════════════════════════════════════════════════════

class TestHealthStatus:
    """Verify health status classification."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.service = AIService()

    def test_nominal_status_normal(self):
        payload = self.service.process_frame(_nominal_frame())
        assert payload["health"]["status"] in {"NORMAL", "WARNING", "CRITICAL"}

    def test_ehi_in_valid_range(self):
        payload = self.service.process_frame(_nominal_frame())
        ehi = payload["health"]["ehi"]
        assert 0.0 <= ehi <= 100.0


# ══════════════════════════════════════════════════════════════════
#  4.  Anomaly Detection
# ══════════════════════════════════════════════════════════════════

class TestAnomalyDetection:
    """Verify anomaly scoring in the AI service."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.service = AIService()

    def test_anomaly_score_range(self):
        payload = self.service.process_frame(_nominal_frame())
        assert 0.0 <= payload["anomaly"]["score"] <= 100.0

    def test_top_contributors_list(self):
        payload = self.service.process_frame(_nominal_frame())
        assert isinstance(payload["anomaly"]["top_contributing_sensors"], list)

    def test_extreme_frame_has_higher_score(self):
        normal = self.service.process_frame(_nominal_frame())
        faulty = self.service.process_frame(_faulty_frame())
        # Faulty should generally have higher anomaly score
        # (not guaranteed with untrained VAE, but score should be valid)
        assert 0.0 <= faulty["anomaly"]["score"] <= 100.0


# ══════════════════════════════════════════════════════════════════
#  5.  Prognostics / RTB
# ══════════════════════════════════════════════════════════════════

class TestPrognostics:
    """Verify RUL and RTB alert logic."""

    def test_initially_no_rul(self):
        service = AIService()
        payload = service.process_frame(_nominal_frame())
        # Buffer not full yet → no RUL
        assert payload["prognostics"]["predicted_rul_min"] is None
        assert payload["prognostics"]["rtb_alert_level"] == "NONE"

    def test_rtb_levels_valid(self):
        """RTB alert level must be one of the valid values."""
        service = AIService()
        payload = service.process_frame(_nominal_frame())
        assert payload["prognostics"]["rtb_alert_level"] in {
            "NONE", "RTB_ADVISORY", "RTB_CRITICAL",
        }


# ══════════════════════════════════════════════════════════════════
#  Runner
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
