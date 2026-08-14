from datetime import datetime, timezone

from newsbot.config import SafetyConfig
from newsbot.models import Assessment, NewsItem
from newsbot.safety import evaluate_safety


def make_config() -> SafetyConfig:
    return SafetyConfig(
        political_keywords=["中央政治局"],
        sensitive_people=["敏感姓名"],
        protected_entities=["浙江畅唐", "同元智算", "同城游", "同元创智"],
        unverified_claim_markers=["网传", "被曝"],
        allegation_keywords=["涉嫌", "涉赌", "诈骗"],
    )


def make_item(text: str) -> NewsItem:
    return NewsItem(
        title=text,
        summary="",
        url="https://example.com/news",
        source_name="测试来源",
        feed_name="test",
        published_at=datetime.now(timezone.utc),
    )


def make_assessment(source_tier: int, corroborating_sources: list[str] | None = None) -> Assessment:
    return Assessment(
        relevant=True,
        score=90,
        level="S",
        category="司法与黑灰产",
        source_tier=source_tier,
        source_label="测试",
        matched_terms=[],
        analysis_points=[],
        watch_points=[],
        corroborating_sources=corroborating_sources or [],
    )


def test_blocks_political_and_sensitive_person_content() -> None:
    config = make_config()
    assert not evaluate_safety(make_item("中央政治局相关报道"), make_assessment(1), config).allowed
    assert not evaluate_safety(make_item("敏感姓名出席活动"), make_assessment(1), config).allowed
    assert not evaluate_safety(make_item("某平台创始人张三回应争议"), make_assessment(1), config).allowed


def test_blocks_protected_entity_content() -> None:
    result = evaluate_safety(make_item("同城游业务动态"), make_assessment(1), make_config())
    assert not result.allowed
    assert result.reason == "保护主体相关内容"


def test_blocks_unverified_claims() -> None:
    result = evaluate_safety(make_item("网传某棋牌游戏公司被曝违规"), make_assessment(1), make_config())
    assert not result.allowed


def test_requires_authority_or_corroboration_for_allegations() -> None:
    config = make_config()
    item = make_item("某棋牌游戏平台涉嫌涉赌")
    assert not evaluate_safety(item, make_assessment(3), config).allowed
    assert not evaluate_safety(item, make_assessment(2), config).allowed
    assert evaluate_safety(item, make_assessment(2, ["另一主流媒体"]), config).allowed
    assert evaluate_safety(item, make_assessment(1), config).allowed


def test_allows_clean_industry_news() -> None:
    result = evaluate_safety(make_item("闲徕互娱股权拟转让"), make_assessment(2), make_config())
    assert result.allowed
