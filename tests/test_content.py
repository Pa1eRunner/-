from datetime import datetime, timezone

from newsbot.content import enrich_summary_from_original
from newsbot.models import Assessment, NewsItem


class FakeResponse:
    text = """
    <html><body><h1>DeepSeek也扛不住了？API将涨价</h1>
    <p>8月6日，DeepSeek发布公告称，计划近期整体上调API服务定价，具体方案以正式通知为准。</p>
    <p>有分析人士认为，DeepSeek调整价格是行业竞争变化的结果。</p>
    <p>8月6日，DeepSeek发布公告称，计划近期整体上调API服务定价，具体方案以正式通知为准。</p>
    <p>调整将涉及模型调用成本和高峰时段计费安排。</p>
    </body></html>
    """

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    trust_env = True

    def get(self, *args, **kwargs):
        return FakeResponse()


class OldArticleResponse(FakeResponse):
    url = "http://www.news.cn/fortune/2022-12/05/example.htm"


class OldArticleSession(FakeSession):
    def get(self, *args, **kwargs):
        return OldArticleResponse()


def test_enriches_missing_summary_from_article_facts(monkeypatch) -> None:
    monkeypatch.setattr("newsbot.content.requests.Session", FakeSession)
    item = NewsItem(
        title="DeepSeek也扛不住了？API将涨价",
        url="https://example.com/article",
        summary="",
        source_name="界面新闻",
        feed_name="测试",
        published_at=datetime.now(timezone.utc),
    )
    assessment = Assessment(True, 80, "A", "平台与业务", 2, "二级信源", ["DeepSeek", "涨价"], [], [])
    enrich_summary_from_original(item, assessment, 5)
    assert "计划近期整体上调API服务定价" in item.summary
    assert "也扛不住了" not in item.summary
    assert item.summary.count("计划近期整体上调API服务定价") == 1
    assert "分析人士认为" not in item.summary


def test_replaces_short_promotional_summary_with_article_fact(monkeypatch) -> None:
    monkeypatch.setattr("newsbot.content.requests.Session", FakeSession)
    item = NewsItem(
        title="DeepSeek API服务调整",
        url="https://example.com/article",
        summary="开放权重正在改变AI游戏规则。",
        source_name="钛媒体",
        feed_name="测试",
        published_at=datetime.now(timezone.utc),
    )
    assessment = Assessment(True, 80, "A", "平台与业务", 2, "二级信源", ["DeepSeek", "调价"], [], [])
    enrich_summary_from_original(item, assessment, 5)
    assert "计划近期整体上调API服务定价" in item.summary
    assert "游戏规则" not in item.summary


def test_corrects_publish_time_from_original_url_even_with_usable_summary(monkeypatch) -> None:
    monkeypatch.setattr("newsbot.content.requests.Session", OldArticleSession)
    item = NewsItem(
        title="中国自动驾驶应用观察",
        url="http://www.news.cn/fortune/2022-12/05/example.htm",
        summary="中国自动驾驶已经进入道路清扫、巡逻和配送等多个实际应用场景。",
        source_name="新华社",
        feed_name="测试",
        published_at=datetime.now(timezone.utc),
    )
    assessment = Assessment(True, 70, "A", "国内科技动态", 2, "二级信源", ["自动驾驶"], [], [])
    enrich_summary_from_original(item, assessment, 5)
    assert item.published_at.year == 2022
    assert item.published_at.month == 12
    assert item.published_at.day == 4


def test_extracts_core_event_time_from_body_when_summary_has_no_date(monkeypatch) -> None:
    monkeypatch.setattr("newsbot.content.requests.Session", FakeSession)
    item = NewsItem(
        title="DeepSeek API服务调整",
        url="https://example.com/article",
        summary="DeepSeek计划调整API服务定价，具体方案以正式通知为准。",
        source_name="界面新闻",
        feed_name="测试",
        published_at=datetime(2026, 8, 17, 3, tzinfo=timezone.utc),
    )
    assessment = Assessment(True, 80, "A", "平台与业务", 2, "二级信源", ["DeepSeek", "调价"], [], [])
    enrich_summary_from_original(item, assessment, 5)
    assert item.core_event_at == datetime(2026, 8, 5, 16, tzinfo=timezone.utc)
