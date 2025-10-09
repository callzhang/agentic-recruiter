from pydantic import BaseModel
import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any

class Settings(BaseModel):
    # Boss Zhipin URLs (from jobs.yaml)
    BASE_URL: str = "https://www.zhipin.com/web/chat"
    CHAT_URL: str = "https://www.zhipin.com/web/chat/index"
    RECOMMEND_URL: str = "https://www.zhipin.com/web/chat/recommend"
    LOGIN_URL: str = "https://www.zhipin.com/web/user"
    STORAGE_STATE: str = "data/state.json"
    CDP_URL: str = "http://127.0.0.1:9222"
    
    # Zilliz Configuration (from secrets.yaml - sensitive data)
    ZILLIZ_ENDPOINT: str = ""
    ZILLIZ_USER: str = ""
    ZILLIZ_PASSWORD: str = ""
    ZILLIZ_COLLECTION_NAME: str = "CN_candidates"
    ZILLIZ_EMBEDDING_MODEL: str = "text-embedding-3-small"
    ZILLIZ_EMBEDDING_DIM: int = 1536
    ZILLIZ_SIMILARITY_TOP_K: int = 5
    ZILLIZ_ENABLE_CACHE: bool = False
    
    # OpenAI Configuration (from secrets.yaml - sensitive data)
    OPENAI_API_KEY: str = ""
    OPENAI_NAME: str = "CN_recruiting_bot"
    
    # DingTalk Configuration (from secrets.yaml - sensitive data)
    DINGTALK_URL: str = ""
    DINGTALK_SECRET: str = ""
    
    # Service Configuration (from jobs.yaml)
    BOSS_SERVICE_BASE_URL: str = "http://127.0.0.1:5001"
    BOSS_CRITERIA_PATH: str = "config/jobs.yaml"
    
    @classmethod
    def load_from_config(cls, secrets_path: str = "config/secrets.yaml", jobs_path: str = "config/jobs.yaml") -> "Settings":
        """Load settings from secrets.yaml and jobs.yaml files."""
        settings_data = {}
        
        # Load from secrets.yaml if it exists (sensitive data)
        secrets_file = Path(secrets_path)
        if secrets_file.exists():
            with open(secrets_file, "r", encoding="utf-8") as f:
                secrets = yaml.safe_load(f) or {}
            
            # Map secrets.yaml structure to settings
            if "zilliz" in secrets:
                zilliz = secrets["zilliz"]
                settings_data.update({
                    "ZILLIZ_ENDPOINT": zilliz.get("endpoint", ""),
                    "ZILLIZ_USER": zilliz.get("user", ""),
                    "ZILLIZ_PASSWORD": zilliz.get("password", ""),
                    "ZILLIZ_COLLECTION_NAME": zilliz.get("collection_name", "CN_candidates"),
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
        
        # Load from jobs.yaml if it exists (configuration data)
        jobs_file = Path(jobs_path)
        if jobs_file.exists():
            with open(jobs_file, "r", encoding="utf-8") as f:
                jobs = yaml.safe_load(f) or {}
            
            # Map jobs.yaml structure to settings
            if "config" in jobs:
                config = jobs["config"]
                settings_data.update({
                    "BASE_URL": config.get("base_url", "https://www.zhipin.com/"),
                    "CHAT_URL": config.get("chat_url", "https://www.zhipin.com/web/chat/index"),
                    "RECOMMEND_URL": config.get("recommend_url", "https://www.zhipin.com/web/chat/recommend"),
                    "LOGIN_URL": config.get("login_url", "https://www.zhipin.com/web/user"),
                    "STORAGE_STATE": config.get("storage_state", "data/state.json"),
                    "CDP_URL": config.get("cdp_url", "http://127.0.0.1:9222"),
                    "BOSS_SERVICE_BASE_URL": config.get("boss_service_base_url", "http://127.0.0.1:5001"),
                    "BOSS_CRITERIA_PATH": config.get("boss_criteria_path", "config/jobs.yaml"),
                })
                    
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
        }
    
    def get_dingtalk_config(self) -> Dict[str, Any]:
        """Get DingTalk configuration as dictionary."""
        return {
            "url": self.DINGTALK_URL,
            "secret": self.DINGTALK_SECRET,
        }

# Load settings from secrets.yaml and jobs.yaml
settings = Settings.load_from_config()

