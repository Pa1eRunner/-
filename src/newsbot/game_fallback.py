from __future__ import annotations

import re
from datetime import datetime, timezone

from .formatter import CHINA_TZ, _trim
from .models import Assessment, NewsItem
from .quality import is_low_information_sentence, neutralize_headline
from .scoring import SPAM_TERMS, classify_source

GAME_ENTITIES = {
    "腾讯游戏": ("腾讯游戏", "腾讯", "王者荣耀", "和平精英", "英雄联盟手游", "金铲铲之战", "地下城与勇士手游"),
    "网易游戏": ("网易游戏", "网易", "梦幻西游", "逆水寒", "第五人格", "永劫无间", "燕云十六声"),
    "米哈游": ("米哈游", "原神", "崩坏：星穹铁道", "崩坏星穹铁道", "绝区零"),
    "世纪华通": ("世纪华通", "盛趣游戏"),
    "三七互娱": ("三七互娱",),
    "恺英网络": ("恺英网络",),
    "完美世界游戏": ("完美世界游戏", "完美世界手游"),
    "莉莉丝游戏": ("莉莉丝游戏", "剑与远征"),
    "叠纸游戏": ("叠纸游戏", "恋与深空", "无限暖暖"),
    "鹰角网络": ("鹰角网络", "明日方舟"),
}

GAME_PROFILES = {
    "中国手游出海": "中国手游出海覆盖SLG、合成经营、动作、塔防和休闲等品类，主要观察海外收入、下载、区域市场结构及长线内容运营表现。",
    "腾讯游戏": "腾讯游戏覆盖MOBA、射击、动作和长线运营手游，微信、QQ及应用宝等渠道使其产品变动具有较广用户和渠道影响。",
    "网易游戏": "网易游戏覆盖MMO、竞技、派对和长线运营产品，产品同时面向国内市场与海外发行，重大调整通常涉及较大规模的研发和运营资源。",
    "米哈游": "米哈游以原神、崩坏系列和绝区零等跨平台产品为核心，采用全球同步内容更新与长期运营模式。",
    "世纪华通": "世纪华通旗下盛趣游戏等业务覆盖端游与手游，拥有多款持续运营时间较长的网络游戏产品。",
    "三七互娱": "三七互娱以手游研发、发行和买量运营为主要业务，产品覆盖国内及海外市场。",
    "恺英网络": "恺英网络的游戏业务覆盖研发、发行与IP产品运营，重点布局长线手游和IP改编产品。",
    "完美世界游戏": "完美世界游戏覆盖端游、手游和多平台产品，核心能力包括MMO研发、IP运营及海外发行。",
    "莉莉丝游戏": "莉莉丝游戏以策略和放置类手游见长，多个产品采用全球化发行与长线内容运营。",
    "叠纸游戏": "叠纸游戏聚焦女性向与跨平台产品，核心产品包括恋与深空和无限暖暖。",
    "鹰角网络": "鹰角网络围绕明日方舟等产品开展研发、内容运营和IP衍生业务。",
}

MAJOR_EVENT_TERMS = {
    "停服": 30,
    "停止运营": 30,
    "关停": 28,
    "下架": 26,
    "处罚": 30,
    "监管": 22,
    "未成年人": 22,
    "收购": 26,
    "并购": 26,
    "出售": 24,
    "控制权": 30,
    "裁员": 24,
    "数据泄露": 28,
    "版号": 18,
    "公测": 18,
    "正式上线": 18,
    "流水": 18,
    "用户规模": 16,
}

SCOPE_TERMS = ("全球", "全国", "全平台", "破亿", "亿元", "千万用户", "百万用户", "同时在线")
GAME_CONTEXT = ("国产游戏", "网络游戏", "手游", "端游", "游戏产品", "游戏公司", "游戏业务", "玩家")
DIGEST_TITLE_TERMS = ("榜单", "排行榜", "收入榜", "畅销榜", "Top", "TOP", "盘点", "周报", "月报", "观察")
MARKET_REPORT_TITLE_TERMS = ("出海收入榜", "手游收入榜", "出海下载榜", "海外收入榜")
MARKET_DATA_AGENCIES = ("Sensor Tower", "点点数据", "七麦数据", "data.ai")


def _entity(text: str) -> str | None:
    for entity, aliases in GAME_ENTITIES.items():
        if any(alias in text for alias in aliases):
            return entity
    return None


def fallback_signature(assessment: Assessment) -> str | None:
    entity = next((term for term in assessment.matched_terms if term in GAME_PROFILES), None)
    return f"国产网游|{entity}|{assessment.category}" if entity else None


def cluster_game_fallback(rows: list[tuple[NewsItem, Assessment]]) -> list[tuple[NewsItem, Assessment]]:
    clusters: dict[str, list[tuple[NewsItem, Assessment]]] = {}
    for item, assessment in rows:
        signature = fallback_signature(assessment) or item.title
        clusters.setdefault(signature, []).append((item, assessment))

    merged: list[tuple[NewsItem, Assessment]] = []
    for cluster in clusters.values():
        primary_item, primary_assessment = min(
            cluster,
            key=lambda row: (row[1].source_tier, -row[1].score, -row[0].published_at.timestamp()),
        )
        other_sources = list(
            dict.fromkeys(
                item.source_name for item, _ in cluster if item.source_name != primary_item.source_name
            )
        )
        if other_sources:
            primary_assessment.corroborating_sources = other_sources
            primary_assessment.score = min(100, primary_assessment.score + min(6, len(other_sources) * 2))
        merged.append((primary_item, primary_assessment))
    return merged


