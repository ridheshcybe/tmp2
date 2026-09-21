"""Render index.html headlessly and measure the frame.

Usage:  python _probe.py <out.png> [old|||new ...]

A patch is OLD|||NEW text applied to the source with src.replace(OLD, NEW),
so a variant can be A/B'd without touching index.html.  Math.random is
seeded and the animation clock is frozen, so two runs differ only where the
edit under test changed something.

The 3D engine itself is index.html; this only drives and measures it.
"""
import os
import sys

import numpy as np
from PIL import Image

import _harness as H


def measure(out):
    """Print brightness, colour and detail statistics for the frame."""
    pixels = np.asarray(Image.open(out).convert("RGB")).astype(float)

    # Crop away the left hand UI column: that is page chrome, not engine.
    sub = pixels[:, 380:, :]
    grey = sub.mean(2)
    red, blue = sub[:, :, 0], sub[:, :, 2]

    print("  mean %.1f | p10/50/90 %.0f/%.0f/%.0f | amber %.4f | white %.4f | "
          "shoulder %.4f | detail %.2f/%.2f" % (
              grey.mean(), *np.percentile(grey, [10, 50, 90]),
              ((red - blue > 50) & (red > 110)).mean(),
              (sub > 245).all(2).mean(),
              ((grey > 200) & (grey <= 245)).mean(),
              np.abs(np.diff(grey, axis=0)).mean(),
              np.abs(np.diff(grey, axis=1)).mean()))


def build(out, patches):
    src = H.index_html()

    for patch in patches:
        old, new = patch.split("|||", 1)
        assert old in src, "patch target not found: " + old[:60]
        src = src.replace(old, new)

    # core.js seeds Math.random, and the scene draws on it while it is being
    # constructed, so this splice has to land ahead of the scene.
    src = H.splice(src, H.SCENE, H.js("core.js"), after=False)

    # Freeze the animation clock.  Two runs otherwise differ by whatever the
    # crank happened to be at and by a frame or two of flame jitter, which
    # puts a ~1.5% noise floor under every A/B diff.
    if H.DELTA not in src:
        raise SystemExit("index.html no longer contains %r, so _probe cannot "
                         "freeze the clock" % H.DELTA)
    src = src.replace(H.DELTA, "const delta = 0;", 1)

    # Report what was actually built, once the model has settled.
    src = H.splice(src, H.ANIMATE, H.js("_diag.js"))

    with H.serve_page(src, "probe") as url:
        stderr = H.run_chrome(url, shot=out, budget=12000)

    for line in H.raw_lines(stderr, "DIAG", "Uncaught", "ERROR:CONSOLE"):
        print("  " + line)

    if not os.path.exists(out):
        raise SystemExit("Chrome wrote no screenshot to " + out)

    measure(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(sys.argv[1] + ":")
    build(sys.argv[1], sys.argv[2:])
