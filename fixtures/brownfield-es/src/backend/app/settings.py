from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_PREFIX: str = "/api/v1"
    DATABASE_URL: str = "sqlite:///conciliacion.db"
    EVENTS_TOPIC: str = "conciliacion-eventos"
    EXPORT_BUCKET: str = "conciliacion-exportes"
    BANK_TOKEN: str = ""


settings = Settings()
