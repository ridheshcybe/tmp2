// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin - Master Cockpit Layout
// ══════════════════════════════════════════════════════════════════════════════
//
// Complete cockpit interface assembling all Phase 5 components:
// - Top navigation with live clock, frame counter, connection status
// - 3D Digital Twin, Dashboard, and Diagnostics views
// - Demo control panel for fault injection
// - Incident log viewer modal
//
// ══════════════════════════════════════════════════════════════════════════════

import React, { useState, useEffect, useCallback } from 'react';
import { TelemetryProvider, useTelemetry, type ConnectionStatus } from './context/TelemetryContext';
import { ToastProvider, useToast } from './components/ui/Toast';
import { useAudioAlarm } from './hooks/useAudioAlarm';

// Dashboard Components
import { 
  MasterHealthGauge, 
  ReturnToBaseHUD, 
  TelemetryStripCharts, 
  SensorHealthStatus 
} from './components/dashboard';

// 3D Components
import { Engine3DView } from './components/digital_twin';

// Diagnostics Components
import { MissionReplayToolbar } from './components/diagnostics';

// Icons
import {
  Activity,
  Wifi,
  WifiOff,
  Layers,
  Box,
  AlertTriangle,
  ChevronUp,
  ChevronDown,
  X,
  Flame,
  Settings2,
  Droplets,
  Snowflake,
  RotateCcw,
  Volume2,
  VolumeX,
} from 'lucide-react';

import clsx from 'clsx';

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

type ViewMode = 'overview' | '3d' | 'diagnostics';

interface IncidentLogEntry {
  timestamp: string;
  frame_id: number;
  event_type: string;
  severity: string;
  ehi: string;
  predicted_rul_min: string;
  trigger_details: string;
  isolated_sensors: string;
}

// ══════════════════════════════════════════════════════════════════════════════
// Demo Control Panel
// ══════════════════════════════════════════════════════════════════════════════

interface DemoControlPanelProps {
  isOpen: boolean;
  onToggle: () => void;
}

