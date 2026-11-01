from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class SynthConfig:
    seed: int
    dataset_version: str
    customer_count_convention: str
    household_sample_size: int
    municipality_shares: dict[str, float]
    municipality_shares_source: str
    barangay_weighting: str
    feeders: dict[str, int]
    transformers_total: int
    transformer_sizes_kva: list[float]
    power_factor: float
    transformer_util_normal: list[float]
    transformer_util_stressed: list[float]
    transformer_stressed_share: float
    weekend_factor: float
    holiday_factor: float
    daily_noise_sigma: float
    daily_noise_clip: float
    household_noise_sigma: float
    demand_thresholds: dict[str, float]
    fixed_holidays: list[str]
    holy_week: bool
    years: Optional[list[int]] = None  # None = all anchor years
    municipality_populations: dict[str, int] = field(default_factory=dict)
    barangay_populations: dict[str, dict[str, int]] = field(default_factory=dict)


def load_config(path: Path) -> SynthConfig:
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    names = SynthConfig.__dataclass_fields__
    unknown = set(data) - set(names)
    if unknown:
        raise ValueError(f"Unknown config keys: {sorted(unknown)}")
    return SynthConfig(**data)
