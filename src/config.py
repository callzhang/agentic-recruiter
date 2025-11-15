"""Configuration management - loads from config.yaml and secrets.yaml"""
import yaml
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any


with open("config/config.yaml", "r", encoding="utf-8") as f:
    _config_values = yaml.safe_load(f)


with open("config/secrets.yaml", "r", encoding="utf-8") as f:
    _secrets_values = yaml.safe_load(f)


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
    return _secrets_values["dingtalk"]


def get_sentry_config() -> Dict[str, Any]:
    """Get Sentry configuration."""
    return _secrets_values["sentry"]
