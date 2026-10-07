from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_PREFIX: str = "/api/v1"
    DATABASE_URL: str = "sqlite:///conciliacion.db"


settings = Settings()
