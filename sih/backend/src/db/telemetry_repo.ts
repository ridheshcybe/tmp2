import { DatabaseClient, getDatabaseClient } from './db_client.js';

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

export interface TelemetryRecord {
  time: Date;
  frameId: number;
  rpm: number | null;
  mapKpa: number | null;
  fuelFlowLph: number | null;
  cht: number[] | null;       // [cyl1, cyl2, cyl3, cyl4]
  egt: number[] | null;       // [cyl1, cyl2, cyl3, cyl4]
  oilPressureKpa: number | null;
  oilTempC: number | null;
  vibrationRms: number | null;
  
  // AI fusion outputs
  ehi: number | null;
  combustionEfficiency: number | null;
  thermalBalanceSpread: number | null;
  
  // Anomaly detection
  anomalyScore: number | null;
  isAnomaly: boolean;
  
  // Prognostics
  predictedRulMin: number | null;
  rtbAlertLevel: string | null;
  
  // Sensor health
  activeSensors: Record<string, boolean> | null;
  sensorIsolationFlags: Array<{ channel: string; reason: string }> | null;
  
  // Environment
  altitudeFt: number | null;
  ambientTempC: number | null;
  
  // Metadata
  missionId?: string;
  injectedFault?: string | null;
}

export interface MissionHistoryQuery {
  startTime: Date;
  endTime: Date;
  missionId?: string;
  limit?: number;
  offset?: number;
}

export interface BatchInsertResult {
  insertedCount: number;
  batchTimeMs: number;
}

// ══════════════════════════════════════════════════════════════════════════════
// Telemetry Repository
// ══════════════════════════════════════════════════════════════════════════════

export class TelemetryRepository {
  private db: DatabaseClient;
  private insertBuffer: TelemetryRecord[] = [];
  private flushInterval: NodeJS.Timeout | null = null;
  private readonly FLUSH_INTERVAL_MS = 500;
  private readonly MAX_BUFFER_SIZE = 100; // Flush early if buffer gets large

  constructor(db?: DatabaseClient) {
    this.db = db ?? getDatabaseClient();
  }

  // ─── Lifecycle ─────────────────────────────────────────────────────────────

  /**
   * Start the batch insert flush timer
   */
  startBatchInsert(): void {
    if (this.flushInterval) {
      return;
    }

    this.flushInterval = setInterval(async () => {
      await this.flushBuffer();
    }, this.FLUSH_INTERVAL_MS);

    console.log(`[TelemetryRepo] Batch insert started (flush every ${this.FLUSH_INTERVAL_MS}ms)`);
  }

  /**
   * Stop the batch insert and flush remaining records
   */
  async stopBatchInsert(): Promise<void> {
    if (this.flushInterval) {
      clearInterval(this.flushInterval);
      this.flushInterval = null;
    }

    // Flush any remaining records
    await this.flushBuffer();
    console.log('[TelemetryRepo] Batch insert stopped');
  }

  // ─── Insert Operations ─────────────────────────────────────────────────────

  /**
   * Buffer a telemetry record for batch insertion
   */
  bufferRecord(record: TelemetryRecord): void {
    this.insertBuffer.push(record);

    // Flush early if buffer is getting large
    if (this.insertBuffer.length >= this.MAX_BUFFER_SIZE) {
      this.flushBuffer().catch((err) => {
        console.error('[TelemetryRepo] Error flushing buffer:', err);
      });
    }
  }

  /**
   * Insert a single record immediately (bypasses buffer)
   */
  async insertRecord(record: TelemetryRecord): Promise<void> {
    const sql = this.buildInsertSQL();
    const params = this.recordToParams(record);

    await this.db.query(sql, params);
  }

  /**
   * Insert multiple records in a single batch
   */
  async insertBatch(records: TelemetryRecord[]): Promise<BatchInsertResult> {
    if (records.length === 0) {
      return { insertedCount: 0, batchTimeMs: 0 };
    }

    const startTime = Date.now();

    // Build multi-row insert
    const values: any[][] = [];
    const placeholders: string[] = [];

    records.forEach((record, index) => {
      const params = this.recordToParams(record);
      const offset = index * this.getColumnCount();
      const placeholder = this.buildPlaceholderRow(offset);
      placeholders.push(`(${placeholder})`);
      values.push(...params);
    });

    const sql = `
      INSERT INTO engine_telemetry (
        time, frame_id, rpm, map_kpa, fuel_flow_lph, cht, egt,
        oil_pressure_kpa, oil_temp_c, vibration_rms,
        ehi, combustion_efficiency, thermal_balance_spread,
        anomaly_score, is_anomaly,
        predicted_rul_min, rtb_alert_level,
        active_sensors, sensor_isolation_flags,
        altitude_ft, ambient_temp_c,
        mission_id, injected_fault
      ) VALUES ${placeholders.join(', ')}
    `;

    await this.db.query(sql, values);

    return {
      insertedCount: records.length,
      batchTimeMs: Date.now() - startTime,
    };
  }

