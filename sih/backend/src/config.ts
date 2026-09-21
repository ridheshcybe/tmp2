import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Load .env file from project root or backend directory
dotenv.config({ path: path.resolve(__dirname, '../../.env') });
dotenv.config({ path: path.resolve(__dirname, '../.env') });

export interface AppConfig {
  // WebSocket ports
  aiStreamPort: number;      // Incoming from Python AI engine
  clientWsPort: number;       // Outgoing to React dashboard
  
  // Database
  databaseUrl: string;
  
  // Logging
  logDir: string;
  logLevel: string;
  
  // Simulation
  simulationHz: number;
  
  // Paths
  dataDir: string;
  frontendUrl: string;
}

function getEnvNumber(key: string, defaultValue: number): number {
  const value = process.env[key];
  if (value === undefined) {
    return defaultValue;
  }
  const parsed = parseInt(value, 10);
  if (isNaN(parsed)) {
    console.warn(`Invalid number for ${key}: ${value}, using default: ${defaultValue}`);
    return defaultValue;
  }
  return parsed;
}

function getEnvString(key: string, defaultValue: string): string {
  return process.env[key] || defaultValue;
}

function getEnvBoolean(key: string, defaultValue: boolean): boolean {
  const value = process.env[key];
  if (value === undefined) {
    return defaultValue;
  }
  return value.toLowerCase() === 'true' || value === '1';
}

export const config: AppConfig = {
  aiStreamPort: getEnvNumber('AI_STREAM_PORT', 8766),
  clientWsPort: getEnvNumber('CLIENT_WS_PORT', 8080),
  databaseUrl: getEnvString('DATABASE_URL', 'postgres://postgres:password@localhost:5432/aerotwin'),
  logDir: getEnvString('LOG_DIR', './logs'),
  logLevel: getEnvString('LOG_LEVEL', 'info'),
  simulationHz: getEnvNumber('SIMULATION_HZ', 10),
  dataDir: getEnvString('DATA_DIR', path.resolve(__dirname, '../../data')),
  frontendUrl: getEnvString('FRONTEND_URL', 'http://localhost:3000'),
};

export function validateConfig(): void {
  const required = ['databaseUrl'];
  const missing = required.filter(
    (key) => !config[key as keyof AppConfig]
  );

  if (missing.length > 0) {
    throw new Error(`Missing required configuration: ${missing.join(', ')}`);
  }

  // Validate port ranges
  if (config.aiStreamPort < 1 || config.aiStreamPort > 65535) {
    throw new Error(`Invalid AI_STREAM_PORT: ${config.aiStreamPort}`);
  }
  if (config.clientWsPort < 1 || config.clientWsPort > 65535) {
    throw new Error(`Invalid CLIENT_WS_PORT: ${config.clientWsPort}`);
  }

  console.log('✓ Configuration validated');
}

export default config;
