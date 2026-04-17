import torch
import torch.nn as nn
import math

class PositionalEncoding(nn.Module):
    """
    Injects some information about the relative or absolute position of the 
    tokens in the sequence. The positional encodings have the same dimension 
    as the embeddings, so that the two can be summed.
    """
    def __init__(self, d_model: int, max_len: int = 5000):
        super().__init__()
        position = torch.arange(max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2) * (-math.log(10000.0) / d_model))
        pe = torch.zeros(max_len, 1, d_model)
        pe[:, 0, 0::2] = torch.sin(position * div_term)
        pe[:, 0, 1::2] = torch.cos(position * div_term)
        self.register_buffer('pe', pe)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Arguments:
            x: Tensor, shape ``[seq_len, batch_size, embedding_dim]``
        """
        x = x + self.pe[:x.size(0)]
        return x

class SpotInterruptionPredictor(nn.Module):
    """
    Transformer-based model for time-series forecasting of Spot interruptions.
    Takes a window of historical features and predicts the probability of an
    interruption occurring in the next prediction horizon.
    """
    def __init__(self, num_features: int, d_model: int = 128, nhead: int = 4, num_layers: int = 4, dropout: float = 0.1):
        super().__init__()
        
        # 1. Feature Projection: maps the raw number of features up to d_model
        self.input_projection = nn.Linear(num_features, d_model)
        
        # 2. Positional Encoding: informs the transformer of sequence order
        self.pos_encoder = PositionalEncoding(d_model)
        
        # 3. Transformer Encoder
        encoder_layers = nn.TransformerEncoderLayer(
            d_model=d_model, 
            nhead=nhead, 
            dim_feedforward=d_model * 4, 
            dropout=dropout,
            batch_first=True # We will feed data as [batch, seq, features]
        )
        self.transformer_encoder = nn.TransformerEncoder(encoder_layers, num_layers)
        
        # 4. Classification Head: map back down to a single probability (0 to 1)
        self.head = nn.Sequential(
            nn.Linear(d_model, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, 1)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: Tensor, shape [batch_size, seq_len, num_features]
        Returns:
            probability of interruption: shape [batch_size, 1]
        """
        # Project features
        x = self.input_projection(x)
        
        # Transform requires [seq_len, batch, features] if batch_first=False
        # But we set batch_first=True, so leave as [batch, seq, features]
        
        # We still need to swap dimensions for our specific positional encoding
        # which expects [seq_len, batch, features]
        x = x.transpose(0, 1) 
        x = self.pos_encoder(x)
        x = x.transpose(0, 1)
        
        # Pass through transformer blocks
        x = self.transformer_encoder(x)
        
        # Global Average Pooling (average across the time sequence dimension)
        # x is [batch_size, seq_len, d_model] -> pooled is [batch_size, d_model]
        pooled = x.mean(dim=1)
        
        # Output raw logits (Sigmoid is applied later in the loss function)
        logits = self.head(pooled)
        return logits
