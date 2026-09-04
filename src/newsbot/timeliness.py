from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .formatter import CHINA_TZ
from .models import Assessment, NewsItem

ACTION_TERMS = (
    "公告", "宣布", "披露", "发布会", "发布", "上线", "下架", "停服", "收购", "出售",
    "融资", "处罚", "调整", "调价", "开源", "定档", "发生", "启动",
)


@dataclass(frozen=True, slots=True)
class TimelinessResult:
    allowed: bool
    reason: str = ""
    event_at: datetime | None = None


def _date_from_sentence(sentence: str, base: datetime) -> datetime | None:
    full = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", sentence)
    if full:
        return datetime(
            int(full.group(1)), int(full.group(2)), int(full.group(3)), tzinfo=CHINA_TZ
        ).astimezone(timezone.utc)

    short = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日", sentence)
    if short:
        local_base = base.astimezone(CHINA_TZ)
        candidate = datetime(
            local_base.year, int(short.group(1)), int(short.group(2)), tzinfo=CHINA_TZ
        )
        if candidate > local_base + timedelta(days=31):
            candidate = candidate.replace(year=candidate.year - 1)
        return candidate.astimezone(timezone.utc)

    if "昨日" in sentence:
        local_base = base.astimezone(CHINA_TZ)
        previous = local_base.date() - timedelta(days=1)
        return datetime.combine(previous, datetime.min.time(), CHINA_TZ).astimezone(timezone.utc)
    if "今日" in sentence or "今天" in sentence:
        local_base = base.astimezone(CHINA_TZ)
        return datetime.combine(local_base.date(), datetime.min.time(), CHINA_TZ).astimezone(timezone.utc)
    return None


def infer_core_event_at(
    text: str,
    item: NewsItem,
    assessment: Assessment,
    maximum_sentences: int = 120,
) -> datetime | None:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？；])", text)
        if sentence.strip()
    ]
    if not sentences:
        sentences = [item.title]

    ranked: list[tuple[int, int, datetime]] = []
    for index, sentence in enumerate(sentences[:maximum_sentences]):
        event_at = _date_from_sentence(sentence, item.published_at)
        if not event_at:
            continue
        matched_count = sum(term in sentence for term in assessment.matched_terms)
        action_count = sum(term in sentence for term in ACTION_TERMS)
        if not matched_count and not action_count:
            continue
        score = matched_count * 4 + action_count * 3
        score += 2 if index == 0 else 0
        ranked.append((score, -index, event_at))
    return max(ranked, default=(0, 0, None))[2]


def _core_event_at(item: NewsItem, assessment: Assessment) -> datetime | None:
    return item.core_event_at or infer_core_event_at(item.summary or item.title, item, assessment, 8)


def evaluate_timeliness(
    item: NewsItem,
    assessment: Assessment,
    maximum_article_age_hours: int,
    maximum_event_age_hours: int,
    now: datetime | None = None,
) -> TimelinessResult:
    now = now or datetime.now(timezone.utc)
    article_age = (now - item.published_at).total_seconds() / 3600
    if article_age > maximum_article_age_hours:
        return TimelinessResult(False, f"原文发布时间已超过{maximum_article_age_hours}小时")

    event_at = _core_event_at(item, assessment)
    if event_at:
        event_age = (now - event_at).total_seconds() / 3600
        if event_age > maximum_event_age_hours:
            return TimelinessResult(False, f"核心事件时间已超过{maximum_event_age_hours}小时", event_at)
    return TimelinessResult(True, event_at=event_at)
