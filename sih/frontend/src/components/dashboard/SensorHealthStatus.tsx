// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin - Sensor Health Status
// ══════════════════════════════════════════════════════════════════════════════
//
// Grid showing the state of all physical sensor channels:
// - CHT 1-4, EGT 1-4, RPM, MAP, Oil Pressure, Oil Temp, Vibration
// - Highlights isolated sensors with red badges
//
// ══════════════════════════════════════════════════════════════════════════════

import { useMemo } from 'react';
import { useTelemetry } from '../../context/TelemetryContext';
import { Activity, Thermometer, Droplets, AlertCircle } from 'lucide-react';
import clsx from 'clsx';

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

interface SensorHealthStatusProps {
  className?: string;
  compact?: boolean;
}

interface SensorChannel {
  id: string;
  label: string;
  category: 'thermal' | 'mechanical' | 'fluid';
  unit: string;
  min: number;
  max: number;
  warningThreshold: number;
  criticalThreshold: number;
  inverted?: boolean; // For sensors where lower is worse
}

// ══════════════════════════════════════════════════════════════════════════════
// Sensor Definitions
// ══════════════════════════════════════════════════════════════════════════════

const SENSOR_CHANNELS: SensorChannel[] = [
  // Thermal (CHT)
  { id: 'cht_1', label: 'CHT 1', category: 'thermal', unit: '°C', min: 60, max: 280, warningThreshold: 190, criticalThreshold: 220 },
  { id: 'cht_2', label: 'CHT 2', category: 'thermal', unit: '°C', min: 60, max: 280, warningThreshold: 190, criticalThreshold: 220 },
  { id: 'cht_3', label: 'CHT 3', category: 'thermal', unit: '°C', min: 60, max: 280, warningThreshold: 190, criticalThreshold: 220 },
  { id: 'cht_4', label: 'CHT 4', category: 'thermal', unit: '°C', min: 60, max: 280, warningThreshold: 190, criticalThreshold: 220 },
  
  // Thermal (EGT)
  { id: 'egt_1', label: 'EGT 1', category: 'thermal', unit: '°C', min: 300, max: 900, warningThreshold: 780, criticalThreshold: 850 },
  { id: 'egt_2', label: 'EGT 2', category: 'thermal', unit: '°C', min: 300, max: 900, warningThreshold: 780, criticalThreshold: 850 },
  { id: 'egt_3', label: 'EGT 3', category: 'thermal', unit: '°C', min: 300, max: 900, warningThreshold: 780, criticalThreshold: 850 },
  { id: 'egt_4', label: 'EGT 4', category: 'thermal', unit: '°C', min: 300, max: 900, warningThreshold: 780, criticalThreshold: 850 },
  
  // Mechanical
  { id: 'rpm', label: 'RPM', category: 'mechanical', unit: 'RPM', min: 0, max: 3000, warningThreshold: 2600, criticalThreshold: 2800 },
  { id: 'map_kpa', label: 'MAP', category: 'mechanical', unit: 'kPa', min: 20, max: 120, warningThreshold: 100, criticalThreshold: 110 },
  { id: 'vibration_rms', label: 'Vibration', category: 'mechanical', unit: 'g', min: 0, max: 5, warningThreshold: 1.8, criticalThreshold: 2.5 },
  
  // Fluid
  { id: 'oil_pressure_kpa', label: 'Oil Press', category: 'fluid', unit: 'kPa', min: 50, max: 700, warningThreshold: 250, criticalThreshold: 150, inverted: true },
  { id: 'oil_temp_c', label: 'Oil Temp', category: 'fluid', unit: '°C', min: 20, max: 150, warningThreshold: 110, criticalThreshold: 130 },
];

// ══════════════════════════════════════════════════════════════════════════════
// Sensor Value Extraction
// ══════════════════════════════════════════════════════════════════════════════

