from pydantic import BaseModel
import os

class Settings(BaseModel):
    BASE_URL: str = os.getenv("BASE_URL", "https://www.zhipin.com/")
    CHAT_URL: str = os.getenv("CHAT_URL", "https://www.zhipin.com/web/chat/index")
    RECOMMEND_URL: str = os.getenv("RECOMMEND_URL", "https://www.zhipin.com/web/chat/recommend")
    LOGIN_URL: str = os.getenv("LOGIN_URL", "https://www.zhipin.com/web/user")
    STORAGE_STATE: str = os.getenv("STORAGE_STATE", "data/state.json")
    CDP_URL: str = os.getenv("CDP_URL", "http://127.0.0.1:9222")

settings = Settings()

