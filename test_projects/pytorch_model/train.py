#!/usr/bin/env python3
"""
PyTorch training script with intentional issues.
Issues: missing random seeds, no validation, data leakage, missing normalization, incorrect metrics
"""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import numpy as np
from sklearn.metrics import accuracy_score
import random

# Missing random seeds - reproducibility issue
# Should have: random.seed(42), np.random.seed(42), torch.manual_seed(42)


class SimpleModel(nn.Module):
    def __init__(self, input_size, hidden_size, output_size):
        super().__init__()
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(hidden_size, output_size)

    def forward(self, x):
        out = self.fc1(x)
        out = self.relu(out)
        out = self.fc2(out)
        return out


# Data leakage: scaling before train/test split
def prepare_data():
    # Simulated data
    X = np.random.randn(1000, 20)
    y = np.random.randint(0, 2, 1000)

    # Bug: fitting scaler on entire dataset before split (data leakage)
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)  # Leakage: uses test data stats

    # No proper train/test split (or using same data for both)
    X_train = X_scaled  # Bug: using all data for training
    X_test = X_scaled  # Bug: test is same as train
    y_train = y
    y_test = y

    return (
        torch.FloatTensor(X_train),
        torch.LongTensor(y_train),
        torch.FloatTensor(X_test),
        torch.LongTensor(y_test),
    )


def train_model():
    # Hyperparameters
    input_size = 20
    hidden_size = 64  # Might be too small/large without justification
    output_size = 2
    learning_rate = 0.1  # Bug: too high, may cause instability
    batch_size = 1024  # Bug: too large, memory issues, poor generalization

    model = SimpleModel(input_size, hidden_size, output_size)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=learning_rate)

    X_train, y_train, X_test, y_test = prepare_data()
    train_dataset = TensorDataset(X_train, y_train)
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)

    # No validation during training
    num_epochs = 50
    for epoch in range(num_epochs):
        model.train()
        for batch_X, batch_y in train_loader:
            optimizer.zero_grad()
            outputs = model(batch_X)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()

        # No validation to check for overfitting
        print(f"Epoch {epoch}, Loss: {loss.item():.4f}")

    # Evaluation on same training data - data leakage
    model.eval()
    with torch.no_grad():
        train_outputs = model(X_train)
        _, predicted = torch.max(train_outputs, 1)
        train_acc = accuracy_score(y_train.numpy(), predicted.numpy())
        print(f"Train Accuracy: {train_acc:.4f}")  # Misleading - same data used

    return model


if __name__ == "__main__":
    model = train_model()
    print("Training complete")
