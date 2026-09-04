from __future__ import annotations

import re
from dataclasses import dataclass

from .config import SafetyConfig
from .models import Assessment, NewsItem


@dataclass(frozen=True, slots=True)
class SafetyResult:
    allowed: bool
    reason: str = ""


PERSON_ROLE_PATTERNS = (
    re.compile(r"(?:董事长|创始人|联合创始人|CEO|总裁|总经理|实控人|实际控制人|负责人|高管)[：:\s“”]*([\u4e00-\u9fff]{2,4})"),
    re.compile(r"([\u4e00-\u9fff]{2,4})(?:董事长|创始人|CEO|总裁|总经理|实控人|实际控制人|负责人|高管)"),
)
NON_PERSON_VALUES = {"公司", "集团", "平台", "企业", "游戏", "相关", "现任", "原任", "一名", "多名"}


def _first_match(text: str, keywords: list[str]) -> str | None:
    return next((keyword for keyword in keywords if keyword and keyword.lower() in text.lower()), None)


def _contains_named_person(text: str) -> bool:
    for pattern in PERSON_ROLE_PATTERNS:
        for match in pattern.finditer(text):
            if match.group(1) not in NON_PERSON_VALUES:
                return True
    return False


def evaluate_safety(item: NewsItem, assessment: Assessment, config: SafetyConfig) -> SafetyResult:
    text = f"{item.title} {item.summary}"

    political_match = _first_match(text, config.political_keywords)
    if political_match:
        return SafetyResult(False, "政治敏感内容")

    person_match = _first_match(text, config.sensitive_people)
    if person_match or _contains_named_person(text):
        return SafetyResult(False, "敏感人名")

    protected_match = _first_match(text, config.protected_entities)
    if protected_match:
        return SafetyResult(False, "保护主体相关内容")

    unverified_match = _first_match(text, config.unverified_claim_markers)
    if unverified_match:
        return SafetyResult(False, "未经证实的消息或指控")

    allegation_match = _first_match(text, config.allegation_keywords)
    if allegation_match:
        if assessment.source_tier == 1:
            return SafetyResult(True)
        if assessment.source_tier == 2 and assessment.corroborating_sources:
            return SafetyResult(True)
        return SafetyResult(False, "指控性内容缺少权威或交叉核验")

    return SafetyResult(True)
