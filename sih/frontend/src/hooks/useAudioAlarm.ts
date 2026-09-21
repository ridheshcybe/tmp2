// ══════════════════════════════════════════════════════════════════════════════
// React Hook for Audio Alarm Service
// ══════════════════════════════════════════════════════════════════════════════

import { useState, useEffect, useCallback, useRef } from 'react';
import { 
  AudioAlarmService, 
  getAudioAlarmService, 
  type AlarmLevel 
} from '../services/AudioAlarmService';

// ══════════════════════════════════════════════════════════════════════════════
// Hook Interface
// ══════════════════════════════════════════════════════════════════════════════

interface UseAudioAlarmReturn {
  isMuted: boolean;
  currentLevel: AlarmLevel;
  isInitialized: boolean;
  toggleMute: () => void;
  setMuted: (muted: boolean) => void;
  setAlarmLevel: (level: AlarmLevel) => void;
  initialize: () => Promise<void>;
}

// ══════════════════════════════════════════════════════════════════════════════
// Hook Implementation
// ══════════════════════════════════════════════════════════════════════════════

export function useAudioAlarm(): UseAudioAlarmReturn {
  const serviceRef = useRef<AudioAlarmService>(getAudioAlarmService());
  const [isMuted, setIsMuted] = useState(false);
  const [currentLevel, setCurrentLevel] = useState<AlarmLevel>('NONE');
  const [isInitialized, setIsInitialized] = useState(false);
  
  // Subscribe to service changes
  useEffect(() => {
    const service = serviceRef.current;
    
    const unsubMute = service.onMuteChanged((muted) => {
      setIsMuted(muted);
    });
    
    const unsubLevel = service.onLevelChanged((level) => {
      setCurrentLevel(level);
    });
    
    // Initialize state from service
    setIsMuted(service.isMutedState());
    setCurrentLevel(service.getAlarmLevel());
    
    return () => {
      unsubMute();
      unsubLevel();
    };
  }, []);
  
  // Initialize on first user interaction
  const initialize = useCallback(async () => {
    if (!isInitialized) {
      await serviceRef.current.initialize();
      setIsInitialized(true);
    }
  }, [isInitialized]);
  
  // Cleanup on unmount
  useEffect(() => {
    return () => {
      // Don't destroy on unmount - service is singleton
      // Service will persist for page lifetime
    };
  }, []);
  
  const toggleMute = useCallback(() => {
    serviceRef.current.toggleMute();
  }, []);
  
  const setMuted = useCallback((muted: boolean) => {
    serviceRef.current.setMuted(muted);
  }, []);
  
  const setAlarmLevel = useCallback((level: AlarmLevel) => {
    serviceRef.current.setAlarmLevel(level);
  }, []);
  
  return {
    isMuted,
    currentLevel,
    isInitialized,
    toggleMute,
    setMuted,
    setAlarmLevel,
    initialize,
  };
}

export default useAudioAlarm;
