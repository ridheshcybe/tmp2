// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin - Mission Replay Toolbar
// ══════════════════════════════════════════════════════════════════════════════
//
// Interactive mission replay controls:
// - Play/Pause toggle
// - 1x / 2x / 5x playback speed
// - Timeline scrubber with anomaly markers
// - Historical data fetching for precise scrubbing
//
// ══════════════════════════════════════════════════════════════════════════════

import React, { useState, useCallback, useRef } from 'react';
import { useTelemetry, type TelemetryFrame } from '../../context/TelemetryContext';
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  RotateCcw,
  Clock,
} from 'lucide-react';
import clsx from 'clsx';

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

interface MissionReplayToolbarProps {
  className?: string;
  missionId?: string;
  startTime?: Date;
  endTime?: Date;
  onFrameSelect?: (frame: TelemetryFrame) => void;
}

interface TimelineMarker {
  time: number; // 0-100 percentage
  type: 'anomaly' | 'fault' | 'rtb' | 'event';
  label: string;
  severity: 'info' | 'warning' | 'critical';
}

// ══════════════════════════════════════════════════════════════════════════════
// Constants
// ══════════════════════════════════════════════════════════════════════════════

const PLAYBACK_SPEEDS = [1, 2, 5] as const;
const SCRUB_DEBOUNCE_MS = 300;

// ══════════════════════════════════════════════════════════════════════════════
// Main Component
// ══════════════════════════════════════════════════════════════════════════════

