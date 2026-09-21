# ============================================================
# SIH Simulator Trainer Module
# Handles model training and artifact generation.
# ============================================================

import numpy as np
import os
from sklearn.model_selection import train_test_split
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

MODEL_PATH = "model_artifacts/sim_model.pkl"

def load_data():
    """Simulates loading large training datasets."""
    print("[TRAINER] Simulating loading vast datasets...")
    # Simulate X (features) and y (labels)
    X = np.random.rand(1000, 5) * 10
    y = (X[:, 0] * 2 + X[:, 2] - 5).flatten() + np.random.randn(1000) * 0.5
    return X, y

def train_model(X, y):
    """Trains the model and returns the fitted model."""
    print("[TRAINER] Standardizing features...")
    X_scaled = StandardScaler().fit_transform(X)

    print("[TRAINER] Training Ridge Regression model...")
    model = Ridge(alpha=1.0)
    model.fit(X_scaled, y)
    return model

def save_model(model):
    """Saves the trained model artifact to disk."""
    if not os.path.exists("model_artifacts"):
        os.makedirs("model_artifacts")
    
    import pickle
    with open(f"{MODEL_PATH}", 'wb') as f:
        pickle.dump(model, f)
    print(f"[TRAINER] Model successfully saved to {MODEL_PATH}")
    return MODEL_PATH

def run_training_workflow():
    """Main function to execute the full training workflow."""
    print("====================================================")
    print("  [START] Running Simulator Training Workflow")
    print("====================================================")
    
    X, y = load_data()
    trained_model = train_model(X, y)
    save_model(trained_model)
    print("[SUCCESS] Training workflow completed.")

if __name__ == "__main__":
    # Ensure all dependencies are installed (pip install scikit-learn numpy)
    run_training_workflow()
