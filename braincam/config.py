import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # App
    PROJECT_NAME: str = "BrainCam AI"
    APP_ENV: str = "production"
    DEBUG: bool = False
    SECRET_KEY: str = "braincam_ai_super_secret_key_change_me"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./braincam.db"

    # AI (Google Gemini)
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"
    GEMINI_FALLBACK_MODEL: str = "gemini-2.0-flash-lite"

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    DEFAULT_LANGUAGE: str = "ru" # "ru" or "uz"

    # Admin info
    ADMIN_TELEGRAM_USERNAME: str = "abdvoris07"
    ADMIN_TELEGRAM_ID: Optional[int] = None # Will be auto-resolved or saved when admin chats with bot

    # Payment info
    VISA_CARD_NUMBER: str = "4916 9903 6185 3101"
    VISA_CARD_HOLDER: str = "Abduvoris Rahimjonov"
    SUBSCRIPTION_MONTHLY_PRICE: str = "300 000 UZS / 25 USD"
    TRIAL_DAYS: int = 7

    # Server / Web Dashboard
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WEB_BASE_URL: str = "http://localhost:8000"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
