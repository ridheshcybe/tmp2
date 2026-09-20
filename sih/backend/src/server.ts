// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin - Master Streaming Gateway
// ══════════════════════════════════════════════════════════════════════════════

import WebSocket, { WebSocketServer } from 'ws';
import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { config, validateConfig } from './config.js';
import { initializeDatabase, shutdownDatabase, getTelemetryRepository } from './db/index.js';
import { initializeCSVLogger, shutdownCSVLogger, getCSVLogger } from './services/index.js';
import type { TelemetryFrame } from './services/csv_logger.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

interface ClientInfo {
  id: string;
  ws: WebSocket;
  connectedAt: Date;
  lastPing: Date;
  ip: string;
}

interface ServerStats {
  uptime: number;
  framesReceived: number;
  framesBroadcast: number;
  connectedClients: number;
  pythonConnected: boolean;
  lastFrameTime: Date | null;
  dbConnected: boolean;
}

interface IncomingCommand {
  action: string;
  [key: string]: any;
}

// ══════════════════════════════════════════════════════════════════════════════
// Gateway Server
// ══════════════════════════════════════════════════════════════════════════════

class StreamingGateway {
  // Python AI Stream connection
  private pythonWs: WebSocket | null = null;
  private pythonReconnectAttempts: number = 0;
  private pythonMaxReconnectAttempts: number = 50;
  private pythonReconnectBaseDelay: number = 1000;
  private pythonReconnectMaxDelay: number = 30000;
  private pythonConnected: boolean = false;

  // Client WebSocket server
  private clientWss: WebSocketServer | null = null;
  private clients: Map<string, ClientInfo> = new Map();
  private clientIdCounter: number = 0;

  // HTTP server for REST endpoints
  private httpServer: http.Server | null = null;

  // Statistics
  private startTime: Date = new Date();
  private framesReceived: number = 0;
  private framesBroadcast: number = 0;
  private lastFrameTime: Date | null = null;

  // Services
  private telemetryRepo = getTelemetryRepository();
  private csvLogger = getCSVLogger();

  // ─── Initialization ──────────────────────────────────────────────────────

  async initialize(): Promise<void> {
    console.log('═══════════════════════════════════════════════════════════════════════════');
    console.log('  Aero Piston Engine Digital Twin - Streaming Gateway');
    console.log('═══════════════════════════════════════════════════════════════════════════\n');

    // Validate configuration
    validateConfig();

    // Initialize database (optional - gracefully handle connection failure)
    try {
      await initializeDatabase();
      console.log('✓ Database connected');
    } catch (err) {
      console.warn('⚠ Database connection failed (continuing without DB):', (err as Error).message);
    }

    // Initialize CSV logger
    await this.csvLogger.initialize();
    console.log('✓ CSV logger initialized');

    // Start batch insert for telemetry
    this.telemetryRepo.startBatchInsert();
    console.log('✓ Telemetry batch insert started');

    // Start client WebSocket server
    this.startClientServer();

    // Start HTTP server for REST endpoints
    this.startHttpServer();

    // Connect to Python AI service
    this.connectToPythonAI();

    console.log('\n✓ Gateway initialized successfully\n');
  }

  // ─── Python AI Stream Connection ─────────────────────────────────────────

  private connectToPythonAI(): void {
    const pythonUrl = `ws://localhost:${config.aiStreamPort}`;
    console.log(`[Python] Connecting to ${pythonUrl}...`);

    try {
      this.pythonWs = new WebSocket(pythonUrl);

      this.pythonWs.on('open', () => {
        console.log(`[Python] ✓ Connected to AI service on port ${config.aiStreamPort}`);
        this.pythonConnected = true;
        this.pythonReconnectAttempts = 0;
      });

      this.pythonWs.on('message', (data: WebSocket.Data) => {
        this.handlePythonMessage(data);
      });

      this.pythonWs.on('close', (code: number, reason: Buffer) => {
        console.log(`[Python] Connection closed (code: ${code}, reason: ${reason.toString()})`);
        this.pythonConnected = false;
        this.schedulePythonReconnect();
      });

      this.pythonWs.on('error', (err: Error) => {
        console.error(`[Python] Error: ${err.message}`);
        this.pythonConnected = false;
      });

      this.pythonWs.on('pong', () => {
        // Heartbeat response received
      });
    } catch (err) {
      console.error(`[Python] Connection failed: ${(err as Error).message}`);
      this.pythonConnected = false;
      this.schedulePythonReconnect();
    }
  }

