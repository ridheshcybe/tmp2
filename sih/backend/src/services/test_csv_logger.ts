#!/usr/bin/env node
// ══════════════════════════════════════════════════════════════════════════════
// CSV Logger Test Script
// Writes 10 dummy incident events and verifies the generated CSV structure
// ══════════════════════════════════════════════════════════════════════════════

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { CSVLogger, IncidentEvent, EventType, Severity } from './csv_logger.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ══════════════════════════════════════════════════════════════════════════════
// Test Configuration
// ══════════════════════════════════════════════════════════════════════════════

const TEST_LOG_DIR = path.resolve(__dirname, '../../../test_logs');
const EXPECTED_COLUMNS = [
  'timestamp',
  'frame_id',
  'event_type',
  'severity',
  'ehi',
  'predicted_rul_min',
  'trigger_details',
  'isolated_sensors',
];

// ══════════════════════════════════════════════════════════════════════════════
// Dummy Incident Events
// ══════════════════════════════════════════════════════════════════════════════

function generateDummyEvents(): IncidentEvent[] {
  const now = new Date();
  
  return [
    // 1. Normal anomaly detection
    {
      timestamp: new Date(now.getTime() - 9000),
      frameId: 100,
      eventType: 'ANOMALY_DETECTED',
      severity: 'INFO',
      ehi: 85.5,
      predictedRulMin: 120.0,
      triggerDetails: { anomaly_score: 25.3, ehi: 85.5 },
      isolatedSensors: [],
    },
    // 2. Warning-level anomaly
    {
      timestamp: new Date(now.getTime() - 8000),
      frameId: 200,
      eventType: 'ANOMALY_DETECTED',
      severity: 'WARNING',
      ehi: 62.0,
      predictedRulMin: 45.0,
      triggerDetails: { anomaly_score: 55.2, ehi: 62.0 },
      isolatedSensors: [],
    },
    // 3. Critical anomaly
    {
      timestamp: new Date(now.getTime() - 7000),
      frameId: 300,
      eventType: 'ANOMALY_DETECTED',
      severity: 'CRITICAL',
      ehi: 28.5,
      predictedRulMin: 12.0,
      triggerDetails: { anomaly_score: 85.7, ehi: 28.5 },
      isolatedSensors: ['cht_2_c'],
    },
    // 4. RTB Warning
    {
      timestamp: new Date(now.getTime() - 6000),
      frameId: 400,
      eventType: 'RTB_WARNING',
      severity: 'WARNING',
      ehi: 55.0,
      predictedRulMin: 25.0,
      triggerDetails: { rtb_alert_level: 'RTB_ADVISORY', predicted_rul_min: 25.0 },
      isolatedSensors: ['cht_2_c'],
    },
    // 5. RTB Critical
    {
      timestamp: new Date(now.getTime() - 5000),
      frameId: 500,
      eventType: 'RTB_CRITICAL',
      severity: 'CRITICAL',
      ehi: 35.0,
      predictedRulMin: 8.0,
      triggerDetails: { rtb_alert_level: 'RTB_CRITICAL', predicted_rul_min: 8.0 },
      isolatedSensors: ['cht_2_c', 'egt_1_c'],
    },
    // 6. Sensor isolation
    {
      timestamp: new Date(now.getTime() - 4000),
      frameId: 600,
      eventType: 'SENSOR_ISOLATED',
      severity: 'WARNING',
      ehi: 72.0,
      predictedRulMin: 80.0,
      triggerDetails: { newly_isolated: ['egt_3_c'], all_isolated: ['egt_3_c'] },
      isolatedSensors: ['egt_3_c'],
    },
    // 7. Critical overheat
    {
      timestamp: new Date(now.getTime() - 3000),
      frameId: 700,
      eventType: 'CRITICAL_OVERHEAT',
      severity: 'CRITICAL',
      ehi: 42.0,
      predictedRulMin: 15.0,
      triggerDetails: { max_cht: 248.5, cht_values: [220, 248.5, 235, 228] },
      isolatedSensors: [],
    },
    // 8. Health degraded
    {
      timestamp: new Date(now.getTime() - 2000),
      frameId: 800,
      eventType: 'HEALTH_DEGRADED',
      severity: 'WARNING',
      ehi: 48.0,
      predictedRulMin: 60.0,
      triggerDetails: { ehi: 48.0, threshold: 50 },
      isolatedSensors: [],
    },
    // 9. Fault injection event
    {
      timestamp: new Date(now.getTime() - 1000),
      frameId: 900,
      eventType: 'FAULT_INJECTED',
      severity: 'INFO',
      ehi: 90.0,
      predictedRulMin: 180.0,
      triggerDetails: { fault_type: 'PISTON_RING_WEAR', severity: 0.3 },
      isolatedSensors: [],
    },
    // 10. Another sensor isolation
    {
      timestamp: now,
      frameId: 1000,
      eventType: 'SENSOR_ISOLATED',
      severity: 'WARNING',
      ehi: 68.0,
      predictedRulMin: 55.0,
      triggerDetails: { newly_isolated: ['oil_pressure_kpa'], all_isolated: ['oil_pressure_kpa'] },
      isolatedSensors: ['oil_pressure_kpa'],
    },
  ];
}

// ══════════════════════════════════════════════════════════════════════════════
// Test Functions
// ══════════════════════════════════════════════════════════════════════════════

