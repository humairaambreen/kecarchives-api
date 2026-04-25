from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


API_DIR = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = API_DIR.parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(WORKSPACE_ROOT / ".env"), str(API_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "KEC Archives API"
    api_port: int = 8000
    database_url: str = f"sqlite:///{(API_DIR / 'dev.db').as_posix()}"

    jwt_secret: str = Field(default="change_me_to_a_long_random_secret", min_length=24)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    email_from: str = "noreply@kecarchives.local"
    email_provider: str = "console"
    cors_origins: list[str] = ["http://localhost:3000"]

    admin_email: str = ""
    admin_password: str = ""
    bypass_otp: str = ""  # Set to a fixed code (e.g. "123456") to skip real OTP emails

    resend_api_key: str = ""
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    # AI — Groq (free, console.groq.com)
    groq_api_key: str = ""

    # AI — HuggingFace (free FLUX.1-schnell, huggingface.co → Settings → Access Tokens)
    # Token type: Fine-grained, permission: "Make calls to Inference Providers"
    hf_token: str = ""

    # Web Push (VAPID) — generate keys once, store in env
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = "mailto:noreply@kecarchives.local"


settings = Settings()