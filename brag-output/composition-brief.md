# Hyperframes Composition Brief: AeroTwin

## Objective
Create a short launch-style brag video for **AeroTwin** — an AI-enabled
real-time digital twin for the DRDO Tapas-BH-201 UAV aero piston engine
(SIH 26054). A physics simulator streams telemetry at 10 Hz; an ML pipeline
predicts failures early with an explainable health index, fault class,
severity, and RUL/RTB alerts.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920×1080
- Duration: ~20 s (voiceover present; scene durations flex to the generated
  narration WAV — do not hardcode lengths before TTS exists)

## Source Material
- Project root: `C:\Users\admin\Downloads\tmp`
- Primary files read: `src/frontend/index.html`, `docs/README.md`,
  `docs/ML_MODELS.md`, `docs/API_REFERENCE.md`, `docs/SIMULATOR.md`,
  `brag-output/brag-plan.md`
- Product name: AeroTwin // V-4
- Tagline / strongest claim: "Early prediction of system failures — for DRDO."
- Key UI or visual moment to recreate: the dashboard's live KPI card row and
  the RTB CRITICAL banner from `src/frontend/index.html`
- Copy that must appear verbatim:
  - "An engine is failing. Nobody can see it yet."
  - "TAPAS-BH-201 · 18,000 FT"
  - "OVERHEATING" · "P=0.94" · "SEV 0.85"
  - "RTB CRITICAL — RUL 23 MIN"
  - "Early prediction of system failures — for DRDO."
  - "Failure predicted. Minutes ahead."

## Creative Direction
- Tone preset: polished
- Creative direction: "Early prediction of system failures for DRDO gov"
  (user-provided direction, preserved verbatim as the closing claim)
- Interpretation: fewer scenes, longer holds, serious typography, no jokes —
  defense-tech credibility through restraint. Every number on screen is one
  the product actually computes (health index, RUL, RTB thresholds, 10 Hz).
- Angle: the engine is dying at 18,000 ft and nobody can see it — until the
  twin catches the fault, quantifies it, and calls the RTB window in minutes.
- Hook: mission-control frame, live RPM ticking, the invisible-failure line.
- Outro: wordmark + "Failure predicted. Minutes ahead." + the DRDO claim.
- Avoid:
  - Generic SaaS language ("streamline", "empower", etc.)
  - Abstract filler visuals
  - Waveform/equalizer visuals for audio-reactive elements

## Visual Identity
- Background: #0d0f12 (dark cockpit); outro card on #f5f0e8 (project paper)
- Text: #f5f0e8 on dark; #1a1a1a on light
- Accent: #ffcc00 (amber) · alert #e63b2e · signal #0055ff
- Display font: Space Grotesk (600/700) · Body font: Inter
- Visual references from the project: KPI cards, status chips ("STATUS:
  NOMINAL", "30Hz REALTIME", "LIVE FEED"), red RTB banner, amber V4 chip

## Storyboard
Use `brag-output/brag-plan.md` as the creative contract. Summary:
1. The invisible failure — ~4s — dark mission-control frame, live RPM,
   "An engine is failing. Nobody can see it yet."
2. The twin — ~5s — wordmark + tagline, 3 KPI cards arrive one by one,
   "10 Hz LIVE" chip
3. Fault injected → caught — ~8s — OVERHEATING slider 0.40→0.85, CHT cyl 3
   96→142.8°C, verdict card, health 100→61, red "RTB CRITICAL — RUL 23 MIN"
4. The claim — ~4s — paper wordmark card, "Failure predicted. Minutes
   ahead.", DRDO claim line

## Audio
- Audio role: cinematic support under narration
- Audio arc: quiet low bed → slight swell at fault injection → duck under
  narration → hard moment at RTB stamp → resolve and fade under wordmark
- Music: happy-beats-business-moves-vol-1-by-ende-dot-app.mp3 (bundled with
  the brag skill; CC-licensed)
- Music treatment: volume ~0.2 baseline; duck to 0.12–0.15 while narration
  plays; fade out under the closing wordmark
- Music cue guidance: bundled preset
  `assets/music/cues/happy-beats-business-moves-vol-1-by-ende-dot-app.music-cues.json`
  — 1–3 strongCue locks: KPI sequence start, RTB banner stamp, wordmark
  landing. Sequential KPI cards snap to beats (holds ≥0.8 s each — reading
  floor beats the grid). If cues don't serve readability, use natural timing.
- Audio-reactive treatment: subtle; RMS/bass modulates the engine-status dot
  glow and hook-frame presence. No waveforms, no equalizer bars
- Audio-coupled moments:
  - Scene 2 KPI cards — soft drop per card
  - Scene 3 slider drag — click; CHT 120°C crossing — alarm tick
  - Scene 3 RTB banner — heavy soft impact on stamp
  - Scene 4 wordmark — one dry bell, restrained
- SFX selection guidance: follow the skill's sfx-analysis.md; prefer low
  high-frequency-risk files for this polished tone
- Exact SFX choice: Hyperframes chooses filenames/timestamps/density after
  the animation exists
- Voiceover: ENABLED (user passed --voice). Script in brag-plan.md §Voiceover
  script. Generate via Kokoro before finalizing scene durations:

```bash
npx hyperframes tts "<narration text>" --voice af_heart \
  --output brag-output/composition/assets/voiceover.wav
```

- Audio files: copy music into `brag-output/composition/assets/music/`;
  SFX + generated voiceover into `brag-output/composition/assets/`

## Hyperframes Instructions
Load `hyperframes-core`, `hyperframes-animation`, `hyperframes-creative`,
`hyperframes-keyframes`, `hyperframes-cli`. /brag is its own workflow — do
not enter the hyperframes entry-point intent interview or its generic
promo/launch-video flow. Prefer native Hyperframes conventions.

Requirements:
- Show at least one real UI recreation from the source project (KPI cards,
  RTB banner, fault matrix card)
- All text readable (respect reading floors; narration lines hold ≥0.3 s/word)
- Total 15–25 s (voiceover-paced)
- Music + SFX + voiceover per plan; music ducks under voice
- 1–3 strongCue locks marked `// beat-locked`; sequential card reveals marked
  `// beat-grid` — natural timing allowed where it serves readability
- At least one subtle audio-reactive element (status dot glow breathing), or
  document extraction failure
- Local assets only; run `npx hyperframes check` before render (single gate)
