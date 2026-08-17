from __future__ import annotations

import calendar
import concurrent.futures
import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

import feedparser
import requests

from .config import FeedConfig, SearchConfig
from .models import NewsItem

LOGGER = logging.getLogger(__name__)
TAG_RE = re.compile(r"<[^>]+>")
TOUTIAO_MARKER = "(T.qf || T.flow).call(T,{ data: "
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136 Safari/537.36"


def clean_text(value: str) -> str:
    value = TAG_RE.sub(" ", value or "")
    return " ".join(html.unescape(value).split())


CHINA_TZ = timezone(timedelta(hours=8))


def _date_from_url(url: str) -> datetime | None:
    match = re.search(r"/(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?:/|$)", urlparse(url).path)
    if not match:
        return None
    return datetime(
        int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=CHINA_TZ
    ).astimezone(timezone.utc)


def _entry_time(entry: feedparser.FeedParserDict, url: str = "") -> datetime:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    url_date = _date_from_url(url)
    if url_date:
        return url_date
    return datetime.now(timezone.utc)


def fetch_feed(feed: FeedConfig, timeout_seconds: float) -> list[NewsItem]:
    response = requests.get(
        feed.url,
        timeout=timeout_seconds,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Invalid feed {feed.name}: {parsed.bozo_exception}")

    items: list[NewsItem] = []
    for entry in parsed.entries:
        source = entry.get("source") or {}
        source_name = clean_text(source.get("title", "")) or feed.name
        title = clean_text(entry.get("title", ""))
        suffix = f" - {source_name}"
        if title.lower().endswith(suffix.lower()):
            title = title[: -len(suffix)].strip()
        url = str(entry.get("link", "")).strip()
        if not title or not url:
            continue
        items.append(
            NewsItem(
                title=title,
                url=url,
                summary=clean_text(entry.get("summary", entry.get("description", ""))),
                source_name=source_name,
                feed_name=feed.name,
                published_at=_entry_time(entry, url),
            )
        )
    return items


def _extract_toutiao_objects(page: str) -> list[dict]:
    decoder = json.JSONDecoder()
    position = 0
    results: list[dict] = []
    while True:
        marker_position = page.find(TOUTIAO_MARKER, position)
        if marker_position < 0:
            break
        data_position = marker_position + len(TOUTIAO_MARKER)
        try:
            value, length = decoder.raw_decode(page[data_position:])
        except json.JSONDecodeError:
            position = data_position + 1
            continue
        position = data_position + length
        if isinstance(value, dict):
            results.append(value)
    return results


def _toutiao_direct_url(value: str) -> str:
    if not value:
        return ""
    values = parse_qs(urlparse(value).query).get("h5_url")
    return values[0] if values else value


def _toutiao_time(value: dict) -> datetime:
    for key in ("publish_time", "create_time", "display_time", "behot_time"):
        timestamp = value.get(key)
        if timestamp:
            try:
                return datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                pass
    date_value = value.get("datetime")
    if date_value:
        try:
            return datetime.strptime(str(date_value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def fetch_toutiao_search(search: SearchConfig, timeout_seconds: float) -> list[NewsItem]:
    response = requests.get(
        "https://so.toutiao.com/search",
        params={"keyword": search.query},
        timeout=timeout_seconds,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    values = _extract_toutiao_objects(response.text)
    if TOUTIAO_MARKER not in response.text:
        raise ValueError("Toutiao result structure is unavailable")

    items: list[NewsItem] = []
    seen: set[str] = set()
    for value in values:
        title = clean_text(str(value.get("title") or ""))
        target = value.get("open_url") or value.get("source_url") or value.get("url") or ""
        url = _toutiao_direct_url(str(target))
        if not title or not url or title in seen:
            continue
        seen.add(title)
        items.append(
            NewsItem(
                title=title,
                url=url,
                summary=clean_text(str(value.get("abstract") or value.get("summary") or "")),
                source_name=clean_text(str(value.get("source") or value.get("media_name") or "头条搜索结果")),
                feed_name=search.name,
                published_at=_toutiao_time(value),
            )
        )
    return items


class _SoNewsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.capture: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "li" and "res-list" in classes and attributes.get("data-url"):
            self.current = {"url": attributes["data-url"] or "", "title": "", "summary": "", "source": "", "time": ""}
        if self.current is None:
            return
        if tag == "a" and attributes.get("title") and not self.current["title"]:
            self.current["title"] = attributes["title"] or ""
        if tag == "p" and "summary" in classes:
            self.capture = "summary"
        elif tag == "cite" and "sitename" in classes:
            self.capture = "source"
        elif tag == "span" and "time" in classes:
            self.capture = "time"

    def handle_data(self, data: str) -> None:
        if self.current is not None and self.capture:
            self.current[self.capture] += data

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "cite", "span"}:
            self.capture = None
        if tag == "li" and self.current is not None:
            if self.current["title"] and self.current["url"]:
                self.items.append(self.current)
            self.current = None
            self.capture = None


def _relative_chinese_time(value: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    text = clean_text(value)
    match = re.search(r"(\d+)\s*(分钟|小时|天)前", text)
    if match:
        amount = int(match.group(1))
        seconds = amount * {"分钟": 60, "小时": 3600, "天": 86400}[match.group(2)]
        return datetime.fromtimestamp(now.timestamp() - seconds, tz=timezone.utc)
    for pattern in (r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})", r"(20\d{2})/(\d{1,2})/(\d{1,2})"):
        match = re.search(pattern, text)
        if match:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=timezone.utc)
    return now


def fetch_so360_search(search: SearchConfig, timeout_seconds: float) -> list[NewsItem]:
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        "https://news.so.com/ns",
        params={"q": search.query, "tn": "news"},
        timeout=timeout_seconds,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    parser = _SoNewsParser()
    parser.feed(response.text)
    if not parser.items:
        raise ValueError("360 News returned no structured results")
    return [
        NewsItem(
            title=clean_text(value["title"]),
            url=value["url"],
            summary=clean_text(value["summary"]),
            source_name=clean_text(value["source"]) or "360资讯结果",
            feed_name=search.name,
            published_at=_relative_chinese_time(value["time"]),
        )
        for value in parser.items
    ]


class _SogouWeixinParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.capture: str | None = None
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "li" and (attributes.get("id") or "").startswith("sogou_vr_11002601_box_"):
            self.current = {"url": "", "title": "", "summary": "", "source": "", "timestamp": ""}
            return
        if self.current is None:
            return
        if tag == "h3":
            self.in_title = True
        elif tag == "a" and self.in_title and not self.current["url"]:
            self.current["url"] = attributes.get("href") or ""
            self.capture = "title"
        elif tag == "p" and "txt-info" in classes:
            self.capture = "summary"
        elif tag == "span" and "all-time-y2" in classes:
            self.capture = "source"
        elif tag == "script":
            self.capture = "timestamp"

    def handle_data(self, data: str) -> None:
        if self.current is not None and self.capture:
            self.current[self.capture] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3":
            self.in_title = False
            self.capture = None
        elif tag in {"a", "p", "span", "script"}:
            self.capture = None
        elif tag == "li" and self.current is not None:
            if self.current["title"] and self.current["url"]:
                self.items.append(self.current)
            self.current = None
            self.capture = None
            self.in_title = False


def _sogou_time(value: str) -> datetime:
    match = re.search(r"timeConvert\(['\"](\d+)['\"]\)", value)
    if match:
        try:
            return datetime.fromtimestamp(int(match.group(1)), tz=timezone.utc)
        except (ValueError, OSError):
            pass
    return datetime.now(timezone.utc)


def fetch_sogou_weixin_search(search: SearchConfig, timeout_seconds: float) -> list[NewsItem]:
    response = requests.get(
        "https://weixin.sogou.com/weixin",
        params={"type": "2", "query": search.query},
        timeout=timeout_seconds,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    if "请输入验证码" in response.text or "用户您好，我们的系统检测到您网络中存在异常访问请求" in response.text:
        raise ValueError("Sogou Weixin requires verification")
    parser = _SogouWeixinParser()
    parser.feed(response.text)
    if not parser.items:
        raise ValueError("Sogou Weixin returned no structured results")
    return [
        NewsItem(
            title=clean_text(value["title"]),
            url=urljoin("https://weixin.sogou.com", html.unescape(value["url"])),
            summary=clean_text(value["summary"]),
            source_name=clean_text(value["source"]) or "微信公众号",
            feed_name=search.name,
            published_at=_sogou_time(value["timestamp"]),
        )
        for value in parser.items
    ]


def fetch_all(
    feeds: list[FeedConfig],
    searches: list[SearchConfig],
    timeout_seconds: float,
) -> list[NewsItem]:
    jobs: list[tuple[str, str, object]] = []
    for feed in feeds:
        jobs.append(("feed", feed.name, feed))
    for search in searches:
        jobs.append(("search", search.name, search))

    def run(job: tuple[str, str, object]) -> list[NewsItem]:
        job_type, name, config = job
        try:
            if job_type == "feed":
                return fetch_feed(config, timeout_seconds)  # type: ignore[arg-type]
            if config.provider == "toutiao":  # type: ignore[union-attr]
                return fetch_toutiao_search(config, timeout_seconds)  # type: ignore[arg-type]
            if config.provider == "so360":  # type: ignore[union-attr]
                return fetch_so360_search(config, timeout_seconds)  # type: ignore[arg-type]
            if config.provider == "sogou_weixin":  # type: ignore[union-attr]
                return fetch_sogou_weixin_search(config, timeout_seconds)  # type: ignore[arg-type]
            LOGGER.warning("Unsupported search provider name=%s provider=%s", name, config.provider)  # type: ignore[union-attr]
        except Exception as exc:
            LOGGER.warning("Source failed type=%s name=%s error=%s", job_type, name, exc)
        return []

    items: list[NewsItem] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(jobs)))) as executor:
        for result in executor.map(run, jobs):
            items.extend(result)
    return items
