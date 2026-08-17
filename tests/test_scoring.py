from datetime import datetime, timedelta, timezone

from newsbot.formatter import format_markdown
from newsbot.app import _cluster_assessments
from newsbot.models import NewsItem
from newsbot.scoring import assess


def make_item(title: str, summary: str, url: str = "https://www.szse.cn/example") -> NewsItem:
    return NewsItem(
        title=title,
        summary=summary,
        url=url,
        source_name="深圳证券交易所",
        feed_name="test",
        published_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )


def test_major_qipai_transaction_is_high_priority() -> None:
    item = make_item(
        "某公司拟出售闲来麻将运营主体股权",
        "本次资产处置涉及棋牌游戏核心产品控制权变更及团队调整。",
    )
    result = assess(item, ["闲来麻将"])
    assert result.relevant
    assert result.category == "资本与组织"
    assert result.level in {"S", "A"}
    assert result.source_tier == 1


def test_unrelated_finance_story_is_filtered() -> None:
    item = make_item("某银行完成股权融资", "该银行计划扩大信贷规模。")
    result = assess(item, [])
    assert not result.relevant
    assert result.score == 0


def test_message_uses_professional_sections_and_keyword() -> None:
    item = make_item(
        "地方棋牌游戏平台因代理抽水涉赌被查",
        "警方通报该平台通过代理层级组织上下分并从牌局抽水。",
        "https://www.gov.cn/example",
    )
    result = assess(item, [])
    title, markdown = format_markdown(item, result, "信源")
    assert "信源" not in title
    assert "案情要点" in markdown
    assert "风险链路" in markdown
    assert "行业影响" in markdown
    assert "信源：" in markdown
    assert "代理抽水" in markdown
    assert "为什么重要" not in markdown
    assert "综合评分" not in markdown
    assert "命中要素" not in markdown
    assert "信源与核验" not in markdown
    assert "接下来关注" not in markdown


def test_betting_seo_pollution_is_filtered() -> None:
    item = make_item(
        "某体育官网发布棋牌游戏合规白皮书",
        "欢迎前往官网下载并领取送彩金。",
    )
    result = assess(item, [])
    assert not result.relevant
    assert result.category == "疑似博彩SEO污染"


def test_same_company_event_is_clustered_across_sources() -> None:
    first = NewsItem(
        title="闲徕互娱股权出售",
        summary="棋牌游戏核心资产出售",
        url="https://example.com/first",
        source_name="普通媒体",
        feed_name="test",
        published_at=datetime.now(timezone.utc) - timedelta(hours=3),
    )
    second = NewsItem(
        title="昆仑万维转让闲徕互娱",
        summary="出售棋牌游戏公司股权",
        url="https://www.stcn.com/example",
        source_name="证券时报",
        feed_name="test",
        published_at=first.published_at + timedelta(hours=2),
    )
    rows = [(first, assess(first, ["闲徕互娱"])), (second, assess(second, ["闲徕互娱"]))]
    clustered = _cluster_assessments(rows, ["闲徕互娱"])
    assert len(clustered) == 1
    assert clustered[0][0].source_name == "证券时报"
    assert clustered[0][1].corroborating_sources == ["普通媒体"]


def test_transaction_summary_ignores_unrelated_listing_paragraph() -> None:
    item = NewsItem(
        title="昆仑万维筹划赴港上市，拟清空所持闲徕互娱股权套现7.5亿元",
        summary=(
            "昆仑万维计划发行H股并申请在港交所上市。"
            "公司拟以7.5亿元出售闲徕互娱99%股权，交易完成后不再持有其股权。"
        ),
        url="https://example.com/transaction",
        source_name="测试媒体",
        feed_name="test",
        published_at=datetime.now(timezone.utc),
    )
    result = assess(item, ["闲徕互娱"])
    _, markdown = format_markdown(item, result, "信源")
    event_section = markdown.split("**标的画像**", 1)[0]
    assert "闲徕互娱99%股权拟转让，交易对价7.5亿元" in event_section
    assert "计划发行H股" not in event_section


def test_transaction_uses_sale_price_not_historic_purchase_price() -> None:
    item = NewsItem(
        title="37亿元买入后，闲徕互娱99%股权拟7.5亿元出售",
        summary="",
        url="https://example.com/price",
        source_name="测试媒体",
        feed_name="test",
        published_at=datetime.now(timezone.utc),
    )
    result = assess(item, ["闲徕互娱"])
    title, markdown = format_markdown(item, result, "信源")
    assert "对价7.5亿元" in title
    assert "交易对价7.5亿元" in markdown
    assert "对价37亿元" not in title


def test_transaction_includes_company_product_profile() -> None:
    item = make_item(
        "昆仑万维拟转让闲徕互娱股权",
        "交易涉及闲徕互娱控制权变化。",
    )
    result = assess(item, ["闲徕互娱"])
    _, markdown = format_markdown(
        item,
        result,
        "信源",
        {"闲徕互娱": "主营地方麻将与斗地主，采用地方玩法适配和区域化运营。"},
    )
    assert "标的画像" in markdown
    assert "地方麻将与斗地主" in markdown


