"""
Advanced anomaly forensic analysis service.
Provides deep analysis on suspicious data patterns.
"""

import numpy as np
import pandas as pd
from typing import Any

def process_anomaly_forensics(payload: Any) -> dict:
    """
    Processes raw payload data to determine anomaly type and severity.
    :param payload: List of tuples (timestamp, value).
    :return: Dictionary detailing the analysis results.
    """
    print("--- Running Anomaly Forensics ---")
    
    if not isinstance(payload, list) or len(payload) < 5:
        return {"status": "error", "message": "Invalid or insufficient data payload (Expected list of tuples)."}

    values = [p[1] for p in payload]
    try:
        std_dev = np.std(values)
        if std_dev > 100:
            return {"status": "alert", "message": "High volatility detected (Severity: Critical)", "metric": "STD_DEV", "value": float(std_dev)}
        else:
            return {"status": "safe", "message": "Nominal data patterns detected.", "metric": "STD_DEV", "value": float(std_dev)}
    except Exception as e:
        return {"status": "error", "message": f"Forensic analysis failed: {str(e)}"}

# The function signature matches the desired call in main.py
process_anomaly_forensics = process_anomaly_forensics
