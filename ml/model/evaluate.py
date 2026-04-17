import torch
import numpy as np
import os
import matplotlib.pyplot as plt
from sklearn.metrics import precision_recall_curve, f1_score, confusion_matrix
from dataset import create_dataloaders
from transformer import SpotInterruptionPredictor

def evaluate_thresholds():
    """
    Evaluates the trained transformer over the validation dataset to find
    the optimal probability threshold (for triggering spot interference warnings).
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    features_csv = os.path.join(base_dir, "../data/features.csv")
    model_path = os.path.join(base_dir, "spot_transformer.pt")

    if not os.path.exists(model_path):
        print(f"Error: Model missing at {model_path}. Train the model first.")
        return

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print("Loading datasets and model for Evaluation...")

    _, val_loader, num_features = create_dataloaders(
        csv_path=features_csv,
        batch_size=64,
        train_split=0.8
    )

    model = SpotInterruptionPredictor(num_features=num_features, d_model=128, nhead=4, num_layers=4)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.to(device)
    model.eval()

    all_preds = []
    all_labels = []

    print("Evaluating validation set...")
    with torch.no_grad():
        for x, y in val_loader:
            x = x.to(device)
            # Logits to Sigmoid for probabilities
            logits = model(x)
            probs = torch.sigmoid(logits).cpu().numpy().flatten()
            
            all_preds.extend(probs)
            all_labels.extend(y.numpy().flatten())

    all_preds = np.array(all_preds)
    all_labels = np.array(all_labels)

    # Calculate Precision-Recall curve
    precisions, recalls, thresholds = precision_recall_curve(all_labels, all_preds)
    
    # We want to find the threshold with the max F1 Score (Harmonic mean of precision & recall)
    # Note: threshold array is len(precisions)-1
    f1_scores = 2 * (precisions[:-1] * recalls[:-1]) / (precisions[:-1] + recalls[:-1] + 1e-10)
    best_index = np.argmax(f1_scores)
    
    best_threshold = thresholds[best_index]
    best_f1 = f1_scores[best_index]
    
    print("\n" + "="*40)
    print("Threshold Tuning Results:")
    print("="*40)
    print(f"Total Validation Samples: {len(all_labels)}")
    print(f"Total Interruption Events (1s) in Val: {np.sum(all_labels)}")
    print(f"Optimal Probability Threshold: {best_threshold:.4f}")
    print(f"Resulting F1-Score: {best_f1:.4f}")
    print(f"Precision at optimal: {precisions[best_index]:.4f}")
    print(f"Recall at optimal:    {recalls[best_index]:.4f}")
    
    # Evaluate a confusion matrix using this optimal threshold
    predicted_labels = (all_preds >= best_threshold).astype(int)
    cm = confusion_matrix(all_labels, predicted_labels)
    print("\nConfusion Matrix at optimal threshold:")
    print(f"True Negatives: {cm[0][0]}  | False Positives (False Alarms): {cm[0][1]}")
    print(f"False Negatives (Missed Spikes): {cm[1][0]} | True Positives (Caught Spikes): {cm[1][1]}")
    print("="*40 + "\n")

if __name__ == "__main__":
    evaluate_thresholds()