# Brag Plan: AeroTwin

## What is this app?
AeroTwin is an AI-enabled real-time digital twin for a DRDO Tapas-BH-201 UAV
aero piston engine: a physics simulator streams telemetry at 10 Hz, an ML
pipeline (anomaly detection, fault classification, degradation severity, RUL)
predicts failures early, and live dashboards surface a transparent 0–100
health index with return-to-base alerts.

## The angle
Defense-tech product film: the engine is dying at 18,000 ft and nobody can
see it — until AeroTwin catches the fault, quantifies it, and calls the
return-to-base window in minutes. Not a feature tour; one dramatic moment
(fault injected → AI detects → RTB alert) framed by a quiet, confident open
and close. The user's line — "Early prediction of system failures for DRDO
gov" — is the closing claim, verbatim.

## Hook (first 2-3 seconds)
A dark mission-control frame: "TAPAS-BH-201 · 18,000 FT · 2400 RPM" ticking
live, then the line: "An engine is failing. Nobody can see it yet."

## Key moments (the middle)
- Telemetry stream visualized as live KPI cards arriving one by one — RPM,
  CHT (4 cylinders), oil pressure — 10 Hz ticker feel.
- Simulated fault injection: a severity slider pushed to 0.85 on
  OVERHEATING; CHT cylinder 3 climbs 96°C → 142.8°C in real time.
- The AI verdict lands as a system card: "OVERHEATING · P=0.94 · severity
  0.85", the health index drains 100 → 61, and a red banner stamps in:
  "RTB CRITICAL — RUL 23 MIN".

## Outro / punchline
"Failure predicted. Minutes ahead." → AEROTWIN // V-4 wordmark with the
closing line "Early prediction of system failures — for DRDO."

## User flow worth showing
Start mission → telemetry streams live (entry) → inject OVERHEATING at
severity 0.85 (key action) → ML pipeline flags the fault, health index
drops, RTB CRITICAL alert with RUL estimate (result). This flow is the
centerpiece: the video shows the product doing its job, not describing it.

## Tone
- Preset: polished
- Creative direction: "Early prediction of system failures for DRDO gov"
  (user-provided) — defense-tech credibility, mission-control restraint
- Interpretation: fewer scenes, longer holds, serious typography, no jokes.
  Confidence through restraint; every claim on screen is one the product
  actually makes (RUL, RTB, health index, 10 Hz).

## Format: landscape — 1920x1080
## Duration: ~20 seconds (voiceover sets final pace)

## Visual identity (from the project)
- Background: #0d0f12 (dark cockpit surface; light-mode paper #f5f0e8 used
  only for the closing wordmark card)
- Accent: #ffcc00 (primary-container amber) with alert red #e63b2e and
  signal blue #0055ff
- Text: #1a1a1a on light surfaces / #f5f0e8 on dark surfaces
- Display font: Space Grotesk (600/700)
- Body font: Inter (400/500/600)
- Strongest visual element: the live KPI card row + the red RTB banner, both
  recreated from index.html's dashboard

## Share copy (draft)
AeroTwin — a digital twin that watches a DRDO UAV engine tick by tick and
predicts failure minutes before it happens: fault class, severity, RUL, and
a return-to-base window you can audit.

## Audio direction
- Role: cinematic support under narration — a warm, low corporate bed that
  stays out of the voice's way
- Music: happy-beats-business-moves-vol-1-by-ende-dot-app.mp3 (bundled)
- Music treatment: enter at scene 1 at low volume (~0.2), swell slightly at
  the fault-injection moment, duck to 0.12–0.15 whenever narration plays,
  fade out under the closing wordmark
- Music cue guidance: bundled preset for vol-1 (cue file read at composition
  time); 1–3 strongCue locks: KPI card sequence start, RTB banner stamp,
  wordmark landing. Sequential KPI cards snap to the beat grid, but holds
  respect reading floors
- Audio-reactive treatment: subtle; RMS/bass makes the engine-status dot and
  the hook frame's glow breathe. No waveform/equalizer visuals
