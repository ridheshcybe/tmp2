// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin - Audio Alarm Service
// ══════════════════════════════════════════════════════════════════════════════
//
// Browser Web Audio API alarm system synthesizing tones without external files:
// - Yellow Advisory: Two short 440 Hz beeps every 5 seconds
// - Red Critical: Continuous pulsing 880 Hz klaxon tone
// - Mute toggle for silent operation
//
// ══════════════════════════════════════════════════════════════════════════════

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

export type AlarmLevel = 'NONE' | 'ADVISORY' | 'CRITICAL';

export interface AudioAlarmConfig {
  advisoryFrequency: number;    // Hz
  advisoryDuration: number;     // seconds
  advisoryInterval: number;     // seconds between alarm cycles
  advisoryBeepCount: number;    // number of beeps per cycle
  
  criticalFrequency: number;    // Hz
  criticalPulseRate: number;    // pulses per second
  criticalDutyCycle: number;    // 0-1, percentage of "on" time
  
  masterVolume: number;         // 0-1
}

// ══════════════════════════════════════════════════════════════════════════════
// Default Configuration
// ══════════════════════════════════════════════════════════════════════════════

const DEFAULT_CONFIG: AudioAlarmConfig = {
  advisoryFrequency: 440,
  advisoryDuration: 0.15,
  advisoryInterval: 5,
  advisoryBeepCount: 2,
  
  criticalFrequency: 880,
  criticalPulseRate: 2,
  criticalDutyCycle: 0.5,
  
  masterVolume: 0.7,
};

// ══════════════════════════════════════════════════════════════════════════════
// Audio Alarm Service Class
// ══════════════════════════════════════════════════════════════════════════════

export class AudioAlarmService {
  private audioContext: AudioContext | null = null;
  private masterGain: GainNode | null = null;
  
  private currentLevel: AlarmLevel = 'NONE';
  private isMuted: boolean = false;
  private isPlaying: boolean = false;
  
  // Advisory alarm state
  private advisoryTimer: ReturnType<typeof setInterval> | null = null;
  private advisoryOscillators: OscillatorNode[] = [];
  
  // Critical alarm state
  private criticalOscillator: OscillatorNode | null = null;
  private criticalLfo: OscillatorNode | null = null;
  private criticalLfoGain: GainNode | null = null;
  
  // Configuration
  private config: AudioAlarmConfig;
  
  // Event listeners
  private onMuteChange: ((muted: boolean) => void)[] = [];
  private onLevelChange: ((level: AlarmLevel) => void)[] = [];
  
  constructor(config?: Partial<AudioAlarmConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }
  
  // ─── Lifecycle ──────────────────────────────────────────────────────────
  
  /**
   * Initialize the audio context (must be called after user interaction)
   */
  async initialize(): Promise<void> {
    if (this.audioContext) return;
    
    this.audioContext = new AudioContext();
    
    // Create master gain node
    this.masterGain = this.audioContext.createGain();
    this.masterGain.gain.value = this.isMuted ? 0 : this.config.masterVolume;
    this.masterGain.connect(this.audioContext.destination);
    
    console.log('[AudioAlarm] Initialized');
  }
  
  /**
   * Resume audio context if suspended (required after user interaction)
   */
  async resume(): Promise<void> {
    if (this.audioContext?.state === 'suspended') {
      await this.audioContext.resume();
    }
  }
  
  /**
   * Stop all alarms and clean up
   */
  destroy(): void {
    this.stopAll();
    
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    
    this.masterGain = null;
    console.log('[AudioAlarm] Destroyed');
  }
  
  // ─── Alarm Control ─────────────────────────────────────────────────────
  
  /**
   * Set the current alarm level
   */
  setAlarmLevel(level: AlarmLevel): void {
    if (level === this.currentLevel) return;
    
    console.log(`[AudioAlarm] Level changed: ${this.currentLevel} -> ${level}`);
    
    // Stop current alarms
    this.stopAll();
    
    this.currentLevel = level;
    
    // Start new alarms if not muted
    if (!this.isMuted && level !== 'NONE') {
      this.startAlarm(level);
    }
    
    // Notify listeners
    this.onLevelChange.forEach((cb) => cb(level));
  }
  
