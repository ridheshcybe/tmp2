# AeroTwin — Hackathon Pitch Script (3:00 total)

Five speakers, thirty-five seconds each, manager closes. Fill in the
content under each topic — the bullets are only the skeleton.

| # | Speaker | Timebox | Clock |
|---|---------|---------|-------|
| 1 | Innovation | 35 s | 0:00 – 0:35 |
| 2 | Backend    | 35 s | 0:35 – 1:10 |
| 3 | AI / ML    | 35 s | 1:10 – 1:45 |
| 4 | Frontend   | 35 s | 1:45 – 2:20 |
| 5 | Manager    | 40 s | 2:20 – 3:00 |

> The live demo (dashboard + 3D cutaway) runs on screen the whole time —
> whoever is speaking points at it, nobody stops to drive it.

---

## 1. Innovation — 0:00–0:35

**Entry (optional):** cold open, no introduction — first sentence is the problem.

**Topics:**
- The problem: engine health is invisible until something fails
- What we built: AeroTwin — a live digital twin of an aero-engine in the browser
- The hook: you can strip it open, break it, and predict the failure — live
- Point at the screen: "everything you see from here is running right now"

**Exit (optional):** "…and here is how it actually works under the hood — [Backend]."

---

## 2. Backend — 0:35–1:10

**Entry (optional):** "Thanks [Innovation]. I built the engine behind the engine."

**Topics:**
- Pipeline in one line: simulator → FastAPI → WebSocket → your screen
- Fault injection: real failure modes, injected live, telemetry keeps streaming
- Every frame is stored — missions, replays and reports come from real data
- Live 24/7 on Render, free tier — nothing here is a mock

**Exit (optional):** "But raw telemetry is just numbers — [AI/ML] turns them into answers."

---

## 3. AI / ML — 1:10–1:45

**Entry (optional):** "Exactly — I make the numbers speak."

**Topics:**
- Four models on the live stream: remaining useful life, degradation, anomaly detection, failure classification
- One Health Index number a human can actually read
- Trained on our own simulated runs — pipeline, features, labels, all in-repo
- Honest fallback mode when a model is not loaded — it never goes silent

**Exit (optional):** "And to make all of this something you can *see* — [Frontend]."

---

## 4. Frontend — 1:45–2:20

**Entry (optional):** "That's me. I put the engine on your screen."

**Topics:**
- Real 3D geometry from the engine's STL files — not an artist's mock
- Strip it system by system, watch every cylinder's stroke live
- Pair your phone by scanning a QR — it becomes the throttle; no app install
- One control per job — everything on screen does exactly one thing

**Exit (optional):** "…and that's the product. [Manager] will tell you what it costs — nothing."

---

## 5. Manager — 2:20–3:00

**Entry (optional):** "Quick recap of what you just saw, and what it took."

**Topics:**
- Three beats: run it → break it → predict it — all in the demo you just watched
- Built end-to-end by a team of five, deployed for ₹0 on free tiers
- Roadmap: fleet dashboard, more fault modes, maintenance scheduling
- The ask: judges' questions

**Exit (ends the whole thing):** "AeroTwin — see the engine fail before it does. Thank you — we're happy to take questions."
