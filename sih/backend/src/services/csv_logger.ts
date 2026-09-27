import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { config } from '../config.js';

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

export type EventType = 
  | 'ANOMALY_DETECTED'
  | 'RTB_WARNING'
  | 'RTB_CRITICAL'
  | 'SENSOR_ISOLATED'
  | 'CRITICAL_OVERHEAT'
  | 'FAULT_INJECTED'
  | 'HEALTH_DEGRADED'
  | 'ENGINE_START'
  | 'ENGINE_STOP';

export type Severity = 'INFO' | 'WARNING' | 'CRITICAL';

export interface IncidentEvent {
  timestamp: Date;
  frameId: number;
  eventType: EventType;
  severity: Severity;
  ehi: number | null;
  predictedRulMin: number | null;
  triggerDetails: Record<string, any>;
  isolatedSensors: string[];
}

export interface TelemetryFrame {
  frame_id: number;
  is_anomaly?: boolean;
  anomaly_score?: number;
  ehi?: number;
  predicted_rul_min?: number;
  rtb_alert_level?: string;
  sensor_isolation_flags?: Array<{ channel: string; reason: string }>;
  [key: string]: any;
}

export interface LoggerStats {
  totalEventsLogged: number;
  eventsByType: Record<string, number>;
  eventsBySeverity: Record<string, number>;
  currentLogFile: string | null;
  isStreaming: boolean;
}

// ══════════════════════════════════════════════════════════════════════════════
// CSV Logger
// ══════════════════════════════════════════════════════════════════════════════

export class CSVLogger {
  private logDir: string;
  private writeStream: fs.WriteStream | null = null;
  private currentLogFile: string | null = null;
  private currentDateString: string | null = null;
  private initialized: boolean = false;
  
  // Statistics
  private totalEventsLogged: number = 0;
  private eventsByType: Record<string, number> = {};
  private eventsBySeverity: Record<string, number> = {};
  
  // Track isolated sensors to avoid duplicate logging
  private previouslyIsolatedSensors: Set<string> = new Set();

  constructor(logDir?: string) {
    this.logDir = logDir ?? path.resolve(config.logDir);
  }

  // ─── Lifecycle ─────────────────────────────────────────────────────────────

  /**
   * Initialize the logger and create/open the daily log file
   */
  async initialize(): Promise<void> {
    // Ensure log directory exists
    if (!fs.existsSync(this.logDir)) {
      fs.mkdirSync(this.logDir, { recursive: true });
      console.log(`[CSVLogger] Created log directory: ${this.logDir}`);
    }

    // Open today's log file
    await this.rotateLogFileIfNeeded();
    
    this.initialized = true;
    console.log(`[CSVLogger] Initialized with log file: ${this.currentLogFile}`);
  }

  /**
   * Close the write stream gracefully
   */
  async shutdown(): Promise<void> {
    if (this.writeStream) {
      await new Promise<void>((resolve, reject) => {
        this.writeStream!.end(() => {
          console.log('[CSVLogger] Write stream closed');
          resolve();
        });
        this.writeStream!.on('error', reject);
      });
      this.writeStream = null;
    }

    this.initialized = false;
    console.log('[CSVLogger] Shutdown complete');
  }

  // ─── Logging ───────────────────────────────────────────────────────────────

  /**
   * Process a telemetry frame and log incidents if applicable
   */
  async processFrame(frame: TelemetryFrame): Promise<void> {
    if (!this.initialized) {
      await this.initialize();
    }

    // Check if we need to rotate to a new day's file
    await this.rotateLogFileIfNeeded();

    // Generate incidents from the frame
    const incidents = this.extractIncidents(frame);

    // Write each incident
    for (const incident of incidents) {
      await this.writeIncident(incident);
    }
  }

  /**
   * Write an incident event directly (bypasses frame filtering)
   */
  async logIncident(event: IncidentEvent): Promise<void> {
    if (!this.initialized) {
      await this.initialize();
    }

    await this.rotateLogFileIfNeeded();
    await this.writeIncident(event);
  }

  // ─── Incident Extraction ───────────────────────────────────────────────────

