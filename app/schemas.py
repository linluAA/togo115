from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangeCredentialsRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class SettingPayload(BaseModel):
    value: dict[str, Any]


class SubscriptionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    media_type: Literal["tv", "movie"] = "tv"
    tmdb_id: int | None = None
    poster_url: str | None = None
    overview: str | None = None
    release_year: int | None = Field(default=None, ge=1900, le=2100)
    tmdb_total_count: int | None = None
    keywords: list[str] = Field(default_factory=list)
    quality_rules: dict[str, Any] = Field(default_factory=dict)
    delivery_mode: Literal["115", "telegram_bot"] = "115"
    target_path: str | None = None


class SubscriptionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    keywords: list[str] | None = None
    quality_rules: dict[str, Any] | None = None
    delivery_mode: Literal["115", "telegram_bot"] | None = None
    target_path: str | None = None
    release_year: int | None = Field(default=None, ge=1900, le=2100)
    status: Literal["active", "paused", "completed"] | None = None


class SubscriptionBulkDeleteRequest(BaseModel):
    ids: list[int] = Field(default_factory=list)


class ResourceBulkDeleteRequest(BaseModel):
    ids: list[int] = Field(default_factory=list)


class SearchRequest(BaseModel):
    title: str
    keywords: list[str] = Field(default_factory=list)
    subscription_id: int | None = None
    media_type: Literal["tv", "movie"] = "tv"
    tmdb_id: int | None = None
    release_year: int | None = Field(default=None, ge=1900, le=2100)
    tmdb_total_count: int | None = None
    tmdb_seasons: list[dict[str, Any]] = Field(default_factory=list)
    emby_episode_keys: list[Any] = Field(default_factory=list)
    emby_count: int = 0
    in_library: bool = False
    quality_rules: dict[str, Any] = Field(default_factory=dict)


class BotCommand(BaseModel):
    command: str
    args: dict[str, Any] = Field(default_factory=dict)


class TelegramCodeRequest(BaseModel):
    phone: str


class TelegramCodeLoginRequest(BaseModel):
    phone: str
    code: str


class TelegramWebAppAuthRequest(BaseModel):
    bot_username: str
    webapp_url: str | None = None
    start_param: str | None = None


class TelegramUrlAuthRequest(BaseModel):
    auth_url: str


class Pan115SaveRequest(BaseModel):
    link: str
    target_path: str | None = None


class Pan115QrRequest(BaseModel):
    channel: str = "web"


class ProxyTestRequest(BaseModel):
    url: str
    modules: list[str] = Field(default_factory=list)


class RssSourceTestRequest(BaseModel):
    source: dict[str, Any] = Field(default_factory=dict)
    query: str | None = None


class HdhiveLoginBrowserRequest(BaseModel):
    source: dict[str, Any] = Field(default_factory=dict)
