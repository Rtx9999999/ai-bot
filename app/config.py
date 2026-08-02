from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_token: str
    admin_ids: str = ""
    database_path: str = "data/bot.db"
    runpod_api_key: str
    runpod_image_endpoint: str
    runpod_video_endpoint: str
    runpod_faceswap_endpoint: str
    runpod_timeout_seconds: int = 600
    s3_endpoint_url: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    s3_region: str = "auto"
    s3_public_url: str
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    solana_wallet: str = ""
    sol_usd_price: float = 150.0
    trongrid_api_url: str = "https://api.trongrid.io"
    trongrid_api_key: str = ""
    tron_wallet: str = ""
    usdt_trc20_contract: str = "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"
    premium_days: int = 30
    premium_credits: int = 100
    free_credits: int = 2
    referral_bonus_percent: int = 10
    rate_limit_seconds: int = 2
    max_upload_mb: int = 15
    watermark_text: str = "PREVIEW • 18+"
    log_level: str = "INFO"

    @property
    def admins(self) -> set[int]:
        return {int(x.strip()) for x in self.admin_ids.split(",") if x.strip()}

    @field_validator("s3_public_url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