function getSensorValue(
  frame: any,
  sensorId: string
): number | null {
  if (!frame) return null;
  
  switch (sensorId) {
    case 'cht_1': return frame.cht?.[0] ?? null;
    case 'cht_2': return frame.cht?.[1] ?? null;
    case 'cht_3': return frame.cht?.[2] ?? null;
    case 'cht_4': return frame.cht?.[3] ?? null;
    case 'egt_1': return frame.egt?.[0] ?? null;
    case 'egt_2': return frame.egt?.[1] ?? null;
    case 'egt_3': return frame.egt?.[2] ?? null;
    case 'egt_4': return frame.egt?.[3] ?? null;
    case 'rpm': return frame.rpm ?? null;
    case 'map_kpa': return frame.map_kpa ?? null;
    case 'vibration_rms': return frame.vibration_rms ?? null;
    case 'oil_pressure_kpa': return frame.oil_pressure_kpa ?? null;
    case 'oil_temp_c': return frame.oil_temp_c ?? null;
    default: return null;
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// Sensor Status Badge Component
// ══════════════════════════════════════════════════════════════════════════════

interface SensorBadgeProps {
  sensor: SensorChannel;
  value: number | null;
  isIsolated: boolean;
  isolationReason?: string;
}

function SensorBadge({ sensor, value, isIsolated, isolationReason }: SensorBadgeProps) {
  // Determine status
  const getStatus = (): 'nominal' | 'warning' | 'critical' | 'isolated' => {
    if (isIsolated) return 'isolated';
    if (value === null) return 'warning';
    
    if (sensor.inverted) {
      if (value < sensor.criticalThreshold) return 'critical';
      if (value < sensor.warningThreshold) return 'warning';
    } else {
      if (value > sensor.criticalThreshold) return 'critical';
      if (value > sensor.warningThreshold) return 'warning';
    }
    
    return 'nominal';
  };
  
  const status = getStatus();
  
  const statusColors = {
    nominal: 'border-nominal-green/50 bg-nominal-green/10',
    warning: 'border-hud-amber/50 bg-hud-amber/10',
    critical: 'border-alert-red/50 bg-alert-red/10',
    isolated: 'border-alert-red bg-alert-red/20',
  };
  
  const textColors = {
    nominal: 'text-nominal-green',
    warning: 'text-hud-amber',
    critical: 'text-alert-red',
    isolated: 'text-alert-red',
  };
  
  const barColors = {
    nominal: 'bg-nominal-green',
    warning: 'bg-hud-amber',
    critical: 'bg-alert-red',
    isolated: 'bg-alert-red',
  };
  
  // Calculate fill percentage
  const fillPercent = value !== null 
    ? Math.min(100, Math.max(0, ((value - sensor.min) / (sensor.max - sensor.min)) * 100))
    : 0;
  
  return (
    <div className={clsx(
      'p-3 rounded-lg border transition-all',
      statusColors[status],
      status === 'critical' && 'animate-pulse',
      status === 'isolated' && 'opacity-75'
    )}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <span className={clsx(
          'text-xs font-medium',
          textColors[status]
        )}>
          {sensor.label}
        </span>
        
        {isIsolated && (
          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-alert-red text-white">
            <AlertCircle className="w-3 h-3" />
            ISOLATED
          </span>
        )}
      </div>
      
      {/* Value */}
      <div className="flex items-baseline gap-1 mb-2">
        <span className={clsx(
          'text-lg font-bold data-display',
          textColors[status]
        )}>
          {value !== null ? value.toFixed(1) : '---'}
        </span>
        <span className="text-xs text-cockpit-muted">{sensor.unit}</span>
      </div>
      
      {/* Progress bar */}
      <div className="h-1.5 bg-cockpit-border rounded-full overflow-hidden">
        <div
          className={clsx(
            'h-full rounded-full transition-all duration-300',
            barColors[status]
          )}
          style={{ width: `${fillPercent}%` }}
        />
      </div>
      
      {/* Isolation reason */}
      {isIsolated && isolationReason && (
        <p className="mt-2 text-[10px] text-alert-red/80">
          {isolationReason}
        </p>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Component
// ══════════════════════════════════════════════════════════════════════════════

export default function SensorHealthStatus({
  className,
  compact = false,
}: SensorHealthStatusProps) {
  const { currentFrame } = useTelemetry();
  
  // Get isolated sensors from frame
  const isolatedSensors = useMemo(() => {
    const isolated = new Map<string, string>();
    
    if (currentFrame?.sensor_status?.isolated_sensors) {
      currentFrame.sensor_status.isolated_sensors.forEach((sensor: string) => {
        isolated.set(sensor, 'ISOLATED');
      });
    }
    
    if (currentFrame?.sensor_status?.active_sensors) {
      Object.entries(currentFrame.sensor_status.active_sensors).forEach(([sensor, active]) => {
        if (!active) {
          isolated.set(sensor, 'INACTIVE');
        }
      });
    }
    
    return isolated;
  }, [currentFrame?.sensor_status]);
  
  // Group sensors by category
  const groupedSensors = useMemo(() => {
    const groups = {
      thermal: SENSOR_CHANNELS.filter(s => s.category === 'thermal'),
      mechanical: SENSOR_CHANNELS.filter(s => s.category === 'mechanical'),
      fluid: SENSOR_CHANNELS.filter(s => s.category === 'fluid'),
    };
    return groups;
  }, []);
  
  // Category icons
  const categoryIcons = {
    thermal: <Thermometer className="w-4 h-4" />,
    mechanical: <Activity className="w-4 h-4" />,
    fluid: <Droplets className="w-4 h-4" />,
  };
  
  const categoryLabels = {
    thermal: 'Thermal (CHT/EGT)',
    mechanical: 'Mechanical',
    fluid: 'Fluid Systems',
  };
  
  return (
    <div className={clsx('hud-panel', className)}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-cockpit-muted">
          Sensor Health Status
        </h3>
        <div className="flex items-center gap-2">
          {isolatedSensors.size > 0 && (
            <span className="flex items-center gap-1 px-2 py-1 rounded bg-alert-red/20 text-alert-red text-xs">
              <AlertCircle className="w-3 h-3" />
              {isolatedSensors.size} Isolated
            </span>
          )}
        </div>
      </div>
      
      {/* Sensor Grid */}
      <div className={clsx(
        'space-y-4',
        compact ? 'max-h-[400px] overflow-y-auto' : ''
      )}>
        {Object.entries(groupedSensors).map(([category, sensors]) => (
          <div key={category}>
            {/* Category Header */}
            <div className="flex items-center gap-2 mb-2 text-cockpit-muted">
              {categoryIcons[category as keyof typeof categoryIcons]}
              <span className="text-xs font-medium uppercase tracking-wider">
                {categoryLabels[category as keyof typeof categoryLabels]}
              </span>
            </div>
            
            {/* Sensors Grid */}
            <div className={clsx(
              'grid gap-2',
              compact ? 'grid-cols-2' : 'grid-cols-2 md:grid-cols-3 lg:grid-cols-4'
            )}>
              {sensors.map((sensor) => {
                const value = getSensorValue(currentFrame, sensor.id);
                const isIsolated = isolatedSensors.has(sensor.id);
                const isolationReason = isolatedSensors.get(sensor.id);
                
                return (
                  <SensorBadge
                    key={sensor.id}
                    sensor={sensor}
                    value={value}
                    isIsolated={isIsolated}
                    isolationReason={isolationReason}
                  />
                );
              })}
            </div>
          </div>
        ))}
      </div>
      
      {/* Summary Footer */}
      <div className="mt-4 pt-4 border-t border-cockpit-border">
        <div className="flex items-center justify-between text-xs text-cockpit-muted">
          <span>Total Sensors: {SENSOR_CHANNELS.length}</span>
          <span>
            Active: {SENSOR_CHANNELS.length - isolatedSensors.size} | 
            Isolated: {isolatedSensors.size}
          </span>
        </div>
      </div>
    </div>
  );
}
