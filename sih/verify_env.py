#!/usr/bin/env python3
"""Verify that all required Python packages are installed."""

import sys

REQUIRED_PACKAGES = {
    "numpy": "numpy",
    "scipy": "scipy",
    "pandas": "pandas",
    "torch": "torch",
    "xgboost": "xgboost",
    "websockets": "websockets",
    "sklearn": "scikit-learn",
}


def check_dependencies() -> bool:
    all_ok = True
    for label, pip_name in REQUIRED_PACKAGES.items():
        try:
            mod = __import__(label)
            version = getattr(mod, "__version__", "unknown")
            print(f"  ✓ {label:<12} (pip: {pip_name:<14}) — {version}")
        except ImportError:
            print(f"  ✗ {label:<12} (pip: {pip_name:<14}) — NOT INSTALLED")
            all_ok = False
    return all_ok


def main() -> None:
    print(f"Python {sys.version}\n")
    print("Checking required packages:\n")
    ok = check_dependencies()

    print()
    if ok:
        print("All dependencies are installed. ✓")
    else:
        print("Some dependencies are missing. Run:  pip install -r requirements.txt")
        sys.exit(1)


if __name__ == "__main__":
    main()
