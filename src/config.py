from datetime import datetime, timezone
from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from supabase import create_client, Client


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
    """
    Retorna o timestamp do último run para o job,
    ou epoch (1970-01-01T00:00:00Z) se não houver ainda registro.
    """
    resp = (
        supabase
        .table("process_metadata")
        .select("last_run")
        .eq("job", job)
        .maybe_single()      # NÃO lança erro se não achar linha
        .execute()
    )
    # extrai com segurança, usa {} caso não exista
    record = getattr(resp, "data", None) or {}
    last = record.get("last_run")
    if last:
        # Supabase já devolve ISO string com timezone
        return datetime.fromisoformat(last)

    # primeira vez: retorna epoch UTC
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
