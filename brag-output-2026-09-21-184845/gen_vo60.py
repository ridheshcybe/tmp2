"""Generate the eight 60s-recut voiceover lines with Kokoro (af_heart)."""
import os
import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

MODELS = os.path.expanduser("~/.cache/hyperframes/tts/models")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "composition", "assets")

LINES = {
    "vo60-1": "A vintage piston engine, alone in a dead dark sky... sputtering toward disaster.",
    "vo60-2": "Watch. The machine dissolves into pure data. A living digital twin.",
    "vo60-3": "Every rotation, every degree of heat: twenty-plus telemetry channels, streamed in real time.",
    "vo60-4": "Stress maps glow where metal strains. Nothing hides from the twin.",
    "vo60-5": "Forty-two minutes before any alarm sounds: failure, predicted.",
    "vo60-6": "Ten thousand simulations a minute. The twin already knows how the story ends.",
    "vo60-7": "Neural loops isolate the fault. Click. Quarantined. Replaced. Zero downtime.",
    "vo60-8": "AI Digital Twin System. Predictive control. Let's build it.",
}

def main():
    kokoro = Kokoro(os.path.join(MODELS, "kokoro-v1.0.onnx"),
                    os.path.join(MODELS, "voices-v1.0.bin"))
    for name, text in LINES.items():
        samples, sample_rate = kokoro.create(text, voice="af_heart", speed=1.0, lang="en-us")
        path = os.path.join(OUT, f"{name}.wav")
        sf.write(path, samples, sample_rate)
        dur = len(samples) / sample_rate
        print(f"{name}.wav  {dur:.2f}s  ({len(text.split())} words)")

if __name__ == "__main__":
    main()
