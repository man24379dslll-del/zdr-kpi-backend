from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str
    supabase_publishable_key: str
    supabase_service_key: str
    cors_origins: str = "*"
    port: int = 8000
    # Сколько прокси перед приложением дописывают адрес в X-Forwarded-For
    # (Railway — 1). Нужно для allowed_ips внешних API-ключей.
    trusted_proxy_hops: int = 1
    external_rate_limit_per_minute: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
