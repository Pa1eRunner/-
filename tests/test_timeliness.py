from datetime import datetime, timezone

from newsbot.models import Assessment, NewsItem
from newsbot.timeliness import evaluate_timeliness


def make_assessment() -> Assessment:
    return Assessment(True, 80, "A", "产品与经营", 2, "二级信源", ["王者万象棋", "发布"], [], [])


def test_rejects_fresh_article_recounting_old_core_event() -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=timezone.utc)
    item = NewsItem(
        title="王者万象棋公布预约数据",
        url="https://example.com/news",
        summary="8月7日，王者万象棋在发布会上公布预约数据并宣布后续公测安排。",
        source_name="游戏茶馆",
        feed_name="测试",
        published_at=datetime(2026, 8, 17, 3, 32, tzinfo=timezone.utc),
    )
    result = evaluate_timeliness(item, make_assessment(), 72, 72, now)
    assert not result.allowed
    assert "核心事件时间" in result.reason


def test_accepts_recent_disclosure_even_when_future_launch_is_mentioned() -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=timezone.utc)
    item = NewsItem(
        title="王者万象棋定档9月",
        url="https://example.com/news",
        summary="8月16日，王者万象棋发布公告，宣布产品定档9月。",
        source_name="游戏茶馆",
        feed_name="测试",
        published_at=datetime(2026, 8, 17, 3, 32, tzinfo=timezone.utc),
    )
    assert evaluate_timeliness(item, make_assessment(), 72, 72, now).allowed


def test_rejects_article_whose_original_publish_time_is_old() -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=timezone.utc)
    item = NewsItem(
        title="中国自动驾驶应用观察",
        url="http://www.news.cn/fortune/2022-12/05/example.htm",
        summary="中国自动驾驶开始进入多个应用场景。",
        source_name="新华社",
        feed_name="测试",
        published_at=datetime(2022, 12, 4, 16, tzinfo=timezone.utc),
    )
    result = evaluate_timeliness(item, make_assessment(), 72, 72, now)
    assert not result.allowed
    assert "原文发布时间" in result.reason
