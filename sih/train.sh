#!/bin/bash
echo "Training ML models..."
echo "Training Anomaly VAE..."
python -m fusion_ml.anomaly_vae train
echo "Training RUL Predictor..."
python -m fusion_ml.rul_predictor train
echo "Training complete."
