from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time
from datetime import datetime, time as datetime_time, timedelta, timezone

from .config import AppConfig, load_config, load_project_environment
from .content import enrich_summary_from_original
from .daily_backup import assess_general_backup, format_general_backup
from .dingtalk import DingTalkClient
from .formatter import CHINA_TZ, format_markdown
from .game_fallback import (
    assess_game_fallback,
    cluster_game_fallback,
    fallback_signature,
    format_game_fallback,
)
from .language import verify_original_chinese
from .quality import quality_issues
from .scoring import assess
from .safety import evaluate_safety
from .sources import fetch_all
from .storage import Storage, fingerprint
from .tech_fallback import (
    assess_tech_fallback,
    cluster_tech_fallback,
    format_tech_fallback,
    tech_fallback_signature,
)

LOGGER = logging.getLogger(__name__)


def _event_signature(assessment, companies: list[str]) -> str | None:
    entities = sorted(company for company in companies if company in assessment.matched_terms)
    if not entities:
        return None
    return f"{assessment.category}|{'|'.join(entities)}"


def _cluster_assessments(
    rows: list[tuple],
    companies: list[str],
) -> list[tuple]:
    clusters: list[list[tuple]] = []
    for item, assessment in rows:
        entities = {company for company in companies if company in assessment.matched_terms}
        target_cluster = None
        if entities:
            for cluster in clusters:
                cluster_item, cluster_assessment = cluster[0]
                cluster_entities = {company for company in companies if company in cluster_assessment.matched_terms}
                hours_apart = abs((item.published_at - cluster_item.published_at).total_seconds()) / 3600
                if assessment.category == cluster_assessment.category and entities & cluster_entities and hours_apart <= 72:
                    target_cluster = cluster
                    break
        if target_cluster is None:
            clusters.append([(item, assessment)])
        else:
            target_cluster.append((item, assessment))

    merged: list[tuple] = []
    preferred_sources = (
        "交易所", "公安", "法院", "检察院", "证券时报", "新华社", "新华网",
        "澎湃", "界面", "中国证券报", "上海证券报", "第一财经", "财联社",
    )

    def source_priority(name: str) -> int:
        for index, source in enumerate(preferred_sources):
            if source in name:
                return index
        return len(preferred_sources)

    def sensational_penalty(title: str) -> int:
        return int(any(term in title for term in ("甩卖", "折价抛售", "亏麻了", "冲击", "信仰充值")))

    for cluster in clusters:
        primary_item, primary_assessment = min(
            cluster,
            key=lambda row: (
                row[1].source_tier,
                source_priority(row[0].source_name),
                sensational_penalty(row[0].title),
                -row[1].score,
                -row[0].published_at.timestamp(),
            ),
        )
        other_sources = list(
            dict.fromkeys(
                item.source_name
                for item, _ in cluster
                if item.source_name != primary_item.source_name
            )
        )
        if other_sources:
            primary_assessment.corroborating_sources = other_sources
            primary_assessment.score = min(100, primary_assessment.score + min(8, len(other_sources) * 2))
            primary_assessment.level = (
                "S" if primary_assessment.score >= 88 else "A" if primary_assessment.score >= 70 else "B"
            )
        merged.append((primary_item, primary_assessment))
    return merged


