// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin - Telemetry Context
// ══════════════════════════════════════════════════════════════════════════════
//
// React Context & Hook for real-time telemetry streaming.
// Features:
// - Auto-reconnecting WebSocket connection
// - requestAnimationFrame throttling for 60 FPS UI
// - Replay mode for historical data playback
// - Active alarm management
//
// ══════════════════════════════════════════════════════════════════════════════

import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
  useMemo,
} from 'react';

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

export type ConnectionStatus = 'CONNECTED' | 'DISCONNECTED' | 'RECONNECTING';

export interface TelemetryFrame {
  timestamp: string;
  frame_id: number;
  altitude_ft: number;
  throttle: number;
  rpm: number;
  map_kpa: number;
  fuel_flow_lph: number;
  cht: [number, number, number, number];
  egt: [number, number, number, number];
  oil_pressure_kpa: number;
  oil_temp_c: number;
  vibration_rms: number;
  ambient_temp_c: number;
  injected_fault: string | null;
  
  // Health data (enriched by AI service)
  health?: {
    ehi: number;
    combustion_efficiency: number;
    thermal_balance_spread: number;
    status: 'NORMAL' | 'WARNING' | 'CRITICAL';
  };
  
  // Anomaly data
  anomaly?: {
    score: number;
    is_detected: boolean;
    top_contributing_sensors: string[];
  };
  
  // Prognostics
  prognostics?: {
    predicted_rul_min: number;
    rtb_alert_level: 'NONE' | 'RTB_ADVISORY' | 'RTB_CRITICAL';
    rtb_window_active: boolean;
  };
  
  // Sensor status
  sensor_status?: {
    isolated_sensors: string[];
    active_sensors: Record<string, boolean>;
  };
}

export interface Alarm {
  id: string;
  type: 'ANOMALY' | 'RTB' | 'SENSOR' | 'OVERHEAT';
  severity: 'INFO' | 'WARNING' | 'CRITICAL';
  message: string;
  timestamp: Date;
  acknowledged: boolean;
}

export interface TelemetryContextValue {
  // Connection
  connectionStatus: ConnectionStatus;
  reconnectAttempts: number;
  
  // Data
  currentFrame: TelemetryFrame | null;
  frameHistory: TelemetryFrame[];
  
  // Replay mode
  isReplayMode: boolean;
  replayData: TelemetryFrame[];
  replayIndex: number;
  replaySpeed: number;
  
  // Alarms
  activeAlarms: Alarm[];
  
  // Actions
  sendCommand: (command: object) => void;
  startReplay: (data: TelemetryFrame[]) => void;
  stopReplay: () => void;
  setReplaySpeed: (speed: number) => void;
  seekReplay: (index: number) => void;
  acknowledgeAlarm: (alarmId: string) => void;
  clearAlarms: () => void;
}

// ══════════════════════════════════════════════════════════════════════════════
// Configuration
// ══════════════════════════════════════════════════════════════════════════════

const WS_URL = 'ws://localhost:8080';
const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 30000;
const MAX_RECONNECT_ATTEMPTS = 50;
const MAX_FRAME_HISTORY = 600; // 60 seconds at 10 Hz
const ALARM_HISTORY_LIMIT = 50;

// ══════════════════════════════════════════════════════════════════════════════
// Context Creation
// ══════════════════════════════════════════════════════════════════════════════

const TelemetryContext = createContext<TelemetryContextValue | null>(null);

// ══════════════════════════════════════════════════════════════════════════════
// Provider Component
// ══════════════════════════════════════════════════════════════════════════════

interface TelemetryProviderProps {
  children: React.ReactNode;
  wsUrl?: string;
}

