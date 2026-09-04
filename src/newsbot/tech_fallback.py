from __future__ import annotations

import re
from datetime import datetime, timezone

from .formatter import CHINA_TZ, _trim
from .models import Assessment, NewsItem
from .quality import is_low_information_sentence, neutralize_headline
from .scoring import SPAM_TERMS, classify_source

TECH_ENTITIES = {
    "阿里巴巴": ("阿里巴巴", "阿里云", "通义千问", "通义", "夸克AI"),
    "腾讯": ("腾讯", "腾讯云", "腾讯混元", "混元大模型"),
    "百度": ("百度", "百度智能云", "文心一言", "文心大模型"),
    "字节跳动": ("字节跳动", "火山引擎", "豆包大模型", "豆包AI"),
    "华为": ("华为", "华为云", "盘古大模型", "昇腾"),
    "小米": ("小米", "小米汽车", "澎湃OS"),
    "京东": ("京东", "京东云", "言犀"),
    "蚂蚁集团": ("蚂蚁集团", "蚂蚁数科", "百灵大模型"),
    "DeepSeek": ("DeepSeek", "深度求索"),
    "科大讯飞": ("科大讯飞", "讯飞星火"),
    "智谱AI": ("智谱AI", "智谱", "GLM"),
    "月之暗面": ("月之暗面", "Kimi"),
    "MiniMax": ("MiniMax", "稀宇科技", "海螺AI"),
    "商汤科技": ("商汤科技", "商汤", "日日新大模型"),
    "长鑫科技": ("长鑫科技", "长鑫存储", "CXMT"),
}

AI_NATIVE_ENTITIES = {"DeepSeek", "科大讯飞", "智谱AI", "月之暗面", "MiniMax", "商汤科技"}

TECH_PROFILES = {
    "阿里巴巴": "阿里巴巴的技术业务覆盖阿里云、通义模型体系和企业级AI服务，模型、云资源及开发工具的调整会同时影响开发者和企业客户。",
    "腾讯": "腾讯的技术业务覆盖混元模型、腾讯云、社交与内容平台，AI能力可通过云服务和既有产品体系触达企业与个人用户。",
    "百度": "百度围绕文心模型、百度智能云和搜索等业务部署AI能力，技术发布通常与云服务、开发平台及既有流量入口联动。",
    "字节跳动": "字节跳动通过豆包、火山引擎及内容平台推进AI应用，业务覆盖模型服务、企业开发平台和大规模消费级产品。",
    "华为": "华为的技术体系覆盖昇腾算力、盘古模型、华为云、终端和操作系统，软硬件协同使重大变动具有较长产业链影响。",
    "小米": "小米的技术业务连接手机、汽车、物联网设备和澎湃OS，AI、芯片或系统级调整可跨多个终端品类落地。",
    "京东": "京东的技术业务覆盖云服务、供应链、零售和物流场景，AI能力主要通过企业服务及内部业务系统规模化应用。",
    "蚂蚁集团": "蚂蚁集团围绕金融科技、数据库和行业模型提供技术服务，重大变化可能影响机构客户、开发平台和数据合规体系。",
    "DeepSeek": "DeepSeek聚焦基础模型研发与开放接口，其模型能力、开源策略和推理成本变化会直接影响国内开发者选型。",
    "科大讯飞": "科大讯飞围绕讯飞星火及语音技术布局教育、办公和企业服务，模型迭代与行业应用结合较紧密。",
    "智谱AI": "智谱AI围绕GLM模型、开放平台和企业服务开展业务，模型开源、融资及商业化进展会影响国内大模型供给。",
    "月之暗面": "月之暗面以Kimi等大模型应用和开放平台为核心，产品用户规模、模型能力及融资变化具有行业参考价值。",
    "MiniMax": "MiniMax覆盖文本、语音、视频模型及消费级应用，业务同时面向国内用户、海外市场和开发者。",
    "商汤科技": "商汤科技围绕日日新模型、计算基础设施和行业解决方案开展业务，覆盖企业及公共服务等多类场景。",
    "长鑫科技": "长鑫科技聚焦DRAM存储芯片研发与制造，产能、制程、上市融资和量产节奏会影响国产存储供应及上下游设备材料需求。",
}

