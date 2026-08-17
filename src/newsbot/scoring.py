from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from .models import Assessment, NewsItem

RELEVANCE_TERMS = {
    "棋牌游戏": 25,
    "地方棋牌": 24,
    "棋牌手游": 24,
    "棋牌小程序": 24,
    "棋牌小游戏": 25,
    "棋牌": 16,
    "棋牌室": 18,
    "麻将": 18,
    "斗地主": 18,
    "掼蛋": 18,
    "扑克": 14,
    "桥牌": 14,
    "德州": 16,
    "日麻": 15,
    "中国象棋": 18,
    "象棋": 12,
    "五子棋": 12,
    "围棋": 14,
    "军棋": 12,
    "陆战棋": 13,
    "跳棋": 10,
    "红中": 12,
    "同花": 10,
    "同花顺": 10,
    "双扣": 14,
    "同心": 10,
    "炒地皮": 14,
    "升级": 8,
    "罗松": 12,
    "比鸡": 14,
    "逮狗腿": 14,
    "保皇": 14,
    "赖子": 10,
    "红五": 12,
    "川麻": 16,
    "血流": 14,
    "地方玩法": 14,
    "房卡": 18,
    "金币场": 14,
    "游戏茶苑": 16,
}

CONTEXT_REQUIRED_TERMS = {"红中", "同花", "同花顺", "同心", "升级", "赖子", "德州"}
GAME_CONTEXT_TERMS = ("棋牌", "扑克", "麻将", "斗地主", "牌局", "地方玩法", "纸牌", "扑克牌", "炸金花", "比鸡")

CATEGORY_TERMS = {
    "监管与合规": {
        "版号": 18, "监管": 14, "新规": 18, "征求意见": 14, "处罚": 22,
        "整改": 14, "未成年人": 10, "实名制": 9, "网络游戏管理": 15,
    },
    "司法与黑灰产": {
        "开设赌场": 30, "涉赌": 25, "赌博": 22, "洗钱": 22, "抓获": 16,
        "判刑": 22, "刑事": 18, "外挂": 12, "跑分": 18, "代理推广": 14,
    },
    "资本与组织": {
        "收购": 24, "并购": 24, "出售": 24, "股权": 16, "控制权": 30,
        "融资": 14, "上市": 16, "退市": 24, "裁员": 18, "管理层": 10,
        "商誉减值": 24, "资产处置": 24,
    },
    "产品与经营": {
        "停服": 28, "下架": 24, "上线": 7, "流水": 16, "用户规模": 12,
        "月活": 11, "收入": 8, "利润": 8, "亏损": 10, "关停": 18,
        "新产品": 6, "赛事": 9, "联动": 7, "爆款": 16, "登顶": 14,
        "日活": 12, "留存": 9,
    },
    "平台与渠道": {
        "微信小游戏": 12, "小游戏": 8, "应用商店": 11, "买量": 10,
        "广告平台": 10, "支付渠道": 12, "抽成": 13, "渠道政策": 15,
        "直播": 6, "投放": 7, "联运": 10, "爆款小游戏": 18,
        "买量小游戏": 20, "变现小游戏": 20, "广告变现": 16,
        "混合变现": 16, "IAA": 13, "IAP": 13, "投放素材": 12,
        "获客成本": 11, "ROI": 12,
    },
    "技术与生态": {
        "反作弊": 12, "AI": 7, "人工智能": 7, "安全漏洞": 15,
        "数据泄露": 16, "出海": 8, "算法": 6,
    },
}

