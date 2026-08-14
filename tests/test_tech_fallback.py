from datetime import datetime, timezone

from newsbot.models import NewsItem
from newsbot.quality import quality_issues
from newsbot.tech_fallback import assess_tech_fallback, cluster_tech_fallback, format_tech_fallback


def make_item(title: str, summary: str, source: str = "证券时报") -> NewsItem:
    return NewsItem(
        title=title,
        summary=summary,
        url="https://www.stcn.com/article/example",
        source_name=source,
        feed_name="test",
        published_at=datetime.now(timezone.utc),
    )


def test_accepts_major_ai_model_release() -> None:
    item = make_item(
        "阿里云发布通义千问新一代大模型并全面开源",
        "阿里云面向全球开发者开放模型权重和企业级接口。",
    )
    assessment = assess_tech_fallback(item)
    assert assessment is not None
    assert assessment.score >= 75
    assert assessment.category == "模型与算力"
    assert assessment.matched_terms[0] == "阿里巴巴"


def test_accepts_major_chip_release() -> None:
    item = make_item(
        "华为发布新一代AI芯片并启动量产",
        "该芯片面向全国企业客户和数据中心提供算力。",
    )
    assessment = assess_tech_fallback(item)
    assert assessment is not None
    assert assessment.category == "模型与算力"


def test_accepts_longxin_market_value_milestone_when_fresh() -> None:
    item = make_item(
        "上市首日，长鑫科技市值登顶A股",
        "长鑫科技主营DRAM存储芯片，总市值突破3万亿元。",
        "上海证券报",
    )
    item.url = "https://paper.cnstock.com/html/example"
    assessment = assess_tech_fallback(item)
    assert assessment is not None
    assert assessment.score >= 88
    assert assessment.matched_terms[0] == "长鑫科技"


def test_accepts_deepseek_api_price_increase_when_fresh() -> None:
    item = make_item(
        "DeepSeek确认模型调价，高峰期API价格翻倍",
        "DeepSeek-V4模型服务计费调整，影响企业客户和开发者。",
        "东方财富网",
    )
    item.url = "https://finance.eastmoney.com/a/example.html"
    assessment = assess_tech_fallback(item)
    assert assessment is not None
    assert assessment.score >= 70
    assert assessment.category == "平台与业务"


def test_rewrites_clickbait_title_and_does_not_copy_it_as_summary() -> None:
    item = make_item(
        "DeepSeek也扛不住了?API降价后又将大幅涨价",
        "",
        "界面新闻",
    )
    item.url = "https://www.jiemian.com/article/example"
    assessment = assess_tech_fallback(item)
    assert assessment is not None
    title, markdown = format_tech_fallback(item, assessment, "信源")
    assert title == "DeepSeek拟调整API服务价格"
    assert "也扛不住了" not in markdown
    assert "?" not in title
    assert "报道显示，DeepSeek计划调整API服务定价" in markdown
    assert quality_issues(markdown) == []


def test_rejects_generic_company_news() -> None:
    assert assess_tech_fallback(make_item("阿里巴巴发布购物节活动", "电商平台公布促销规则。")) is None
    assert assess_tech_fallback(make_item("小米发布新款背包", "新品在全国门店销售。")) is None


def test_requires_entity_in_title_and_tech_context() -> None:
    item = make_item("国内大模型完成新一轮融资", "智谱AI获得亿元融资。")
    assert assess_tech_fallback(item) is None
    assert assess_tech_fallback(make_item("腾讯宣布收购零售企业", "交易金额达到百亿元。")) is None


def test_rejects_digest_and_unrated_source() -> None:
    assert assess_tech_fallback(make_item("国内AI公司融资榜单", "智谱AI完成亿元融资。")) is None
    item = make_item("DeepSeek全面开源新模型", "面向全球开发者开放模型权重。", "未知自媒体")
    item.url = "https://example.com/news"
    assert assess_tech_fallback(item) is None


def test_rejects_question_style_explainer_as_breaking_news() -> None:
    item = make_item(
        "从DeepSeek、Kimi到黄仁勋联盟：AI模型开源，到底开了什么？",
        "开放权重正在改变AI游戏规则。",
        "钛媒体",
    )
    item.url = "https://www.tmtpost.com/example"
    assert assess_tech_fallback(item) is None


def test_minor_tech_news_only_enters_daily_backup_pool() -> None:
    item = make_item("百度更新AI开发工具", "百度面向开发者更新模型服务文档。")
    assert assess_tech_fallback(item) is None
    assessment = assess_tech_fallback(item, allow_minor=True)
    assert assessment is not None
    assert assessment.score >= 50


def test_tech_message_passes_quality_gate() -> None:
    item = make_item(
        "百度发布文心新一代大模型",
        "百度发布大模型并向全国企业客户开放云服务接口。",
    )
    assessment = assess_tech_fallback(item)
    assert assessment is not None
    _, markdown = format_tech_fallback(item, assessment, "信源")
    assert "核心事件" in markdown
    assert "主体业务" in markdown
    assert quality_issues(markdown) == []


def test_clusters_same_tech_event_and_prefers_mainstream_source() -> None:
    first = make_item("DeepSeek全面开源新模型", "模型面向全球开发者开放。", "36氪")
    first.url = "https://www.36kr.com/p/example"
    second = make_item("DeepSeek宣布全面开源模型", "模型向全球开发者开放。", "证券时报")
    rows = [(first, assess_tech_fallback(first)), (second, assess_tech_fallback(second))]
    clustered = cluster_tech_fallback([(item, assessment) for item, assessment in rows if assessment])
    assert len(clustered) == 1
    assert clustered[0][0].source_name == "证券时报"