MAJOR_EVENT_TERMS = {
    "发布大模型": 24,
    "推出大模型": 24,
    "模型发布": 24,
    "上线新模型": 20,
    "开源模型": 24,
    "模型开源": 24,
    "全面开源": 26,
    "发布芯片": 26,
    "芯片发布": 26,
    "芯片量产": 28,
    "启动量产": 24,
    "发布操作系统": 24,
    "系统开源": 22,
    "机器人量产": 24,
    "自动驾驶获批": 24,
    "收购": 26,
    "并购": 26,
    "控制权": 30,
    "上市": 22,
    "IPO": 22,
    "融资": 20,
    "战略投资": 18,
    "裁员": 24,
    "业务关停": 28,
    "停止服务": 30,
    "下架": 26,
    "监管处罚": 30,
    "反垄断": 28,
    "数据泄露": 30,
    "安全漏洞": 28,
    "市值登顶": 24,
    "市值突破": 20,
    "价格翻倍": 26,
    "价格上调": 24,
    "价格调整": 22,
    "计费调整": 22,
    "调价": 22,
    "涨价": 24,
}

SCOPE_TERMS = {
    "全球": 5,
    "全国": 5,
    "全量": 5,
    "全面开放": 5,
    "全平台": 4,
    "亿用户": 8,
    "千万用户": 5,
    "百亿": 8,
    "亿元": 4,
    "核心业务": 5,
    "开发者": 4,
    "企业客户": 4,
    "万亿": 8,
    "A股": 5,
}

TECH_CONTEXT = (
    "人工智能", "大模型", "AI", "云计算", "云服务", "芯片", "算力", "开源模型",
    "智能体", "操作系统", "数据库", "数据中心", "机器人", "自动驾驶", "模型服务",
)
DIGEST_TITLE_TERMS = (
    "榜单", "排行", "盘点", "周报", "月报", "传闻", "预测", "概念股", "到底",
    "为什么", "如何看", "怎么看", "是什么", "一文读懂", "深度解读",
)


def _contains(text: str, term: str) -> bool:
    if term == "AI":
        return bool(re.search(r"(?<![A-Za-z])AI(?![A-Za-z])", text, re.IGNORECASE))
    return term.lower() in text.lower()


def _entity(title: str) -> str | None:
    for entity, aliases in TECH_ENTITIES.items():
        if any(_contains(title, alias) for alias in aliases):
            return entity
    return None


def tech_fallback_signature(assessment: Assessment) -> str | None:
    entity = next((term for term in assessment.matched_terms if term in TECH_PROFILES), None)
    return f"国内科技|{entity}|{assessment.category}" if entity else None


def cluster_tech_fallback(rows: list[tuple[NewsItem, Assessment]]) -> list[tuple[NewsItem, Assessment]]:
    clusters: dict[str, list[tuple[NewsItem, Assessment]]] = {}
    for item, assessment in rows:
        signature = tech_fallback_signature(assessment) or item.title
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


def assess_tech_fallback(
    item: NewsItem,
    now: datetime | None = None,
    allow_minor: bool = False,
) -> Assessment | None:
    now = now or datetime.now(timezone.utc)
    text = f"{item.title} {item.summary} {item.source_name}"
    if any(term in text for term in SPAM_TERMS) or any(term in item.title for term in DIGEST_TITLE_TERMS):
        return None

    entity = _entity(item.title)
    if not entity:
        return None
    has_tech_context = entity in AI_NATIVE_ENTITIES or any(_contains(text, term) for term in TECH_CONTEXT)
    if not has_tech_context:
        return None

    event_matches = [term for term in MAJOR_EVENT_TERMS if _contains(text, term)]
    if not event_matches and not allow_minor:
        return None
    event_score = min(30, sum(MAJOR_EVENT_TERMS[term] for term in event_matches)) if event_matches else 0
    scope_matches = [term for term in SCOPE_TERMS if _contains(text, term)]
    scope_score = min(15, sum(SCOPE_TERMS[term] for term in scope_matches))
    if not allow_minor and (event_score < 18 or (event_score < 24 and scope_score < 5)):
        return None

    source_tier, source_label = classify_source(item)
    if source_tier >= 4 or (not allow_minor and source_tier == 3 and event_score < 24):
        return None
    source_score = {1: 17, 2: 14, 3: 10}[source_tier]
    age_hours = max(0, (now - item.published_at).total_seconds() / 3600)
    freshness_score = 8 if age_hours <= 6 else 6 if age_hours <= 24 else 4 if age_hours <= 72 else 0
    score = min(100, 30 + event_score + scope_score + source_score + freshness_score)

    category = (
        "监管与安全"
        if any(term in event_matches for term in ("监管处罚", "反垄断", "数据泄露", "安全漏洞", "下架"))
        else "资本与组织"
        if any(term in event_matches for term in ("收购", "并购", "控制权", "上市", "IPO", "融资", "战略投资", "裁员"))
        else "平台与业务"
        if any(term in event_matches for term in (
            "业务关停", "停止服务", "自动驾驶获批", "价格翻倍", "价格上调",
            "价格调整", "计费调整", "调价", "涨价",
        ))
        else "模型与算力"
    )
    level = "S" if score >= 88 else "A" if score >= 70 else "B"
    matched_terms = [entity, *event_matches, *scope_matches]
    return Assessment(True, score, level, category, source_tier, source_label, matched_terms, [], [])


