/*
 * =============================================================
 * Merged Main Application Entry Point
 * =============================================================
 * This file now orchestrates calls to the merged frontend modules,
 * fulfilling the role of the primary initialization script.
 */

import { initializeSystem, displayCoreData } from './src/core.js';
import { processScanData } from './src/_scan.js';
import { runDiagnostics } from './src/_diag.js';

// Global setup on load
window.onload = () => {
    // 1. Initialize Core System
    initializeSystem();
    
    // 2. Run initial scan data visualization (dummy data for now)
    processScanData([10, 20, 30]);

    // 3. Run initial diagnostics check
    // runDiagnostics(); // Run manually or via button click
};

// Expose functions globally for inline HTML button clicks
window.initializeSystem = initializeSystem;
window.processScanData = processScanData;
window.runDiagnostics = runDiagnostics;
