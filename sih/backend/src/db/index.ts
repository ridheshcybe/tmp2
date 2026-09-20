// ══════════════════════════════════════════════════════════════════════════════
// Database Module Exports
// ══════════════════════════════════════════════════════════════════════════════

export { DatabaseClient, getDatabaseClient, initializeDatabase, shutdownDatabase } from './db_client.js';
export type { DatabaseConfig, QueryResult } from './db_client.js';

export { TelemetryRepository, getTelemetryRepository } from './telemetry_repo.js';
export type { TelemetryRecord, MissionHistoryQuery, BatchInsertResult } from './telemetry_repo.js';
