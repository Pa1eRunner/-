from __future__ import annotations

import re
from datetime import datetime, timezone

from .formatter import CHINA_TZ, _trim
from .models import Assessment, NewsItem
from .quality import is_low_information_sentence, neutralize_headline
from .scoring import SPAM_TERMS, classify_source

GAME_TERMS = {
    "国产游戏": 24,
    "网络游戏": 20,
    "游戏行业": 20,
    "游戏公司": 18,
    "手游": 18,
    "端游": 16,
    "小游戏": 16,
    "爆款小游戏": 24,
    "买量小游戏": 24,
    "变现小游戏": 24,
    "微信小游戏": 20,
    "抖音小游戏": 20,
    "电竞": 14,
}

TECH_TERMS = {
    "人工智能": 24,
    "大模型": 24,
    "AI": 20,
    "芯片": 22,
    "半导体": 20,
    "算力": 18,
    "云计算": 16,
    "云服务": 14,
    "机器人": 16,
    "自动驾驶": 16,
    "操作系统": 14,
}

DOMESTIC_TERMS = (
    "中国", "国内", "国产", "腾讯", "网易", "米哈游", "阿里", "百度", "字节跳动",
    "华为", "小米", "京东", "DeepSeek", "科大讯飞", "智谱", "月之暗面", "MiniMax",
    "商汤", "长鑫", "微信小游戏", "抖音小游戏",
)

EVENT_TERMS = {
    "发布": 8,
    "上线": 8,
    "开源": 12,
    "融资": 12,
    "收购": 14,
    "并购": 14,
    "上市": 12,
    "合作": 6,
    "收入": 8,
    "用户": 6,
    "赛事": 8,
    "爆款": 12,
    "登顶": 12,
    "买量": 10,
    "投放": 8,
    "变现": 10,
    "广告变现": 12,
    "混合变现": 12,
    "IAA": 10,
    "IAP": 10,
    "ROI": 10,
    "日活": 8,
    "留存": 8,
    "停服": 16,
    "下架": 16,
    "处罚": 18,
    "调价": 12,
    "涨价": 14,
}

DIGEST_TITLE_TERMS = (
    "彩票", "博彩", "概念股", "荐股", "行情预测", "早盘", "收盘综述", "到底",
    "为什么", "如何看", "怎么看", "是什么", "一文读懂", "深度解读",
)


def _contains(text: str, term: str) -> bool:
    if term == "AI":
        return bool(re.search(r"(?<![A-Za-z])AI(?![A-Za-z])", text, re.IGNORECASE))
    return term.lower() in text.lower()


def assess_general_backup(item: NewsItem, now: datetime | None = None) -> Assessment | None:
    now = now or datetime.now(timezone.utc)
    text = f"{item.title} {item.summary} {item.source_name}"
    if any(term in text for term in SPAM_TERMS) or any(term in item.title for term in DIGEST_TITLE_TERMS):
        return None
    if not any(_contains(text, term) for term in DOMESTIC_TERMS):
        return None

    game_matches = [term for term in GAME_TERMS if _contains(text, term)]
    tech_matches = [term for term in TECH_TERMS if _contains(text, term)]
    if not game_matches and not tech_matches:
        return None
    category = "国产游戏动态" if sum(GAME_TERMS[term] for term in game_matches) >= sum(
        TECH_TERMS[term] for term in tech_matches
    ) else "国内科技动态"
    topic_matches = game_matches if category == "国产游戏动态" else tech_matches
    topic_weights = GAME_TERMS if category == "国产游戏动态" else TECH_TERMS

    source_tier, source_label = classify_source(item)
    if source_tier > 3:
        return None
    topic_score = min(45, sum(topic_weights[term] for term in topic_matches))
    event_matches = [term for term in EVENT_TERMS if _contains(text, term)]
    event_score = min(20, sum(EVENT_TERMS[term] for term in event_matches))
    source_score = {1: 20, 2: 17, 3: 12}[source_tier]
    age_hours = max(0, (now - item.published_at).total_seconds() / 3600)
    freshness_score = 8 if age_hours <= 6 else 6 if age_hours <= 24 else 4 if age_hours <= 72 else 0
    score = min(100, topic_score + event_score + source_score + freshness_score)
    level = "A" if score >= 70 else "B" if score >= 55 else "C"
    return Assessment(
        True,
        score,
        level,
        category,
        source_tier,
        source_label,
        [*topic_matches, *event_matches],
        [],
        [],
    )


def _event_summary(item: NewsItem, assessment: Assessment) -> str:
    title_key = re.sub(r"\W", "", item.title.lower())
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？；])", item.summary or "")
        if sentence.strip()
        and re.sub(r"\W", "", sentence.lower()) != title_key
        and not is_low_information_sentence(sentence)
    ]
    ranked = sorted(
        sentences,
        key=lambda sentence: sum(term in sentence for term in assessment.matched_terms),
        reverse=True,
    )
    if ranked:
        return _trim("".join(ranked[:2]), 220)
    objective_title = neutralize_headline(item.title)
    return _trim(f"报道显示，{objective_title.rstrip('。！？；')}。具体内容以原文披露为准。", 220)


def format_general_backup(item: NewsItem, assessment: Assessment, security_keyword: str) -> tuple[str, str]:
    title = _trim(neutralize_headline(item.title), 70)
    impact = (
        "该事件涉及国产游戏的产品、发行、运营或市场变化，可能影响同品类竞争、渠道资源和用户注意力分配。"
        if assessment.category == "国产游戏动态"
        else "该事件涉及国内AI或科技产业的产品、技术、算力或商业化变化，可能影响开发者选型和企业服务市场。"
    )
    sources = [item.source_name, *assessment.corroborating_sources]
    source_text = "、".join(list(dict.fromkeys(source for source in sources if source))[:3])
    published = item.published_at.astimezone(CHINA_TZ).strftime("%m-%d %H:%M")
    markdown = f"""### {title}

**事件要点**  
{_event_summary(item, assessment)}

**行业关联**  
{impact}

{security_keyword}：{source_text}｜{published}  
[原文]({item.url})
"""
    return title, markdown