TIER_ONE_DOMAINS = (
    ".gov.cn", "gov.cn", "court.gov.cn", "spp.gov.cn", "mps.gov.cn",
    "cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk",
)
TIER_TWO_DOMAINS = (
    "xinhuanet.com", "news.cn", "people.com.cn", "chinanews.com.cn", "sina.com.cn", "stcn.com",
    "cs.com.cn", "cnstock.com", "yicai.com", "21jingji.com", "jiemian.com",
    "thepaper.cn", "caixin.com", "abematv.co.jp", "tvbanywhere.com", "hkmahjong.org",
)
TIER_THREE_DOMAINS = (
    "gamelook.com.cn", "youxituoluo.com", "gamewower.com", "donews.com",
    "sootoo.com", "tmtpost.com", "36kr.com", "eastmoney.com",
)
TIER_TWO_SOURCES = (
    "新华社", "人民日报", "中国新闻网", "证券时报", "中国证券报", "上海证券报",
    "第一财经", "界面新闻", "澎湃新闻", "财新", "财联社", "21世纪经济报道",
    "新华网", "新浪财经", "光明网", "金台资讯", "南方都市报", "国际金融报", "时代周报", "红网",
)
TIER_THREE_SOURCES = (
    "gamelook", "游戏陀螺", "游戏茶馆", "游戏日报", "donews", "钛媒体", "36氪", "东方财富",
)

ANALYSIS_LIBRARY = {
    "监管与合规": [
        "合规边界：核对规则是否直接覆盖棋牌品类、小游戏载体、虚拟道具及概率型玩法，避免把泛游戏要求等同于棋牌专项监管。",
        "产品影响：重点评估实名、未保、付费限额、开房/组局链路和运营活动是否需要同步调整。",
    ],
    "司法与黑灰产": [
        "模式识别：区分平台正常运营与代理抽水、上下分、银商兑换、俱乐部组织化运营等涉赌链条，判断案件是否具有行业可复制性。",
        "风控影响：复核同类玩法的资金闭环、代理层级、异常牌局、设备团伙和外部支付通道，关注侦查机关披露的定罪关键事实。",
    ],
    "资本与组织": [
        "竞争格局：判断交易标的是产品、用户资产、牌照主体、研发团队还是渠道资源，并评估地方棋牌市场集中度与存量用户迁移。",
        "经营质量：拆分交易对价、历史投入、利润承诺、商誉及关联交易，避免仅依据标题判断资产真实质量和退出意图。",
    ],
    "产品与经营": [
        "经营信号：结合产品生命周期、区域渗透、付费结构和赛事/俱乐部运营判断变化属于常规迭代还是业务收缩。",
        "用户影响：关注账号与虚拟资产处置、迁服安排、渠道包状态及核心地方玩法供给，评估用户外溢方向。",
    ],
    "平台与渠道": [
        "流量影响：评估平台规则对获客成本、广告素材审核、小游戏入口、分享裂变和支付转化链路的实际约束。",
        "渠道依赖：比较小游戏、原生包及私域运营的受影响程度，关注政策是否改变棋牌产品的渠道组合和利润结构。",
    ],
    "技术与生态": [
        "技术影响：判断相关能力对牌局公平性、团伙识别、内容审核、客服成本和研发效率的实际改善，而非只看概念性发布。",
        "落地条件：关注训练数据、实时计算成本、误杀率、可解释性以及与现有反作弊策略的联动能力。",
    ],
}

WATCH_LIBRARY = {
    "监管与合规": "观察正式文件、适用范围、实施日期及地方执行口径。",
    "司法与黑灰产": "观察判决书或警方通报中的资金规模、代理层级、技术鉴定及平台责任认定。",
    "资本与组织": "观察正式公告、交割条件、业绩承诺、核心团队去向及产品运营主体变化。",
    "产品与经营": "观察官方公告、渠道状态、用户补偿、版本更新频率及区域用户迁移。",
    "平台与渠道": "观察平台细则、灰度范围、申诉机制及头部产品的实际调整动作。",
    "技术与生态": "观察真实业务指标、部署范围以及是否形成可验证的成本或风控收益。",
}

SPAM_TERMS = (
    "体育官网", "体育网址", "体育平台", "电子娱乐", "备用网址", "送彩金",
    "app下载", "官网下载", "赌博体育", "体育投注", "现金网", "博彩网站",
)


