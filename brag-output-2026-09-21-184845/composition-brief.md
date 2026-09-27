# Hyperframes Composition Brief: AeroTwin — The AI Digital Twin System

## Objective
Create a 45-second cinematic/funny presentation-intro video for AeroTwin,
executing the user's provided production script (their beats, their copy, their
yellow/black spec) with a spoken voiceover.

## Output
- Composition directory: `brag-output-2026-09-21-184845/composition/`
- Rendered video: `brag-output-2026-09-21-184845/brag.mp4`
- Format: landscape — 1920x1080
- Duration: 45 seconds (user-mandated; narration sets the pace — flex scene
  data-duration to the generated WAV, do not hardcode)

## Source Material
- Project root: repo root (this workspace)
- Primary files read: src/frontend/index.html, src/frontend/cutaway.html,
  sih/backend/services/simulator.py, sih/simulator/telemetry_gen/mission_profiles.py,
  docs/API_REFERENCE.md, README.md
- Product name: AeroTwin (V-4 Digital Twin / DRDO Tapas-BH-201)
- Tagline / strongest claim: "Component failure predicted hours before the
  operator even notices a glitch."
- Key UI or visual moment to recreate: the live telemetry readouts and amber
  alert banner (dashboard), the wireframe cutaway engine (simulator), the fault
  vocabulary and RUL countdown (backend)
- Copy that must appear verbatim:
  - "FLIGHT 404: OPERATOR ERROR?"
  - "MEET THE TWIN."
  - "AI vs. HUMAN REFLEXES"
  - "CRITICAL FAILURE PREDICTED: 42 MINUTES REMAINING"
  - "FAILURE PREDICTED BEFORE IT HAPPENS"
  - "Let's Build It. Welcome to the Presentation."

## Creative Direction
- Tone preset: cinematic
- Creative direction: user-supplied — "Cinematic, Funny, Energetic but
  Conversational; high-contrast Yellow and Black (#FFD700 & #000000); audience:
  engineering/tech students"
- Interpretation: wide dramatic reveals, big type, hard cuts; copy stays
  conversational and winking. Yellow-on-black does the visual work; no clutter.
- Angle: the presentation's own intro — human vs. machine comedy wrapping a
  real predictive-digital-twin claim.
- Hook: sputtering plane + "FLIGHT 404: OPERATOR ERROR?" + record scratch
- Outro / punchline: "Let's Build It." → "Welcome to the Presentation." hard cut
- Avoid:
  - Generic SaaS language
  - Abstract filler visuals (every scene uses engine/telemetry/terminal material)
  - Unrelated visual redesign

## Visual Identity
- Background: #000000
- Text: #FFD700 display; #FFFF00 warning blocks; #FFFFFF minor/secondary
- Accent: #FFD700 (primary), amber #FFB020 for the warning banner edge
- Display font: Space Grotesk (Google Fonts; the dashboard's headline font)
- Body font: ui-monospace/Menlo for terminal + telemetry
- Visual references from the project: cutaway engine wireframe, KPI readouts,
  phase chip, fault-injection sliders, terminal JSON drawer, amber alert banner

## Storyboard
Use the storyboard in brag-output-2026-09-21-184845/brag-plan.md as the creative
contract (5 scenes: 6s fake-out hook / 9s meet-the-twin / 13s AI-vs-human /
12s climax / 5s outro; flex to voiceover WAV).

## Audio
- Audio role: cinematic support + voiceover lead
- Audio arc: sputter/scratch hook → high-tech hum → keyboard-clatter tension →
  sub-bass drop + chime → swell-and-hard-cut; music ducked to 0.12-0.15 under
  every VO line
- Music: assets/music/happy-beats-business-moves-vol-1-by-ende-dot-app.mp3
  (copy into composition/assets/music/)
- Music treatment: fade in under scene 1, ducked under VO, full after "boom"
  (scene 4), swell in scene 5, hard fade at ~44.5s
- Music cue guidance: preset cues available at
  .agents/skills/brag/assets/music/cues/happy-beats-business-moves-vol-1-by-ende-dot-app.music-cues.json —
  target strong cues for the freeze/reveal (~6s) and warning slam (~28s); use
  the beat grid only for non-text staccato accents in scene 3
- Audio-reactive treatment: subtle — wireframe engine glow breathes with music
  RMS; no waveform/equalizer/strobe visuals
- Audio-coupled moments:
  - Scene 1 — title slam on the record scratch
  - Scene 2 — telemetry count-ups on the hum
  - Scene 3 — key tick per typed terminal line
  - Scene 4 — banner slam on the drop; chime on component lock-in
  - Scene 5 — title cut lands with the music cut
- SFX selection guidance: motion-matched, moderate density; use the bundled
  sfx-analysis.md; prefer low high-frequency-risk sounds for the repeated key
  ticks (assets/sfx/keyboard/)
- Exact SFX choice: Hyperframes chooses filenames/timestamps/volume from the
  implemented animation; copy chosen files into composition/assets/sfx/
- Voiceover: ENABLED (user's script has spoken VO). Write the five VO lines from
  brag-plan.md §Voiceover script, generate with:
  npx hyperframes tts "<script>" --voice af_heart --output <out>/composition/assets/voiceover.wav
  (one WAV per line or one combined script — Hyperframes' choice; wire on its
  own track, index 3, music ducks under it; scene durations flex to the WAV)

## Hyperframes Instructions
Load hyperframes-core, hyperframes-animation, hyperframes-creative,
hyperframes-keyframes, hyperframes-cli. /brag owns product angle, copy, tone,
storyboard, and audio intent; Hyperframes owns composition structure, timing
mechanics, runtimes, lint, and render. Do not enter the hyperframes
entry-point interview.

Requirements:
- 1920x1080, 45s, 5 scenes per the plan; all on-screen copy verbatim from the brief
- At least one real product visual (wireframe engine + live telemetry readouts)
- All text readable; fast-in + hold, never flash
- Include music + SFX + voiceover layers as specified
- At least one audio-reactive element (engine glow) or documented extraction failure
- Beat-lock 1-3 major reveals to strong cues (mark // beat-locked); grid-snap
  only non-text accents in scene 3 (mark // beat-grid)
- Run `npx hyperframes check` in composition/ — zero errors is the render gate
- Render with `npx hyperframes render --quality high --output ../brag.mp4`
