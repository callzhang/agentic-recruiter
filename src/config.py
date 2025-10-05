from pydantic import BaseModel
import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any

class Settings(BaseModel):
    # Boss Zhipin URLs
    BASE_URL: str = os.getenv("BASE_URL", "https://www.zhipin.com/")
    CHAT_URL: str = os.getenv("CHAT_URL", "https://www.zhipin.com/web/chat/index")
    RECOMMEND_URL: str = os.getenv("RECOMMEND_URL", "https://www.zhipin.com/web/chat/recommend")
    LOGIN_URL: str = os.getenv("LOGIN_URL", "https://www.zhipin.com/web/user")
    STORAGE_STATE: str = os.getenv("STORAGE_STATE", "data/state.json")
    CDP_URL: str = os.getenv("CDP_URL", "http://127.0.0.1:9222")
    
    # Zilliz Configuration
    ZILLIZ_ENDPOINT: str = os.getenv("ZILLIZ_ENDPOINT", "")
    ZILLIZ_USER: str = os.getenv("ZILLIZ_USER", "")
    ZILLIZ_PASSWORD: str = os.getenv("ZILLIZ_PASSWORD", "")
    ZILLIZ_COLLECTION_NAME: str = os.getenv("ZILLIZ_COLLECTION_NAME", "CN_recruitment")
    ZILLIZ_EMBEDDING_MODEL: str = os.getenv("ZILLIZ_EMBEDDING_MODEL", "text-embedding-3-small")
    ZILLIZ_EMBEDDING_DIM: int = int(os.getenv("ZILLIZ_EMBEDDING_DIM", "1536"))
    ZILLIZ_SIMILARITY_TOP_K: int = int(os.getenv("ZILLIZ_SIMILARITY_TOP_K", "5"))
    ZILLIZ_ENABLE_CACHE: bool = os.getenv("ZILLIZ_ENABLE_CACHE", "false").lower() == "true"
    
    # OpenAI Configuration
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_NAME: str = os.getenv("OPENAI_NAME", "CN_recruiting_bot")
    
    # DingTalk Configuration
    DINGTALK_URL: str = os.getenv("DINGTALK_URL", "")
    DINGTALK_SECRET: str = os.getenv("DINGTALK_SECRET", "")
    
    # Service Configuration
    BOSS_SERVICE_BASE_URL: str = os.getenv("BOSS_SERVICE_BASE_URL", "http://127.0.0.1:5001")
    BOSS_CRITERIA_PATH: str = os.getenv("BOSS_CRITERIA_PATH", "config/jobs.yaml")
    
    @classmethod
    def load_from_secrets(cls, secrets_path: str = "config/secrets.yaml") -> "Settings":
        """Load settings from secrets.yaml file."""
        settings_data = {}
        
        # Load from secrets.yaml if it exists
        secrets_file = Path(secrets_path)
        if secrets_file.exists():
            try:
                with open(secrets_file, "r", encoding="utf-8") as f:
                    secrets = yaml.safe_load(f) or {}
                
                # Map secrets.yaml structure to environment variables
                if "zilliz" in secrets:
                    zilliz = secrets["zilliz"]
                    settings_data.update({
                        "ZILLIZ_ENDPOINT": zilliz.get("endpoint", ""),
                        "ZILLIZ_USER": zilliz.get("user", ""),
                        "ZILLIZ_PASSWORD": zilliz.get("password", ""),
                        "ZILLIZ_COLLECTION_NAME": zilliz.get("collection_name", "CN_recruitment"),
                        "ZILLIZ_EMBEDDING_MODEL": zilliz.get("embedding_model", "text-embedding-3-small"),
                        "ZILLIZ_EMBEDDING_DIM": zilliz.get("embedding_dim", 1536),
                        "ZILLIZ_SIMILARITY_TOP_K": zilliz.get("similarity_top_k", 5),
                        "ZILLIZ_ENABLE_CACHE": zilliz.get("enable_cache", False),
                    })
                
                if "openai" in secrets:
                    openai = secrets["openai"]
                    settings_data.update({
                        "OPENAI_API_KEY": openai.get("api_key", ""),
                        "OPENAI_NAME": openai.get("name", "CN_recruiting_bot"),
                    })
                
                if "dingtalk" in secrets:
                    dingtalk = secrets["dingtalk"]
                    settings_data.update({
                        "DINGTALK_URL": dingtalk.get("url", ""),
                        "DINGTALK_SECRET": dingtalk.get("secret", ""),
                    })
                    
            except Exception as e:
                print(f"Warning: Failed to load secrets from {secrets_path}: {e}")
        
        # Create settings instance with loaded data
        return cls(**settings_data)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary."""
        return self.dict()
    
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
        }
    
    def get_dingtalk_config(self) -> Dict[str, Any]:
        """Get DingTalk configuration as dictionary."""
        return {
            "url": self.DINGTALK_URL,
            "secret": self.DINGTALK_SECRET,
        }

# Load settings from secrets.yaml
settings = Settings.load_from_secrets()

