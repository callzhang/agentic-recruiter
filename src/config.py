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
        
        # Load config.yaml (non-sensitive configuration)
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        # Load secrets.yaml (sensitive data)
        with open(secrets_path, "r", encoding="utf-8") as f:
            secrets = yaml.safe_load(f)
        
        # Build settings data
        boss = config["boss_zhipin"]
        service = config["service"]
        browser = config["browser"]
        config_zilliz = config["zilliz"]
        config_openai = config["openai"]
        
        secrets_zilliz = secrets["zilliz"]
        secrets_openai = secrets["openai"]
        dingtalk = secrets["dingtalk"]
        sentry = secrets["sentry"]
        
        settings_data = {
            # Boss Zhipin URLs
            "BASE_URL": boss["base_url"],
            "CHAT_URL": boss["chat_url"],
            "RECOMMEND_URL": boss["recommend_url"],
            "LOGIN_URL": boss["login_url"],
            
            # Service Configuration
            "BOSS_SERVICE_HOST": service["host"],
            "BOSS_SERVICE_PORT": service["port"],
            "BOSS_SERVICE_BASE_URL": service["base_url"],
            "BOSS_CRITERIA_PATH": service["criteria_path"],
            
            # Browser Configuration
            "STORAGE_STATE": browser["storage_state"],
            "CDP_URL": browser["cdp_url"],
            
            # Zilliz Configuration
            "ZILLIZ_ENDPOINT": secrets_zilliz["endpoint"],
            "ZILLIZ_USER": secrets_zilliz["user"],
            "ZILLIZ_PASSWORD": secrets_zilliz["password"],
            "ZILLIZ_COLLECTION_NAME": config_zilliz["collection_name"],
            "ZILLIZ_EMBEDDING_MODEL": config_zilliz["embedding_model"],
            "ZILLIZ_EMBEDDING_DIM": config_zilliz["embedding_dim"],
            "ZILLIZ_SIMILARITY_TOP_K": config_zilliz["similarity_top_k"],
            "ZILLIZ_ENABLE_CACHE": config_zilliz["enable_cache"],
            
            # OpenAI Configuration
            "OPENAI_API_KEY": secrets_openai["api_key"],
            "OPENAI_NAME": config_openai["name"],
            "OPENAI_MODEL": config_openai["model"],
            "OPENAI_TEMPERATURE": config_openai["temperature"],
            "OPENAI_MAX_TOKENS": config_openai["max_tokens"],
            
            # DingTalk Configuration
            "DINGTALK_URL": dingtalk["url"],
            "DINGTALK_SECRET": dingtalk["secret"],
            
            # Sentry Configuration
            "SENTRY_DSN": sentry["dsn"],
            "SENTRY_ENVIRONMENT": sentry["environment"],
            "SENTRY_RELEASE": sentry["release"],
            
            # Store original YAML data
            "SECRETS": secrets,
            "CONFIG": config,
        }
        
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
