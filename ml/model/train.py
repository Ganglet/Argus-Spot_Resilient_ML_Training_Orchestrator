import torch
import torch.nn as nn
import torch.optim as optim
import os
from dataset import create_dataloaders
from transformer import SpotInterruptionPredictor

class FocalLoss(nn.Module):
    """
    Spot interruptions are rare. If we use standard BCE loss, the model will 
    just output 0 (no interruption) every time and achieve 99% accuracy.
    Focal loss forces the model to heavily penalize missing the rare disruptions.
    """
    def __init__(self, alpha=1.0, gamma=2.0):
        super(FocalLoss, self).__init__()
        self.alpha = alpha
        self.gamma = gamma
        self.bce_logit_loss = nn.BCEWithLogitsLoss(reduction='none')

    def forward(self, inputs, targets):
        bce_loss = self.bce_logit_loss(inputs, targets)
        pt = torch.exp(-bce_loss)  # probability of the correct class
        focal_loss = self.alpha * (1 - pt) ** self.gamma * bce_loss
        return focal_loss.mean()

def train_model():
    """
    Executes a local training run of the Spot Predictor on the downloaded AWS data.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    features_csv = os.path.join(base_dir, "../data/features.csv")
    
    if not os.path.exists(features_csv):
        print(f"Error: {features_csv} not found. Run dataset generation first.")
        return

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Executing Training Loop on {device}... This might take a bit.")

    # 1. Build DataLoader
    train_loader, val_loader, input_features = create_dataloaders(
        csv_path=features_csv,
        batch_size=64,
        train_split=0.8
    )

    # 2. Define Model (from transformer.py)
    model = SpotInterruptionPredictor(num_features=input_features, d_model=128, nhead=4, num_layers=4)
    model.to(device)

    # 3. Handle Imbalance with Focal Loss
    criterion = FocalLoss(alpha=0.75, gamma=2.0)
    optimizer = optim.AdamW(model.parameters(), lr=0.001)

    # 4. Training Loop (First Run - Verify Loss Decreasing)
    epochs = 3  # Keep it small just for verifying loss drops
    
    for epoch in range(epochs):
        model.train()
        running_loss = 0.0
        
        for batch_idx, (x, y) in enumerate(train_loader):
            x, y = x.to(device), y.to(device)

            optimizer.zero_grad()

            raw_logits = model(x)
            loss = criterion(raw_logits, y)

            loss.backward()
            optimizer.step()

            running_loss += loss.item()
            
            if batch_idx % 200 == 0:
                print(f"Epoch {epoch+1}/{epochs} | Batch {batch_idx}/{len(train_loader)} | Loss: {loss.item():.4f}")

        avg_loss = running_loss / len(train_loader)
        print(f"==> Epoch {epoch+1} Complete. Average Training Loss: {avg_loss:.4f}\n")
    
    # 5. Save Checkpoint
    checkpoint_path = os.path.join(base_dir, "spot_transformer.pt")
    torch.save(model.state_dict(), checkpoint_path)
    print(f"Model saved to {checkpoint_path}")

if __name__ == "__main__":
    train_model()