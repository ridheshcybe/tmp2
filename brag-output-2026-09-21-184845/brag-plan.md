# Brag Plan: AeroTwin — The AI Digital Twin System

## What is this app?
AeroTwin is a physics-constrained digital twin for the DRDO Tapas-BH-201 MALE UAV
aero engine: a real-time software clone that ingests every telemetry byte (10 Hz,
4 cylinders, 20+ channels), runs ML anomaly detection / fault classification / RUL
prediction on it, and predicts component failure before a human could ever notice.

## The angle
The user's presentation script IS the angle — keep it. "Trusting a human operator
to catch a system failure before it happens? Absolute madness." The video is the
45-second intro for a presentation: cinematic fake-out hook (sputtering plane,
record scratch) → holographic engine reveal → AI vs. sleepy human comedy beat →
"CRITICAL FAILURE PREDICTED" climax → "Let's Build It." Yellow/black high-contrast
carries every frame. The product's real material powers the middle: the actual
telemetry stream (RPM 5,600 / CHT 96.2°C / RUL countdown), the fault vocabulary
(OVERHEATING, MISFIRE, LUBRICATION_FAILURE), the phase chip (STARTUP → TAKEOFF →
CLIMB → CRUISE), and the mission profile the engine really flies.

## Hook (first 2-3 seconds)
Black screen. "FLIGHT 404: OPERATOR ERROR?" slams in over a propeller sputter…
record scratch. Total silence for a beat. Then the VO: "Imagine trusting a human
operator to catch a system failure before it happens. Absolute madness, right?"

## Key moments (the middle)
- **MEET THE TWIN** — plane freezes mid-air; camera dives into the engine; the
  cylinders morph into a glowing yellow wireframe V4 (the cutaway engine, wireframe
  treatment). Real telemetry values tick beneath it: RPM, CHT, oil pressure.
- **AI vs. HUMAN REFLEXES** — split screen: left, a sleepy operator + cold coffee
  ("HUMAN: 1 sip deep"); right, hyperspeed yellow terminal lines (real fault
  classes and channel names from the backend: `inject_fault(OVERHEATING, 0.85)`,
  `anomaly_score 0.91`, `EGT_C3 +220°C`). Keyboard clatter builds.
- **The countdown** — "CRITICAL FAILURE PREDICTED: 42 MINUTES REMAINING" warning
  block slams in (the RUL field, real scale), then the faulty component swaps out
  in the sim — "MAINTENANCE ORCHESTRATED — DOWNTIME: 0 MINUTES."

## Outro / punchline
Cut to pure black. Single yellow title: **"Let's Build It."** then
**"Welcome to the Presentation."** Music swells, hard cut on the last word.

## User flow worth showing
Open dashboard → live telemetry streams at 10 Hz (KPI cards + sparklines, phase
chip tracks the flight) → anomaly detected / fault classified → RUL countdown and
RTB advisory. That IS the flow the twin performs every second; the terminal and
countdown scenes recreate it with real values and real channel names.

## Tone
- Preset: cinematic
- Creative direction: user-supplied — "Cinematic, Funny, Energetic but
  Conversational; high-contrast yellow and black; audience = engineering students"
- Interpretation: wide dramatic reveals and big type, but the copy stays
  conversational and winking (madness / boom / let's build it). Restraint on
  decoration — yellow on black does the work.

## Format: landscape — 1920x1080
## Duration: 45 seconds (user-mandated; overrides the 15-25s default — five VO
beats at 6/9/13/12/5 seconds, scene durations flex to the generated narration)

