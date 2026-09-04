from datetime import datetime, timezone

from newsbot.game_fallback import assess_game_fallback, cluster_game_fallback, format_game_fallback
from newsbot.models import NewsItem
from newsbot.quality import quality_issues


def make_item(title: str, summary: str, source: str = "证券时报") -> NewsItem:
    return NewsItem(
        title=title,
        summary=summary,
        url="https://www.stcn.com/article/example",
        source_name=source,
        feed_name="test",
        published_at=datetime.now(timezone.utc),
    )


def test_accepts_major_head_game_event() -> None:
    item = make_item(
        "腾讯游戏宣布旗下手游全平台正式上线",
        "该网络游戏覆盖全国用户并开启全平台运营。",
    )
    result = assess_game_fallback(item)
    assert result is not None
    assert result.score >= 70
    assert result.matched_terms[0] == "腾讯游戏"


def test_rejects_generic_or_non_head_game_news() -> None:
    assert assess_game_fallback(make_item("腾讯游戏发布日常活动", "手游更新普通活动。")) is None
    assert assess_game_fallback(make_item("某小型游戏公司产品正式上线", "国产手游开启运营。")) is None
    assert assess_game_fallback(make_item("腾讯宣布收购一家金融公司", "交易涉及金融科技业务。")) is None


def test_minor_game_news_only_enters_daily_backup_pool() -> None:
    item = make_item("腾讯游戏更新手游版本", "该网络游戏面向全国玩家更新玩法内容。")
    assert assess_game_fallback(item) is None
    assessment = assess_game_fallback(item, allow_minor=True)
    assert assessment is not None
    assert assessment.score >= 50


def test_accepts_head_company_when_game_context_is_explicit() -> None:
    item = make_item("腾讯宣布收购一家游戏公司", "交易涉及国产游戏和手游发行业务。")
    assert assess_game_fallback(item) is not None


def test_rejects_digest_that_only_mentions_head_company_in_summary() -> None:
    item = make_item(
        "7月出海收入榜：三款游戏进入Top5",
        "榜单同时提到腾讯游戏和网易游戏的手游收入变化及新产品正式上线。",
    )
    assert assess_game_fallback(item) is None


def test_requires_head_entity_in_title() -> None:
    item = make_item(
        "国产手游市场发生重大并购",
        "腾讯游戏参与交易，涉及亿元规模的游戏业务。",
    )
    assert assess_game_fallback(item) is None


def test_accepts_trusted_mobile_game_export_report() -> None:
    item = make_item(
        "7月中国手游出海收入榜：三款产品进入前五",
        "Sensor Tower发布中国手游海外收入榜，多款国产手游收入环比增长。",
        "游戏陀螺",
    )
    assessment = assess_game_fallback(item)
    assert assessment is not None
    assert assessment.category == "市场数据"
    assert assessment.score >= 70


def test_prioritizes_hit_minigame_buying_and_monetization_news() -> None:
    item = make_item(
        "爆款微信小游戏登顶畅销榜，买量与混合变现同步放量",
        "该小游戏月流水破亿，投放素材、IAA广告变现和IAP内购共同驱动增长。",
        "游戏陀螺",
    )
    assessment = assess_game_fallback(item)
    assert assessment is not None
    assert assessment.matched_terms[0] == "小游戏赛道"
    assert assessment.category == "商业化运营"
    assert assessment.score >= 70
    title, markdown = format_game_fallback(item, assessment, "信源")
    assert title.startswith("爆款微信小游戏")
    assert "小游戏赛道爆款" not in markdown


def test_rejects_minigame_content_without_business_event() -> None:
    item = make_item("微信小游戏新手攻略", "介绍小游戏基础操作和普通关卡技巧。", "游戏陀螺")
    assert assess_game_fallback(item) is None


def test_fallback_message_passes_quality_gate() -> None:
    item = make_item(
        "网易游戏宣布一款网络游戏停止运营",
        "网易游戏公告，该网络游戏将在全平台停止运营，并公布用户资产处理安排。",
    )
    assessment = assess_game_fallback(item)
    assert assessment is not None
    _, markdown = format_game_fallback(item, assessment, "信源")
    assert "核心事件" in markdown
    assert "业务体量" in markdown
    assert quality_issues(markdown) == []


def test_clusters_same_head_game_event() -> None:
    first = make_item("米哈游旗下游戏正式上线", "原神相关网络游戏全平台正式上线。", "游戏陀螺")
    second = make_item("米哈游新游戏正式上线", "原神相关手游全平台正式上线。", "证券时报")
    rows = [(first, assess_game_fallback(first)), (second, assess_game_fallback(second))]
    clustered = cluster_game_fallback([(item, assessment) for item, assessment in rows if assessment])
    assert len(clustered) == 1
    assert clustered[0][0].source_name == "证券时报"
