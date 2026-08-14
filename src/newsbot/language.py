from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser

import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136 Safari/537.36"
HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
KANA_RE = re.compile(r"[\u3040-\u30ff]")
HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
LATIN_RE = re.compile(r"[A-Za-z]")


@dataclass(frozen=True, slots=True)
class LanguageResult:
    allowed: bool
    reason: str = ""


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.language = ""
        self.text_parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "html":
            self.language = (attributes.get("lang") or "").lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth and data.strip():
            self.text_parts.append(data.strip())


def detect_chinese_html(page: str) -> LanguageResult:
    parser = _VisibleTextParser()
    parser.feed(page)
    if parser.language.startswith(("ja", "ko", "en")):
        return LanguageResult(False, f"页面语言为{parser.language}")

    text = " ".join(parser.text_parts)
    han_count = len(HAN_RE.findall(text))
    kana_count = len(KANA_RE.findall(text))
    hangul_count = len(HANGUL_RE.findall(text))
    latin_count = len(LATIN_RE.findall(text))
    language_characters = han_count + kana_count + hangul_count + latin_count
    if kana_count >= 8 or hangul_count >= 8:
        return LanguageResult(False, "正文包含大量日文或韩文字符")
    if han_count < 30:
        return LanguageResult(False, "正文中文字符不足")
    if language_characters and han_count / language_characters < 0.18:
        return LanguageResult(False, "正文中文占比不足")
    return LanguageResult(True)


@lru_cache(maxsize=512)
def verify_original_chinese(url: str, timeout_seconds: float) -> LanguageResult:
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(url, timeout=timeout_seconds, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type and "html" not in content_type and "text" not in content_type:
            return LanguageResult(False, "原文不是可核验的中文网页")
        return detect_chinese_html(response.text)
    except Exception as exc:
        return LanguageResult(False, f"原文语言核验失败：{type(exc).__name__}")
