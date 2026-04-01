import re
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_admin_ids(raw: str) -> str:
    """Normalize comma/semicolon list: strip junk, keep comma-separated digits."""
    s = (raw or "").strip()
    s = s.replace("\ufeff", "").replace(";", ",")
    parts: list[str] = []
    for chunk in s.split(","):
        t = chunk.strip()
        if not t:
            continue
        digits = re.sub(r"\D", "", t)
        if digits:
            parts.append(digits)
    return ",".join(parts)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(..., description="Telegram Bot API token")
    channel_id: int = Field(
        ...,
        description="Target channel id as integer (e.g. -1001234567890)",
    )
    admin_ids: str = Field(
        ...,
        description="Comma-separated Telegram user ids allowed to use the bot",
    )

    llm_base_url: str = Field(default="https://api.openai.com/v1")
    llm_api_key: str = Field(default="")
    llm_model: str = Field(default="gpt-4o-mini")
    llm_timeout_seconds: float = Field(default=60.0)
    llm_max_retries: int = Field(
        default=4,
        ge=0,
        le=12,
        description="Повторы POST chat/completions при 429/5xx",
    )
    llm_retry_base_seconds: float = Field(
        default=1.0,
        ge=0.1,
        description="База экспоненциального backoff между повторами LLM",
    )
    caption_cache_ttl_seconds: int = Field(
        default=0,
        ge=0,
        description="Кэш подписей LLM по хэшу текста промпта, сек; 0 — выкл.",
    )
    llm_max_tokens: int = Field(
        default=800,
        ge=64,
        le=4096,
        description="max_tokens в запросе chat/completions",
    )
    llm_max_output_chars: int = Field(
        default=900,
        description="Target max chars for caption; Telegram hard limit 1024",
    )

    manager_username: str = Field(
        default="",
        description="Telegram @username без @; если пусто — CTA без @никнейма",
    )

    database_path: str = Field(default="./data/bot.db")

    dedup_ttl_days: int = Field(default=30)

    log_level: str = Field(default="INFO")

    auto_schedule_cron: str = Field(
        default="",
        description="Cron (5 полей APScheduler); пусто — выкл. Черновики → первый ADMIN_IDS с кнопкой одобрения",
    )

    auto_schedule_filters_json: str = Field(
        default="{}",
        description='Default JSON filters for scheduled auto runs, e.g. {"limit": 5}',
    )

    mashina_monitor_token: str = Field(
        default="",
        description="Секрет для POST /api/mashina/probe; пусто — только localhost",
    )

    playwright_headless: bool = Field(default=True)

    fx_enabled: bool = Field(
        default=True,
        description="Подмешивать в LLM актуальные курсы НБ РБ (USD/BYN, RUB/BYN)",
    )
    nbrb_fx_url: str = Field(
        default="https://api.nbrb.by/exrates/rates?periodicity=0",
        description="Официальный JSON API НБ РБ",
    )
    fx_cache_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        description="Кэш курсов НБ РБ (сек)",
    )

    listing_source: str = Field(
        default="stub",
        description="stub | lalafo | mashina — источник для автопостинга",
    )
    lalafo_search_url: str = Field(
        default="https://lalafo.kg/kyrgyzstan/avtomobili-s-probegom",
        description="Страница категории Lalafo",
    )
    lalafo_request_delay_seconds: float = Field(
        default=2.0,
        ge=0.5,
        description="Пауза Playwright (сек)",
    )
    mashina_search_url: str = Field(
        default="https://m.mashina.kg/search/all/?region=all",
        description="Мобильная выдача Mashina.kg",
    )
    mashina_request_delay_seconds: float = Field(
        default=2.0,
        ge=0.5,
        description="Пауза Playwright для Mashina.kg (сек)",
    )
    auto_detail_concurrency: int = Field(
        default=3,
        ge=1,
        le=12,
        description="Параллельных fetch_detail в автопайплайне",
    )
    auto_llm_concurrency: int = Field(
        default=2,
        ge=1,
        le=12,
        description="Параллельных LLM генераций в автопайплайне",
    )

    channel_gallery_min_photos: int = Field(
        default=4,
        ge=1,
        le=10,
        description="Желаемый минимум фото в посте (если в объявлении меньше — публикуем сколько есть)",
    )
    channel_gallery_max_photos: int = Field(
        default=6,
        ge=1,
        le=10,
        description="Максимум фото в одном посте канала (после фильтра мусорных URL)",
    )
    channel_post_cooldown_seconds: float = Field(
        default=4.0,
        ge=0.5,
        le=120.0,
        description="Пауза между публикациями в канал (снижает Flood control Telegram)",
    )
    image_download_concurrency: int = Field(
        default=4,
        ge=1,
        le=12,
        description="Параллельных HTTP GET при скачивании фото объявления",
    )

    redis_url: str = Field(
        default="",
        description="Redis: FSM aiogram + опциональная очередь пайплайна; пусто — MemoryStorage",
    )
    pipeline_queue_key: str = Field(
        default="car-bot:pipeline:jobs",
        description="LPUSH/BRPOP ключ заданий для car-pipeline-worker",
    )
    fsm_state_ttl_seconds: int = Field(
        default=604_800,
        ge=60,
        description="TTL состояния FSM в Redis (state_ttl / data_ttl)",
    )

    @model_validator(mode="after")
    def _gallery_min_max(self) -> "Settings":
        if self.channel_gallery_max_photos < self.channel_gallery_min_photos:
            raise ValueError(
                "channel_gallery_max_photos must be >= channel_gallery_min_photos",
            )
        return self

    @field_validator("admin_ids", mode="before")
    @classmethod
    def normalize_admin_ids(cls, v: object) -> str:
        if v is None:
            return ""
        return _parse_admin_ids(str(v))

    @property
    def admin_id_list(self) -> list[int]:
        if not self.admin_ids.strip():
            return []
        return [int(x.strip()) for x in self.admin_ids.split(",") if x.strip().isdigit()]

    @property
    def manager_slug(self) -> str:
        return (self.manager_username or "").strip().lstrip("@")

    @property
    def manager_mention(self) -> str:
        return f"@{self.manager_slug}" if self.manager_slug else ""

    @property
    def price_missing_hint(self) -> str:
        if self.manager_slug:
            return f"уточнить у {self.manager_mention}"
        return "уточнить у менеджера (контакты в объявлении / канале)"

    @property
    def cta_tail(self) -> str:
        if self.manager_slug:
            return f"Пишите для деталей! ✅ {self.manager_mention}"
        return "Пишите для деталей! ✅ (контакты в объявлении или канале)"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