export default function MissionReplayToolbar({
  className,
  missionId,
  startTime,
  endTime,
  onFrameSelect,
}: MissionReplayToolbarProps) {
  const {
    replayData,
    replayIndex,
    replaySpeed,
    startReplay,
    setReplaySpeed,
    seekReplay,
  } = useTelemetry();
  
  // Local state
  const [isPlaying, setIsPlaying] = useState(false);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const [scrubPosition, setScrubPosition] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [markers, setMarkers] = useState<TimelineMarker[]>([]);
  
  // Refs
  const scrubTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sliderRef = useRef<HTMLInputElement>(null);
  
  // Calculate current position percentage
  const currentPosition = replayData.length > 0
    ? (replayIndex / (replayData.length - 1)) * 100
    : 0;
  
  // ─── Load Mission Data ─────────────────────────────────────────────────
  
  const loadMissionData = useCallback(async () => {
    if (!startTime || !endTime) return;
    
    setIsLoading(true);
    
    try {
      const params = new URLSearchParams({
        start: startTime.toISOString(),
        end: endTime.toISOString(),
      });
      
      if (missionId) {
        params.set('mission_id', missionId);
      }
      
      const response = await fetch(`/api/mission/replay?${params}`);
      const data = await response.json();
      
      if (data.data && data.data.length > 0) {
        startReplay(data.data);
        generateMarkers(data.data);
        setIsPlaying(true);
      }
    } catch (err) {
      console.error('[Replay] Failed to load mission data:', err);
    } finally {
      setIsLoading(false);
    }
  }, [missionId, startTime, endTime, startReplay]);
  
  // ─── Generate Timeline Markers ─────────────────────────────────────────
  
  const generateMarkers = useCallback((data: TelemetryFrame[]) => {
    const newMarkers: TimelineMarker[] = [];
    const totalFrames = data.length;
    
    data.forEach((frame, index) => {
      const position = (index / totalFrames) * 100;
      
      // Anomaly markers
      if (frame.anomaly?.is_detected) {
        newMarkers.push({
          time: position,
          type: 'anomaly',
          label: `Anomaly (Score: ${frame.anomaly.score?.toFixed(1)})`,
          severity: (frame.anomaly.score ?? 0) > 70 ? 'critical' : 'warning',
        });
      }
      
      // RTB markers
      if (frame.prognostics?.rtb_alert_level === 'RTB_ADVISORY') {
        newMarkers.push({
          time: position,
          type: 'rtb',
          label: 'RTB Advisory',
          severity: 'warning',
        });
      } else if (frame.prognostics?.rtb_alert_level === 'RTB_CRITICAL') {
        newMarkers.push({
          time: position,
          type: 'rtb',
          label: 'RTB Critical',
          severity: 'critical',
        });
      }
      
      // Fault injection markers
      if (frame.injected_fault) {
        newMarkers.push({
          time: position,
          type: 'fault',
          label: `Fault: ${frame.injected_fault}`,
          severity: 'critical',
        });
      }
      
      // Sensor isolation markers
      if (frame.sensor_status?.isolated_sensors?.length) {
        newMarkers.push({
          time: position,
          type: 'event',
          label: `Sensor Isolated: ${frame.sensor_status.isolated_sensors.join(', ')}`,
          severity: 'warning',
        });
      }
    });
    
    setMarkers(newMarkers);
  }, []);
  
  // ─── Playback Controls ─────────────────────────────────────────────────
  
  const togglePlayPause = useCallback(() => {
    if (isPlaying) {
      setIsPlaying(false);
      // Pause is handled by the TelemetryContext replay loop
    } else {
      if (replayData.length === 0) {
        loadMissionData();
      } else {
        setIsPlaying(true);
      }
    }
  }, [isPlaying, replayData.length, loadMissionData]);
  
  const handleSpeedChange = useCallback((speed: number) => {
    setReplaySpeed(speed);
  }, [setReplaySpeed]);
  
  const handleReset = useCallback(() => {
    seekReplay(0);
    setIsPlaying(true);
  }, [seekReplay]);
  
  const handleSkipBack = useCallback(() => {
    const skipAmount = Math.floor(replayData.length * 0.05); // 5%
    seekReplay(Math.max(0, replayIndex - skipAmount));
  }, [replayIndex, replayData.length, seekReplay]);
  
  const handleSkipForward = useCallback(() => {
    const skipAmount = Math.floor(replayData.length * 0.05); // 5%
    seekReplay(Math.min(replayData.length - 1, replayIndex + skipAmount));
  }, [replayIndex, replayData.length, seekReplay]);
  
  // ─── Timeline Scrubbing ────────────────────────────────────────────────
  
  const handleScrubStart = useCallback(() => {
    setIsScrubbing(true);
    setIsPlaying(false);
  }, []);
  
  const handleScrubChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const position = parseFloat(e.target.value);
    setScrubPosition(position);
    
    // Debounce the actual seek
    if (scrubTimeoutRef.current) {
      clearTimeout(scrubTimeoutRef.current);
    }
    
    scrubTimeoutRef.current = setTimeout(() => {
      const frameIndex = Math.floor((position / 100) * (replayData.length - 1));
      seekReplay(frameIndex);
      
      // Notify parent of selected frame
      if (onFrameSelect && replayData[frameIndex]) {
        onFrameSelect(replayData[frameIndex]);
      }
    }, SCRUB_DEBOUNCE_MS);
  }, [replayData.length, seekReplay, onFrameSelect]);
  
  const handleScrubEnd = useCallback(() => {
    setIsScrubbing(false);
  }, []);
  
  // ─── Time Formatting ───────────────────────────────────────────────────
  
  const formatTime = (index: number): string => {
    if (replayData.length === 0) return '00:00';
    
    const frame = replayData[index];
    if (frame?.timestamp) {
      const date = new Date(frame.timestamp);
      return date.toLocaleTimeString(undefined, {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    }
    
    // Fallback: calculate from index (10 Hz)
    const totalSeconds = index / 10;
    const mins = Math.floor(totalSeconds / 60);
    const secs = Math.floor(totalSeconds % 60);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };
  
  const formatDuration = (data: TelemetryFrame[]): string => {
    if (data.length === 0) return '00:00';
    
    const firstTime = new Date(data[0].timestamp).getTime();
    const lastTime = new Date(data[data.length - 1].timestamp).getTime();
    const durationSeconds = (lastTime - firstTime) / 1000;
    
    const mins = Math.floor(durationSeconds / 60);
    const secs = Math.floor(durationSeconds % 60);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };
  
  // ─── Render ────────────────────────────────────────────────────────────
  
  return (
    <div className={clsx('hud-panel', className)}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-cockpit-muted" />
          <h3 className="text-sm font-medium text-cockpit-muted">
            Mission Replay
          </h3>
        </div>
        
        {replayData.length > 0 && (
          <span className="text-xs text-cockpit-muted">
            {replayData.length} frames • {formatDuration(replayData)}
          </span>
        )}
      </div>
      
      {/* Main Controls */}
      <div className="flex items-center justify-center gap-3 mb-4">
        {/* Reset */}
        <button
          onClick={handleReset}
          className="p-2 rounded-lg bg-cockpit-surface hover:bg-cockpit-border transition-colors"
          title="Reset to start"
        >
          <RotateCcw className="w-4 h-4 text-cockpit-muted" />
        </button>
        
        {/* Skip Back */}
        <button
          onClick={handleSkipBack}
          className="p-2 rounded-lg bg-cockpit-surface hover:bg-cockpit-border transition-colors"
          title="Skip back 5%"
        >
          <SkipBack className="w-4 h-4 text-white" />
        </button>
        
        {/* Play/Pause */}
        <button
          onClick={togglePlayPause}
          disabled={isLoading}
          className={clsx(
            'p-4 rounded-full transition-all',
            isPlaying
              ? 'bg-hud-amber text-cockpit-bg hover:bg-hud-amber/80'
              : 'bg-cyber-cyan text-cockpit-bg hover:bg-cyber-cyan/80',
            isLoading && 'opacity-50 cursor-not-allowed'
          )}
          title={isPlaying ? 'Pause' : 'Play'}
        >
          {isLoading ? (
            <div className="w-5 h-5 border-2 border-cockpit-bg border-t-transparent rounded-full animate-spin" />
          ) : isPlaying ? (
            <Pause className="w-5 h-5" />
          ) : (
            <Play className="w-5 h-5 ml-0.5" />
          )}
        </button>
        
        {/* Skip Forward */}
        <button
          onClick={handleSkipForward}
          className="p-2 rounded-lg bg-cockpit-surface hover:bg-cockpit-border transition-colors"
          title="Skip forward 5%"
        >
          <SkipForward className="w-4 h-4 text-white" />
        </button>
        
        {/* Speed Selector */}
        <div className="flex items-center gap-1 ml-4">
          {PLAYBACK_SPEEDS.map((speed) => (
            <button
              key={speed}
              onClick={() => handleSpeedChange(speed)}
              className={clsx(
                'px-2 py-1 rounded text-xs font-medium transition-colors',
                replaySpeed === speed
                  ? 'bg-cyber-cyan text-cockpit-bg'
                  : 'bg-cockpit-surface text-cockpit-muted hover:bg-cockpit-border'
              )}
            >
              {speed}x
            </button>
          ))}
        </div>
      </div>
      
      {/* Timeline Scrubber */}
      <div className="relative mt-4">
        {/* Time display */}
        <div className="flex justify-between mb-2 text-xs font-mono text-cockpit-muted">
          <span>{formatTime(replayIndex)}</span>
          <span>{formatDuration(replayData)}</span>
        </div>
        
        {/* Slider track with markers */}
        <div className="relative h-8">
          {/* Background track */}
          <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-2 bg-cockpit-border rounded-full" />
          
          {/* Progress fill */}
          <div
            className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-2 bg-cyber-cyan rounded-full transition-all duration-100"
            style={{ width: `${isScrubbing ? scrubPosition : currentPosition}%` }}
          />
          
          {/* Anomaly markers */}
          {markers.map((marker, i) => (
            <div
              key={i}
              className={clsx(
                'absolute top-1/2 -translate-y-1/2 w-2 h-4 rounded-sm cursor-pointer z-10',
                'hover:scale-150 transition-transform',
                marker.type === 'fault' && 'bg-hud-amber',
                marker.type === 'anomaly' && marker.severity === 'critical' && 'bg-alert-red',
                marker.type === 'anomaly' && marker.severity === 'warning' && 'bg-hud-amber',
                marker.type === 'rtb' && marker.severity === 'critical' && 'bg-alert-red',
                marker.type === 'rtb' && marker.severity === 'warning' && 'bg-hud-amber',
                marker.type === 'event' && 'bg-cyber-cyan',
              )}
              style={{ left: `${marker.time}%` }}
              title={marker.label}
            />
          ))}
          
          {/* Range input (invisible, for interaction) */}
          <input
            ref={sliderRef}
            type="range"
            min="0"
            max="100"
            step="0.1"
            value={isScrubbing ? scrubPosition : currentPosition}
            onMouseDown={handleScrubStart}
            onTouchStart={handleScrubStart}
            onChange={handleScrubChange}
            onMouseUp={handleScrubEnd}
            onTouchEnd={handleScrubEnd}
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-20"
          />
          
          {/* Thumb indicator */}
          <div
            className={clsx(
              'absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-4 h-4 rounded-full',
              'bg-white border-2 border-cyber-cyan shadow-lg',
              'transition-all duration-100 pointer-events-none',
              isScrubbing && 'scale-125'
            )}
            style={{ left: `${isScrubbing ? scrubPosition : currentPosition}%` }}
          />
        </div>
        
        {/* Marker legend */}
        {markers.length > 0 && (
          <div className="flex items-center justify-center gap-4 mt-3 text-xs text-cockpit-muted">
            <div className="flex items-center gap-1">
              <div className="w-2 h-3 bg-hud-amber rounded-sm" />
              <span>Anomaly</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-2 h-3 bg-alert-red rounded-sm" />
              <span>Critical</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-2 h-3 bg-cyber-cyan rounded-sm" />
              <span>Event</span>
            </div>
          </div>
        )}
      </div>
      
      {/* Load button (when no data) */}
      {replayData.length === 0 && !isLoading && (
        <button
          onClick={loadMissionData}
          className="mt-4 w-full py-2 rounded-lg bg-cyber-cyan/20 text-cyber-cyan hover:bg-cyber-cyan/30 transition-colors text-sm font-medium"
        >
          Load Mission Data
        </button>
      )}
      
      {/* Current frame info */}
      {replayData[replayIndex] && (
        <div className="mt-4 pt-4 border-t border-cockpit-border grid grid-cols-4 gap-2 text-xs">
          <div className="text-center">
            <p className="text-cockpit-muted">RPM</p>
            <p className="data-display text-white">
              {replayData[replayIndex].rpm?.toFixed(0) ?? '---'}
            </p>
          </div>
          <div className="text-center">
            <p className="text-cockpit-muted">EHI</p>
            <p className="data-display text-cyber-cyan">
              {replayData[replayIndex].health?.ehi?.toFixed(1) ?? '---'}
            </p>
          </div>
          <div className="text-center">
            <p className="text-cockpit-muted">Anomaly</p>
            <p className={clsx(
              'data-display',
              (replayData[replayIndex].anomaly?.score ?? 0) > 50 ? 'text-alert-red' : 'text-nominal-green'
            )}>
              {replayData[replayIndex].anomaly?.score?.toFixed(1) ?? '0.0'}
            </p>
          </div>
          <div className="text-center">
            <p className="text-cockpit-muted">RUL</p>
            <p className="data-display text-hud-amber">
              {replayData[replayIndex].prognostics?.predicted_rul_min?.toFixed(0) ?? '---'}m
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