function DemoControlPanel({ isOpen, onToggle }: DemoControlPanelProps) {
  const { sendCommand } = useTelemetry();
  const { addToast } = useToast();

  const handleFaultInjection = (faultType: string, label: string) => {
    sendCommand({
      action: 'TRIGGER_FAULT',
      fault: faultType,
      severity: 0.7,
    });
    addToast(`🔥 Injected ${label}`, 'warning');
  };

  const handleSensorFreeze = () => {
    sendCommand({
      action: 'TRIGGER_FAULT',
      fault: 'SENSOR_FREEZE',
      sensor: 'CHT_2',
      severity: 1.0,
    });
    addToast('❄ CHT_2 Sensor Frozen', 'info');
  };

  const handleReset = () => {
    sendCommand({
      action: 'CLEAR_FAULTS',
    });
    addToast('🔄 Engine Reset to Nominal', 'success');
  };

  return (
    <div className={clsx(
      'fixed bottom-0 left-0 right-0 z-40 transition-transform duration-300',
      isOpen ? 'translate-y-0' : 'translate-y-[calc(100%-40px)]'
    )}>
      {/* Toggle Bar */}
      <button
        onClick={onToggle}
        className="w-full h-10 bg-cockpit-surface border-t border-cockpit-border flex items-center justify-center gap-2 hover:bg-cockpit-border transition-colors"
      >
        {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
        <span className="text-sm font-medium text-cockpit-muted">
          Demo Control Panel
        </span>
        {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
      </button>

      {/* Panel Content */}
      <div className="bg-cockpit-surface border-t border-cockpit-border p-4">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-hud-amber flex items-center gap-2">
              <Settings2 className="w-4 h-4" />
              Interactive Judge Demo Controls
            </h3>
            <p className="text-xs text-cockpit-muted">
              Click to inject faults and demonstrate system response
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            {/* Lean Burn Runaway */}
            <button
              onClick={() => handleFaultInjection('LEAN_BURN_RUNAWAY', 'Lean Burn Runaway')}
              className="flex items-center gap-2 px-4 py-3 rounded-lg bg-hud-amber/20 border border-hud-amber/50 hover:bg-hud-amber/30 transition-all group"
            >
              <Flame className="w-5 h-5 text-hud-amber group-hover:animate-pulse" />
              <div className="text-left">
                <p className="text-sm font-medium text-hud-amber">Inject Lean Burn Runaway</p>
                <p className="text-xs text-cockpit-muted">EGT spike {'>'} 850°C</p>
              </div>
            </button>

            {/* Piston Ring Degradation */}
            <button
              onClick={() => handleFaultInjection('PISTON_RING_WEAR', 'Piston Ring Degradation')}
              className="flex items-center gap-2 px-4 py-3 rounded-lg bg-hud-amber/20 border border-hud-amber/50 hover:bg-hud-amber/30 transition-all group"
            >
              <Settings2 className="w-5 h-5 text-hud-amber group-hover:animate-spin" />
              <div className="text-left">
                <p className="text-sm font-medium text-hud-amber">Inject Piston Ring Degradation</p>
                <p className="text-xs text-cockpit-muted">RPM drop + vibration increase</p>
              </div>
            </button>

            {/* Oil Pressure Loss */}
            <button
              onClick={() => handleFaultInjection('OIL_LEAK_PRESSURE_LOSS', 'Oil Pressure Loss')}
              className="flex items-center gap-2 px-4 py-3 rounded-lg bg-alert-red/20 border border-alert-red/50 hover:bg-alert-red/30 transition-all group"
            >
              <Droplets className="w-5 h-5 text-alert-red group-hover:animate-pulse" />
              <div className="text-left">
                <p className="text-sm font-medium text-alert-red">Inject Oil Pressure Loss</p>
                <p className="text-xs text-cockpit-muted">Oil P drop + CHT rise</p>
              </div>
            </button>

            {/* Sensor Freeze */}
            <button
              onClick={handleSensorFreeze}
              className="flex items-center gap-2 px-4 py-3 rounded-lg bg-cyber-cyan/20 border border-cyber-cyan/50 hover:bg-cyber-cyan/30 transition-all group"
            >
              <Snowflake className="w-5 h-5 text-cyber-cyan group-hover:animate-spin" />
              <div className="text-left">
                <p className="text-sm font-medium text-cyber-cyan">Freeze CHT_2 Sensor</p>
                <p className="text-xs text-cockpit-muted">Test isolation detection</p>
              </div>
            </button>

            {/* Reset */}
            <button
              onClick={handleReset}
              className="flex items-center gap-2 px-4 py-3 rounded-lg bg-nominal-green/20 border border-nominal-green/50 hover:bg-nominal-green/30 transition-all group"
            >
              <RotateCcw className="w-5 h-5 text-nominal-green group-hover:animate-spin" />
              <div className="text-left">
                <p className="text-sm font-medium text-nominal-green">Reset Engine to Nominal</p>
                <p className="text-xs text-cockpit-muted">Clear all faults</p>
              </div>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Incident Log Modal
// ══════════════════════════════════════════════════════════════════════════════

interface IncidentLogModalProps {
  isOpen: boolean;
  onClose: () => void;
}

function IncidentLogModal({ isOpen, onClose }: IncidentLogModalProps) {
  const [logs, setLogs] = useState<IncidentLogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const fetchLogs = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch('/api/logs/download');
      if (response.ok) {
        const text = await response.text();
        const lines = text.trim().split('\n');
        
        const entries = lines.slice(1).map((line) => {
          const values = line.split(',');
          return {
            timestamp: values[0] || '',
            frame_id: parseInt(values[1] || '0', 10),
            event_type: values[2] || '',
            severity: values[3] || '',
            ehi: values[4] || '',
            predicted_rul_min: values[5] || '',
            trigger_details: values[6] || '',
            isolated_sensors: values[7] || '',
          };
        });

        setLogs(entries.slice(-100).reverse()); // Last 100 entries, newest first)
      }
    } catch (err) {
      console.error('Failed to fetch logs:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      fetchLogs();
    }
  }, [isOpen, fetchLogs]);

  if (!isOpen) return null;

  const getSeverityColor = (severity: string) => {
    switch (severity.toUpperCase()) {
      case 'CRITICAL': return 'text-alert-red bg-alert-red/20';
      case 'WARNING': return 'text-hud-amber bg-hud-amber/20';
      default: return 'text-nominal-green bg-nominal-green/20';
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="glass-card w-[90vw] max-w-4xl max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-cockpit-border">
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 text-hud-amber" />
            <h2 className="text-lg font-bold text-white">Incident Log Viewer</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchLogs}
              className="p-2 rounded-lg bg-cockpit-surface hover:bg-cockpit-border transition-colors"
            >
              <RotateCcw className="w-4 h-4 text-cockpit-muted" />
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded-lg bg-cockpit-surface hover:bg-cockpit-border transition-colors"
            >
              <X className="w-4 h-4 text-cockpit-muted" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-4">
          {isLoading ? (
            <div className="flex items-center justify-center h-32">
              <div className="w-8 h-8 border-2 border-cyber-cyan border-t-transparent rounded-full animate-spin" />
            </div>
          ) : logs.length === 0 ? (
            <div className="text-center text-cockpit-muted py-8">
              No incident logs found
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-cockpit-muted border-b border-cockpit-border">
                    <th className="pb-2 font-medium">Timestamp</th>
                    <th className="pb-2 font-medium">Frame</th>
                    <th className="pb-2 font-medium">Event Type</th>
                    <th className="pb-2 font-medium">Severity</th>
                    <th className="pb-2 font-medium">EHI</th>
                    <th className="pb-2 font-medium">RUL</th>
                    <th className="pb-2 font-medium">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log, i) => (
                    <tr key={i} className="border-b border-cockpit-border/50 hover:bg-cockpit-surface/50">
                      <td className="py-2 font-mono text-xs text-cockpit-muted">
                        {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : '---'}
                      </td>
                      <td className="py-2 font-mono text-xs">{log.frame_id}</td>
                      <td className="py-2">
                        <span className="px-2 py-1 rounded text-xs bg-cockpit-surface">
                          {log.event_type}
                        </span>
                      </td>
                      <td className="py-2">
                        <span className={clsx('px-2 py-1 rounded text-xs font-medium', getSeverityColor(log.severity))}>
                          {log.severity}
                        </span>
                      </td>
                      <td className="py-2 font-mono text-xs">{log.ehi ? `${Number(log.ehi).toFixed(1)}%` : '---'}</td>
                      <td className="py-2 font-mono text-xs">{log.predicted_rul_min ? `${Number(log.predicted_rul_min).toFixed(0)}m` : '---'}</td>
                      <td className="py-2 text-xs text-cockpit-muted max-w-[200px] truncate">
                        {log.trigger_details}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-cockpit-border flex items-center justify-between">
          <span className="text-xs text-cockpit-muted">
            Showing {logs.length} entries
          </span>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-cockpit-surface hover:bg-cockpit-border transition-colors text-sm"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Top Navigation Bar
// ══════════════════════════════════════════════════════════════════════════════

interface TopNavBarProps {
  viewMode: ViewMode;
  onViewModeChange: (mode: ViewMode) => void;
  onOpenIncidents: () => void;
}

function TopNavBar({ viewMode, onViewModeChange, onOpenIncidents }: TopNavBarProps) {
  const { connectionStatus, frameHistory, isReplayMode } = useTelemetry();
  const { isMuted, toggleMute, initialize: initAudio } = useAudioAlarm();
  const [currentTime, setCurrentTime] = useState(new Date());

  // Update clock every second
  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const connectionStatusColor: Record<ConnectionStatus, string> = {
    CONNECTED: 'bg-nominal-green',
    RECONNECTING: 'bg-hud-amber animate-pulse',
    DISCONNECTED: 'bg-alert-red animate-pulse',
  };

  const views: { id: ViewMode; label: string; icon: React.ReactNode }[] = [
    { id: 'overview', label: 'Cockpit Overview', icon: <Layers className="w-4 h-4" /> },
    { id: '3d', label: '3D Digital Twin', icon: <Box className="w-4 h-4" /> },
    { id: 'diagnostics', label: 'Diagnostics & Logs', icon: <AlertTriangle className="w-4 h-4" /> },
  ];

  return (
    <header className="h-14 bg-cockpit-surface border-b border-cockpit-border flex items-center justify-between px-4 z-50">
      {/* Left: Title */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyber-cyan to-hud-amber flex items-center justify-center">
          <Activity className="w-5 h-5 text-cockpit-bg" />
        </div>
        <div className="hidden lg:block">
          <h1 className="text-sm font-bold text-white leading-tight">
            AeroTwin: MALE UAV Aero-Engine Digital Twin
          </h1>
          <p className="text-[10px] text-cockpit-muted">
            DRDO Tapas-BH-201 Simulation
          </p>
        </div>
      </div>

      {/* Center: View Tabs */}
      <nav className="flex items-center gap-1 bg-cockpit-bg rounded-lg p-1">
        {views.map((view) => (
          <button
            key={view.id}
            onClick={() => onViewModeChange(view.id)}
            className={clsx(
              'flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-all',
              viewMode === view.id
                ? 'bg-cockpit-surface text-white shadow-lg'
                : 'text-cockpit-muted hover:text-white'
            )}
          >
            {view.icon}
            <span className="hidden md:inline">{view.label}</span>
          </button>
        ))}
      </nav>

      {/* Right: Status Indicators */}
      <div className="flex items-center gap-4">
        {/* Audio Toggle */}
        <button
          onClick={() => {
            initAudio();
            toggleMute();
          }}
          className={clsx(
            'p-2 rounded-lg transition-colors',
            isMuted ? 'bg-cockpit-surface text-cockpit-muted' : 'bg-cyber-cyan/20 text-cyber-cyan'
          )}
          title={isMuted ? 'Unmute alarms' : 'Mute alarms'}
        >
          {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
        </button>

        {/* Incident Logs */}
        <button
          onClick={onOpenIncidents}
          className="p-2 rounded-lg bg-cockpit-surface hover:bg-cockpit-border transition-colors"
          title="View incident logs"
        >
          <AlertTriangle className="w-4 h-4 text-hud-amber" />
        </button>

        {/* Frame Counter */}
        <div className="text-right">
          <p className="text-xs text-cockpit-muted">Frames</p>
          <p className="data-display text-sm text-white">{frameHistory.length}</p>
        </div>

        {/* UTC Clock */}
        <div className="text-right">
          <p className="text-xs text-cockpit-muted">UTC</p>
          <p className="data-display text-sm text-cyber-cyan">
            {currentTime.toUTCString().slice(17, 25)}
          </p>
        </div>

        {/* Connection Status */}
        <div className="flex items-center gap-2">
          <div className={clsx('w-3 h-3 rounded-full', connectionStatusColor[connectionStatus])} />
          {connectionStatus === 'CONNECTED' ? (
            <Wifi className="w-4 h-4 text-nominal-green" />
          ) : (
            <WifiOff className="w-4 h-4 text-alert-red" />
          )}
        </div>

        {/* Replay Mode Indicator */}
        {isReplayMode && (
          <div className="px-2 py-1 rounded bg-hud-amber/20 border border-hud-amber">
            <span className="text-xs text-hud-amber font-medium">REPLAY</span>
          </div>
        )}
      </div>
    </header>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// View: Cockpit Overview
// ══════════════════════════════════════════════════════════════════════════════

function CockpitOverview() {
  return (
    <div className="grid grid-cols-12 gap-4 h-full">
      {/* Left Column: Health & RTB */}
      <div className="col-span-12 lg:col-span-3 space-y-4">
        <MasterHealthGauge size={280} />
        <ReturnToBaseHUD />
      </div>

      {/* Center Column: 3D View */}
      <div className="col-span-12 lg:col-span-5">
        <div className="hud-panel h-[500px]">
          <Engine3DView showControls={true} />
        </div>
      </div>

      {/* Right Column: Sensors */}
      <div className="col-span-12 lg:col-span-4">
        <SensorHealthStatus />
      </div>

      {/* Bottom: Strip Charts */}
      <div className="col-span-12">
        <TelemetryStripCharts />
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// View: 3D Digital Twin Detailed
// ══════════════════════════════════════════════════════════════════════════════

function DigitalTwinDetailed() {
  return (
    <div className="grid grid-cols-12 gap-4 h-full">
      {/* Main 3D View */}
      <div className="col-span-12 lg:col-span-8">
        <div className="hud-panel h-[600px]">
          <Engine3DView showControls={true} />
        </div>
      </div>

      {/* Right Panel */}
      <div className="col-span-12 lg:col-span-4 space-y-4">
        <MasterHealthGauge size={250} />
        <SensorHealthStatus compact />
      </div>

      {/* Bottom: Charts */}
      <div className="col-span-12">
        <TelemetryStripCharts />
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// View: Diagnostics & Logs
// ══════════════════════════════════════════════════════════════════════════════

function DiagnosticsView() {
  return (
    <div className="grid grid-cols-12 gap-4 h-full">
      {/* Left: Replay Toolbar */}
      <div className="col-span-12 lg:col-span-4 space-y-4">
        <MissionReplayToolbar />
        <ReturnToBaseHUD />
      </div>

      {/* Center: 3D View */}
      <div className="col-span-12 lg:col-span-5">
        <div className="hud-panel h-[400px]">
          <Engine3DView showControls={false} />
        </div>
      </div>

      {/* Right: Health */}
      <div className="col-span-12 lg:col-span-3">
        <MasterHealthGauge size={220} />
      </div>

      {/* Bottom: All Charts */}
      <div className="col-span-12">
        <TelemetryStripCharts />
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Dashboard Component
// ══════════════════════════════════════════════════════════════════════════════

function Dashboard() {
  const [viewMode, setViewMode] = useState<ViewMode>('overview');
  const [isDemoPanelOpen, setIsDemoPanelOpen] = useState(false);
  const [isIncidentModalOpen, setIsIncidentModalOpen] = useState(false);

  const renderView = () => {
    switch (viewMode) {
      case 'overview':
        return <CockpitOverview />;
      case '3d':
        return <DigitalTwinDetailed />;
      case 'diagnostics':
        return <DiagnosticsView />;
      default:
        return <CockpitOverview />;
    }
  };

  return (
    <div className="min-h-screen bg-cockpit-bg flex flex-col">
      {/* Top Navigation */}
      <TopNavBar
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        onOpenIncidents={() => setIsIncidentModalOpen(true)}
      />

      {/* Main Content */}
      <main className="flex-1 overflow-auto p-4 pb-24">
        {renderView()}
      </main>

      {/* Demo Control Panel */}
      <DemoControlPanel
        isOpen={isDemoPanelOpen}
        onToggle={() => setIsDemoPanelOpen(!isDemoPanelOpen)}
      />

      {/* Incident Log Modal */}
      <IncidentLogModal
        isOpen={isIncidentModalOpen}
        onClose={() => setIsIncidentModalOpen(false)}
      />
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// App Export with Providers
// ══════════════════════════════════════════════════════════════════════════════

function App() {
  return (
    <TelemetryProvider>
      <ToastProvider>
        <Dashboard />
      </ToastProvider>
    </TelemetryProvider>
  );
}

export default App;
