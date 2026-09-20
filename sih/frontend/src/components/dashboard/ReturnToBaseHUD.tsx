// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin - Return to Base HUD
// ══════════════════════════════════════════════════════════════════════════════
//
// Displays AI-predicted Remaining Useful Life (RUL) with RTB alerts:
// - Large digital MM:SS display
// - Amber pulsing banner when RUL <= 30 minutes
// - Red flashing banner when RUL <= 10 minutes
//
// ══════════════════════════════════════════════════════════════════════════════

import { useTelemetry } from '../../context/TelemetryContext';
import { AlertTriangle, Clock, Shield } from 'lucide-react';
import clsx from 'clsx';

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

interface ReturnToBaseHUDProps {
  className?: string;
  showDetails?: boolean;
  /** Optional override — when provided, takes precedence over live telemetry. */
  rulMinutes?: number;
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Component
// ══════════════════════════════════════════════════════════════════════════════

export default function ReturnToBaseHUD({
  className,
  showDetails = true,
  rulMinutes: rulMinutesOverride,
}: ReturnToBaseHUDProps) {
  const { currentFrame } = useTelemetry();
  
  // Extract RUL and RTB status (prop override wins, used by tests)
  const rulMinutes = rulMinutesOverride ?? currentFrame?.prognostics?.predicted_rul_min ?? null;
  const rtbAlertLevel = currentFrame?.prognostics?.rtb_alert_level ?? 'NONE';
  const rtbWindowActive = currentFrame?.prognostics?.rtb_window_active ?? false;
  
  // Convert to MM:SS format
  const formatRUL = (minutes: number | null): string => {
    if (minutes === null) return '--:--';
    const mins = Math.floor(Math.max(0, minutes));
    const secs = Math.floor((minutes - mins) * 60);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };
  
  const rulFormatted = formatRUL(rulMinutes);
  
  // Determine alert level for styling
  const isCritical = rtbAlertLevel === 'RTB_CRITICAL' || (rulMinutes !== null && rulMinutes <= 10);
  const isAdvisory = rtbAlertLevel === 'RTB_ADVISORY' || (rulMinutes !== null && rulMinutes <= 30);
  
  // Calculate urgency color
  const getRulColor = (): string => {
    if (rulMinutes === null) return 'text-cockpit-muted';
    if (isCritical) return 'text-alert-red';
    if (isAdvisory) return 'text-hud-amber';
    return 'text-cyber-cyan';
  };
  
  // Progress percentage (based on 180 min mission endurance)
  const missionEndurance = 180;
  const progressPercent = rulMinutes !== null 
    ? Math.min(100, (rulMinutes / missionEndurance) * 100)
    : 100;
  
  return (
    <div className={clsx('hud-panel relative overflow-hidden', className)}>
      {/* Critical RTB Banner */}
      {isCritical && (
        <div className="absolute inset-0 flex items-center justify-center bg-alert-red/10 animate-pulse z-10 pointer-events-none">
          <div className="text-center">
            <p className="text-2xl font-bold text-alert-red flex items-center justify-center gap-2">
              <AlertTriangle className="w-6 h-6" />
              CRITICAL RTB
            </p>
            <p className="text-sm text-alert-red/80 mt-1">
              ENGINE SEIZURE IMMINENT
            </p>
          </div>
        </div>
      )}
      
      {/* Advisory Banner */}
      {isAdvisory && !isCritical && (
        <div className="absolute top-0 left-0 right-0 bg-hud-amber/20 border-b border-hud-amber animate-pulse">
          <div className="px-4 py-2 flex items-center justify-center gap-2">
            <AlertTriangle className="w-4 h-4 text-hud-amber" />
            <p className="text-sm font-medium text-hud-amber">
              ⚠ RETURN TO BASE ADVISORY — MARGIN: {Math.ceil(rulMinutes ?? 0)} MIN
            </p>
          </div>
        </div>
      )}
      
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Clock className="w-5 h-5 text-cockpit-muted" />
          <h3 className="text-sm font-medium text-cockpit-muted">
            Remaining Useful Life
          </h3>
        </div>
        {rtbWindowActive && (
          <div className="flex items-center gap-1 px-2 py-1 rounded bg-hud-amber/20 border border-hud-amber/50">
            <Shield className="w-3 h-3 text-hud-amber" />
            <span className="text-xs text-hud-amber">RTB WINDOW</span>
          </div>
        )}
      </div>
      
      {/* Main RUL Display */}
      <div className={clsx(
        'text-center py-6',
        isCritical && 'animate-pulse'
      )}>
        <p 
          className={clsx(
            'text-7xl font-bold data-display tracking-wider',
            getRulColor(),
            isCritical && 'drop-shadow-[0_0_20px_rgba(239,68,68,0.8)]',
            isAdvisory && !isCritical && 'drop-shadow-[0_0_15px_rgba(245,158,11,0.6)]'
          )}
        >
          {rulFormatted}
        </p>
        <p className={clsx(
          'text-lg mt-2 font-medium',
          getRulColor()
        )}>
          MINUTES REMAINING
        </p>
      </div>
      
      {/* Progress Bar */}
      {showDetails && (
        <div className="mt-4">
          <div className="flex justify-between text-xs text-cockpit-muted mb-2">
            <span>0 min</span>
            <span>Mission Endurance</span>
            <span>{missionEndurance} min</span>
          </div>
          <div className="h-3 bg-cockpit-border rounded-full overflow-hidden relative">
            {/* Background gradient */}
            <div className="absolute inset-0 bg-gradient-to-r from-alert-red via-hud-amber to-nominal-green opacity-30" />
            
            {/* Progress fill */}
            <div
              className={clsx(
                'h-full rounded-full transition-all duration-500 relative',
                isCritical ? 'bg-alert-red' : 
                isAdvisory ? 'bg-hud-amber' : 
                'bg-cyber-cyan'
              )}
              style={{ width: `${progressPercent}%` }}
            >
              {/* Glow effect */}
              <div className={clsx(
                'absolute inset-0 rounded-full',
                isCritical && 'shadow-[0_0_10px_rgba(239,68,68,0.8)]',
                isAdvisory && 'shadow-[0_0_10px_rgba(245,158,11,0.6)]'
              )} />
            </div>
            
            {/* Threshold markers */}
            <div 
              className="absolute top-0 bottom-0 w-0.5 bg-hud-amber"
              style={{ left: `${(30 / missionEndurance) * 100}%` }}
              title="30 min advisory"
            />
            <div 
              className="absolute top-0 bottom-0 w-0.5 bg-alert-red"
              style={{ left: `${(10 / missionEndurance) * 100}%` }}
              title="10 min critical"
            />
          </div>
        </div>
      )}
      
      {/* Details Grid */}
      {showDetails && (
        <div className="grid grid-cols-3 gap-4 mt-6 pt-4 border-t border-cockpit-border">
          <div className="text-center">
            <p className="text-xs text-cockpit-muted mb-1">RTB Status</p>
            <p className={clsx(
              'text-sm font-medium',
              rtbAlertLevel === 'RTB_CRITICAL' ? 'text-alert-red' :
              rtbAlertLevel === 'RTB_ADVISORY' ? 'text-hud-amber' :
              'text-nominal-green'
            )}>
              {rtbAlertLevel === 'NONE' ? 'NORMAL' : rtbAlertLevel.replace('_', ' ')}
            </p>
          </div>
          
          <div className="text-center">
            <p className="text-xs text-cockpit-muted mb-1">Engine Status</p>
            <p className={clsx(
              'text-sm font-medium',
              currentFrame?.health?.status === 'CRITICAL' ? 'text-alert-red' :
              currentFrame?.health?.status === 'WARNING' ? 'text-hud-amber' :
              'text-nominal-green'
            )}>
              {currentFrame?.health?.status ?? 'UNKNOWN'}
            </p>
          </div>
          
          <div className="text-center">
            <p className="text-xs text-cockpit-muted mb-1">Anomaly Score</p>
            <p className={clsx(
              'text-sm font-medium data-display',
              (currentFrame?.anomaly?.score ?? 0) > 50 ? 'text-alert-red' :
              (currentFrame?.anomaly?.score ?? 0) > 25 ? 'text-hud-amber' :
              'text-nominal-green'
            )}>
              {currentFrame?.anomaly?.score?.toFixed(1) ?? '0.0'}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