async function testCSVLogger(): Promise<void> {
  console.log('═══════════════════════════════════════════════════════════════════════════');
  console.log('CSV Logger Test');
  console.log('═══════════════════════════════════════════════════════════════════════════\n');

  // Clean up test directory
  if (fs.existsSync(TEST_LOG_DIR)) {
    fs.rmSync(TEST_LOG_DIR, { recursive: true });
  }

  // Create logger with test directory
  const logger = new CSVLogger(TEST_LOG_DIR);
  await logger.initialize();

  console.log('✓ Logger initialized');
  console.log(`  Log directory: ${TEST_LOG_DIR}`);
  console.log(`  Log file: ${logger.getStats().currentLogFile}\n`);

  // Generate and write dummy events
  const events = generateDummyEvents();
  console.log(`Writing ${events.length} dummy incident events...\n`);

  for (const event of events) {
    await logger.logIncident(event);
    console.log(`  ✓ ${event.eventType} (${event.severity}) at frame ${event.frameId}`);
  }

  // Get statistics
  const stats = logger.getStats();
  console.log('\n--- Logger Statistics ---');
  console.log(`Total events logged: ${stats.totalEventsLogged}`);
  console.log(`Events by type:`, stats.eventsByType);
  console.log(`Events by severity:`, stats.eventsBySeverity);

  // Shutdown logger
  await logger.shutdown();
  console.log('\n✓ Logger shutdown complete');

  // Verify CSV file
  await verifyCSVFile(stats.currentLogFile!);
}

async function verifyCSVFile(filePath: string): Promise<void> {
  console.log('\n═══════════════════════════════════════════════════════════════════════════');
  console.log('CSV File Verification');
  console.log('═══════════════════════════════════════════════════════════════════════════\n');

  if (!fs.existsSync(filePath)) {
    console.error('✗ CSV file does not exist:', filePath);
    process.exit(1);
  }

  const content = fs.readFileSync(filePath, 'utf-8');
  const lines = content.trim().split('\n');

  console.log(`File: ${filePath}`);
  console.log(`Total lines (including header): ${lines.length}`);
  console.log(`Data rows: ${lines.length - 1}\n`);

  // Verify header
  const header = lines[0];
  const columns = header.split(',');

  console.log('--- Header Verification ---');
  console.log(`Expected columns: ${EXPECTED_COLUMNS.length}`);
  console.log(`Actual columns: ${columns.length}`);
  
  const headerValid = EXPECTED_COLUMNS.every((col, idx) => columns[idx] === col);
  if (headerValid) {
    console.log('✓ Header columns match expected format');
  } else {
    console.error('✗ Header columns do not match');
    console.error('  Expected:', EXPECTED_COLUMNS);
    console.error('  Got:', columns);
    process.exit(1);
  }

  // Verify data rows
  console.log('\n--- Data Row Verification ---');
  let validRows = 0;
  let invalidRows = 0;

  for (let i = 1; i < lines.length; i++) {
    const row = lines[i];
    const fields = parseCSVRow(row);

    if (fields.length === EXPECTED_COLUMNS.length) {
      validRows++;
      
      // Verify event types
      const eventType = fields[2] as EventType;
      const validEventTypes: EventType[] = [
        'ANOMALY_DETECTED', 'RTB_WARNING', 'RTB_CRITICAL',
        'SENSOR_ISOLATED', 'CRITICAL_OVERHEAT', 'FAULT_INJECTED',
        'HEALTH_DEGRADED', 'ENGINE_START', 'ENGINE_STOP',
      ];
      
      if (!validEventTypes.includes(eventType)) {
        console.error(`  ✗ Row ${i}: Invalid event type: ${eventType}`);
        invalidRows++;
      }
    } else {
      console.error(`  ✗ Row ${i}: Expected ${EXPECTED_COLUMNS.length} fields, got ${fields.length}`);
      invalidRows++;
    }
  }

  console.log(`✓ Valid rows: ${validRows}`);
  if (invalidRows > 0) {
    console.error(`✗ Invalid rows: ${invalidRows}`);
    process.exit(1);
  }

  // Print sample rows
  console.log('\n--- Sample Rows (first 3) ---');
  for (let i = 1; i <= Math.min(3, lines.length - 1); i++) {
    const fields = parseCSVRow(lines[i]);
    console.log(`\nRow ${i}:`);
    EXPECTED_COLUMNS.forEach((col, idx) => {
      const value = fields[idx] ?? '';
      const displayValue = value.length > 50 ? value.substring(0, 50) + '...' : value;
      console.log(`  ${col}: ${displayValue}`);
    });
  }

  console.log('\n═══════════════════════════════════════════════════════════════════════════');
  console.log('✓ All tests passed!');
  console.log('═══════════════════════════════════════════════════════════════════════════\n');
}

/**
 * Parse a CSV row, handling quoted fields with commas
 */
function parseCSVRow(row: string): string[] {
  const fields: string[] = [];
  let current = '';
  let inQuotes = false;

  for (let i = 0; i < row.length; i++) {
    const char = row[i];
    const nextChar = row[i + 1];

    if (inQuotes) {
      if (char === '"' && nextChar === '"') {
        // Escaped quote
        current += '"';
        i++; // Skip next quote
      } else if (char === '"') {
        // End of quoted field
        inQuotes = false;
      } else {
        current += char;
      }
    } else {
      if (char === '"') {
        // Start of quoted field
        inQuotes = true;
      } else if (char === ',') {
        // End of field
        fields.push(current);
        current = '';
      } else {
        current += char;
      }
    }
  }

  // Don't forget the last field
  fields.push(current);

  return fields;
}

// ══════════════════════════════════════════════════════════════════════════════
// Run Tests
// ══════════════════════════════════════════════════════════════════════════════

testCSVLogger().catch((err) => {
  console.error('Test failed:', err);
  process.exit(1);
});
