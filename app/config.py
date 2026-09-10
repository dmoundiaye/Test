"""Application configuration using pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    DATABASE_URL: str = "mysql+pymysql://devnet:devnetpassword@localhost:3306/devnet2"
    GNS3_HOST: str = "127.0.0.1"
    GNS3_PORT: int = 3080
    GNS3_USERNAME: str = "admin"
    GNS3_PASSWORD: str = "admin"
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    class Config:
        env_file = ".env"


settings = Settings()