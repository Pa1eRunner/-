from __future__ import annotations

import re
from datetime import timedelta, timezone

from .models import Assessment, NewsItem
from .quality import is_low_information_sentence, neutralize_headline

CHINA_TZ = timezone(timedelta(hours=8))

CATEGORY_MARKERS = {
    "监管与合规": ("处罚", "整改", "监管", "新规", "版号", "未成年人", "实名制"),
    "司法与黑灰产": ("开设赌场", "涉赌", "赌博", "洗钱", "抓获", "判刑", "外挂"),
    "资本与组织": ("控制权", "出售", "转让", "清空", "股权", "收购", "并购", "停服", "上市"),
    "产品与经营": ("停服", "关停", "下架", "上线", "流水", "用户", "收入", "亏损"),
    "平台与渠道": ("微信小游戏", "小游戏", "应用商店", "买量", "广告", "支付", "抽成"),
    "技术与生态": ("反作弊", "安全漏洞", "数据泄露", "AI", "人工智能", "出海"),
}

CATEGORY_SECTIONS = {
    "监管与合规": ("政策要点", "适用边界", "业务影响"),
    "司法与黑灰产": ("案情要点", "风险链路", "行业影响"),
    "资本与组织": ("交易要点", "标的画像", "行业影响"),
    "产品与经营": ("产品动态", "业务背景", "经营影响"),
    "平台与渠道": ("规则变化", "渠道背景", "经营影响"),
    "技术与生态": ("技术动态", "应用场景", "业务影响"),
}


def _trim(value: str, length: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= length else f"{value[:length - 1]}…"


def _primary_entity(assessment: Assessment) -> str:
    for term in assessment.matched_terms:
        if len(term) >= 4 and term not in CATEGORY_MARKERS.get(assessment.category, ()):
            return term
    return "相关棋牌业务"


def _transaction_facts(item: NewsItem, assessment: Assessment) -> tuple[str, str | None, str | None]:
    entity = _primary_entity(assessment)
    sentences = [item.title, *re.split(r"(?<=[。！？；])|\n", item.summary or "")]
    transaction_markers = ("出售", "转让", "卖出", "交易对价", "交易价格", "作价")
    excluded_markers = ("首期", "余款", "应付股利", "分期支付", "历史投入", "累计耗资")

    def sentence_score(sentence: str) -> int:
        score = 0
        score += 8 if entity in sentence else 0
        score += 6 * sum(marker in sentence for marker in transaction_markers)
        score += 5 if re.search(r"\d+(?:\.\d+)?%\s*股权", sentence) else 0
        score += 4 if re.search(r"\d+(?:\.\d+)?亿(?:元)?", sentence) else 0
        score += 4 if "公告" in sentence else 0
        score -= 10 * sum(marker in sentence for marker in excluded_markers)
        score -= 8 if sentence.startswith(("在此背景下", "一方面", "另一方面", "对于")) else 0
        return score

    candidates = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip() and any(marker in sentence for marker in transaction_markers)
    ]
    fact_sentence = max(candidates, key=sentence_score, default=item.title)
    percentage_match = re.search(r"(\d+(?:\.\d+)?%)\s*股权", fact_sentence)
    amount_patterns = (
        r"(?:交易对价(?:为)?|交易价格(?:为)?|作价|以)\s*(\d+(?:\.\d+)?亿(?:元)?)",
        r"(\d+(?:\.\d+)?亿(?:元)?)\s*(?:卖出|出售|转让)",
        r"(?:卖出|出售|转让)[^。；，]{0,24}?(\d+(?:\.\d+)?亿(?:元)?)",
    )
    amount = None
    for pattern in amount_patterns:
        matches = re.findall(pattern, fact_sentence)
        if matches:
            amount = matches[-1]
            break
    if amount is None:
        amounts = re.findall(r"\d+(?:\.\d+)?亿(?:元)?", fact_sentence)
        amount = amounts[-1] if amounts else None
    if amount and amount.endswith("亿"):
        amount += "元"
    return entity, percentage_match.group(1) if percentage_match else None, amount


def _headline(item: NewsItem, assessment: Assessment) -> str:
    entity = _primary_entity(assessment)
    text = f"{item.title} {item.summary}"
    if assessment.category == "资本与组织" and any(term in text for term in ("出售", "转让", "清空", "股权")):
        entity, percentage, amount = _transaction_facts(item, assessment)
        details = percentage or ""
        details += "股权拟转让"
        if amount:
            details += f"，对价{amount}"
        return _trim(f"{entity}{details}", 70)
    return _trim(neutralize_headline(item.title, entity), 70)


