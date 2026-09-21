"""Regenerate the 30s-recut voiceover lines with Kokoro (af_heart).

Tighter re-cut of the original five VO lines: ~56 spoken words so the whole
narration fits ~22s, leaving room for scene beats inside a 30s timeline.
Scene boundaries will flex to these WAV durations afterwards.
"""
import os
import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

MODELS = os.path.expanduser("~/.cache/hyperframes/tts/models")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "composition", "assets")

LINES = {
    "vo1": "Imagine trusting a human to catch a system failure before it happens. Absolute madness, right?",
    "vo2": "This isn't an animation. It's a living AI digital twin, tracking every byte in real time.",
    "vo3": "While the operator waits for coffee, the twin has already run ten thousand failure simulations.",
    "vo4": "Failure predicted forty-two minutes before any alarm. That's predictive AI orchestration.",
    "vo5": "Now... let's build it.",
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
