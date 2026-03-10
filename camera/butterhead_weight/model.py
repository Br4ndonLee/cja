from __future__ import annotations

from pathlib import Path

import torch
from torch import nn
from torchvision.models import EfficientNet_B0_Weights, efficientnet_b0

from .features import MODEL_FEATURE_NAMES

EXTRA_FEATURE_DIM = len(MODEL_FEATURE_NAMES)


class EfficientNetB0Regressor(nn.Module):
    def __init__(self, pretrained: bool = True, extra_feature_dim: int = EXTRA_FEATURE_DIM) -> None:
        super().__init__()
        weights = EfficientNet_B0_Weights.DEFAULT if pretrained else None
        backbone = efficientnet_b0(weights=weights)
        in_features = backbone.classifier[1].in_features
        backbone.classifier = nn.Identity()

        self.backbone = backbone
        self.feature_encoder = nn.Sequential(
            nn.Linear(extra_feature_dim, 16),
            nn.ReLU(inplace=True),
            nn.Linear(16, 16),
            nn.ReLU(inplace=True),
        )
        self.regressor = nn.Sequential(
            nn.Dropout(p=0.2),
            nn.Linear(in_features + 16, 128),
            nn.SiLU(inplace=True),
            nn.Dropout(p=0.15),
            nn.Linear(128, 1),
        )

    def forward(self, images: torch.Tensor, extra_features: torch.Tensor) -> torch.Tensor:
        image_embedding = self.backbone(images)
        feature_embedding = self.feature_encoder(extra_features)
        joined = torch.cat([image_embedding, feature_embedding], dim=1)
        return self.regressor(joined).squeeze(1)


def save_checkpoint(model: nn.Module, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), output_path)


def load_checkpoint(model: nn.Module, checkpoint_path: Path, device: torch.device) -> nn.Module:
    state = torch.load(checkpoint_path, map_location=device)
    model.load_state_dict(state)
    return model
