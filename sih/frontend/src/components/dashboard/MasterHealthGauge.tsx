// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin - Master Health Gauge
// ══════════════════════════════════════════════════════════════════════════════
//
// High-visibility circular radial gauge displaying:
// - Engine Health Index (EHI): 0% - 100%
// - Combustion Efficiency sub-metric
// - Vibration Level sub-metric
//
// ══════════════════════════════════════════════════════════════════════════════

import { useMemo } from 'react';
import { useTelemetry } from '../../context/TelemetryContext';
import clsx from 'clsx';

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

interface MasterHealthGaugeProps {
  size?: number;
  className?: string;
}

// ══════════════════════════════════════════════════════════════════════════════
// SVG Arc Generator
// ══════════════════════════════════════════════════════════════════════════════

function describeArc(
  x: number,
  y: number,
  radius: number,
  startAngle: number,
  endAngle: number
): string {
  const start = polarToCartesian(x, y, radius, endAngle);
  const end = polarToCartesian(x, y, radius, startAngle);
  const largeArcFlag = endAngle - startAngle <= 180 ? '0' : '1';
  
  return [
    'M', start.x, start.y,
    'A', radius, radius, 0, largeArcFlag, 0, end.x, end.y,
  ].join(' ');
}

function polarToCartesian(
  centerX: number,
  centerY: number,
  radius: number,
  angleInDegrees: number
) {
  const angleInRadians = ((angleInDegrees - 90) * Math.PI) / 180.0;
  return {
    x: centerX + radius * Math.cos(angleInRadians),
    y: centerY + radius * Math.sin(angleInRadians),
  };
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Component
// ══════════════════════════════════════════════════════════════════════════════

export default function MasterHealthGauge({
  size = 300,
  className,
}: MasterHealthGaugeProps) {
  const { currentFrame } = useTelemetry();
  
  // Extract values
  const ehi = currentFrame?.health?.ehi ?? 0;
  const combustionEfficiency = currentFrame?.health?.combustion_efficiency ?? 0;
  const vibration = currentFrame?.vibration_rms ?? 0;
  
  // Calculate gauge parameters
  const center = size / 2;
  const radius = (size / 2) - 20;
  const strokeWidth = 12;
  
  // Arc angles (270° sweep from -225° to 45°)
  const startAngle = -225;
  const endAngle = 45;
  const totalSweep = endAngle - startAngle; // 270°
  
  // EHI arc
  const ehiAngle = startAngle + (ehi / 100) * totalSweep;
  
  // Color based on EHI value
  const getEhiColor = (value: number): string => {
    if (value >= 80) return '#10b981'; // Nominal green
    if (value >= 60) return '#f59e0b'; // Warning amber
    return '#ef4444'; // Critical red
  };
  
  const getEhiStatus = (value: number): string => {
    if (value >= 80) return 'NOMINAL';
    if (value >= 60) return 'DEGRADED';
    return 'CRITICAL';
  };
  
  const ehiColor = getEhiColor(ehi);
  const ehiStatus = getEhiStatus(ehi);
  
  // Vibration color
  const getVibrationColor = (value: number): string => {
    if (value < 1.5) return '#10b981';
    if (value < 2.0) return '#f59e0b';
    return '#ef4444';
  };
  
  // Generate tick marks
  const ticks = useMemo(() => {
    const tickCount = 27; // Every 10%
    const ticks = [];
    
    for (let i = 0; i <= tickCount; i++) {
      const angle = startAngle + (i / tickCount) * totalSweep;
      const isMajor = i % 3 === 0; // Major tick every 30%
      const innerRadius = radius - (isMajor ? 25 : 18);
      const outerRadius = radius - 8;
      
      const inner = polarToCartesian(center, center, innerRadius, angle);
      const outer = polarToCartesian(center, center, outerRadius, angle);
      
      ticks.push({
        x1: inner.x,
        y1: inner.y,
        x2: outer.x,
        y2: outer.y,
        isMajor,
        label: isMajor ? `${i * (100 / tickCount)}` : null,
        labelPos: polarToCartesian(center, center, innerRadius - 12, angle),
      });
    }
    
    return ticks;
  }, [center, radius, startAngle, totalSweep]);
  
  return (
    <div className={clsx('hud-panel flex flex-col items-center', className)}>
      <h3 className="text-sm font-medium text-cockpit-muted mb-4">
        Engine Health Index
      </h3>
      
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {/* Background arc */}
        <path
          d={describeArc(center, center, radius, startAngle, endAngle)}
          fill="none"
          stroke="#1f2937"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
        />
        
        {/* Gradient segments (green -> amber -> red) */}
        <defs>
          <linearGradient id="gaugeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#ef4444" />
            <stop offset="40%" stopColor="#f59e0b" />
            <stop offset="100%" stopColor="#10b981" />
          </linearGradient>
          <filter id="glow">
            <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
            <feMerge>
              <feMergeNode in="coloredBlur"/>
              <feMergeNode in="SourceGraphic"/>
            </feMerge>
          </filter>
        </defs>
        
        {/* Colored progress arc */}
        <path
          d={describeArc(center, center, radius, startAngle, ehiAngle)}
          fill="none"
          stroke={ehiColor}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          filter="url(#glow)"
          style={{ transition: 'stroke-dashoffset 0.5s ease-out' }}
        />
        
        {/* Tick marks */}
        {ticks.map((tick, i) => (
          <g key={i}>
            <line
              x1={tick.x1}
              y1={tick.y1}
              x2={tick.x2}
              y2={tick.y2}
              stroke={tick.isMajor ? '#6b7280' : '#374151'}
              strokeWidth={tick.isMajor ? 2 : 1}
            />
            {tick.label && (
              <text
                x={tick.labelPos.x}
                y={tick.labelPos.y}
                textAnchor="middle"
                dominantBaseline="middle"
                fill="#6b7280"
                fontSize="10"
                fontFamily="monospace"
              >
                {tick.label}
              </text>
            )}
          </g>
        ))}
        
        {/* Center display */}
        <text
          x={center}
          y={center - 20}
          textAnchor="middle"
          dominantBaseline="middle"
          fill={ehiColor}
          fontSize="48"
          fontWeight="bold"
          fontFamily="monospace"
          filter="url(#glow)"
        >
          {ehi.toFixed(1)}
        </text>
        
        <text
          x={center}
          y={center + 15}
          textAnchor="middle"
          dominantBaseline="middle"
          fill="#9ca3af"
          fontSize="14"
          fontFamily="monospace"
        >
          % EHI
        </text>
        
        <text
          x={center}
          y={center + 40}
          textAnchor="middle"
          dominantBaseline="middle"
          fill={ehiColor}
          fontSize="12"
          fontWeight="bold"
          fontFamily="sans-serif"
        >
          {ehiStatus}
        </text>
      </svg>
      
      {/* Sub-metrics */}
      <div className="grid grid-cols-2 gap-4 mt-4 w-full max-w-xs">
        {/* Combustion Efficiency */}
        <div className="text-center p-3 rounded-lg bg-cockpit-bg/50">
          <p className="text-xs text-cockpit-muted mb-1">Combustion</p>
          <p className="data-display text-lg text-cyber-cyan">
            {combustionEfficiency.toFixed(1)}%
          </p>
          <div className="mt-2 h-1 bg-cockpit-border rounded-full overflow-hidden">
            <div
              className="h-full bg-cyber-cyan transition-all duration-300"
              style={{ width: `${combustionEfficiency}%` }}
            />
          </div>
        </div>
        
        {/* Vibration Level */}
        <div className="text-center p-3 rounded-lg bg-cockpit-bg/50">
          <p className="text-xs text-cockpit-muted mb-1">Vibration</p>
          <p 
            className="data-display text-lg"
            style={{ color: getVibrationColor(vibration) }}
          >
            {vibration.toFixed(2)} g
          </p>
          <div className="mt-2 h-1 bg-cockpit-border rounded-full overflow-hidden">
            <div
              className="h-full transition-all duration-300"
              style={{ 
                width: `${Math.min(100, (vibration / 5) * 100)}%`,
                backgroundColor: getVibrationColor(vibration),
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