  /**
   * Flush the internal buffer to the database
   */
  private async flushBuffer(): Promise<void> {
    if (this.insertBuffer.length === 0) {
      return;
    }

    const records = this.insertBuffer.splice(0);
    
    try {
      const result = await this.insertBatch(records);
      console.log(
        `[TelemetryRepo] Flushed ${result.insertedCount} records in ${result.batchTimeMs}ms`
      );
    } catch (err) {
      console.error('[TelemetryRepo] Flush failed, re-buffering records:', err);
      // Re-add records to buffer for retry
      this.insertBuffer.unshift(...records);
    }
  }

  // ─── Query Operations ──────────────────────────────────────────────────────

  /**
   * Get mission history for replay
   */
  async getMissionHistory(query: MissionHistoryQuery): Promise<TelemetryRecord[]> {
    const {
      startTime,
      endTime,
      missionId,
      limit = 10000,
      offset = 0,
    } = query;

    let sql = `
      SELECT 
        time, frame_id, rpm, map_kpa, fuel_flow_lph, cht, egt,
        oil_pressure_kpa, oil_temp_c, vibration_rms,
        ehi, combustion_efficiency, thermal_balance_spread,
        anomaly_score, is_anomaly,
        predicted_rul_min, rtb_alert_level,
        active_sensors, sensor_isolation_flags,
        altitude_ft, ambient_temp_c,
        mission_id, injected_fault
      FROM engine_telemetry
      WHERE time >= $1 AND time <= $2
    `;
    const params: any[] = [startTime, endTime];

    if (missionId) {
      sql += ` AND mission_id = $3`;
      params.push(missionId);
    }

    sql += ` ORDER BY time ASC`;
    
    if (missionId) {
      sql += ` LIMIT $4 OFFSET $5`;
      params.push(limit, offset);
    } else {
      sql += ` LIMIT $3 OFFSET $4`;
      params.push(limit, offset);
    }

    const result = await this.db.query(sql, params);
    return result.rows.map(this.rowToRecord);
  }

  /**
   * Get recent telemetry (last N seconds)
   */
  async getRecentTelemetry(
    seconds: number = 60,
    missionId?: string
  ): Promise<TelemetryRecord[]> {
    const startTime = new Date(Date.now() - seconds * 1000);
    const endTime = new Date();

    return this.getMissionHistory({
      startTime,
      endTime,
      missionId,
      limit: seconds * 10, // 10 Hz
    });
  }

  /**
   * Get all anomalies for a mission
   */
  async getAnomalies(
    startTime: Date,
    endTime: Date,
    missionId?: string
  ): Promise<TelemetryRecord[]> {
    let sql = `
      SELECT 
        time, frame_id, rpm, map_kpa, fuel_flow_lph, cht, egt,
        oil_pressure_kpa, oil_temp_c, vibration_rms,
        ehi, combustion_efficiency, thermal_balance_spread,
        anomaly_score, is_anomaly,
        predicted_rul_min, rtb_alert_level,
        active_sensors, sensor_isolation_flags,
        altitude_ft, ambient_temp_c,
        mission_id, injected_fault
      FROM engine_telemetry
      WHERE is_anomaly = TRUE
        AND time >= $1 AND time <= $2
    `;
    const params: any[] = [startTime, endTime];

    if (missionId) {
      sql += ` AND mission_id = $3`;
      params.push(missionId);
    }

    sql += ` ORDER BY time ASC`;

    const result = await this.db.query(sql, params);
    return result.rows.map(this.rowToRecord);
  }

  /**
   * Get RTB alert events
   */
  async getRTBAlerts(
    startTime: Date,
    endTime: Date,
    missionId?: string
  ): Promise<TelemetryRecord[]> {
    let sql = `
      SELECT 
        time, frame_id, rpm, map_kpa, fuel_flow_lph, cht, egt,
        oil_pressure_kpa, oil_temp_c, vibration_rms,
        ehi, combustion_efficiency, thermal_balance_spread,
        anomaly_score, is_anomaly,
        predicted_rul_min, rtb_alert_level,
        active_sensors, sensor_isolation_flags,
        altitude_ft, ambient_temp_c,
        mission_id, injected_fault
      FROM engine_telemetry
      WHERE rtb_alert_level IN ('RTB_ADVISORY', 'RTB_CRITICAL')
        AND time >= $1 AND time <= $2
    `;
    const params: any[] = [startTime, endTime];

    if (missionId) {
      sql += ` AND mission_id = $3`;
      params.push(missionId);
    }

    sql += ` ORDER BY time ASC`;

    const result = await this.db.query(sql, params);
    return result.rows.map(this.rowToRecord);
  }

