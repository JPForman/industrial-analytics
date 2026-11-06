from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jwt_secret: str  # required: the app refuses to start without it
    token_minutes: int = 60
    database_url: str = "postgresql+asyncpg://industrial:industrial@localhost:5432/industrial"


@lru_cache
def get_settings() -> Settings:
    return Settings()
