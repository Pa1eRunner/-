from datetime import datetime, timedelta, timezone

from newsbot.models import Assessment, NewsItem
from newsbot.storage import Storage


def test_recent_sent_event_is_suppressed(tmp_path) -> None:
    storage = Storage(str(tmp_path / "test.sqlite3"))
    item = NewsItem(
        title="闲徕互娱出售",
        url="https://example.com/one",
        summary="",
        source_name="测试",
        feed_name="测试",
        published_at=datetime.now(timezone.utc),
    )
    assessment = Assessment(True, 80, "A", "资本与组织", 2, "二级信源", ["闲徕互娱"], [], [])
    storage.save(item, assessment, sent=True, event_signature="资本与组织|闲徕互娱")
    later = NewsItem(
        title="昆仑万维转让闲徕互娱",
        url="https://example.com/two",
        summary="",
        source_name="测试二",
        feed_name="测试",
        published_at=item.published_at + timedelta(hours=2),
    )
    assert storage.was_event_sent_recently("资本与组织|闲徕互娱", later)
    storage.close()


def test_lower_threshold_requeues_only_previously_below_threshold_items(tmp_path) -> None:
    storage = Storage(str(tmp_path / "threshold.sqlite3"))
    storage.sync_push_threshold(55, 72)
    now = datetime.now(timezone.utc)
    for index, (score, sent) in enumerate(((40, False), (60, False), (40, True), (20, False))):
        item = NewsItem(
            title=f"棋牌新闻{index}",
            url=f"https://example.com/{index}",
            summary="",
            source_name="测试",
            feed_name="测试",
            published_at=now,
        )
        assessment = Assessment(True, score, "B", "产品与经营", 2, "二级信源", ["棋牌"], [], [])
        storage.save(item, assessment, sent=sent)

    assert storage.sync_push_threshold(30, 72) == 1
    remaining_scores = storage.connection.execute(
        "SELECT score, sent_at IS NOT NULL FROM news_items ORDER BY score, sent_at"
    ).fetchall()
    assert remaining_scores == [(20, 0), (40, 1), (60, 0)]
    storage.close()


def test_daily_backup_candidates_are_claimed_once_and_can_be_marked_sent(tmp_path) -> None:
    storage = Storage(str(tmp_path / "daily.sqlite3"))
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    item = NewsItem(
        title="DeepSeek更新AI开发工具",
        url="https://www.stcn.com/article/example",
        summary="面向开发者更新模型服务。",
        source_name="证券时报",
        feed_name="测试",
        published_at=start + timedelta(hours=2),
    )
    assessment = Assessment(True, 52, "C", "模型与算力", 2, "二级信源", ["DeepSeek"], [], [])
    storage.save(item, assessment, candidate_kind="tech")

    rows = storage.load_unsent_candidates(start, start + timedelta(days=1))
    assert len(rows) == 1
    assert rows[0][1] == "tech"
    storage.initialize_daily_backup_date("2026-08-12")
    assert not storage.is_daily_backup_complete("2026-08-13")
    assert storage.record_daily_backup_sent("2026-08-13", 2, 3) == 2
    assert not storage.is_daily_backup_complete("2026-08-13")
    assert storage.record_daily_backup_sent("2026-08-13", 1, 3) == 3
    assert storage.is_daily_backup_complete("2026-08-13")

    storage.mark_sent(item, "国内科技|DeepSeek|模型与算力")
    assert storage.sent_count_between(start, start + timedelta(days=1)) == 1
    storage.close()
