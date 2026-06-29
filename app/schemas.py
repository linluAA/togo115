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
    keywords: list[str] = Field(default_factory=list)
    delivery_mode: Literal["115", "telegram_bot"] = "115"
    target_path: str | None = None


class SubscriptionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    keywords: list[str] | None = None
    delivery_mode: Literal["115", "telegram_bot"] | None = None
    target_path: str | None = None
    status: Literal["active", "paused"] | None = None


class SearchRequest(BaseModel):
    title: str
    keywords: list[str] = Field(default_factory=list)


class BotCommand(BaseModel):
    command: str
    args: dict[str, Any] = Field(default_factory=dict)


class TelegramPasswordRequest(BaseModel):
    password: str


class Pan115SaveRequest(BaseModel):
    link: str
    target_path: str | None = None
