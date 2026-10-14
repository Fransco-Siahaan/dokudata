"""Load TOML configuration shared by the pipeline, training scripts and API."""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("DOKUDATA_CONFIG_DIR", ROOT / "config"))
MODELS_DIR = Path(os.environ.get("DOKUDATA_MODELS_DIR", ROOT / "models"))


@lru_cache
def rules_config() -> dict[str, Any]:
    with open(CONFIG_DIR / "rules.toml", "rb") as f:
        return tomllib.load(f)


def decision_config() -> dict[str, Any]:
    """Decision thresholds: trained values from models/ when present, else the TOML defaults."""
    cfg = dict(rules_config()["decision"])
    trained = MODELS_DIR / "decision.toml"
    if trained.exists():
        with open(trained, "rb") as f:
            cfg.update(tomllib.load(f))
    return cfg