def _event_summary(item: NewsItem, assessment: Assessment) -> str:
    text = f"{item.title} {item.summary}"
    if assessment.category == "资本与组织" and any(term in text for term in ("出售", "转让", "卖出", "股权")):
        entity, percentage, amount = _transaction_facts(item, assessment)
        fact = f"{entity}{percentage or ''}股权拟转让"
        if amount:
            fact += f"，交易对价{amount}"
        return f"{fact}。"

    summary = " ".join((item.summary or "").split())
    markers = [term for term in CATEGORY_MARKERS.get(assessment.category, ()) if term in item.title]
    dominant = [term for term in markers if term not in {"上市", "收入", "用户"}] or markers
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？；])", summary)
        if sentence.strip()
        and re.sub(r"\W", "", sentence.lower()) != re.sub(r"\W", "", item.title.lower())
        and not is_low_information_sentence(sentence)
    ]
    ranked: list[tuple[int, str]] = []
    for sentence in sentences:
        marker_hits = sum(3 for marker in markers if marker in sentence)
        entity_hits = sum(4 for term in assessment.matched_terms[:6] if len(term) >= 4 and term in sentence)
        ranked.append((marker_hits + entity_hits, sentence))
    ranked.sort(key=lambda row: row[0], reverse=True)
    selected = [sentence for score, sentence in ranked if score > 0 and (not dominant or any(term in sentence for term in dominant))]
    if selected:
        return _trim("".join(selected[:2]), 220)
    objective_title = neutralize_headline(item.title, _primary_entity(assessment))
    return _trim(f"报道显示，{objective_title.rstrip('。！？；')}。具体范围和执行安排以正式信息为准。", 220)


def _business_impact(item: NewsItem, assessment: Assessment) -> list[str]:
    entity = _primary_entity(assessment)
    text = f"{item.title} {item.summary}"
    if assessment.category == "资本与组织":
        if any(term in text for term in ("出售", "转让", "清空", "控制权", "股权")):
            return [
                f"{entity}的运营主体可能发生变化；对产品的实际影响取决于团队、渠道合作和持续投入是否一并承接。",
                "地方棋牌存量产品换手不会立即改变市场格局，后续版本节奏、区域运营和用户服务更值得关注。",
            ]
        return [f"{entity}的组织调整暂不等于产品策略变化，重点看研发、运营和发行资源是否重新配置。"]
    if assessment.category == "司法与黑灰产":
        return [
            "案件暴露的风险通常集中在代理抽水、上下分、银商兑换和外部支付闭环，应对照现有代理及牌局风控排查。",
            "需区分涉案团伙行为与平台责任，警方通报和后续判决中的资金链、技术链认定最关键。",
        ]
    if assessment.category == "监管与合规":
        return ["重点检查新要求是否触及组局、虚拟道具、未保、实名和付费链路，并明确产品改造范围。"]
    if assessment.category == "产品与经营":
        return ["直接影响集中在版本维护、账号及虚拟资产处理、渠道包状态和地方玩法用户迁移。"]
    if assessment.category == "平台与渠道":
        return ["重点影响获客成本、小游戏入口、分享裂变、支付转化和广告素材审核。"]
    return ["关注该变化能否改善牌局公平、团伙识别和运营效率，而不只看技术概念。"]


def _industry_context(
    item: NewsItem,
    assessment: Assessment,
    company_profiles: dict[str, str],
) -> str:
    text = f"{item.title} {item.summary}"
    for company, profile in company_profiles.items():
        if company in text or company in assessment.matched_terms:
            return _trim(profile, 260)
    return {
        "监管与合规": "棋牌产品的合规差异主要落在地方组局、虚拟道具、代理推广和付费链路，需先确认文件是否直接覆盖相关业务形态。",
        "司法与黑灰产": "此类案件的关键不是棋牌玩法本身，而是代理组织牌局、平台外上下分、银商兑换和抽水获利是否形成闭环。",
        "资本与组织": "地方棋牌公司的核心资产通常包括区域玩法产品、存量用户、代理网络、研发运营团队及持续服务能力，股权变更不等于产品立即退出市场。",
        "产品与经营": "地方棋牌高度依赖区域玩法适配、熟人组局和长期运营，单一版本动作需要结合覆盖地区、用户迁移和渠道状态判断。",
        "平台与渠道": "棋牌产品对小游戏入口、社交裂变、支付能力和广告审核较敏感，渠道规则变化会直接影响获客与转化效率。",
        "技术与生态": "棋牌技术价值主要体现在反作弊、团伙识别、牌局公平和运营提效，应以真实部署范围与效果衡量。",
    }.get(assessment.category, "需结合产品、用户、渠道和运营主体判断其实际行业影响。")


def format_markdown(
    item: NewsItem,
    assessment: Assessment,
    security_keyword: str,
    company_profiles: dict[str, str] | None = None,
) -> tuple[str, str]:
    headline = _headline(item, assessment)
    title = headline
    event_heading, context_heading, impact_heading = CATEGORY_SECTIONS.get(
        assessment.category,
        ("事件要点", "业务背景", "行业影响"),
    )
    impacts = "\n".join(f"- {point}" for point in _business_impact(item, assessment))
    sources = [item.source_name, *assessment.corroborating_sources]
    source_text = "、".join(list(dict.fromkeys(source for source in sources if source))[:3])
    published = item.published_at.astimezone(CHINA_TZ).strftime("%m-%d %H:%M")
    markdown = f"""### {title}

**{event_heading}**  
{_event_summary(item, assessment)}

**{context_heading}**  
{_industry_context(item, assessment, company_profiles or {})}

**{impact_heading}**  
{impacts}

{security_keyword}：{source_text}｜{published}  
[原文]({item.url})
"""
    return title, markdown
