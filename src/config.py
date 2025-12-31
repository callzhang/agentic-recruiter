"""Configuration management - loads from config.yaml and secrets.yaml"""
import os
import yaml
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "config.yaml"
_DEFAULT_SECRETS_PATH = _REPO_ROOT / "config" / "secrets.yaml"


def _load_yaml(path: Path, *, label: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {label} at '{path}'. "
            "Run from repo root or set BOSS_CONFIG_YAML / BOSS_SECRETS_YAML env vars."
        )
    with open(path, "r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid YAML for {label} at '{path}': expected a mapping at root.")
    return payload


_config_path = Path(os.getenv("BOSS_CONFIG_YAML", str(_DEFAULT_CONFIG_PATH))).expanduser()
_secrets_path = Path(os.getenv("BOSS_SECRETS_YAML", str(_DEFAULT_SECRETS_PATH))).expanduser()

_config_values = _load_yaml(_config_path, label="config.yaml")
_secrets_values = _load_yaml(_secrets_path, label="secrets.yaml")


def get_boss_zhipin_config() -> Dict[str, str]:
    """Get Boss Zhipin URLs configuration."""
    return _config_values["boss_zhipin"]


def get_service_config() -> Dict[str, Any]:
    """Get service configuration."""
    return _config_values["service"]


def get_browser_config() -> Dict[str, str]:
    """Get browser configuration."""
    return _config_values["browser"]


def get_zilliz_config() -> Dict[str, Any]:
    """Get Zilliz configuration (merges config.yaml and secrets.yaml)."""
    config_zilliz = _config_values["zilliz"]
    secrets_zilliz = _secrets_values["zilliz"]
    return config_zilliz | secrets_zilliz


def get_openai_config() -> Dict[str, Any]:
    """Get OpenAI configuration (merges config.yaml and secrets.yaml)."""
    config_openai = _config_values["openai"]
    secrets_openai = _secrets_values["openai"]
    return config_openai | secrets_openai
    
def get_dingtalk_config() -> Dict[str, str]:
    """Get DingTalk configuration."""
    env_url = os.getenv("DINGTALK_WEBHOOK")
    env_secret = os.getenv("DINGTALK_SECRET")
    if env_url:
        return {"url": env_url, "secret": env_secret or ""}
    return _secrets_values["dingtalk"]

    
def get_sentry_config() -> Dict[str, Any]:
    """Get Sentry configuration."""
    return _secrets_values["sentry"]


def get_vercel_config() -> Dict[str, str]:
    """Get Vercel configuration."""
    return _config_values.get("vercel", {})