  private schedulePythonReconnect(): void {
    if (this.pythonReconnectAttempts >= this.pythonMaxReconnectAttempts) {
      console.error(`[Python] Max reconnect attempts reached (${this.pythonMaxReconnectAttempts}). Giving up.`);
      return;
    }

    this.pythonReconnectAttempts++;

    // Exponential backoff with jitter
    const baseDelay = this.pythonReconnectBaseDelay;
    const maxDelay = this.pythonReconnectMaxDelay;
    const exponentialDelay = Math.min(baseDelay * Math.pow(2, this.pythonReconnectAttempts - 1), maxDelay);
    const jitter = Math.random() * 0.1 * exponentialDelay;
    const delay = Math.round(exponentialDelay + jitter);

    console.log(`[Python] Reconnecting in ${delay}ms (attempt ${this.pythonReconnectAttempts}/${this.pythonMaxReconnectAttempts})...`);

    setTimeout(() => {
      this.connectToPythonAI();
    }, delay);
  }

  private handlePythonMessage(data: WebSocket.Data): void {
    try {
      const message = data.toString();
      const frame: TelemetryFrame = JSON.parse(message);

      this.framesReceived++;
      this.lastFrameTime = new Date();

      // Process frame for incident logging
      this.csvLogger.processFrame(frame).catch((err) => {
        console.error('[CSVLogger] Error processing frame:', err);
      });

      // Store in database (async, non-blocking)
      this.storeTelemetryFrame(frame).catch((err) => {
        console.error('[DB] Error storing frame:', err);
      });

      // Broadcast to all connected clients
      this.broadcastToClients(message);

    } catch (err) {
      console.error('[Python] Failed to parse message:', (err as Error).message);
    }
  }

  private async storeTelemetryFrame(frame: TelemetryFrame): Promise<void> {
    try {
      await this.telemetryRepo.bufferRecord({
        time: new Date(),
        frameId: frame.frame_id ?? 0,
        rpm: frame.rpm ?? null,
        mapKpa: frame.map_kpa ?? null,
        fuelFlowLph: frame.fuel_flow_lph ?? null,
        cht: frame.cht ?? null,
        egt: frame.egt ?? null,
        oilPressureKpa: frame.oil_pressure_kpa ?? null,
        oilTempC: frame.oil_temp_c ?? null,
        vibrationRms: frame.vibration_rms ?? null,
        ehi: frame.health?.ehi ?? null,
        combustionEfficiency: frame.health?.combustion_efficiency ?? null,
        thermalBalanceSpread: null,
        anomalyScore: frame.anomaly?.score ?? null,
        isAnomaly: frame.anomaly?.is_detected ?? false,
        predictedRulMin: frame.prognostics?.predicted_rul_min ?? null,
        rtbAlertLevel: frame.prognostics?.rtb_alert_level ?? null,
        activeSensors: frame.sensor_status?.active_sensors ?? null,
        sensorIsolationFlags: frame.sensor_status?.isolated_sensors ?? null,
        altitudeFt: frame.altitude_ft ?? null,
        ambientTempC: frame.ambient_temp_c ?? null,
      });
    } catch (err) {
      // Silently fail - database is optional
    }
  }

  // ─── Client WebSocket Server ─────────────────────────────────────────────

