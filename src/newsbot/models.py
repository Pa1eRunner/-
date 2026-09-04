from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class NewsItem:
    title: str
    url: str
    summary: str
    source_name: str
    feed_name: str
    published_at: datetime
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    core_event_at: datetime | None = None


@dataclass(slots=True)
class Assessment:
    relevant: bool
    score: int
    level: str
    category: str
    source_tier: int
    source_label: str
    matched_terms: list[str]
    analysis_points: list[str]
    watch_points: list[str]
    corroborating_sources: list[str] = field(default_factory=list)