def assess_game_fallback(
    item: NewsItem,
    now: datetime | None = None,
    allow_minor: bool = False,
) -> Assessment | None:
    now = now or datetime.now(timezone.utc)
    text = f"{item.title} {item.summary} {item.source_name}"
    if any(term in text for term in SPAM_TERMS):
        return None
    is_market_report = (
        any(term in item.title for term in MARKET_REPORT_TITLE_TERMS)
        and any(agency.lower() in text.lower() for agency in MARKET_DATA_AGENCIES)
        and "手游" in text
    )
    if any(term in item.title for term in DIGEST_TITLE_TERMS) and not is_market_report:
        return None
    entity = "中国手游出海" if is_market_report else _entity(item.title)
    event_matches = ["市场榜单"] if is_market_report else [term for term in MAJOR_EVENT_TERMS if term in text]
    if not entity or (not event_matches and not allow_minor):
        return None
    if not is_market_report and not any(term in text for term in GAME_CONTEXT):
        return None

    source_tier, source_label = classify_source(item)
    event_score = 30 if is_market_report else min(30, sum(MAJOR_EVENT_TERMS[term] for term in event_matches)) if event_matches else 0
    if source_tier >= 4 or (not allow_minor and source_tier == 3 and event_score < 24):
        return None
    scope_score = min(10, sum(5 for term in SCOPE_TERMS if term in text))
    source_score = {1: 17, 2: 14, 3: 10}[source_tier]
    age_hours = max(0, (now - item.published_at).total_seconds() / 3600)
    freshness_score = 8 if age_hours <= 6 else 6 if age_hours <= 24 else 4 if age_hours <= 72 else 0
    score = min(100, 35 + event_score + scope_score + source_score + freshness_score)
    category = "市场数据" if is_market_report else "产品运营" if not event_matches else (
        "产品运营"
        if any(term in event_matches for term in ("停服", "停止运营", "关停", "下架", "公测", "正式上线", "流水", "用户规模"))
        else "资本组织"
        if any(term in event_matches for term in ("收购", "并购", "出售", "控制权", "裁员"))
        else "监管安全"
    )
    level = "S" if score >= 88 else "A" if score >= 70 else "B"
    return Assessment(True, score, level, category, source_tier, source_label, [entity, *event_matches], [], [])


def _event_summary(item: NewsItem, assessment: Assessment) -> str:
    markers = [term for term in assessment.matched_terms if term in MAJOR_EVENT_TERMS]
    entity = next((term for term in assessment.matched_terms if term in GAME_PROFILES), "相关游戏业务")
    if assessment.category == "市场数据":
        return _trim(item.summary or item.title.rstrip("。！？；") + "。", 220)
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
        key=lambda sentence: (entity in sentence) * 5 + sum(marker in sentence for marker in markers) * 3,
        reverse=True,
    )
    selected = [sentence for sentence in ranked if entity in sentence or any(marker in sentence for marker in markers)]
    if selected:
        return _trim("".join(selected[:2]), 220)
    objective_title = neutralize_headline(item.title, entity)
    return _trim(f"报道显示，{objective_title.rstrip('。！？；')}。具体范围和执行安排以正式信息为准。", 220)


def format_game_fallback(item: NewsItem, assessment: Assessment, security_keyword: str) -> tuple[str, str]:
    entity = next(term for term in assessment.matched_terms if term in GAME_PROFILES)
    title = _trim(neutralize_headline(item.title, entity), 70)
    impact = {
        "产品运营": [
            "头部产品的上线、下架或运营调整会直接影响大规模用户迁移、渠道资源和同品类竞争节奏。",
            "需结合实际用户规模、平台范围和后续版本投入判断影响，不能只依据单一传播数据。",
        ],
        "资本组织": [
            "头部厂商的资产和团队调整会改变研发预算、发行资源及重点品类的竞争强度。",
            "实际行业影响取决于产品、核心团队、IP和发行体系是否随交易或组织调整发生迁移。",
        ],
        "监管安全": [
            "头部产品覆盖用户广，监管或安全事件可能同步影响产品设计、渠道审核和行业合规执行。",
            "应以正式文件、处罚决定或企业公告确定适用范围和整改要求。",
        ],
        "市场数据": [
            "出海收入与下载榜可以反映区域上线、版本活动和买量节奏的阶段性效果，但不能替代完整流水和利润数据。",
            "应结合收入来源地区、产品生命周期和统计口径判断增长质量，避免只依据单月排名得出长期结论。",
        ],
    }[assessment.category]
    impacts = "\n".join(f"- {point}" for point in impact)
    sources = [item.source_name, *assessment.corroborating_sources]
    source_text = "、".join(list(dict.fromkeys(source for source in sources if source))[:3])
    published = item.published_at.astimezone(CHINA_TZ).strftime("%m-%d %H:%M")
    markdown = f"""### {title}

**核心事件**  
{_event_summary(item, assessment)}

**业务体量**  
{GAME_PROFILES[entity]}

**行业影响**  
{impacts}

{security_keyword}：{source_text}｜{published}  
[原文]({item.url})
"""
    return title, markdown
