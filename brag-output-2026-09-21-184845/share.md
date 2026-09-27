# Share Copy

**Post:**
Flight 404 was never about operator error. AeroTwin predicts engine failure
42 minutes before it happens — meet the AI digital twin. Let's build it. 🛩️⚡

**One-liner:** 45-second presentation intro for AeroTwin, the AI digital twin
that predicts aero-engine failure before a human could ever notice.

**Alt versions:**
- "While the operator waits for coffee, the twin has already run 10,000 failure simulations. 45 seconds on why we built it that way."
- "CRITICAL FAILURE PREDICTED: 42 MINUTES REMAINING. Predicted — not detected. Meet AeroTwin."

# Deliverables

- `brag.mp4` — 1920×1080, 45.0s, AAC audio, 7.6 MB
- `poster.png` — warning-banner frame (29.6s)
- `poster-reveal.png` — "MEET THE TWIN." wireframe-engine frame (12s)
- `snapshots/` — six verification frames + contact sheet
- `composition/` — the Hyperframes project (`npx hyperframes preview` to open it live)

# Production notes

- Script executed verbatim from the user's production matrix — all five copy
  blocks appear exactly as written.
- Aesthetic: #000000 field, #FFD700 gold type, #FFFF00 warning block — the
  user's high-contrast spec.
- Audio: Kokoro `af_heart` voiceover (5 lines), music bed ducked under every
  line (0.14–0.16) and swelling to 0.6 before the hard cut at 44.6s, 24
  motion-matched SFX (freeze glitch, keyboard clatter, bell on the reveal,
  chime on the component swap).
- Beat-locked reveals: "MEET THE TWIN." on the strong cue at 9.02s, the
  warning banner on the intensity-1.0 cue at 28.51s (`// beat-locked` in
  source). Scene-3 typing cadence runs on the track's 0.5s beat grid.
- Audio-reactive: the wireframe engine's glow is driven by a pre-baked music
  RMS curve (417 points, 0.25s hop) sampled synchronously from the timeline —
  deterministic and seek-safe.
- `npx hyperframes check`: 0 errors, 24/24 contrast checks pass WCAG AA.
