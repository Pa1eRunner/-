from datetime import datetime, time, timedelta

from newsbot.app import NewsBot
from newsbot.config import load_config
from newsbot.formatter import CHINA_TZ
from newsbot.models import NewsItem
from newsbot.tech_fallback import assess_tech_fallback


class AllowedLanguage:
    allowed = True
    reason = ""


def test_daily_backup_sends_at_most_three_once(monkeypatch) -> None:
    monkeypatch.setattr("newsbot.app.verify_original_chinese", lambda *_: AllowedLanguage())
    bot = NewsBot(load_config("config/config.yaml"), dry_run=True)
    now = datetime.now(CHINA_TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    target_date = now.date() - timedelta(days=1)
    bot.storage.connection.execute(
        "UPDATE metadata SET value=? WHERE key='daily_backup_last_date'",
        ((target_date - timedelta(days=1)).isoformat(),),
    )
    bot.storage.connection.commit()

    rows = (
        ("DeepSeek更新AI开发工具", "DeepSeek面向全球开发者更新模型服务。"),
        ("百度更新文心AI开发工具", "百度面向全国企业客户更新大模型服务。"),
        ("阿里云更新通义AI开发平台", "阿里云面向开发者更新大模型接口。"),
        ("腾讯云更新混元AI服务", "腾讯云面向企业客户更新大模型服务。"),
    )
    for index, (title, summary) in enumerate(rows):
        item = NewsItem(
            title=title,
            url=f"https://www.stcn.com/article/{index}",
            summary=summary,
            source_name="证券时报",
            feed_name="测试",
            published_at=datetime.combine(target_date, time(12, index), CHINA_TZ),
        )
        assessment = assess_tech_fallback(item, allow_minor=True)
        assert assessment is not None
        bot.storage.save(item, assessment, candidate_kind="tech")

    assert bot._run_daily_backup(now) == 3
    assert bot._run_daily_backup(now) == 0
    bot.close()
