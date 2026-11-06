"""Loads config/ (policy + source definitions) and <data dir>/roles.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    return Path(os.environ.get("JFDC_CONFIG_DIR", REPO_ROOT / "config"))


@dataclass
class Config:
    policy: dict[str, Any]
    sources: dict[str, dict[str, Any]]
    roles: dict[str, list[str]] = field(default_factory=dict)

    def scope_for_fy(self, fy: int) -> dict[str, list[str]]:
        scope = self.policy.get("scope", {}).get(fy)
        if scope is None:
            raise KeyError(
                f"No in-scope Engage processes configured for FY{fy}. Add `scope: {fy}:` to config/policy.yaml."
            )
        return scope


def load_config(data_dir: Path | None = None) -> Config:
    cdir = config_dir()
    policy = yaml.safe_load((cdir / "policy.yaml").read_text())
    sources = {}
    for p in sorted((cdir / "sources").glob("*.yaml")):
        spec = yaml.safe_load(p.read_text())
        sources[spec["key"]] = spec
    roles: dict[str, list[str]] = {}
    if data_dir is not None and (data_dir / "roles.yaml").exists():
        raw = yaml.safe_load((data_dir / "roles.yaml").read_text()) or {}
        roles = {k: [e.strip().lower() for e in (v or [])] for k, v in raw.items()}
    return Config(policy=policy, sources=sources, roles=roles)
