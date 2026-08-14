from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class BotConfig:
    webhook_env: str
    security_keyword: str
    request_timeout_seconds: float
    minimum_send_interval_seconds: float


@dataclass(frozen=True, slots=True)
class MonitorConfig:
    poll_interval_seconds: int
    maximum_item_age_hours: int
    instant_push_score: int
    maximum_alerts_per_cycle: int
    send_on_first_run: bool
    database_path: str
    log_path: str


@dataclass(frozen=True, slots=True)
class FeedConfig:
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class SearchConfig:
    name: str
    provider: str
    query: str


@dataclass(frozen=True, slots=True)
class SafetyConfig:
    political_keywords: list[str]
    sensitive_people: list[str]
    protected_entities: list[str]
    unverified_claim_markers: list[str]
    allegation_keywords: list[str]


@dataclass(frozen=True, slots=True)
class FallbackConfig:
    enabled: bool
    trigger_when_qipai_sent_below: int
    maximum_game_per_cycle: int
    maximum_tech_per_cycle: int
    minimum_score: int


@dataclass(frozen=True, slots=True)
class DailyBackupConfig:
    enabled: bool
    send_after: str
    required_items: int
    minimum_score: int


@dataclass(frozen=True, slots=True)
class AppConfig:
    bot: BotConfig
    monitor: MonitorConfig
    feeds: list[FeedConfig]
    searches: list[SearchConfig]
    companies: list[str]
    company_profiles: dict[str, str]
    safety: SafetyConfig
    fallback: FallbackConfig
    daily_backup: DailyBackupConfig


def load_env_file(path: str | Path) -> bool:
    env_path = Path(path)
    if not env_path.is_file():
        return False
    for line_number, raw_line in enumerate(env_path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"Invalid .env entry at {env_path}:{line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not ENV_KEY_RE.fullmatch(key):
            raise ValueError(f"Invalid environment variable name at {env_path}:{line_number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)
    return True


def load_project_environment(config_path: str | Path) -> list[Path]:
    candidates = [Path.cwd() / ".env", Path(config_path).resolve().parent.parent / ".env"]
    loaded: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if load_env_file(resolved):
            loaded.append(resolved)
    return loaded


def _required(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ValueError(f"Missing configuration key: {key}")
    return mapping[key]


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    bot = _required(raw, "bot")
    monitor = _required(raw, "monitor")
    feeds = [FeedConfig(name=item["name"], url=item["url"]) for item in raw.get("feeds", [])]
    searches = [
        SearchConfig(name=item["name"], provider=item["provider"], query=item["query"])
        for item in raw.get("searches", [])
    ]
    if not feeds and not searches:
        raise ValueError("At least one news feed or search source is required")
    safety = raw.get("safety", {})
    fallback = raw.get("fallback", {})
    daily_backup = raw.get("daily_backup", {})
    return AppConfig(
        bot=BotConfig(
            webhook_env=_required(bot, "webhook_env"),
            security_keyword=_required(bot, "security_keyword"),
            request_timeout_seconds=float(bot.get("request_timeout_seconds", 15)),
            minimum_send_interval_seconds=float(bot.get("minimum_send_interval_seconds", 1.2)),
        ),
        monitor=MonitorConfig(
            poll_interval_seconds=int(monitor.get("poll_interval_seconds", 600)),
            maximum_item_age_hours=int(monitor.get("maximum_item_age_hours", 72)),
            instant_push_score=int(monitor.get("instant_push_score", 72)),
            maximum_alerts_per_cycle=int(monitor.get("maximum_alerts_per_cycle", 5)),
            send_on_first_run=bool(monitor.get("send_on_first_run", False)),
            database_path=str(monitor.get("database_path", "data/newsbot.sqlite3")),
            log_path=str(monitor.get("log_path", "data/newsbot.log")),
        ),
        feeds=feeds,
        searches=searches,
        companies=[str(company) for company in raw.get("companies", [])],
        company_profiles={str(name): str(profile) for name, profile in raw.get("company_profiles", {}).items()},
        safety=SafetyConfig(
            political_keywords=[str(value) for value in safety.get("political_keywords", [])],
            sensitive_people=[str(value) for value in safety.get("sensitive_people", [])],
            protected_entities=[str(value) for value in safety.get("protected_entities", [])],
            unverified_claim_markers=[str(value) for value in safety.get("unverified_claim_markers", [])],
            allegation_keywords=[str(value) for value in safety.get("allegation_keywords", [])],
        ),
        fallback=FallbackConfig(
            enabled=bool(fallback.get("enabled", True)),
            trigger_when_qipai_sent_below=int(fallback.get("trigger_when_qipai_sent_below", 2)),
            maximum_game_per_cycle=min(1, int(fallback.get("maximum_game_per_cycle", 1))),
            maximum_tech_per_cycle=min(1, int(fallback.get("maximum_tech_per_cycle", 1))),
            minimum_score=int(fallback.get("minimum_score", 70)),
        ),
        daily_backup=DailyBackupConfig(
            enabled=bool(daily_backup.get("enabled", True)),
            send_after=str(daily_backup.get("send_after", "09:30")),
            required_items=3,
            minimum_score=int(daily_backup.get("minimum_score", 35)),
        ),
    )
