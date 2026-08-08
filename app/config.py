from functools import lru_cache
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PLACEHOLDERS = ("replace_me", "account_id", "endpoint_id", "example.com", "123456:")


def configured(*values: str) -> bool:
    return all(value and not any(marker in value.lower() for marker in PLACEHOLDERS) for value in values)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    telegram_token: str = Field(validation_alias=AliasChoices("TELEGRAM_TOKEN", "BOT_TOKEN", "TELEGRAM_BOT_TOKEN"))
    backup_telegram_token: str = ""
    backup_bot_username: str = ""
    required_channel: str = ""
    groq_api_key: str = ""
    groq_chat_model: str = "llama-3.1-8b-instant"
    admin_ids: str = ""
    database_path: str = "data/bot.db"
    runpod_api_key: str = ""
    runpod_image_endpoint: str = ""
    runpod_video_endpoint: str = ""
    runpod_faceswap_endpoint: str = ""
    runpod_timeout_seconds: int = 600
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = ""
    s3_region: str = "auto"
    s3_public_url: str = ""
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    solana_wallet: str = ""
    sol_usd_price: float = 150.0
    toncenter_api_url: str = "https://toncenter.com/api/v2"
    toncenter_api_key: str = ""
    ton_wallet: str = ""
    ton_usd_price: float = 6.0
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

    @property
    def required_channel_username(self) -> str:
        value = self.required_channel.strip()
        if value.startswith("https://t.me/"):
            value = value.removeprefix("https://t.me/").split("?", 1)[0]
        return value.lstrip("@")

    @property
    def media_backend_ready(self) -> bool:
        return configured(self.s3_endpoint_url, self.s3_access_key, self.s3_secret_key, self.s3_bucket)

    def generation_backend_ready(self, kind: str) -> bool:
        endpoint = self.runpod_video_endpoint if kind == "video" else self.runpod_image_endpoint
        return configured(self.runpod_api_key, endpoint) and self.media_backend_ready

    @property
    def faceswap_backend_ready(self) -> bool:
        return configured(self.runpod_api_key, self.runpod_faceswap_endpoint) and self.media_backend_ready

    @field_validator("s3_public_url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