def test_transaction_ignores_installment_percentage_and_dividend_amount() -> None:
    item = NewsItem(
        title="35亿买入、7.5亿卖出：昆仑万维拟出售闲徕互娱",
        summary=(
            "昆仑万维公告，拟将持有的闲徕互娱99%股权转让，交易对价为7.5亿元。"
            "在此背景下，出售闲徕互娱理由也很充分。"
            "交易采用分期支付，首期支付50%，并代偿约1.96亿元应付股利。"
        ),
        url="https://example.com/transaction-details",
        source_name="游戏陀螺",
        feed_name="test",
        published_at=datetime.now(timezone.utc),
    )
    result = assess(item, ["闲徕互娱"])
    title, markdown = format_markdown(item, result, "信源")
    assert title == "闲徕互娱99%股权拟转让，对价7.5亿元"
    assert "闲徕互娱99%股权拟转让，交易对价7.5亿元。" in markdown
    assert "50%股权" not in markdown
    assert "1.96亿元" not in markdown
    assert "理由也很充分" not in markdown


def test_qipai_relevance_has_larger_score_share() -> None:
    item = make_item("棋牌游戏行业观察", "地方玩法产品动态。", "https://www.stcn.com/example")
    result = assess(item, [])
    assert result.relevant
    assert result.score >= 45


def test_added_gameplay_keywords_are_recognized() -> None:
    keywords = (
        "扑克", "地方棋牌", "棋牌手游", "棋牌小程序", "红中", "同花", "同花顺", "双扣",
        "同心", "炒地皮", "升级", "罗松", "比鸡", "逮狗腿", "保皇", "赖子", "象棋",
        "中国象棋", "五子棋", "围棋", "军棋", "陆战棋", "跳棋", "红五", "川麻", "血流",
        "棋牌室", "桥牌", "德州", "日麻",
    )
    for keyword in keywords:
        item = make_item(f"地方棋牌游戏新增{keyword}玩法", "产品版本已上线。")
        result = assess(item, [])
        assert result.relevant, keyword
        assert keyword in result.matched_terms, keyword


def test_ambiguous_tonghuashun_requires_game_context() -> None:
    item = make_item("同花顺发布证券市场年度报告", "公司持续发展金融信息服务。")
    result = assess(item, [])
    assert not result.relevant


def test_dezhou_place_name_is_not_treated_as_poker() -> None:
    item = make_item(
        "山东落实税费支持政策助企纾困",
        "位于德州市的轮胎企业正在加快生产。",
        "https://www.news.cn/example",
    )
    result = assess(item, [])
    assert not result.relevant


def test_generic_game_upgrade_is_not_treated_as_qipai() -> None:
    item = make_item(
        "王者荣耀电竞赛事体系升级",
        "移动游戏赛事开展品牌联动并正式上线。",
        "https://www.youxituoluo.com/example",
    )
    result = assess(item, [])
    assert not result.relevant


def test_event_keywords_include_tournament_cooperation_and_joint_operation() -> None:
    tournament = assess(make_item("地方棋牌赛事启动", "麻将赛事开放报名。"), [])
    cooperation = assess(make_item("棋牌游戏开展品牌联动", "联动活动已经上线。"), [])
    joint_operation = assess(make_item("棋牌手游签署渠道联运协议", "产品将由双方联合运营。"), [])
    assert tournament.category == "产品与经营"
    assert "赛事" in tournament.matched_terms
    assert cooperation.category == "产品与经营"
    assert "联动" in cooperation.matched_terms
    assert joint_operation.category == "平台与渠道"
    assert "联运" in joint_operation.matched_terms


def test_qipai_minigame_commercialization_has_high_priority() -> None:
    item = make_item(
        "棋牌买量小游戏投放增长",
        "一款麻将爆款小游戏采用IAA与IAP混合变现，日活和投放ROI同步提升。",
        "https://www.youxituoluo.com/example",
    )
    result = assess(item, [])
    assert result.relevant
    assert result.category == "平台与渠道"
    assert result.score >= 70
    assert "买量小游戏" in result.matched_terms


def test_chinese_tvb_mahjong_event_clears_current_threshold() -> None:
    item = NewsItem(
        title="TVB麻将健脑大赛进入8月赛程",
        summary="赛事采用传统广东麻将规则，在多个海外城市举行。",
        url="https://freezone.tvbanywhere.com/tc/event/tvbmahjong",
        source_name="TVB官方活动页",
        feed_name="test",
        published_at=datetime.now(timezone.utc),
    )
    result = assess(item, [])
    assert result.relevant
    assert result.source_tier == 2
    assert result.score >= 30