  private startClientServer(): void {
    this.clientWss = new WebSocketServer({
      port: config.clientWsPort,
      perMessageDeflate: false,
    });

    this.clientWss.on('listening', () => {
      console.log(`[Clients] ✓ WebSocket server listening on port ${config.clientWsPort}`);
    });

    this.clientWss.on('connection', (ws: WebSocket, req: http.IncomingMessage) => {
      this.handleClientConnection(ws, req);
    });

    this.clientWss.on('error', (err: Error) => {
      console.error(`[Clients] Server error: ${err.message}`);
    });
  }

  private handleClientConnection(ws: WebSocket, req: http.IncomingMessage): void {
    const clientId = `client_${++this.clientIdCounter}`;
    const ip = req.socket.remoteAddress ?? 'unknown';

    const clientInfo: ClientInfo = {
      id: clientId,
      ws,
      connectedAt: new Date(),
      lastPing: new Date(),
      ip,
    };

    this.clients.set(clientId, clientInfo);
    console.log(`[Clients] ✓ Client connected: ${clientId} (IP: ${ip})`);
    console.log(`[Clients]   Total connected: ${this.clients.size}`);

    // Send welcome message
    this.sendToClient(ws, {
      type: 'WELCOME',
      clientId,
      serverTime: new Date().toISOString(),
    });

    // Handle incoming messages from client
    ws.on('message', (data: WebSocket.Data) => {
      this.handleClientMessage(clientId, data);
    });

    // Handle client disconnect
    ws.on('close', (code: number, reason: Buffer) => {
      console.log(`[Clients] Client disconnected: ${clientId} (code: ${code})`);
      this.clients.delete(clientId);
      console.log(`[Clients]   Total connected: ${this.clients.size}`);
    });

    // Handle errors
    ws.on('error', (err: Error) => {
      console.error(`[Clients] Client error (${clientId}): ${err.message}`);
      this.clients.delete(clientId);
    });

    // Heartbeat pong
    ws.on('pong', () => {
      clientInfo.lastPing = new Date();
    });
  }

  private handleClientMessage(clientId: string, data: WebSocket.Data): void {
    try {
      const message = data.toString();
      const command: IncomingCommand = JSON.parse(message);

      console.log(`[Clients] Received command from ${clientId}:`, command.action);

      switch (command.action) {
        case 'TRIGGER_FAULT':
          this.forwardCommandToPython({
            command: 'INJECT_FAULT',
            type: command.fault,
            severity: command.severity ?? 0.5,
          });
          break;

        case 'CLEAR_FAULTS':
          this.forwardCommandToPython({
            command: 'CLEAR_FAULTS',
          });
          break;

        case 'SET_THROTTLE':
          this.forwardCommandToPython({
            command: 'SET_THROTTLE',
            throttle: command.throttle,
          });
          break;

        case 'SET_ALTITUDE':
          this.forwardCommandToPython({
            command: 'SET_ALTITUDE',
            altitude_ft: command.altitude_ft,
          });
          break;

        case 'PING':
          this.sendToClient(this.clients.get(clientId)!.ws, {
            type: 'PONG',
            serverTime: new Date().toISOString(),
          });
          break;

        case 'GET_STATS':
          this.sendToClient(this.clients.get(clientId)!.ws, {
            type: 'STATS',
            ...this.getStats(),
          });
          break;

        default:
          console.warn(`[Clients] Unknown command: ${command.action}`);
          this.sendToClient(this.clients.get(clientId)!.ws, {
            type: 'ERROR',
            message: `Unknown command: ${command.action}`,
          });
      }
    } catch (err) {
      console.error(`[Clients] Failed to parse command from ${clientId}:`, (err as Error).message);
    }
  }

  private forwardCommandToPython(command: object): void {
    if (this.pythonWs && this.pythonWs.readyState === WebSocket.OPEN) {
      this.pythonWs.send(JSON.stringify(command));
      console.log('[Python] Forwarded command:', command);
    } else {
      console.warn('[Python] Cannot forward command - not connected');
    }
  }

