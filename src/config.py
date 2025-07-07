from datetime import datetime, timezone
from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from supabase import create_client, Client
from dateutil import parser as dtparse
from typing import Any

class Settings(BaseSettings):
    SUPABASE_URL: str | None = None
    SUPABASE_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4.1-mini"
    OPENAI_TEMP: float = 0.1

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )


settings = Settings()

supabase: Client = create_client(
    str(settings.SUPABASE_URL),
    str(settings.SUPABASE_KEY)
)

def get_last_run_time(job: str) -> datetime:
    resp: Any = (
        supabase
        .table("process_metadata")
        .select("last_run")
        .eq("job", job)
        .maybe_single()
        .execute()
    )
    record = getattr(resp, "data", None) or {}
    last = record.get("last_run")
    if last:
        try:
            # tenta ISO puro
            return datetime.fromisoformat(last)
        except ValueError:
            # fallback robusto
            return dtparse.parse(last)
    # sem registro: epoch UTC
    return datetime.fromtimestamp(0, tz=timezone.utc)
    
def set_last_run_time(job: str, ts: datetime):
    """
    Upsert do last_run para o job na tabela process_metadata.
    """
    record = {
        "job": job,
        "last_run": ts.isoformat()
    }
    supabase.table("process_metadata").upsert(
        record,
        on_conflict="job"
    ).execute()