class NewsBot:
    def __init__(self, config: AppConfig, dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run
        storage_path = ":memory:" if dry_run else config.monitor.database_path
        self.storage = Storage(storage_path)
        requeued = self.storage.sync_push_threshold(
            config.monitor.instant_push_score,
            config.monitor.maximum_item_age_hours,
        )
        if requeued:
            LOGGER.info(
                "Push threshold lowered score=%s requeued=%s",
                config.monitor.instant_push_score,
                requeued,
            )
        self.storage.backfill_event_signatures(config.companies)
        yesterday = datetime.now(CHINA_TZ).date() - timedelta(days=1)
        self.storage.initialize_daily_backup_date(yesterday.isoformat())
        webhook = os.environ.get(config.bot.webhook_env, "")
        self.client = None
        if not dry_run:
            if not webhook:
                raise RuntimeError(f"Environment variable {config.bot.webhook_env} is required")
            self.client = DingTalkClient(
                webhook=webhook,
                security_keyword=config.bot.security_keyword,
                timeout_seconds=config.bot.request_timeout_seconds,
                minimum_send_interval_seconds=config.bot.minimum_send_interval_seconds,
            )

    def run_once(self) -> int:
        initialized = self.storage.is_initialized()
        candidates = fetch_all(
            self.config.feeds,
            self.config.searches,
            self.config.bot.request_timeout_seconds,
        )
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.config.monitor.maximum_item_age_hours)
        ranked = []
        game_fallback_ranked = []
        tech_fallback_ranked = []
        cycle_fingerprints: set[str] = set()
        for item in candidates:
            item_fingerprint = fingerprint(item)
            if item_fingerprint in cycle_fingerprints:
                continue
            cycle_fingerprints.add(item_fingerprint)
            if item.published_at < cutoff or self.storage.exists_or_similar(item):
                continue
            assessment = assess(item, self.config.companies)
            if assessment.relevant:
                signature = _event_signature(assessment, self.config.companies)
                if signature and self.storage.was_event_sent_recently(signature, item):
                    continue
                ranked.append((item, assessment))
            elif self.config.fallback.enabled:
                fallback_assessment = assess_game_fallback(item)
                if fallback_assessment and fallback_assessment.score >= self.config.fallback.minimum_score:
                    signature = fallback_signature(fallback_assessment)
                    if signature and self.storage.was_event_sent_recently(signature, item):
                        continue
                    game_fallback_ranked.append((item, fallback_assessment))
                else:
                    fallback_assessment = assess_tech_fallback(item)
                    if fallback_assessment and fallback_assessment.score >= self.config.fallback.minimum_score:
                        signature = tech_fallback_signature(fallback_assessment)
                        if signature and self.storage.was_event_sent_recently(signature, item):
                            continue
                        tech_fallback_ranked.append((item, fallback_assessment))
                    elif self.config.daily_backup.enabled:
                        backup_assessment = assess_game_fallback(item, allow_minor=True)
                        backup_kind = "game"
                        if backup_assessment is None:
                            backup_assessment = assess_tech_fallback(item, allow_minor=True)
                            backup_kind = "tech"
                        if backup_assessment is None:
                            backup_assessment = assess_general_backup(item)
                            backup_kind = "general"
                        if backup_assessment and backup_assessment.score >= self.config.daily_backup.minimum_score:
                            self.storage.save(
                                item,
                                backup_assessment,
                                candidate_kind=backup_kind,
                            )

        ranked = _cluster_assessments(ranked, self.config.companies)
        ranked.sort(key=lambda pair: pair[1].score, reverse=True)
        game_fallback_ranked = cluster_game_fallback(game_fallback_ranked)
        tech_fallback_ranked = cluster_tech_fallback(tech_fallback_ranked)
        fallback_ranked = [
            *((item, assessment, "game") for item, assessment in game_fallback_ranked),
            *((item, assessment, "tech") for item, assessment in tech_fallback_ranked),
        ]
        fallback_ranked.sort(key=lambda row: row[1].score, reverse=True)
        can_send = initialized or self.config.monitor.send_on_first_run or self.dry_run
        sent_count = 0
        for item, assessment in ranked:
            safety_result = evaluate_safety(item, assessment, self.config.safety)
            should_push = assessment.score >= self.config.monitor.instant_push_score
            should_push = should_push and assessment.source_tier <= 3 and can_send and safety_result.allowed
            sent = False
            if not safety_result.allowed:
                LOGGER.warning(
                    "Safety filter blocked reason=%s source=%s",
                    safety_result.reason,
                    item.source_name,
                )
            if should_push and sent_count < self.config.monitor.maximum_alerts_per_cycle:
                language_result = verify_original_chinese(item.url, self.config.bot.request_timeout_seconds)
                if not language_result.allowed:
                    LOGGER.warning(
                        "Language gate blocked reason=%s source=%s",
                        language_result.reason,
                        item.source_name,
                    )
                else:
                    enrich_summary_from_original(item, assessment, self.config.bot.request_timeout_seconds)
                    title, markdown = format_markdown(
                        item,
                        assessment,
                        self.config.bot.security_keyword,
                        self.config.company_profiles,
                    )
                    issues = quality_issues(markdown)
                    if issues:
                        LOGGER.warning("Quality gate blocked issues=%s source=%s", "; ".join(issues), item.source_name)
                    else:
                        if self.dry_run:
                            print(f"\n{'=' * 72}\n{markdown}")
                        else:
                            assert self.client is not None
                            self.client.send_markdown(title, markdown)
                        sent = True
                        sent_count += 1
                        action = "prepared" if self.dry_run else "sent"
                        LOGGER.info("Alert %s level=%s score=%s title=%s", action, assessment.level, assessment.score, item.title)
            self.storage.save(
                item,
                assessment,
                sent=sent,
                event_signature=_event_signature(assessment, self.config.companies),
                candidate_kind="qipai",
            )

        fallback_sent = {"game": 0, "tech": 0}
        fallback_limits = {
            "game": self.config.fallback.maximum_game_per_cycle,
            "tech": self.config.fallback.maximum_tech_per_cycle,
        }
        fallback_allowed = (
            self.config.fallback.enabled
            and sent_count < self.config.fallback.trigger_when_qipai_sent_below
            and sent_count < self.config.monitor.maximum_alerts_per_cycle
            and can_send
        )
        for item, assessment, fallback_kind in fallback_ranked:
            sent = False
            if fallback_allowed and fallback_sent[fallback_kind] < fallback_limits[fallback_kind]:
                safety_result = evaluate_safety(item, assessment, self.config.safety)
                language_result = verify_original_chinese(item.url, self.config.bot.request_timeout_seconds)
                if not safety_result.allowed:
                    LOGGER.warning("Fallback safety blocked reason=%s source=%s", safety_result.reason, item.source_name)
                elif not language_result.allowed:
                    LOGGER.warning("Fallback language blocked reason=%s source=%s", language_result.reason, item.source_name)
                else:
                    enrich_summary_from_original(item, assessment, self.config.bot.request_timeout_seconds)
                    formatter = format_game_fallback if fallback_kind == "game" else format_tech_fallback
                    title, markdown = formatter(item, assessment, self.config.bot.security_keyword)
                    issues = quality_issues(markdown)
                    if issues:
                        LOGGER.warning("Fallback quality blocked issues=%s source=%s", "; ".join(issues), item.source_name)
                    else:
                        if self.dry_run:
                            print(f"\n{'=' * 72}\n{markdown}")
                        else:
                            assert self.client is not None
                            self.client.send_markdown(title, markdown)
                        sent = True
                        sent_count += 1
                        fallback_sent[fallback_kind] += 1
                        action = "prepared" if self.dry_run else "sent"
                        LOGGER.info(
                            "%s fallback %s level=%s score=%s title=%s",
                            fallback_kind.capitalize(),
                            action,
                            assessment.level,
                            assessment.score,
                            item.title,
                        )
            self.storage.save(
                item,
                assessment,
                sent=sent,
                event_signature=(
                    fallback_signature(assessment)
                    if fallback_kind == "game"
                    else tech_fallback_signature(assessment)
                ),
                candidate_kind=fallback_kind,
            )

        daily_backup_sent = self._run_daily_backup()
        sent_count += daily_backup_sent

        if not initialized:
            self.storage.mark_initialized()
            if not self.config.monitor.send_on_first_run and not self.dry_run:
                LOGGER.info("Initial feed snapshot stored without sending historical alerts")
        LOGGER.info(
            "Cycle complete fetched=%s qipai_new=%s fallback_new=%s sent=%s fallback_sent=%s",
            len(candidates),
            len(ranked),
            len(fallback_ranked),
            sent_count,
            sum(fallback_sent.values()),
        )
        return sent_count

    def _run_daily_backup(self, now: datetime | None = None) -> int:
        if not self.config.daily_backup.enabled:
            return 0
        now = now or datetime.now(CHINA_TZ)
        send_hour, send_minute = (int(part) for part in self.config.daily_backup.send_after.split(":", 1))
        if now.time() < datetime_time(send_hour, send_minute):
            return 0

        target_date = now.date() - timedelta(days=1)
        target_start = datetime.combine(target_date, datetime_time.min, CHINA_TZ)
        target_end = target_start + timedelta(days=1)
        target_key = target_date.isoformat()
        if self.storage.is_daily_backup_complete(target_key):
            return 0
        if self.storage.sent_count_between(target_start, target_end) > 0:
            self.storage.complete_daily_backup_date(target_key)
            LOGGER.info("Daily backup skipped date=%s reason=previous_day_sent", target_date)
            return 0

        progress = self.storage.daily_backup_progress(target_key)
        required_now = self.config.daily_backup.required_items - progress
        if required_now <= 0:
            self.storage.complete_daily_backup_date(target_key)
            return 0

        pool_start = now - timedelta(hours=self.config.monitor.maximum_item_age_hours)
        rows = self.storage.load_unsent_candidates(pool_start, now)
        qipai_rows = []
        game_rows = []
        tech_rows = []
        general_rows = []
        for item, candidate_kind in rows:
            if candidate_kind == "qipai":
                assessment = assess(item, self.config.companies)
                if assessment.relevant:
                    qipai_rows.append((item, assessment))
            elif candidate_kind == "game":
                assessment = assess_game_fallback(item, allow_minor=True)
                if assessment:
                    game_rows.append((item, assessment))
            elif candidate_kind == "tech":
                assessment = assess_tech_fallback(item, allow_minor=True)
                if assessment:
                    tech_rows.append((item, assessment))
            elif candidate_kind == "general":
                assessment = assess_general_backup(item)
                if assessment:
                    general_rows.append((item, assessment))

        ranked = [
            *((item, assessment, "qipai") for item, assessment in _cluster_assessments(qipai_rows, self.config.companies)),
            *((item, assessment, "game") for item, assessment in cluster_game_fallback(game_rows)),
            *((item, assessment, "tech") for item, assessment in cluster_tech_fallback(tech_rows)),
            *((item, assessment, "general") for item, assessment in general_rows),
        ]
        ranked.sort(key=lambda row: (row[1].score, row[0].published_at), reverse=True)

        sent_count = 0
        for item, assessment, candidate_kind in ranked:
            if (
                sent_count >= required_now
                or assessment.score < self.config.daily_backup.minimum_score
                or assessment.source_tier > 3
            ):
                continue
            safety_result = evaluate_safety(item, assessment, self.config.safety)
            if not safety_result.allowed:
                continue
            language_result = verify_original_chinese(item.url, self.config.bot.request_timeout_seconds)
            if not language_result.allowed:
                continue
            enrich_summary_from_original(item, assessment, self.config.bot.request_timeout_seconds)
            if candidate_kind == "qipai":
                title, markdown = format_markdown(
                    item,
                    assessment,
                    self.config.bot.security_keyword,
                    self.config.company_profiles,
                )
                signature = _event_signature(assessment, self.config.companies)
            elif candidate_kind == "game":
                title, markdown = format_game_fallback(item, assessment, self.config.bot.security_keyword)
                signature = fallback_signature(assessment)
            elif candidate_kind == "tech":
                title, markdown = format_tech_fallback(item, assessment, self.config.bot.security_keyword)
                signature = tech_fallback_signature(assessment)
            else:
                title, markdown = format_general_backup(item, assessment, self.config.bot.security_keyword)
                signature = None
            if signature and self.storage.was_event_sent_recently(signature, item):
                continue
            if quality_issues(markdown):
                continue
            if self.dry_run:
                print(f"\n{'=' * 72}\n{markdown}")
            else:
                assert self.client is not None
                self.client.send_markdown(title, markdown)
            self.storage.mark_sent(item, signature)
            self.storage.record_daily_backup_sent(
                target_key,
                1,
                self.config.daily_backup.required_items,
            )
            sent_count += 1
            LOGGER.info(
                "Daily backup sent kind=%s score=%s title=%s",
                candidate_kind,
                assessment.score,
                item.title,
            )
        total = self.storage.daily_backup_progress(target_key)
        LOGGER.info(
            "Daily backup cycle date=%s candidates=%s sent=%s total=%s required=%s",
            target_date,
            len(ranked),
            sent_count,
            total,
            self.config.daily_backup.required_items,
        )
        return sent_count

    def send_connection_test(self) -> None:
        title = f"{self.config.bot.security_keyword}｜机器人连通性测试"
        markdown = f"""### {title}

Webhook 环境变量已成功加载，钉钉消息通道连接正常。

- 消息类型：系统测试
- 业务推送：尚未触发
- 下一步：启动舆情轮询服务
"""
        if self.dry_run:
            print(markdown)
            return
        assert self.client is not None
        self.client.send_markdown(title, markdown)
        LOGGER.info("DingTalk connection test sent successfully")

    def close(self) -> None:
        self.storage.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Qipai industry DingTalk news bot")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--once", action="store_true", help="Run one polling cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print alerts without sending to DingTalk")
    parser.add_argument("--test-webhook", action="store_true", help="Send one DingTalk connection test and exit")
    return parser.parse_args()


def setup_logging(log_path: str) -> None:
    path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    handlers.append(RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"))
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    setup_logging(config.monitor.log_path)
    loaded_env_files = load_project_environment(args.config)
    if loaded_env_files:
        LOGGER.info("Loaded environment file: %s", loaded_env_files[0])
    bot = NewsBot(config, dry_run=args.dry_run)
    try:
        if args.test_webhook:
            bot.send_connection_test()
            return 0
        if args.once or args.dry_run:
            bot.run_once()
            return 0
        while True:
            try:
                bot.run_once()
            except Exception:
                LOGGER.exception("Polling cycle failed")
            time.sleep(config.monitor.poll_interval_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        bot.close()


if __name__ == "__main__":
    sys.exit(main())