  /**
   * Get aggregated statistics for a time range
   */
  async getAggregatedStats(
    startTime: Date,
    endTime: Date,
    bucketSeconds: number = 60,
    missionId?: string
  ): Promise<any[]> {
    let sql = `
      SELECT 
        time_bucket('${bucketSeconds} seconds', time) AS bucket,
        AVG(rpm) AS avg_rpm,
        MAX(rpm) AS max_rpm,
        MIN(rpm) AS min_rpm,
        AVG(map_kpa) AS avg_map_kpa,
        AVG(fuel_flow_lph) AS avg_fuel_flow_lph,
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
      WHERE time >= $1 AND time <= $2
    `;
    const params: any[] = [startTime, endTime];

    if (missionId) {
      sql += ` AND mission_id = $3`;
      params.push(missionId);
    }

    sql += `
      GROUP BY bucket
      ORDER BY bucket ASC
    `;

    const result = await this.db.query(sql, params);
    return result.rows;
  }

  // ─── Helper Methods ────────────────────────────────────────────────────────

  private buildInsertSQL(): string {
    return `
      INSERT INTO engine_telemetry (
        time, frame_id, rpm, map_kpa, fuel_flow_lph, cht, egt,
        oil_pressure_kpa, oil_temp_c, vibration_rms,
        ehi, combustion_efficiency, thermal_balance_spread,
        anomaly_score, is_anomaly,
        predicted_rul_min, rtb_alert_level,
        active_sensors, sensor_isolation_flags,
        altitude_ft, ambient_temp_c,
        mission_id, injected_fault
      ) VALUES (
        $1, $2, $3, $4, $5, $6, $7,
        $8, $9, $10,
        $11, $12, $13,
        $14, $15,
        $16, $17,
        $18, $19,
        $20, $21,
        $22, $23
      )
    `;
  }

  private recordToParams(record: TelemetryRecord): any[] {
    return [
      record.time,
      record.frameId,
      record.rpm,
      record.mapKpa,
      record.fuelFlowLph,
      record.cht,
      record.egt,
      record.oilPressureKpa,
      record.oilTempC,
      record.vibrationRms,
      record.ehi,
      record.combustionEfficiency,
      record.thermalBalanceSpread,
      record.anomalyScore,
      record.isAnomaly,
      record.predictedRulMin,
      record.rtbAlertLevel,
      record.activeSensors ? JSON.stringify(record.activeSensors) : null,
      record.sensorIsolationFlags ? JSON.stringify(record.sensorIsolationFlags) : null,
      record.altitudeFt,
      record.ambientTempC,
      record.missionId ?? null,
      record.injectedFault ?? null,
    ];
  }

  private getColumnCount(): number {
    return 23;
  }

  private buildPlaceholderRow(offset: number): string {
    return Array.from({ length: this.getColumnCount() }, (_, i) => `$${offset + i + 1}`).join(', ');
  }

  private rowToRecord(row: any): TelemetryRecord {
    return {
      time: new Date(row.time),
      frameId: row.frame_id,
      rpm: row.rpm,
      mapKpa: row.map_kpa,
      fuelFlowLph: row.fuel_flow_lph,
      cht: row.cht,
      egt: row.egt,
      oilPressureKpa: row.oil_pressure_kpa,
      oilTempC: row.oil_temp_c,
      vibrationRms: row.vibration_rms,
      ehi: row.ehi,
      combustionEfficiency: row.combustion_efficiency,
      thermalBalanceSpread: row.thermal_balance_spread,
      anomalyScore: row.anomaly_score,
      isAnomaly: row.is_anomaly,
      predictedRulMin: row.predicted_rul_min,
      rtbAlertLevel: row.rtb_alert_level,
      activeSensors: row.active_sensors,
      sensorIsolationFlags: row.sensor_isolation_flags,
      altitudeFt: row.altitude_ft,
      ambientTempC: row.ambient_temp_c,
      missionId: row.mission_id,
      injectedFault: row.injected_fault,
    };
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// Singleton Instance
// ══════════════════════════════════════════════════════════════════════════════

let instance: TelemetryRepository | null = null;

export function getTelemetryRepository(): TelemetryRepository {
  if (!instance) {
    instance = new TelemetryRepository();
  }
  return instance;
}

export default TelemetryRepository;