def _event_summary(item: NewsItem, assessment: Assessment) -> str:
    markers = [term for term in assessment.matched_terms if term in MAJOR_EVENT_TERMS]
    entity = next((term for term in assessment.matched_terms if term in TECH_PROFILES), "相关科技业务")
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
    pricing_terms = {"价格翻倍", "价格上调", "价格调整", "计费调整", "调价", "涨价"}
    if pricing_terms.intersection(markers):
        return _trim(
            f"报道显示，{entity}计划调整API服务定价。具体调整幅度、生效时间和适用时段以正式通知为准。",
            220,
        )
    objective_title = neutralize_headline(item.title, entity)
    return _trim(f"报道显示，{objective_title.rstrip('。！？；')}。相关范围和实施安排以正式信息为准。", 220)


def _headline(item: NewsItem, assessment: Assessment, entity: str) -> str:
    markers = set(assessment.matched_terms)
    pricing_terms = {"价格翻倍", "价格上调", "价格调整", "计费调整", "调价", "涨价"}
    if pricing_terms.intersection(markers):
        timing = "API高峰时段" if "高峰" in f"{item.title} {item.summary}" else "API服务"
        action = "拟调整" if any(term in item.title for term in ("将", "拟", "计划", "即将")) else "调整"
        return _trim(f"{entity}{action}{timing}价格", 70)
    return _trim(neutralize_headline(item.title, entity), 70)


def format_tech_fallback(item: NewsItem, assessment: Assessment, security_keyword: str) -> tuple[str, str]:
    entity = next(term for term in assessment.matched_terms if term in TECH_PROFILES)
    title = _headline(item, assessment, entity)
    impact = {
        "模型与算力": [
            "模型、芯片或基础软件的关键升级会改变推理成本、部署方式和开发者技术选型。",
            "开源许可、可用权重、算力适配、接口价格及实际部署效果决定其产业影响能否落地。",
        ],
        "资本与组织": [
            "大额交易、融资或组织调整会改变研发投入、算力采购和重点产品的推进节奏。",
            "实际影响取决于核心团队、技术资产、客户合同和产品路线是否随之变化。",
        ],
        "监管与安全": [
            "监管或安全事件可能影响模型开放范围、数据处理规则、产品审核和企业采购决策。",
            "适用产品、受影响用户、整改边界及官方处置文件决定事件的实际业务范围。",
        ],
        "平台与业务": [
            "核心服务或平台级变化会影响企业客户、开发者接口及既有产品生态的连续性。",
            "替代方案、迁移安排、服务覆盖和商业化节奏决定上下游承接成本。",
        ],
    }[assessment.category]
    impacts = "\n".join(f"- {point}" for point in impact)
    sources = [item.source_name, *assessment.corroborating_sources]
    source_text = "、".join(list(dict.fromkeys(source for source in sources if source))[:3])
    published = item.published_at.astimezone(CHINA_TZ).strftime("%m-%d %H:%M")
    markdown = f"""### {title}

**核心事件**  
{_event_summary(item, assessment)}

**主体业务**  
{TECH_PROFILES[entity]}

**行业影响**  
{impacts}

{security_keyword}：{source_text}｜{published}  
[原文]({item.url})
"""
    return title, markdown
