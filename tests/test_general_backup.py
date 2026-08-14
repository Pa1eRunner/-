from datetime import datetime, timezone

from newsbot.daily_backup import assess_general_backup, format_general_backup
from newsbot.models import NewsItem
from newsbot.quality import quality_issues


def make_item(title: str, summary: str) -> NewsItem:
    return NewsItem(
        title=title,
        summary=summary,
        url="https://www.stcn.com/article/example",
        source_name="证券时报",
        feed_name="测试",
        published_at=datetime.now(timezone.utc),
    )


def test_accepts_broad_domestic_game_and_tech_candidates() -> None:
    game = assess_general_backup(make_item("国产游戏新品开启测试", "国内手游公司发布新产品。"))
    tech = assess_general_backup(make_item("国内机器人企业发布新产品", "中国人工智能产业加快商业化。"))
    assert game is not None
    assert game.category == "国产游戏动态"
    assert tech is not None
    assert tech.category == "国内科技动态"


def test_rejects_unrelated_or_unrated_candidates() -> None:
    assert assess_general_backup(make_item("国内商场举办促销", "零售企业开展活动。")) is None
    item = make_item("国产芯片企业发布产品", "国内半导体产业动态。")
    item.url = "https://example.com/news"
    item.source_name = "未知自媒体"
    assert assess_general_backup(item) is None


def test_general_backup_message_passes_quality_gate() -> None:
    item = make_item("国产游戏新品开启测试", "国内手游公司发布新产品并公布运营安排。")
    assessment = assess_general_backup(item)
    assert assessment is not None
    _, markdown = format_general_backup(item, assessment, "信源")
    assert quality_issues(markdown) == []
