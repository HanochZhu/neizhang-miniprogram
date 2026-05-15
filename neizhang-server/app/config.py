import secrets

try:
    from pydantic_settings import BaseSettings
except ImportError:
    BaseSettings = object  # fallback if not installed


class Settings(BaseSettings):
    deepseek_base_url: str = "https://api.deepseek.com/anthropic"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"

    jwt_secret: str = secrets.token_hex(32)
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 30

    database_url: str = "sqlite+aiosqlite:///./neizhang.db"

    wechat_app_id: str = "wxa31676d2dc0ca5d3"
    wechat_app_secret: str = "placeholder_wechat_secret"

    upload_dir: str = "uploads"

    # 为 true 时在服务端日志打印对话 ReAct 循环（迭代、工具名与入参摘要等）
    chat_trace: bool = False

    if BaseSettings is not object:
        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"


settings = Settings()