  /**
   * Extract incidents from a telemetry frame based on filtering rules
   */
  private extractIncidents(frame: TelemetryFrame): IncidentEvent[] {
    const incidents: IncidentEvent[] = [];
    const timestamp = new Date();
    const frameId = frame.frame_id ?? 0;

    // 1. Anomaly Detection
    if (frame.is_anomaly === true) {
      incidents.push({
        timestamp,
        frameId,
        eventType: 'ANOMALY_DETECTED',
        severity: this.determineAnomalySeverity(frame),
        ehi: frame.ehi ?? null,
        predictedRulMin: frame.predicted_rul_min ?? null,
        triggerDetails: {
          anomaly_score: frame.anomaly_score,
          ehi: frame.ehi,
        },
        isolatedSensors: this.extractIsolatedSensorNames(frame),
      });
    }

    // 2. RTB Alerts
    if (frame.rtb_alert_level && frame.rtb_alert_level !== 'NONE') {
      const severity: Severity = frame.rtb_alert_level === 'RTB_CRITICAL' ? 'CRITICAL' : 'WARNING';
      incidents.push({
        timestamp,
        frameId,
        eventType: frame.rtb_alert_level === 'RTB_CRITICAL' ? 'RTB_CRITICAL' : 'RTB_WARNING',
        severity,
        ehi: frame.ehi ?? null,
        predictedRulMin: frame.predicted_rul_min ?? null,
        triggerDetails: {
          rtb_alert_level: frame.rtb_alert_level,
          predicted_rul_min: frame.predicted_rul_min,
        },
        isolatedSensors: this.extractIsolatedSensorNames(frame),
      });
    }

    // 3. Sensor Isolation (only log newly isolated sensors)
    const currentIsolated = this.extractIsolatedSensorNames(frame);
    const newlyIsolated = currentIsolated.filter(
      (sensor) => !this.previouslyIsolatedSensors.has(sensor)
    );

    if (newlyIsolated.length > 0) {
      incidents.push({
        timestamp,
        frameId,
        eventType: 'SENSOR_ISOLATED',
        severity: 'WARNING',
        ehi: frame.ehi ?? null,
        predictedRulMin: frame.predicted_rul_min ?? null,
        triggerDetails: {
          newly_isolated: newlyIsolated,
          all_isolated: currentIsolated,
        },
        isolatedSensors: currentIsolated,
      });

      // Update tracking set
      newlyIsolated.forEach((s) => this.previouslyIsolatedSensors.add(s));
    }

    // 4. Critical Overheat (CHT > 240°C)
    const maxCht = this.getMaxCht(frame);
    if (maxCht !== null && maxCht > 240) {
      incidents.push({
        timestamp,
        frameId,
        eventType: 'CRITICAL_OVERHEAT',
        severity: 'CRITICAL',
        ehi: frame.ehi ?? null,
        predictedRulMin: frame.predicted_rul_min ?? null,
        triggerDetails: {
          max_cht: maxCht,
          cht_values: frame.cht,
        },
        isolatedSensors: currentIsolated,
      });
    }

    // 5. Health Degraded (EHI < 50)
    if (frame.ehi !== null && frame.ehi !== undefined && frame.ehi < 50) {
      // Only log if not already covered by anomaly detection
      if (!frame.is_anomaly) {
        incidents.push({
          timestamp,
          frameId,
          eventType: 'HEALTH_DEGRADED',
          severity: 'WARNING',
          ehi: frame.ehi,
          predictedRulMin: frame.predicted_rul_min ?? null,
          triggerDetails: {
            ehi: frame.ehi,
            threshold: 50,
          },
          isolatedSensors: currentIsolated,
        });
      }
    }

    return incidents;
  }

  // ─── File Writing ──────────────────────────────────────────────────────────

  /**
   * Write a single incident to the CSV file
   */
  private async writeIncident(incident: IncidentEvent): Promise<void> {
    if (!this.writeStream) {
      console.error('[CSVLogger] No write stream available');
      return;
    }

    const row = this.incidentToCSVRow(incident);
    
    return new Promise((resolve, reject) => {
      this.writeStream!.write(row + '\n', (err) => {
        if (err) {
          console.error('[CSVLogger] Write error:', err);
          reject(err);
        } else {
          // Update statistics
          this.totalEventsLogged++;
          this.eventsByType[incident.eventType] = 
            (this.eventsByType[incident.eventType] ?? 0) + 1;
          this.eventsBySeverity[incident.severity] = 
            (this.eventsBySeverity[incident.severity] ?? 0) + 1;
          
          resolve();
        }
      });
    });
  }

  /**
   * Convert an incident to a CSV row
   */
  private incidentToCSVRow(incident: IncidentEvent): string {
    const fields = [
      incident.timestamp.toISOString(),
      incident.frameId.toString(),
      incident.eventType,
      incident.severity,
      incident.ehi?.toFixed(2) ?? '',
      incident.predictedRulMin?.toFixed(2) ?? '',
      this.escapeCSVField(JSON.stringify(incident.triggerDetails)),
      this.escapeCSVField(JSON.stringify(incident.isolatedSensors)),
    ];

    return fields.join(',');
  }