def _contains(text: str, term: str) -> bool:
    if term == "AI":
        return bool(re.search(r"(?<![A-Za-z])AI(?![A-Za-z])", text, re.IGNORECASE))
    return term.lower() in text.lower()


def _contains_relevance(text: str, term: str) -> bool:
    if not _contains(text, term):
        return False
    if term not in CONTEXT_REQUIRED_TERMS:
        return True
    remaining_text = text.lower().replace(term.lower(), " ")
    return any(context.lower() in remaining_text for context in GAME_CONTEXT_TERMS)


def classify_source(item: NewsItem) -> tuple[int, str]:
    host = (urlparse(item.url).hostname or "").lower()
    source = item.source_name.lower()
    if any(host == domain or host.endswith(domain) for domain in TIER_ONE_DOMAINS):
        return 1, "一级信源·官方/公告"
    if any(domain in source for domain in ("公安", "法院", "检察院", "政府", "交易所")):
        return 1, "一级信源·官方机构"
    if any(host.endswith(domain) for domain in TIER_TWO_DOMAINS):
        return 2, "二级信源·主流媒体"
    if any(host.endswith(domain) for domain in TIER_THREE_DOMAINS):
        return 3, "三级信源·行业媒体"
    if any(name.lower() in source for name in TIER_TWO_SOURCES):
        return 2, "二级信源·主流媒体"
    if any(name.lower() in source for name in TIER_THREE_SOURCES):
        return 3, "三级信源·行业/商业媒体"
    return 4, "四级信源·待交叉核验"


def assess(item: NewsItem, companies: list[str], now: datetime | None = None) -> Assessment:
    now = now or datetime.now(timezone.utc)
    text = f"{item.title} {item.summary} {item.source_name}"
    if any(term in text for term in SPAM_TERMS):
        return Assessment(False, 0, "C", "疑似博彩SEO污染", 4, "不可信内容", [], [], [])
    matched_relevance = [term for term in RELEVANCE_TERMS if _contains_relevance(text, term)]
    matched_companies = [company for company in companies if _contains(text, company)]
    relevant = bool(matched_relevance or matched_companies)
    if not relevant:
        return Assessment(False, 0, "C", "非行业舆情", 4, "未评级", [], [], [])

    relevance_score = min(
        45,
        sum(RELEVANCE_TERMS[term] for term in matched_relevance) + min(40, 24 * len(matched_companies)),
    )
    category_scores: dict[str, int] = {}
    event_matches: dict[str, list[str]] = {}
    for category, terms in CATEGORY_TERMS.items():
        matches = [term for term in terms if _contains(text, term)]
        event_matches[category] = matches
        category_scores[category] = min(30, sum(terms[term] for term in matches))
    category = max(category_scores, key=category_scores.get)
    impact_score = category_scores[category]
    if impact_score == 0:
        category = "产品与经营"

    source_tier, source_label = classify_source(item)
    source_score = {1: 17, 2: 14, 3: 10, 4: 4}[source_tier]
    age_hours = max(0, (now - item.published_at).total_seconds() / 3600)
    freshness_score = 8 if age_hours <= 6 else 6 if age_hours <= 24 else 4 if age_hours <= 72 else 0
    score = min(100, relevance_score + impact_score + source_score + freshness_score)
    level = "S" if score >= 88 else "A" if score >= 70 else "B" if score >= 55 else "C"
    matched_terms = list(dict.fromkeys(matched_companies + matched_relevance + event_matches[category]))

    analysis_points = list(ANALYSIS_LIBRARY.get(category, []))
    if source_tier >= 4:
        analysis_points.append("信源约束：当前缺少公告或权威报道背书，不宜据此形成确定性经营结论。")
    watch_points = [WATCH_LIBRARY.get(category, "观察后续权威信息和企业实际动作。")]
    return Assessment(
        relevant=True,
        score=score,
        level=level,
        category=category,
        source_tier=source_tier,
        source_label=source_label,
        matched_terms=matched_terms,
        analysis_points=analysis_points,
        watch_points=watch_points,
    )
