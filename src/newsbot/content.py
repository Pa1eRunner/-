from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

from .models import Assessment, NewsItem
from .timeliness import infer_core_event_at
from .webtext import decoded_response_text

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136 Safari/537.36"
HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
CHINA_TZ = timezone(timedelta(hours=8))
PUBLISHED_META_NAMES = {
    "article:published_time", "datepublished", "publishdate", "pubdate", "publication_date",
}


class _ArticleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.published_values: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag == "meta":
            name = (attributes.get("property") or attributes.get("name") or "").lower()
            if name in PUBLISHED_META_NAMES and attributes.get("content"):
                self.published_values.append(attributes["content"])
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not self.skip_depth and len(HAN_RE.findall(text)) >= 8:
            self.parts.append(text)


def _normalized(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", value.lower())


def _summary_is_usable(item: NewsItem, assessment: Assessment) -> bool:
    summary = " ".join(item.summary.split())
    if len(HAN_RE.findall(summary)) < 28:
        return False
    if SequenceMatcher(None, _normalized(item.title), _normalized(summary)).ratio() >= 0.82:
        return False
    terms = [term for term in assessment.matched_terms if len(term) >= 2]
    factual_markers = ("公告", "宣布", "发布", "调整", "上线", "收购", "融资", "用户", "收入", "价格")
    return any(term.lower() in summary.lower() for term in terms) or any(
        marker in summary for marker in factual_markers
    )


def _parse_datetime(value: str) -> datetime | None:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        match = re.search(
            r"(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})(?:日|[T\s]+)?\s*(\d{1,2})?:?(\d{1,2})?",
            normalized,
        )
        if not match:
            return None
        parsed = datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4) or 0),
            int(match.group(5) or 0),
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CHINA_TZ)
    return parsed.astimezone(timezone.utc)


def _original_published_at(page: str, url: str, parser: _ArticleTextParser) -> datetime | None:
    values = list(parser.published_values)
    values.extend(re.findall(r'"datePublished"\s*:\s*"([^"]+)"', page, re.IGNORECASE))
    values.extend(re.findall(r"published at\s+([0-9:\-\s]+)", page, re.IGNORECASE))
    for value in values:
        parsed = _parse_datetime(value)
        if parsed:
            return parsed

    path = urlparse(url).path
    match = re.search(r"/(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?:/|$)", path)
    if match:
        return datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            tzinfo=CHINA_TZ,
        ).astimezone(timezone.utc)
    return None


def enrich_summary_from_original(
    item: NewsItem,
    assessment: Assessment,
    timeout_seconds: float,
) -> None:
    summary_is_usable = _summary_is_usable(item, assessment)
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(item.url, timeout=timeout_seconds, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        page = decoded_response_text(response)
        parser = _ArticleTextParser()
        parser.feed(page)
    except Exception:
        return

    published_at = _original_published_at(page, getattr(response, "url", item.url), parser)
    if published_at:
        item.published_at = published_at
    item.core_event_at = infer_core_event_at(" ".join(parser.parts), item, assessment)
    if summary_is_usable:
        return

    title_key = _normalized(item.title)
    terms = [term for term in assessment.matched_terms if len(term) >= 2]
    candidates: list[tuple[int, int, str]] = []
    seen_sentences: set[str] = set()
    for index, part in enumerate(parser.parts):
        for sentence in re.split(r"(?<=[。！？；])", part):
            sentence = sentence.strip()
            if len(sentence) < 18 or len(sentence) > 260:
                continue
            sentence = sentence.replace("“", "").replace("”", "").replace('"', "")
            sentence_key = _normalized(sentence)
            if not sentence_key or SequenceMatcher(None, title_key, sentence_key).ratio() >= 0.88:
                continue
            if sentence_key in seen_sentences:
                continue
            seen_sentences.add(sentence_key)
            term_hits = sum(term.lower() in sentence.lower() for term in terms)
            factual_hits = sum(
                term in sentence
                for term in ("公告", "宣布", "计划", "正式通知", "调整", "上调", "下调", "价格", "定价")
            )
            if not term_hits and not factual_hits:
                continue
            score = term_hits * 4 + factual_hits * 3
            score += 4 if re.search(r"\d", sentence) else 0
            score += 8 if any(term in sentence for term in ("公告称", "宣布", "正式通知")) else 0
            score -= 15 if any(term in sentence for term in ("分析人士认为", "有观点认为", "机构认为", "业内认为")) else 0
            score -= 15 if any(term in sentence for term in ("添一把猛火", "坐不住了", "猛攻", "游戏规则", "谁不爱", "疯狂")) else 0
            candidates.append((score, index, sentence))

    selected = sorted(candidates, key=lambda row: (-row[0], row[1]))[:2]
    if selected and len(selected[0][2]) >= 45:
        selected = selected[:1]
    if selected:
        item.summary = "".join(sentence for _, _, sentence in sorted(selected, key=lambda row: row[1]))