  /**
   * Get current alarm level
   */
  getAlarmLevel(): AlarmLevel {
    return this.currentLevel;
  }
  
  // ─── Mute Control ──────────────────────────────────────────────────────
  
  /**
   * Toggle mute state
   */
  toggleMute(): boolean {
    this.setMuted(!this.isMuted);
    return this.isMuted;
  }
  
  /**
   * Set mute state
   */
  setMuted(muted: boolean): void {
    if (muted === this.isMuted) return;
    
    this.isMuted = muted;
    
    // Update master gain
    if (this.masterGain) {
      this.masterGain.gain.setTargetAtTime(
        muted ? 0 : this.config.masterVolume,
        this.audioContext?.currentTime ?? 0,
        0.05
      );
    }
    
    // Start/stop alarms based on mute state
    if (muted) {
      this.stopAll();
    } else if (this.currentLevel !== 'NONE') {
      this.startAlarm(this.currentLevel);
    }
    
    console.log(`[AudioAlarm] Mute: ${muted}`);
    
    // Notify listeners
    this.onMuteChange.forEach((cb) => cb(muted));
  }
  
  /**
   * Get mute state
   */
  isMutedState(): boolean {
    return this.isMuted;
  }
  
  // ─── Event Listeners ────────────────────────────────────────────────────
  
  /**
   * Subscribe to mute state changes
   */
  onMuteChanged(callback: (muted: boolean) => void): () => void {
    this.onMuteChange.push(callback);
    return () => {
      this.onMuteChange = this.onMuteChange.filter((cb) => cb !== callback);
    };
  }
  
  /**
   * Subscribe to alarm level changes
   */
  onLevelChanged(callback: (level: AlarmLevel) => void): () => void {
    this.onLevelChange.push(callback);
    return () => {
      this.onLevelChange = this.onLevelChange.filter((cb) => cb !== callback);
    };
  }
  
  // ─── Internal Alarm Generation ─────────────────────────────────────────
  
  private startAlarm(level: AlarmLevel): void {
    if (!this.audioContext || !this.masterGain) {
      console.warn('[AudioAlarm] Not initialized');
      return;
    }
    
    // Resume if suspended
    if (this.audioContext.state === 'suspended') {
      this.audioContext.resume();
    }
    
    switch (level) {
      case 'ADVISORY':
        this.startAdvisoryAlarm();
        break;
      case 'CRITICAL':
        this.startCriticalAlarm();
        break;
    }
    
    this.isPlaying = true;
  }
  
  private stopAll(): void {
    this.stopAdvisoryAlarm();
    this.stopCriticalAlarm();
    this.isPlaying = false;
  }
  
  // ─── Advisory Alarm (440 Hz Beeps) ─────────────────────────────────────
  
  private startAdvisoryAlarm(): void {
    if (!this.audioContext || !this.masterGain) return;
    
    // Play initial beep pair
    this.playBeepPair();
    
    // Set up recurring beeps
    this.advisoryTimer = setInterval(() => {
      this.playBeepPair();
    }, this.config.advisoryInterval * 1000);
  }
  
  private playBeepPair(): void {
    if (!this.audioContext || !this.masterGain || this.isMuted) return;
    
    const now = this.audioContext.currentTime;
    const { advisoryFrequency, advisoryDuration, advisoryBeepCount } = this.config;
    
    for (let i = 0; i < advisoryBeepCount; i++) {
      const startTime = now + i * (advisoryDuration * 2.5);
      this.playBeep(advisoryFrequency, advisoryDuration, startTime);
    }
  }
  
  private playBeep(
    frequency: number,
    duration: number,
    startTime: number
  ): void {
    if (!this.audioContext || !this.masterGain) return;
    
    // Create oscillator
    const oscillator = this.audioContext.createOscillator();
    oscillator.type = 'sine';
    oscillator.frequency.value = frequency;
    
    // Create gain envelope
    const gainNode = this.audioContext.createGain();
    gainNode.gain.setValueAtTime(0, startTime);
    gainNode.gain.linearRampToValueAtTime(0.8, startTime + 0.01);
    gainNode.gain.setValueAtTime(0.8, startTime + duration - 0.02);
    gainNode.gain.linearRampToValueAtTime(0, startTime + duration);
    
    // Connect nodes
    oscillator.connect(gainNode);
    gainNode.connect(this.masterGain);
    
    // Start and stop
    oscillator.start(startTime);
    oscillator.stop(startTime + duration);
    
    this.advisoryOscillators.push(oscillator);
    
    // Clean up after playing
    oscillator.onended = () => {
      oscillator.disconnect();
      gainNode.disconnect();
      this.advisoryOscillators = this.advisoryOscillators.filter((o) => o !== oscillator);
    };
  }
  
