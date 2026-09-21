#!/bin/bash
# Train the SIH ML models (anomaly VAE + RUL predictor).
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd):$(pwd)/backend"
export PYTHONIOENCODING=utf-8
echo "Training ML models..."
echo "Training Anomaly VAE..."
python3 -m fusion_ml.anomaly_vae train
echo "Training RUL Predictor..."
python3 -m fusion_ml.rul_predictor train
echo "Training complete."
