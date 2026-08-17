from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from .models import Assessment, NewsItem


def fingerprint(item: NewsItem) -> str:
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", item.title.lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class Storage:
    def __init__(self, path: str) -> None:
        database_path = Path(path)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS news_items (
                fingerprint TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                source_name TEXT NOT NULL,
                published_at TEXT NOT NULL,
                discovered_at TEXT NOT NULL,
                score INTEGER NOT NULL,
                level TEXT NOT NULL,
                category TEXT NOT NULL,
                sent_at TEXT
            )
            """
        )
        columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(news_items)").fetchall()
        }
        if "event_signature" not in columns:
            self.connection.execute("ALTER TABLE news_items ADD COLUMN event_signature TEXT")
        if "summary" not in columns:
            self.connection.execute("ALTER TABLE news_items ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
        if "feed_name" not in columns:
            self.connection.execute("ALTER TABLE news_items ADD COLUMN feed_name TEXT NOT NULL DEFAULT ''")
        if "candidate_kind" not in columns:
            self.connection.execute("ALTER TABLE news_items ADD COLUMN candidate_kind TEXT")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self.connection.commit()

    def is_initialized(self) -> bool:
        row = self.connection.execute("SELECT value FROM metadata WHERE key='initialized'").fetchone()
        return bool(row)

    def mark_initialized(self) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('initialized', datetime('now'))"
        )
        self.connection.commit()

    def initialize_daily_backup_date(self, target_date: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES('daily_backup_last_date', ?)",
            (target_date,),
        )
        self.connection.commit()

    def is_daily_backup_complete(self, target_date: str) -> bool:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key='daily_backup_last_date'"
        ).fetchone()
        return bool(row and row[0] == target_date)

    def daily_backup_progress(self, target_date: str) -> int:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key='daily_backup_progress'"
        ).fetchone()
        if not row:
            return 0
        date_value, _, count_value = row[0].partition("|")
        return int(count_value) if date_value == target_date and count_value.isdigit() else 0

    def record_daily_backup_sent(self, target_date: str, sent: int, required: int) -> int:
        total = self.daily_backup_progress(target_date) + sent
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('daily_backup_progress', ?)",
            (f"{target_date}|{total}",),
        )
        if total >= required:
            self.complete_daily_backup_date(target_date)
        self.connection.commit()
        return total

    def complete_daily_backup_date(self, target_date: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('daily_backup_last_date', ?)",
            (target_date,),
        )
        self.connection.commit()

    def sync_push_threshold(self, current_score: int, maximum_item_age_hours: int) -> int:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key='instant_push_score'"
        ).fetchone()
        previous_score = int(row[0]) if row else None
        requeued = 0
        if previous_score is not None and current_score < previous_score:
            cursor = self.connection.execute(
                """
                DELETE FROM news_items
                WHERE sent_at IS NULL
                  AND score>=?
                  AND score<?
                  AND datetime(published_at)>=datetime('now', ?)
                """,
                (current_score, previous_score, f"-{maximum_item_age_hours} hours"),
            )
            requeued = max(0, cursor.rowcount)
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('instant_push_score', ?)",
            (str(current_score),),
        )
        self.connection.commit()
        return requeued

    def backfill_event_signatures(self, companies: list[str]) -> None:
        rows = self.connection.execute(
            "SELECT fingerprint, title, category FROM news_items WHERE event_signature IS NULL"
        ).fetchall()
        for item_fingerprint, title, category in rows:
            entities = sorted(company for company in companies if company in title)
            if not entities:
                continue
            signature = f"{category}|{'|'.join(entities)}"
            self.connection.execute(
                "UPDATE news_items SET event_signature=? WHERE fingerprint=?",
                (signature, item_fingerprint),
            )
        self.connection.commit()

    def exists_or_similar(self, item: NewsItem) -> bool:
        if self.connection.execute(
            "SELECT 1 FROM news_items WHERE fingerprint=?", (fingerprint(item),)
        ).fetchone():
            return True
        normalized = re.sub(r"\s+", "", item.title.lower())
        rows = self.connection.execute(
            "SELECT title FROM news_items WHERE discovered_at >= datetime('now', '-7 days')"
        ).fetchall()
        return any(SequenceMatcher(None, normalized, re.sub(r"\s+", "", row[0].lower())).ratio() >= 0.86 for row in rows)

    def was_event_sent_recently(self, signature: str, item: NewsItem, hours: int = 72) -> bool:
        cutoff = (item.published_at - timedelta(hours=hours)).isoformat()
        row = self.connection.execute(
            """
            SELECT 1 FROM news_items
            WHERE event_signature=? AND sent_at IS NOT NULL AND published_at>=?
            LIMIT 1
            """,
            (signature, cutoff),
        ).fetchone()
        return bool(row)

    def save(
        self,
        item: NewsItem,
        assessment: Assessment,
        sent: bool = False,
        event_signature: str | None = None,
        candidate_kind: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO news_items(
                fingerprint, title, url, source_name, published_at, discovered_at,
                score, level, category, sent_at, event_signature, summary, feed_name, candidate_kind
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? THEN datetime('now') ELSE NULL END, ?, ?, ?, ?)
            """,
            (
                fingerprint(item), item.title, item.url, item.source_name,
                item.published_at.isoformat(), item.discovered_at.isoformat(), assessment.score,
                assessment.level, assessment.category, int(sent), event_signature,
                item.summary, item.feed_name, candidate_kind,
            ),
        )
        self.connection.commit()

    def sent_count_between(self, start: datetime, end: datetime) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) FROM news_items
            WHERE sent_at IS NOT NULL
              AND datetime(sent_at)>=datetime(?)
              AND datetime(sent_at)<datetime(?)
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        return int(row[0]) if row else 0

    def load_unsent_candidates(self, start: datetime, end: datetime) -> list[tuple[NewsItem, str]]:
        rows = self.connection.execute(
            """
            SELECT title, url, summary, source_name, feed_name, published_at, candidate_kind
            FROM news_items
            WHERE sent_at IS NULL
              AND candidate_kind IS NOT NULL
              AND datetime(published_at)>=datetime(?)
              AND datetime(published_at)<datetime(?)
            ORDER BY score DESC, datetime(published_at) DESC
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [
            (
                NewsItem(
                    title=title,
                    url=url,
                    summary=summary or "",
                    source_name=source_name,
                    feed_name=feed_name or "",
                    published_at=datetime.fromisoformat(published_at),
                ),
                candidate_kind,
            )
            for title, url, summary, source_name, feed_name, published_at, candidate_kind in rows
        ]

    def mark_sent(self, item: NewsItem, event_signature: str | None = None) -> None:
        self.connection.execute(
            """
            UPDATE news_items
            SET sent_at=datetime('now'), event_signature=COALESCE(?, event_signature)
            WHERE fingerprint=?
            """,
            (event_signature, fingerprint(item)),
        )
        self.connection.commit()

    def update_content_metadata(self, item: NewsItem) -> None:
        self.connection.execute(
            """
            UPDATE news_items
            SET summary=?, published_at=?
            WHERE fingerprint=?
            """,
            (item.summary, item.published_at.isoformat(), fingerprint(item)),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
