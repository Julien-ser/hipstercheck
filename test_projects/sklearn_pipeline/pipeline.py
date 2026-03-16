#!/usr/bin/env python3
"""
scikit-learn pipeline with intentional issues.
Issues: data leakage, missing train/test split, no cross-validation, improper metrics
"""

import numpy as np
import pandas as pd
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score
from sklearn.pipeline import Pipeline


def load_and_process_data():
    """Create synthetic data with known issues."""
    X, y = make_classification(
        n_samples=1000, n_features=20, n_informative=15, n_redundant=5, random_state=42
    )

    # Bug 1: No train/test split - evaluating on training data
    # Bug 2: Data leakage - scaler fit on entire dataset
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)  # Leakage

    return X_scaled, y


def build_and_train_model():
    X, y = load_and_process_data()

    # No train/test split - uses same data for train and test
    X_train = X  # Should be split
    y_train = y

    # Missing cross-validation
    model = Pipeline(
        [
            ("scaler", StandardScaler()),  # Bug: redundant, already scaled
            ("classifier", LogisticRegression(max_iter=100)),
        ]
    )

    # Train on entire dataset
    model.fit(X_train, y_train)

    # Evaluate on same training data - overly optimistic
    predictions = model.predict(X_train)
    acc = accuracy_score(y_train, predictions)

    print(f"Training Accuracy: {acc:.4f}")  # Misleading

    # No proper testing, no confusion matrix, no ROC-AUC for binary classification
    # Missing feature importance analysis

    return model


def predict_without_calibration(model, X):
    """Using model without checking probability calibration."""
    # For logistic regression, this is usually fine, but no calibration check
    return model.predict(X)


if __name__ == "__main__":
    model = build_and_train_model()
    print("Model trained (with data leakage)")