  /**
   * Escape a CSV field (handle commas, quotes, newlines)
   */
  private escapeCSVField(value: string): string {
    if (value.includes(',') || value.includes('"') || value.includes('\n')) {
      return `"${value.replace(/"/g, '""')}"`;
    }
    return value;
  }

  // ─── Log File Rotation ─────────────────────────────────────────────────────

  /**
   * Rotate to a new log file if the date has changed
   */
  private async rotateLogFileIfNeeded(): Promise<void> {
    const today = this.getDateString();

    // Only rotate if date has changed or first initialization
    if (today === this.currentDateString && this.writeStream) {
      return;
    }

    // Close existing stream
    if (this.writeStream) {
      await new Promise<void>((resolve) => {
        this.writeStream!.end(() => resolve());
      });
    }

    // Create new log file path
    const logFileName = `incident_log_${today}.csv`;
    const logFilePath = path.join(this.logDir, logFileName);

    // Check if file exists to determine if we need to write header
    const fileExists = fs.existsSync(logFilePath);

    // Open file in append mode
    this.writeStream = fs.createWriteStream(logFilePath, {
      flags: 'a',
      encoding: 'utf-8',
    });

    // Write header if this is a new file
    if (!fileExists) {
      await new Promise<void>((resolve, reject) => {
        this.writeStream!.write(this.getCSVHeader() + '\n', (err) => {
          if (err) reject(err);
          else resolve();
        });
      });
      console.log(`[CSVLogger] Created new log file: ${logFilePath}`);
    } else {
      console.log(`[CSVLogger] Appending to existing log file: ${logFilePath}`);
    }

    this.currentLogFile = logFilePath;
    this.currentDateString = today;
  }

  /**
   * Get CSV header row
   */
  private getCSVHeader(): string {
    return 'timestamp,frame_id,event_type,severity,ehi,predicted_rul_min,trigger_details,isolated_sensors';
  }

  /**
   * Get current date string in YYYY-MM-DD format
   */
  private getDateString(): string {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  // ─── Helper Methods ────────────────────────────────────────────────────────

  private determineAnomalySeverity(frame: TelemetryFrame): Severity {
    const score = frame.anomaly_score ?? 0;
    
    if (score > 80 || (frame.ehi !== null && frame.ehi !== undefined && frame.ehi < 30)) {
      return 'CRITICAL';
    } else if (score > 50 || (frame.ehi !== null && frame.ehi !== undefined && frame.ehi < 60)) {
      return 'WARNING';
    }
    return 'INFO';
  }

  private extractIsolatedSensorNames(frame: TelemetryFrame): string[] {
    if (!frame.sensor_isolation_flags || !Array.isArray(frame.sensor_isolation_flags)) {
      return [];
    }
    return frame.sensor_isolation_flags.map((f) => f.channel);
  }

  private getMaxCht(frame: TelemetryFrame): number | null {
    if (!frame.cht || !Array.isArray(frame.cht) || frame.cht.length === 0) {
      return null;
    }
    return Math.max(...frame.cht.filter((v) => v !== null && v !== undefined));
  }

  // ─── Statistics ────────────────────────────────────────────────────────────

  /**
   * Get logger statistics
   */
  getStats(): LoggerStats {
    return {
      totalEventsLogged: this.totalEventsLogged,
      eventsByType: { ...this.eventsByType },
      eventsBySeverity: { ...this.eventsBySeverity },
      currentLogFile: this.currentLogFile,
      isStreaming: this.writeStream !== null && !this.writeStream.destroyed,
    };
  }

  /**
   * Reset isolated sensor tracking (e.g., on mission restart)
   */
  resetIsolatedSensorTracking(): void {
    this.previouslyIsolatedSensors.clear();
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// Singleton Instance
// ══════════════════════════════════════════════════════════════════════════════

let instance: CSVLogger | null = null;

export function getCSVLogger(): CSVLogger {
  if (!instance) {
    instance = new CSVLogger();
  }
  return instance;
}

export async function initializeCSVLogger(): Promise<CSVLogger> {
  const logger = getCSVLogger();
  await logger.initialize();
  return logger;
}

export async function shutdownCSVLogger(): Promise<void> {
  if (instance) {
    await instance.shutdown();
    instance = null;
  }
}

export default CSVLogger;
