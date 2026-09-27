-- ══════════════════════════════════════════════════════════════════════════════
-- Aero Piston Engine Digital Twin - TimescaleDB Schema
-- ══════════════════════════════════════════════════════════════════════════════

-- Enable TimescaleDB extension (idempotent)
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ══════════════════════════════════════════════════════════════════════════════
-- Engine Telemetry Table
-- ══════════════════════════════════════════════════════════════════════════════

DROP TABLE IF EXISTS engine_telemetry CASCADE;

CREATE TABLE engine_telemetry (
    -- Time column (required for hypertable)
    time            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Frame identifier
    frame_id        BIGINT NOT NULL,
    
    -- Engine sensors
    rpm             REAL,
    map_kpa         REAL,
    fuel_flow_lph   REAL,
    cht             REAL[],          -- [cyl1, cyl2, cyl3, cyl4]
    egt             REAL[],          -- [cyl1, cyl2, cyl3, cyl4]
    oil_pressure_kpa REAL,
    oil_temp_c      REAL,
    vibration_rms   REAL,
    
    -- AI fusion outputs
    ehi                     REAL,    -- Engine Health Index (0-100)
    combustion_efficiency   REAL,    -- CDM (0-100)
    thermal_balance_spread  REAL,    -- Cylinder thermal balance
    
    -- Anomaly detection
    anomaly_score   REAL,            -- VAE anomaly score (0-100)
    is_anomaly      BOOLEAN DEFAULT FALSE,
    
    -- Prognostics
    predicted_rul_min       REAL,    -- Remaining useful life in minutes
    rtb_alert_level         TEXT,    -- NONE, RTB_ADVISORY, RTB_CRITICAL
    
    -- Sensor health
    active_sensors          JSONB,   -- {"rpm": true, "cht_2_c": false, ...}
    sensor_isolation_flags  JSONB,   -- [{"channel": "cht_2_c", "reason": "ISOLATED_FROZEN"}]
    
    -- Environment
    altitude_ft             REAL,
    ambient_temp_c          REAL,
    
    -- Fault injection (for training data)
    injected_fault          TEXT,    -- e.g., "PISTON_RING_WEAR" or NULL
    
    -- Metadata
    mission_id      UUID DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════════════════════
-- Convert to TimescaleDB Hypertable
-- ══════════════════════════════════════════════════════════════════════════════

-- Chunk interval: 1 day (appropriate for 10 Hz telemetry = ~864,000 rows/day)
SELECT create_hypertable('engine_telemetry', 'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- ══════════════════════════════════════════════════════════════════════════════
-- Indices for Query Performance
-- ══════════════════════════════════════════════════════════════════════════════

-- Primary time-based index (descending for recent-first queries)
CREATE INDEX IF NOT EXISTS idx_engine_telemetry_time_desc 
    ON engine_telemetry (time DESC);

-- Anomaly detection queries
CREATE INDEX IF NOT EXISTS idx_engine_telemetry_is_anomaly 
    ON engine_telemetry (is_anomaly) 
    WHERE is_anomaly = TRUE;

-- Mission replay queries
CREATE INDEX IF NOT EXISTS idx_engine_telemetry_mission_id 
    ON engine_telemetry (mission_id, time DESC);

-- RUL threshold queries
CREATE INDEX IF NOT EXISTS idx_engine_telemetry_rul 
    ON engine_telemetry (predicted_rul_min ASC NULLS LAST)
    WHERE predicted_rul_min IS NOT NULL;

-- RTB alert queries
CREATE INDEX IF NOT EXISTS idx_engine_telemetry_rtb_alert 
    ON engine_telemetry (rtb_alert_level)
    WHERE rtb_alert_level != 'NONE';

-- Composite index for time-range anomaly queries
CREATE INDEX IF NOT EXISTS idx_engine_telemetry_time_anomaly 
    ON engine_telemetry (time DESC, is_anomaly)
    WHERE is_anomaly = TRUE;

-- ══════════════════════════════════════════════════════════════════════════════
-- Continuous Aggregates (for dashboard rollups)
-- ══════════════════════════════════════════════════════════════════════════════

-- 1-minute rollup for dashboard charts
CREATE MATERIALIZED VIEW IF NOT EXISTS engine_telemetry_1min
    WITH (timescaledb.continuous) AS
    SELECT 
        time_bucket('1 minute', time) AS bucket,
        mission_id,
        AVG(rpm) AS avg_rpm,
        MAX(rpm) AS max_rpm,
        MIN(rpm) AS min_rpm,
        AVG(map_kpa) AS avg_map_kpa,
        AVG(fuel_flow_lph) AS avg_fuel_flow_lph,
        AVG(unnest(cht)) AS avg_cht,  -- Note: requires expansion
        AVG(egt[1]) AS avg_egt_cyl1,
        AVG(egt[2]) AS avg_egt_cyl2,
        AVG(egt[3]) AS avg_egt_cyl3,
        AVG(egt[4]) AS avg_egt_cyl4,
        AVG(oil_pressure_kpa) AS avg_oil_pressure,
        AVG(oil_temp_c) AS avg_oil_temp,
        AVG(vibration_rms) AS avg_vibration,
        AVG(ehi) AS avg_ehi,
        MIN(ehi) AS min_ehi,
        MAX(anomaly_score) AS max_anomaly_score,
        SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END) AS anomaly_count,
        MIN(predicted_rul_min) AS min_rul,
        COUNT(*) AS sample_count
    FROM engine_telemetry
    GROUP BY bucket, mission_id
    WITH NO DATA;

-- Add refresh policy (refresh every 5 minutes)
SELECT add_continuous_aggregate_policy('engine_telemetry_1min',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE
);

-- ══════════════════════════════════════════════════════════════════════════════
-- Data Retention Policy (optional - keep raw data for 30 days)
-- ══════════════════════════════════════════════════════════════════════════════

SELECT add_retention_policy('engine_telemetry', INTERVAL '30 days', if_not_exists => TRUE);

-- ══════════════════════════════════════════════════════════════════════════════
-- Compression Policy (compress chunks older than 7 days)
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE engine_telemetry SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'mission_id',
    timescaledb.compress_orderby = 'time DESC'
);

SELECT add_compression_policy('engine_telemetry', INTERVAL '7 days', if_not_exists => TRUE);

-- ══════════════════════════════════════════════════════════════════════════════
-- Sample Queries (for reference)
-- ══════════════════════════════════════════════════════════════════════════════

/*
-- Get recent telemetry (last 5 minutes)
SELECT * FROM engine_telemetry 
WHERE time > NOW() - INTERVAL '5 minutes'
ORDER BY time DESC 
LIMIT 100;

-- Get all anomalies during a mission
SELECT time, frame_id, anomaly_score, ehi, predicted_rul_min, rtb_alert_level
FROM engine_telemetry
WHERE mission_id = 'your-mission-uuid'
  AND is_anomaly = TRUE
ORDER BY time ASC;

-- Mission replay (time-series data for charting)
SELECT time, rpm, cht, egt, ehi, anomaly_score
FROM engine_telemetry
WHERE mission_id = 'your-mission-uuid'
  AND time BETWEEN '2024-01-01 10:00:00' AND '2024-01-01 12:00:00'
ORDER BY time ASC;

-- RTB alert events
SELECT time, predicted_rul_min, rtb_alert_level
FROM engine_telemetry
WHERE rtb_alert_level IN ('RTB_ADVISORY', 'RTB_CRITICAL')
ORDER BY time DESC;
*/
