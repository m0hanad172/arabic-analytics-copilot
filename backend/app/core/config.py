from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("backend/.env", "backend/.env.pilot"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str
    # Active database backend. Keep "postgres" as default; "sqlserver" support
    # is being introduced incrementally via the dialect layer (Phase A).
    database_backend: str = "postgres"
    allowed_schema: str = "bi"
    default_max_rows: int = 200
    statement_timeout_ms: int = 8000

settings = Settings()
