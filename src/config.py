from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from supabase import create_client, Client

class Settings(BaseSettings):
    SUPABASE_URL: str | None = None
    SUPABASE_KEY: str| None = None
    OPENAI_API_KEY: str| None = None
    OPENAI_MODEL: str = "gpt-4.1-mini"
    OPENAI_TEMP: float = 0.1

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

supabase: Client = create_client(
    str(settings.SUPABASE_URL),
    str(settings.SUPABASE_KEY)
)