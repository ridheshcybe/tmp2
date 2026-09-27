"""Interaction test: does clicking and switching anything actually work?

Serves a copy of index.html with the scan test (_scan.js) spliced into it,
dispatches real pointer events at the canvas and prints the log the page
reports back.

Usage:  python _scan.py
"""
import _harness as H


if __name__ == "__main__":
    H.run_test("scan", "_scan.js", budget=20000, shot="_i.png")