  private broadcastToClients(message: string): void {
    const broadcastStart = Date.now();
    let sentCount = 0;

    this.clients.forEach((client) => {
      if (client.ws.readyState === WebSocket.OPEN) {
        client.ws.send(message, (err) => {
          if (err) {
            console.error(`[Clients] Broadcast error to ${client.id}:`, err.message);
          }
        });
        sentCount++;
      }
    });

    this.framesBroadcast += sentCount;

    const broadcastTime = Date.now() - broadcastStart;
    if (broadcastTime > 5) {
      console.warn(`[Clients] Broadcast took ${broadcastTime}ms (target: <5ms)`);
    }
  }

  private sendToClient(ws: WebSocket, data: object): void {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data));
    }
  }

  // ─── HTTP REST Server ───────────────────────────────────────────────────

  private startHttpServer(): void {
    this.httpServer = http.createServer((req, res) => {
      this.handleHttpRequest(req, res);
    });

    this.httpServer.listen(config.clientWsPort + 1, () => {
      console.log(`[HTTP] ✓ REST API server listening on port ${config.clientWsPort + 1}`);
    });

    this.httpServer.on('error', (err: Error) => {
      console.error(`[HTTP] Server error: ${err.message}`);
    });
  }

  private async handleHttpRequest(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', `http://localhost:${config.clientWsPort + 1}`);
    const pathname = url.pathname;

    // CORS headers
    res.setHeader('Access-Control-Allow-Origin', config.frontendUrl);
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
      res.writeHead(204);
      res.end();
      return;
    }

    try {
      switch (pathname) {
        case '/health':
          await this.handleHealthEndpoint(req, res);
          break;

        case '/api/mission/replay':
          await this.handleMissionReplayEndpoint(req, res, url);
          break;

        case '/api/logs/download':
          await this.handleLogDownloadEndpoint(req, res);
          break;

        default:
          this.sendJsonResponse(res, 404, { error: 'Not found' });
      }
    } catch (err) {
      console.error(`[HTTP] Error handling ${pathname}:`, err);
      this.sendJsonResponse(res, 500, { error: 'Internal server error' });
    }
  }

  private async handleHealthEndpoint(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const stats = this.getStats();

    this.sendJsonResponse(res, 200, {
      status: 'ok',
      timestamp: new Date().toISOString(),
      uptime: stats.uptime,
      components: {
        python_ai: {
          connected: stats.pythonConnected,
          port: config.aiStreamPort,
        },
        websocket_clients: {
          connected: stats.connectedClients,
          port: config.clientWsPort,
        },
        database: {
          connected: stats.dbConnected,
        },
        telemetry: {
          frames_received: stats.framesReceived,
          frames_broadcast: stats.framesBroadcast,
          last_frame_time: stats.lastFrameTime?.toISOString() ?? null,
        },
        csv_logger: this.csvLogger.getStats(),
      },
    });
  }

  private async handleMissionReplayEndpoint(
    req: http.IncomingMessage,
    res: http.ServerResponse,
    url: URL
  ): Promise<void> {
    const startTimeStr = url.searchParams.get('start');
    const endTimeStr = url.searchParams.get('end');
    const missionId = url.searchParams.get('mission_id') ?? undefined;
    const limit = parseInt(url.searchParams.get('limit') ?? '10000', 10);

    if (!startTimeStr || !endTimeStr) {
      this.sendJsonResponse(res, 400, {
        error: 'Missing required parameters: start, end',
        example: '/api/mission/replay?start=2024-01-01T10:00:00Z&end=2024-01-01T12:00:00Z',
      });
      return;
    }

    const startTime = new Date(startTimeStr);
    const endTime = new Date(endTimeStr);

    if (isNaN(startTime.getTime()) || isNaN(endTime.getTime())) {
      this.sendJsonResponse(res, 400, {
        error: 'Invalid date format. Use ISO 8601 format.',
      });
      return;
    }

    const records = await this.telemetryRepo.getMissionHistory({
      startTime,
      endTime,
      missionId,
      limit,
    });

    this.sendJsonResponse(res, 200, {
      count: records.length,
      start_time: startTime.toISOString(),
      end_time: endTime.toISOString(),
      mission_id: missionId ?? null,
      data: records,
    });
  }

  private async handleLogDownloadEndpoint(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const logStats = this.csvLogger.getStats();

    if (!logStats.currentLogFile || !fs.existsSync(logStats.currentLogFile)) {
      this.sendJsonResponse(res, 404, {
        error: 'No log file available',
      });
      return;
    }

    const fileName = path.basename(logStats.currentLogFile);
    
    res.setHeader('Content-Type', 'text/csv');
    res.setHeader('Content-Disposition', `attachment; filename="${fileName}"`);
    res.writeHead(200);

    const fileStream = fs.createReadStream(logStats.currentLogFile);
    fileStream.pipe(res);
  }

  private sendJsonResponse(res: http.ServerResponse, statusCode: number, data: object): void {
    res.setHeader('Content-Type', 'application/json');
    res.writeHead(statusCode);
    res.end(JSON.stringify(data, null, 2));
  }

  // ─── Statistics ─────────────────────────────────────────────────────────

  private getStats(): ServerStats {
    return {
      uptime: Math.floor((Date.now() - this.startTime.getTime()) / 1000),
      framesReceived: this.framesReceived,
      framesBroadcast: this.framesBroadcast,
      connectedClients: this.clients.size,
      pythonConnected: this.pythonConnected,
      lastFrameTime: this.lastFrameTime,
      dbConnected: false, // Would need to check actual DB status
    };
  }

  // ─── Shutdown ───────────────────────────────────────────────────────────

  async shutdown(): Promise<void> {
    console.log('\n[Gateway] Shutting down...');

    // Stop telemetry batch insert
    await this.telemetryRepo.stopBatchInsert();
    console.log('[Gateway] ✓ Telemetry batch insert stopped');

    // Shutdown CSV logger
    await this.csvLogger.shutdown();
    console.log('[Gateway] ✓ CSV logger shutdown');

    // Disconnect from Python
    if (this.pythonWs) {
      this.pythonWs.close();
      this.pythonWs = null;
    }
    console.log('[Gateway] ✓ Python connection closed');

    // Close client connections
    this.clients.forEach((client) => {
      client.ws.close();
    });
    this.clients.clear();
    console.log('[Gateway] ✓ Client connections closed');

    // Close client WebSocket server
    if (this.clientWss) {
      await new Promise<void>((resolve) => {
        this.clientWss!.close(() => resolve());
      });
    }
    console.log('[Gateway] ✓ Client WebSocket server closed');

    // Close HTTP server
    if (this.httpServer) {
      await new Promise<void>((resolve) => {
        this.httpServer!.close(() => resolve());
      });
    }
    console.log('[Gateway] ✓ HTTP server closed');

    // Shutdown database
    await shutdownDatabase();
    console.log('[Gateway] ✓ Database shutdown');

    console.log('[Gateway] ✓ Shutdown complete\n');
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Entry Point
// ══════════════════════════════════════════════════════════════════════════════

const gateway = new StreamingGateway();

// Handle graceful shutdown
async function gracefulShutdown(signal: string): Promise<void> {
  console.log(`\n[Main] Received ${signal}. Starting graceful shutdown...`);
  await gateway.shutdown();
  process.exit(0);
}

process.on('SIGINT', () => gracefulShutdown('SIGINT'));
process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));

// Handle uncaught errors
process.on('uncaughtException', (err) => {
  console.error('[Main] Uncaught exception:', err);
  gracefulShutdown('uncaughtException');
});

process.on('unhandledRejection', (reason) => {
  console.error('[Main] Unhandled rejection:', reason);
});

// Start the gateway
gateway.initialize().catch((err) => {
  console.error('[Main] Failed to initialize gateway:', err);
  process.exit(1);
});

export default StreamingGateway;
