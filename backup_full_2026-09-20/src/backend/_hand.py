"""Test the hand control and tooltip coverage headlessly, without a camera.

Serves a copy of index.html with the hand test (_hand.js) spliced into it and
prints the log the page reports back.  The camera is driven to failure on
purpose: headless Chrome never settles a real camera prompt, and the page has
to survive that with its UI intact.

Usage:  python _hand.py
"""
import _harness as H


if __name__ == "__main__":
    H.run_test("hand", "_hand.js", budget=30000, shot="_h.png")
