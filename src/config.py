from pydantic import BaseModel
import yaml
from pathlib import Path
from typing import Dict, Any

class Settings(BaseModel):
    """Application settings loaded from config.yaml and secrets.yaml"""
    
    # Boss Zhipin URLs
    BASE_URL: str = ""
    CHAT_URL: str = ""
    RECOMMEND_URL: str = ""
    LOGIN_URL: str = ""
    
    # Browser Configuration
    STORAGE_STATE: str = ""
    CDP_URL: str = ""
    
    # Service Configuration
    BOSS_SERVICE_HOST: str = ""
    BOSS_SERVICE_PORT: int = 5001
    BOSS_SERVICE_BASE_URL: str = ""
    BOSS_CRITERIA_PATH: str = ""
    
    # Zilliz Configuration
    ZILLIZ_ENDPOINT: str = ""
    ZILLIZ_USER: str = ""
    ZILLIZ_PASSWORD: str = ""
    ZILLIZ_COLLECTION_NAME: str = ""
    ZILLIZ_EMBEDDING_MODEL: str = ""
    ZILLIZ_EMBEDDING_DIM: int = 1536
    ZILLIZ_SIMILARITY_TOP_K: int = 5
    ZILLIZ_ENABLE_CACHE: bool = False
    
    # OpenAI Configuration
    OPENAI_API_KEY: str = ""
    OPENAI_NAME: str = ""
    OPENAI_MODEL: str = ""
    OPENAI_TEMPERATURE: float = 0.7
    OPENAI_MAX_TOKENS: int = 2000
    
    # DingTalk Configuration
    DINGTALK_URL: str = ""
    DINGTALK_SECRET: str = ""
    
    # Sentry Configuration
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = ""
    SENTRY_RELEASE: str = ""
    
    # Store original YAML data for nested access
    SECRETS: Dict[str, Any] = {}
    CONFIG: Dict[str, Any] = {}
    
    @classmethod
    def load_from_config(
        cls, 
        config_path: str = "config/config.yaml",
        secrets_path: str = "config/secrets.yaml"
    ) -> "Settings":
        """Load settings from config.yaml and secrets.yaml files."""
        settings_data = {}
        
        # Load from config.yaml (non-sensitive configuration)
        config_file = Path(config_path)
        config = {}
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            
            # Boss Zhipin URLs
            if "boss_zhipin" in config:
                boss = config["boss_zhipin"]
                settings_data.update({
                    "BASE_URL": boss.get("base_url", ""),
                    "CHAT_URL": boss.get("chat_url", ""),
                    "RECOMMEND_URL": boss.get("recommend_url", ""),
                    "LOGIN_URL": boss.get("login_url", ""),
                })
            
            # Service Configuration
            if "service" in config:
                service = config["service"]
                settings_data.update({
                    "BOSS_SERVICE_HOST": service.get("host", "127.0.0.1"),
                    "BOSS_SERVICE_PORT": service.get("port", 5001),
                    "BOSS_SERVICE_BASE_URL": service.get("base_url", ""),
                    "BOSS_CRITERIA_PATH": service.get("criteria_path", ""),
                })
            
            # Browser Configuration
            if "browser" in config:
                browser = config["browser"]
                settings_data.update({
                    "STORAGE_STATE": browser.get("storage_state", ""),
                    "CDP_URL": browser.get("cdp_url", ""),
                })
            
            # Zilliz Configuration (non-sensitive)
            if "zilliz" in config:
                zilliz = config["zilliz"]
                settings_data.update({
                    "ZILLIZ_COLLECTION_NAME": zilliz.get("collection_name", "CN_candidates"),
                    "ZILLIZ_EMBEDDING_MODEL": zilliz.get("embedding_model", "text-embedding-3-small"),
                    "ZILLIZ_EMBEDDING_DIM": zilliz.get("embedding_dim", 1536),
                    "ZILLIZ_SIMILARITY_TOP_K": zilliz.get("similarity_top_k", 5),
                    "ZILLIZ_ENABLE_CACHE": zilliz.get("enable_cache", False),
                })
            
            # OpenAI Configuration (non-sensitive)
            if "openai" in config:
                openai = config["openai"]
                settings_data.update({
                    "OPENAI_NAME": openai.get("name", "CN_recruiting_bot"),
                    "OPENAI_MODEL": openai.get("model", "gpt-4o-mini"),
                    "OPENAI_TEMPERATURE": openai.get("temperature", 0.7),
                    "OPENAI_MAX_TOKENS": openai.get("max_tokens", 2000),
                })
        
        # Load from secrets.yaml (sensitive data)
        secrets_file = Path(secrets_path)
        secrets = {}
        if secrets_file.exists():
            with open(secrets_file, "r", encoding="utf-8") as f:
                secrets = yaml.safe_load(f) or {}
            
            # Zilliz sensitive data
            if "zilliz" in secrets:
                zilliz = secrets["zilliz"]
                settings_data.update({
                    "ZILLIZ_ENDPOINT": zilliz.get("endpoint", ""),
                    "ZILLIZ_USER": zilliz.get("user", ""),
                    "ZILLIZ_PASSWORD": zilliz.get("password", ""),
                })
                # Override collection_name if specified in secrets
                if "collection_name" in zilliz:
                    settings_data["ZILLIZ_COLLECTION_NAME"] = zilliz["collection_name"]
            
            # OpenAI sensitive data
            if "openai" in secrets:
                openai = secrets["openai"]
                settings_data.update({
                    "OPENAI_API_KEY": openai.get("api_key", ""),
                })
            
            # DingTalk Configuration
            if "dingtalk" in secrets:
                dingtalk = secrets["dingtalk"]
                settings_data.update({
                    "DINGTALK_URL": dingtalk.get("url", ""),
                    "DINGTALK_SECRET": dingtalk.get("secret", ""),
                })
            
            # Sentry Configuration
            if "sentry" in secrets:
                sentry = secrets["sentry"]
                settings_data.update({
                    "SENTRY_DSN": sentry.get("dsn", ""),
                    "SENTRY_ENVIRONMENT": sentry.get("environment", ""),
                    "SENTRY_RELEASE": sentry.get("release", ""),
                })
        
        # Store original YAML data
        settings_data["SECRETS"] = secrets
        settings_data["CONFIG"] = config
        
        # Create settings instance with loaded data
        return cls(**settings_data)
    
    def get_zilliz_config(self) -> Dict[str, Any]:
        """Get Zilliz configuration as dictionary."""
        return {
            "endpoint": self.ZILLIZ_ENDPOINT,
            "user": self.ZILLIZ_USER,
            "password": self.ZILLIZ_PASSWORD,
            "collection_name": self.ZILLIZ_COLLECTION_NAME,
            "embedding_model": self.ZILLIZ_EMBEDDING_MODEL,
            "embedding_dim": self.ZILLIZ_EMBEDDING_DIM,
            "similarity_top_k": self.ZILLIZ_SIMILARITY_TOP_K,
            "enable_cache": self.ZILLIZ_ENABLE_CACHE,
        }
    
    def get_openai_config(self) -> Dict[str, Any]:
        """Get OpenAI configuration as dictionary."""
        return {
            "api_key": self.OPENAI_API_KEY,
            "name": self.OPENAI_NAME,
            "model": self.OPENAI_MODEL,
            "temperature": self.OPENAI_TEMPERATURE,
            "max_tokens": self.OPENAI_MAX_TOKENS,
        }
    
    def get_dingtalk_config(self) -> Dict[str, Any]:
        """Get DingTalk configuration as dictionary."""
        return {
            "url": self.DINGTALK_URL,
            "secret": self.DINGTALK_SECRET,
        }
    
    def get_sentry_config(self) -> Dict[str, Any]:
        """Get Sentry configuration as dictionary."""
        return {
            "dsn": self.SENTRY_DSN,
            "environment": self.SENTRY_ENVIRONMENT,
            "release": self.SENTRY_RELEASE,
        }

# Load settings from config.yaml and secrets.yaml
settings = Settings.load_from_config()