- SFX posture: minimal but present (polished) — soft UI drops for KPI cards,
  one alarm-adjacent accent when RTB stamps, one dry payoff on the wordmark
- Audio-coupled moments: KPI cards arriving one by one (soft drop), fault
  slider push (click), RTB banner stamp (heavy soft impact), wordmark
  (bell, restrained)
- Restraint rule: nothing aggressive, nothing comedic; the music must duck,
  never compete with the narrator

## Voiceover script
Narration (Kokoro, af_heart). Scenes flex to the generated WAV duration.

1. (Scene 1) "Eighteen thousand feet. An engine is about to fail — and no
   one can see it yet."
2. (Scene 2) "AeroTwin is a digital twin for the DRDO Tapas UAV. Physics on
   one side, machine learning on the other — watching every tick."
3. (Scene 3) "Inject a fault. The twin catches it — health drops, and a
   return-to-base alert fires, twenty-three minutes ahead of failure."
4. (Scene 4) "AeroTwin. Early prediction of system failures. For DRDO."

## Storyboard

### Scene 1 — The invisible failure (hook) — ~4s
Dark mission-control frame. Top strip: "TAPAS-BH-201 · 18,000 FT" with a
pulsing engine-status dot and a live RPM readout ticking (2400 ± wobble).
Center line fades up: "An engine is failing." then "Nobody can see it yet."
Sequential/interaction: no — one frame, two text beats
Audio intent: quiet dread; low bed begins under the narration
Audio-coupled idea: subtle key ticks as the RPM digits tick; status-dot glow
breathes with music RMS (audio-reactive)
Music: warm low bed, low volume
Transition mood: soft crossfade → Scene 2

### Scene 2 — The twin (reveal) — ~5s
AeroTwin wordmark top-left, tagline: "AI digital twin · DRDO Tapas-BH-201".
Below, three KPI cards arrive one by one — RPM 2400 · CHT CYL 96°C · OIL
310 kPa — each with a small sparkline; a "10 Hz LIVE" chip pulses.
Sequential/interaction: yes — 3 KPI cards arrive one by one (beat-grid,
holds ≥0.8s each)
Audio intent: steady, professional; the bed finds its pulse
Audio-coupled idea: soft drop SFX per card; "10 Hz" chip tick on beat
Music: same bed, slight swell
Transition mood: slide → Scene 3

### Scene 3 — Fault injected → caught (the moment) — ~8s
Center: a fault-matrix card "OVERHEATING" with a severity slider pushed from
0.40 to 0.85 (simulated cursor drag). CHT CYL 3 readout climbs 96°C → 142.8°C
with its sparkline bending up and the card flushing toward alert red. Then
the AI verdict card stamps in: "FAULT DETECTED — OVERHEATING · P=0.94 ·
SEV 0.85". Health index bar drains 100 → 61 (amber). Red banner slams in:
"RTB CRITICAL — RUL 23 MIN".
Sequential/interaction: yes — slider drag, then verdict card, then index
drain, then banner — each a distinct beat
Audio intent: rising tension, one hard moment of truth at the banner
Audio-coupled idea: slider click at drag start; CHT alarm tick as it passes
120°C; heavy soft impact exactly when the RTB banner stamps (strong cue)
Music: swell into the banner, then duck under narration tail
Transition mood: hard cut on the banner → Scene 4

### Scene 4 — The claim (outro) — ~4s
Cut to the light paper surface (#f5f0e8). Center: AEROTWIN // V-4 wordmark
(amber V4 chip). Line beneath: "Failure predicted. Minutes ahead." Final
line, verbatim: "Early prediction of system failures — for DRDO."
Sequential/interaction: no — wordmark lands, two lines settle
Audio intent: resolution; the bed resolves and fades
Audio-coupled idea: one dry bell on the wordmark landing (strong cue)
Music: fade out under the wordmark
Transition mood: none (end)

**Music mood for this video:** polished/cinematic support (warm corporate bed)
**Audio summary:** a quiet low bed under four narration lines, three restrained
SFX accents (cards, banner, wordmark), music ducking to 0.12–0.15 under the
voice and fading out at the end.