  private stopAdvisoryAlarm(): void {
    if (this.advisoryTimer) {
      clearInterval(this.advisoryTimer);
      this.advisoryTimer = null;
    }
    
    // Stop all advisory oscillators
    this.advisoryOscillators.forEach((osc) => {
      try {
        osc.stop();
      } catch (e) {
        // Already stopped
      }
    });
    this.advisoryOscillators = [];
  }
  
  // ─── Critical Alarm (880 Hz Klaxon) ────────────────────────────────────
  
  private startCriticalAlarm(): void {
    if (!this.audioContext || !this.masterGain) return;
    
    const now = this.audioContext.currentTime;
    const { criticalFrequency, criticalPulseRate, criticalDutyCycle } = this.config;
    
    // Main oscillator
    this.criticalOscillator = this.audioContext.createOscillator();
    this.criticalOscillator.type = 'sawtooth';
    this.criticalOscillator.frequency.value = criticalFrequency;
    
    // LFO for pulsing effect
    this.criticalLfo = this.audioContext.createOscillator();
    this.criticalLfo.type = 'square';
    this.criticalLfo.frequency.value = criticalPulseRate;
    
    // LFO gain (controls modulation depth)
    this.criticalLfoGain = this.audioContext.createGain();
    this.criticalLfoGain.gain.value = 0.8;
    
    // Main gain node
    const mainGain = this.audioContext.createGain();
    mainGain.gain.value = 0;
    
    // Connect LFO to main gain
    this.criticalLfo.connect(this.criticalLfoGain);
    this.criticalLfoGain.connect(mainGain.gain);
    
    // Connect oscillator to main gain
    this.criticalOscillator.connect(mainGain);
    
    // Connect to master output
    mainGain.connect(this.masterGain);
    
    // Start oscillators
    this.criticalLfo.start(now);
    this.criticalOscillator.start(now);
    
    // Add duty cycle modulation
    this.modulateDutyCycle(mainGain, criticalPulseRate, criticalDutyCycle);
  }
  
  private modulateDutyCycle(
    gainNode: GainNode,
    pulseRate: number,
    dutyCycle: number
  ): void {
    if (!this.audioContext) return;
    
    const period = 1 / pulseRate;
    const onTime = period * dutyCycle;
    
    // Create repeating pattern
    const scheduleNextPulse = (startTime: number) => {
      if (!this.audioContext || !this.isPlaying || this.currentLevel !== 'CRITICAL') {
        return;
      }
      
      const now = this.audioContext.currentTime;
      
      // On
      gainNode.gain.setValueAtTime(1, startTime);
      
      // Off
      gainNode.gain.setValueAtTime(0, startTime + onTime);
      
      // Schedule next
      const nextTime = startTime + period;
      if (nextTime < now + 10) { // Schedule 10 seconds ahead
        setTimeout(() => scheduleNextPulse(nextTime), (nextTime - now) * 1000);
      }
    };
    
    scheduleNextPulse(this.audioContext.currentTime);
  }
  
  private stopCriticalAlarm(): void {
    try {
      this.criticalOscillator?.stop();
    } catch (e) {}
    
    try {
      this.criticalLfo?.stop();
    } catch (e) {}
    
    this.criticalOscillator?.disconnect();
    this.criticalLfo?.disconnect();
    this.criticalLfoGain?.disconnect();
    
    this.criticalOscillator = null;
    this.criticalLfo = null;
    this.criticalLfoGain = null;
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// Singleton Instance
// ══════════════════════════════════════════════════════════════════════════════

let instance: AudioAlarmService | null = null;

export function getAudioAlarmService(): AudioAlarmService {
  if (!instance) {
    instance = new AudioAlarmService();
  }
  return instance;
}

export default AudioAlarmService;