## Visual identity (from the user's spec + project)
- Background: #000000 (pitch black)
- Accent: #FFD700 primary gold; #FFFF00 for warning blocks (user spec lists both)
- Text: #FFFFFF for secondary; all display text yellow
- Display font: Space Grotesk (the dashboard's headline font)
- Body font: ui-monospace / Menlo for terminal lines
- Strongest visual element: the glowing wireframe engine + the live telemetry
  readouts (RPM / CHT / EGT / RUL) and the amber fault banner
- Warning banner styling mirrors the dashboard's real alert chip (amber on dark)

## Share copy (draft)
"Flight 404 was never about operator error. AeroTwin predicts engine failure
42 minutes before it happens — meet the AI digital twin. Let's build it."

## Audio direction
- Role: cinematic support + voiceover lead
- Music: `happy-beats-business-moves-vol-1-by-ende-dot-app.mp3` (closest bundled
  bed with real beats; ducked hard under VO)
- Music treatment: starts at 0.0 under the sputter, ducks to 0.12-0.15 for all
  VO lines, swells to full after "boom", hard-fades at 44.5s
- Music cue guidance: preset cue file read for vol-1; strong cues targeted for
  the freeze-frame reveal (~6s) and the warning-block slam (~28s); beat grid for
  the terminal-line staccato (non-text ticks only, ~10.5-13s)
- Audio-reactive treatment: subtle — the wireframe engine's glow breathes with
  music RMS; no waveform/equalizer visuals
- SFX posture: moderate, motion-matched (sputter → record scratch → electronic
  hum → keyboard clatter → sub-bass drop → chime → swell/cut)
- Audio-coupled moments: typed terminal lines (key ticks), countdown flip,
  warning banner slam, component-swap chime, final title cut
- Restraint rule: nothing overpowers the VO; SFX fire with motion, never between
  VO sentences; no strobing

## Voiceover script
VO-1 (0-6s, excited/conversational): "Imagine trusting a human operator to catch
a system failure before it happens. Absolute madness, right?"

VO-2 (6-15s): "Look closer. This isn't just an animation — it's a living,
breathing AI Digital Twin. A real-time software clone tracking every single byte
of data."

VO-3 (15-28s): "While the human operator is still waiting for their morning
coffee to kick in… the digital twin has already run ten thousand failure
simulations."

VO-4 (28-40s): "Boom. Structural anomalies caught. Component failure predicted
hours before the operator even notices a glitch. That is the power of predictive
AI orchestration."

VO-5 (40-45s): "Now… let's look under the hood and see how we actually build it."

(Generate with Kokoro af_heart; scene timings flex to the WAV durations.)

## Storyboard

### Scene 1 — The Fake-Out Hook — 6s
Black. A stylized yellow-line propeller plane sputters through digital clouds
(pure graphic — two rotating prop blades as arcs, stuttering translate). Big
yellow title slams in: "FLIGHT 404: OPERATOR ERROR?" Holds ~1.8s settled.
Sequential/interaction: none
Audio intent: drama then comedy — loud sputter, record scratch, beat of silence
Audio-coupled idea: title slam lands with the scratch; plane shake on each sputter
Music: bed fades in low under the sputter
Transition mood: hard (scratch) → Scene 2

### Scene 2 — MEET THE TWIN — 9s
Plane freezes mid-air. Camera zooms hard into the engine block; cylinders morph
into a glowing yellow wireframe V4 (crankcase + 4 pistons as outline meshes,
slowly rotating; glow breathes with music RMS). Title: "MEET THE TWIN." Beneath
the engine, three live telemetry readouts tick with real values: RPM 5,600 ·
CHT 96.2°C · OIL 45.2 PSI (count-up entrance, then live jitter).
Sequential/interaction: readouts tick up one after another
Audio intent: sudden high-tech hum, sense of scale
Audio-coupled idea: readout count-ups; hum swells as the wireframe resolves
Music: bed ducked under VO-2
Transition mood: dramatic push → Scene 3

### Scene 3 — AI vs. HUMAN REFLEXES — 13s
Split screen. LEFT (dark grey panel): sleepy operator silhouette slumped in a
chair, cold coffee cup, Zzz floating up; label "HUMAN: 1 SIP DEEP". RIGHT (black
+ yellow terminal): hyper-speed lines typing in — `> anomaly_score: 0.91`,
`> fault_class: OVERHEATING (0.85)`, `> EGT_C3: +220°C`, `> inject_fault()…done`,
`> simulations_run: 10,000`. Title across the top: "AI vs. HUMAN REFLEXES".
Sequential/interaction: yes — terminal lines type in one by one (~6 lines, each
holds after typing; full set stays on screen)
Audio intent: mechanical keyboard clatter building urgency
Audio-coupled idea: key ticks per typed line; Zzz floats on a slow beat
Music: bed ducked under VO-3
Transition mood: hard cut → Scene 4

### Scene 4 — THE CLIMAX — 12s
Full-screen black. Massive amber/yellow warning block slams in:
"⚠ CRITICAL FAILURE PREDICTED — 42 MINUTES REMAINING" (mirrors the dashboard's
real RTB alert styling). Sub-drop. Then the wireframe engine returns small:
the faulty cylinder (red-outline) slides out, a fresh yellow one slides in —
chime. Caption: "FAILURE PREDICTED BEFORE IT HAPPENS".
Sequential/interaction: warning block → swap animation → caption
Audio intent: sub-bass drop, then satisfying chime
Audio-coupled idea: banner slam on the drop; chime on component lock-in
Music: bed rises to full after VO-4's "boom"
Transition mood: dramatic → Scene 5

### Scene 5 — Outro — 5s
Pure black. Single bold yellow title fades in center: "Let's Build It." —
one beat — second line: "Welcome to the Presentation." Music swells and cuts
sharply on the last word.
Sequential/interaction: two title lines, sequential
Audio intent: swell then hard cut
Audio-coupled idea: title cut lands with the music cut
Music: swell → hard cut at 44.5s

**Voiceover mapping:** VO-1→S1, VO-2→S2, VO-3→S3, VO-4→S4, VO-5→S5 (own track,
music ducked to 0.12-0.15 during each line; scene data-duration flexes to WAV).

**Music mood for this video:** cinematic (bed) with kinetic keyboard percussion
**Audio summary:** drama hook → high-tech hum → typing tension → drop/chime →
swell-and-cut, all under a ducked bed so the narration always leads.