export function TelemetryProvider({
  children,
  wsUrl = WS_URL,
}: TelemetryProviderProps) {
  // ─── Connection State ──────────────────────────────────────────────────
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('DISCONNECTED');
  const [reconnectAttempts, setReconnectAttempts] = useState(0);

  // ─── Data State ────────────────────────────────────────────────────────
  const [currentFrame, setCurrentFrame] = useState<TelemetryFrame | null>(null);
  const [frameHistory, setFrameHistory] = useState<TelemetryFrame[]>([]);

  // ─── Replay State ──────────────────────────────────────────────────────
  const [isReplayMode, setIsReplayMode] = useState(false);
  const [replayData, setReplayData] = useState<TelemetryFrame[]>([]);
  const [replayIndex, setReplayIndex] = useState(0);
  const [replaySpeed, setReplaySpeed] = useState(1);

  // ─── Alarm State ───────────────────────────────────────────────────────
  const [activeAlarms, setActiveAlarms] = useState<Alarm[]>([]);

  // ─── Refs ──────────────────────────────────────────────────────────────
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingFrameRef = useRef<TelemetryFrame | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const previousFrameRef = useRef<TelemetryFrame | null>(null);

  // ─── WebSocket Connection ──────────────────────────────────────────────

  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    console.log(`[Telemetry] Connecting to ${wsUrl}...`);
    setConnectionStatus('RECONNECTING');

    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('[Telemetry] Connected');
      wsRef.current = ws;
      setConnectionStatus('CONNECTED');
      setReconnectAttempts(0);
    };

    ws.onmessage = (event) => {
      try {
        const frame: TelemetryFrame = JSON.parse(event.data);
        
        // Skip non-telemetry messages
        if (!frame.frame_id && frame.frame_id !== 0) {
          console.log('[Telemetry] Received non-telemetry message:', frame);
          return;
        }

        // Store frame for RAF throttled update
        pendingFrameRef.current = frame;
      } catch (err) {
        console.error('[Telemetry] Failed to parse message:', err);
      }
    };

    ws.onclose = (event) => {
      console.log(`[Telemetry] Connection closed (code: ${event.code})`);
      wsRef.current = null;
      setConnectionStatus('DISCONNECTED');
      
      // Schedule reconnection
      scheduleReconnect();
    };

    ws.onerror = (error) => {
      console.error('[Telemetry] WebSocket error:', error);
    };
  }, [wsUrl]);

  const scheduleReconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }

    setReconnectAttempts((prev) => {
      const newAttempts = prev + 1;
      
      if (newAttempts > MAX_RECONNECT_ATTEMPTS) {
        console.error('[Telemetry] Max reconnect attempts reached');
        return prev;
      }

      // Exponential backoff with jitter
      const baseDelay = RECONNECT_BASE_DELAY;
      const maxDelay = RECONNECT_MAX_DELAY;
      const exponentialDelay = Math.min(
        baseDelay * Math.pow(2, newAttempts - 1),
        maxDelay
      );
      const jitter = Math.random() * 0.1 * exponentialDelay;
      const delay = Math.round(exponentialDelay + jitter);

      console.log(`[Telemetry] Reconnecting in ${delay}ms (attempt ${newAttempts})...`);
      
      reconnectTimeoutRef.current = setTimeout(() => {
        connectWebSocket();
      }, delay);

      return newAttempts;
    });
  }, [connectWebSocket]);

  // ─── RAF Throttled Frame Update ────────────────────────────────────────

  useEffect(() => {
    let running = true;

    const updateFrame = () => {
      if (!running) return;

      const pendingFrame = pendingFrameRef.current;
      
      if (pendingFrame && pendingFrame !== previousFrameRef.current) {
        previousFrameRef.current = pendingFrame;

        // Update current frame
        setCurrentFrame(pendingFrame);

        // Update history (maintain max length)
        setFrameHistory((prev) => {
          const newHistory = [...prev, pendingFrame];
          if (newHistory.length > MAX_FRAME_HISTORY) {
            return newHistory.slice(-MAX_FRAME_HISTORY);
          }
          return newHistory;
        });

        // Check for alarms
        checkForAlarms(pendingFrame);

        // Clear pending frame
        pendingFrameRef.current = null;
      }

      // Schedule next frame
      rafIdRef.current = requestAnimationFrame(updateFrame);
    };

    // Start RAF loop
    rafIdRef.current = requestAnimationFrame(updateFrame);

    return () => {
      running = false;
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
      }
    };
  }, []);

  // ─── Alarm Detection ───────────────────────────────────────────────────

  const checkForAlarms = useCallback((frame: TelemetryFrame) => {
    const newAlarms: Alarm[] = [];

    // Anomaly detection
    if (frame.anomaly?.is_detected) {
      newAlarms.push({
        id: `anomaly-${frame.frame_id}`,
        type: 'ANOMALY',
        severity: frame.anomaly.score > 70 ? 'CRITICAL' : 'WARNING',
        message: `Anomaly detected (score: ${frame.anomaly.score.toFixed(1)})`,
        timestamp: new Date(frame.timestamp),
        acknowledged: false,
      });
    }

    // RTB alerts
    if (frame.prognostics?.rtb_alert_level === 'RTB_CRITICAL') {
      newAlarms.push({
        id: `rtb-critical-${frame.frame_id}`,
        type: 'RTB',
        severity: 'CRITICAL',
        message: `RTB CRITICAL - RUL: ${frame.prognostics.predicted_rul_min.toFixed(1)} min`,
        timestamp: new Date(frame.timestamp),
        acknowledged: false,
      });
    } else if (frame.prognostics?.rtb_alert_level === 'RTB_ADVISORY') {
      newAlarms.push({
        id: `rtb-advisory-${frame.frame_id}`,
        type: 'RTB',
        severity: 'WARNING',
        message: `RTB Advisory - RUL: ${frame.prognostics.predicted_rul_min.toFixed(1)} min`,
        timestamp: new Date(frame.timestamp),
        acknowledged: false,
      });
    }

    // Sensor isolation
    if (frame.sensor_status?.isolated_sensors?.length) {
      newAlarms.push({
        id: `sensor-${frame.frame_id}`,
        type: 'SENSOR',
        severity: 'WARNING',
        message: `Sensors isolated: ${frame.sensor_status.isolated_sensors.join(', ')}`,
        timestamp: new Date(frame.timestamp),
        acknowledged: false,
      });
    }

    // Critical overheat (CHT > 240°C)
    const maxCht = Math.max(...(frame.cht || []));
    if (maxCht > 240) {
      newAlarms.push({
        id: `overheat-${frame.frame_id}`,
        type: 'OVERHEAT',
        severity: 'CRITICAL',
        message: `Critical overheat - Max CHT: ${maxCht.toFixed(1)}°C`,
        timestamp: new Date(frame.timestamp),
        acknowledged: false,
      });
    }

    if (newAlarms.length > 0) {
      setActiveAlarms((prev) => {
        const combined = [...prev, ...newAlarms];
        // Keep only recent alarms
        return combined.slice(-ALARM_HISTORY_LIMIT);
      });
    }
  }, []);

  // ─── Actions ───────────────────────────────────────────────────────────

  const sendCommand = useCallback((command: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(command));
      console.log('[Telemetry] Sent command:', command);
    } else {
      console.warn('[Telemetry] Cannot send command - not connected');
    }
  }, []);

  const startReplay = useCallback((data: TelemetryFrame[]) => {
    setReplayData(data);
    setReplayIndex(0);
    setIsReplayMode(true);
    console.log(`[Telemetry] Started replay with ${data.length} frames`);
  }, []);

  const stopReplay = useCallback(() => {
    setIsReplayMode(false);
    setReplayData([]);
    setReplayIndex(0);
    console.log('[Telemetry] Stopped replay');
  }, []);

  const seekReplay = useCallback((index: number) => {
    setReplayIndex(Math.max(0, Math.min(index, replayData.length - 1)));
  }, [replayData.length]);

  const acknowledgeAlarm = useCallback((alarmId: string) => {
    setActiveAlarms((prev) =>
      prev.map((alarm) =>
        alarm.id === alarmId ? { ...alarm, acknowledged: true } : alarm
      )
    );
  }, []);

  const clearAlarms = useCallback(() => {
    setActiveAlarms([]);
  }, []);

  // ─── Replay Loop ───────────────────────────────────────────────────────

  useEffect(() => {
    if (!isReplayMode || replayData.length === 0) return;

    const interval = setInterval(() => {
      setReplayIndex((prev) => {
        if (prev >= replayData.length - 1) {
          // Loop back to start
          return 0;
        }
        return prev + 1;
      });
    }, 100 / replaySpeed); // Base interval: 100ms (10 Hz)

    return () => clearInterval(interval);
  }, [isReplayMode, replayData.length, replaySpeed]);

  // Update current frame in replay mode
  useEffect(() => {
    if (isReplayMode && replayData[replayIndex]) {
      setCurrentFrame(replayData[replayIndex]);
    }
  }, [isReplayMode, replayData, replayIndex]);

  // ─── Connect on Mount ──────────────────────────────────────────────────

  useEffect(() => {
    connectWebSocket();

    return () => {
      // Cleanup
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
      }
    };
  }, [connectWebSocket]);

  // ─── Context Value ─────────────────────────────────────────────────────

  const value: TelemetryContextValue = useMemo(
    () => ({
      // Connection
      connectionStatus,
      reconnectAttempts,

      // Data
      currentFrame,
      frameHistory,

      // Replay
      isReplayMode,
      replayData,
      replayIndex,
      replaySpeed,

      // Alarms
      activeAlarms,

      // Actions
      sendCommand,
      startReplay,
      stopReplay,
      setReplaySpeed,
      seekReplay,
      acknowledgeAlarm,
      clearAlarms,
    }),
    [
      connectionStatus,
      reconnectAttempts,
      currentFrame,
      frameHistory,
      isReplayMode,
      replayData,
      replayIndex,
      replaySpeed,
      activeAlarms,
      sendCommand,
      startReplay,
      stopReplay,
      seekReplay,
      acknowledgeAlarm,
      clearAlarms,
    ]
  );

  return (
    <TelemetryContext.Provider value={value}>
      {children}
    </TelemetryContext.Provider>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Hook
// ══════════════════════════════════════════════════════════════════════════════

export function useTelemetry(): TelemetryContextValue {
  const context = useContext(TelemetryContext);
  
  if (!context) {
    throw new Error('useTelemetry must be used within a TelemetryProvider');
  }
  
  return context;
}

export default TelemetryContext;
