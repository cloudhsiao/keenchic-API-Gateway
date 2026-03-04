from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Required: API key for authenticating incoming requests (X-API-KEY header)
    KEENCHIC_API_KEY: str = ""

    # Backend selection: GPU (TensorRT, fallback to OV), CPU/openvino, AUTO
    KEENCHIC_BACKEND: str = "GPU"

    # Optional: directory to persist raw uploaded images to disk
    KEENCHIC_UPLOAD_DIR: str | None = None

    # Logging: format ("text" or "json") and level ("DEBUG"/"INFO"/"WARNING"/"ERROR")
    LOG_FORMAT: str = "text"
    LOG_LEVEL: str = "INFO"


settings = Settings()
