# Project Documentation

This directory, `c:\Users\admin\Downloads\tmp`, contains the structured source code and assets for a mechanical/forensic simulation project. The files have been logically reorganized into two main directories to enhance maintainability and clarity.

## 📁 Project Structure Overview

*   **`src/`:** Contains all the functional source code. This folder includes scripts and logic that drive the project.
*   **`assets/`:** Contains all static media and physical models used by the project.
*   **`sih/` (Inside `src/`):** Contains structural or supplemental code/data related to the main source files.

---

## 📚 Directory Details

### 📂 `src/` (Source Code)
This directory houses all the computational logic.
*   **Code Types:** Python (`.py`), JavaScript (`.js`), and HTML (`.html`).
*   **Core Functionality:** Contains scripts for various modules, such as:
    *   `engine.html`: The main user interface or entry point.
    *   `core.js`: Core JavaScript logic.
    *   `_anomaly_forensics.py`: Scripts dedicated to analyzing anomalies.
    *   `_verify_calibration.py`: Scripts for verifying system calibration.
    *   *(...and all other related scripts)*

### 📂 `assets/` (Media & Models)
This directory stores all graphical, visual, and physical model assets.
*   **Image Files:** (`.jpg`, `.png`) - Diagrams, UI backgrounds, and visual components.
*   **3D Models:** (`.stl`) - Physical parts and components used in simulations (e.g., `piston.stl`, `engine_block.stl`).

---

## 🚀 Getting Started

To run the project, please follow these general steps:

1.  **Dependencies:** Check the `src/` directory for any dependency requirements (e.g., listed in a `requirements.txt` or `package.json`).
2.  **Execution:** Execute the main entry point, typically found in `src/index.html` or running a primary script like `src/core.js` via a local web server.
3.  **Model Use:** When working with 3D models, ensure the correct assets are referenced in your code paths, pointing to files within the `assets/` folder.

---

## 🚧 Maintenance Notes
*   Always ensure new assets are placed in `assets/` and new code modules are placed in `src/`.
*   The scripts follow a naming convention prefixed with `_` (e.g., `_scan.js`, `_diag.js`) to denote their functional role.
